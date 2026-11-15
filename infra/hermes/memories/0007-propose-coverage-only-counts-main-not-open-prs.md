---
name: propose-coverage-only-counts-main-not-open-prs
description: The propose picker's gap-coverage set is built from proposals on main — an open-but-unmerged propose-* PR doesn't cover its gap, so the next tick can pick the same gap again and ship a duplicate proposal
metadata:
  type: feedback
---

# The propose picker's gap-coverage set only sees proposals on `main`; open PRs don't count

## Context

Reflecting over the past 7 days of `.dolios/tick-log.jsonl`,
`services/coder/.ledger.jsonl`, and the resulting PRs.

Two separate "same gap, two PRs" episodes:

1. **`propose-compliance-f6003ab812` — 3 dispatches on 2026-11-14**
   (10:33, 11:03, 11:33). PR #21 merged in 43 s; PRs #22 and #23 fired
   twice more against the same gap and were manually closed hours later.
   This was BEFORE
   `proposals/dolios/2026-11-14-sync-base-before-picking-work.md` merged
   (chunks landed 14:12 and 15:26). Memory [[0004-ops-cutoff-resets-on-loop-code-merge]]
   covers the metrics side of that proposal.

2. **`propose-supply_chain-81adaf8216` — 2 dispatches on 2026-11-15**
   (05:34 → PR #38, 06:04 → PR #39). This was AFTER the sync-base fix
   merged. PR #38 (adds `proposals/dolios/2026-11-15-adopt-dependabot.md`
   + attempts to claim memory slot 0006) opened at 05:34, CI went green
   at 05:34:57Z, but it never auto-merged. The next `propose` tick fired
   30 minutes later, synced `main` (fix working as designed), evaluated
   the backlog, and still found the supply-chain gap uncovered — because
   the covering proposal was sitting on a `auto/coder/propose-*` branch,
   not on `main`. It generated a second, independent proposal
   (`enable-dependabot.md`, PR #39) which merged in 45 s. PR #38 is now
   stuck OPEN with a dead `0006-dependabot-…` memory name that would
   conflict on merge with the actually-merged
   `0006-presence-metrics-hide-broken-content.md`.

Tracing the mechanism to `services/coder/backlog.py`:

```python
# build_repo_backlog
covered: set[str] = set()
for fm in proposals:  # _load_proposals_for_repo → proposals/<repo>/*.md on disk
    status = fm.get("status")
    if status in ACTIVE_PROPOSAL_STATUSES:
        for gid in fm.get("gap_ids", []) or []:
            covered.add(gid)
```

`_load_proposals_for_repo` reads the working tree. The sync-base fix
guarantees that working tree is up-to-date with `origin/main`, but
*open PRs are not in the working tree*. The dispatcher's own branch
isn't checked out when the picker runs on the next tick.

## The rule

The propose picker treats a gap as covered only after the proposal
touches `main`. **Any time between "propose dispatch opened PR" and
"PR merged" is a window in which the same gap can be picked again.**
With a 30-minute tick cadence and non-trivial review latency, that
window is routinely large enough to trip.

## Why

Picker correctness depends on `main` being the single source of truth
for "what proposals exist." Branches and open PRs are deliberately not
consulted — this is a reasonable simplification, but it assumes
auto-merge back onto `main` happens inside one tick interval. For
propose PRs that rely on CODEOWNERS routing, draft status, or any kind
of human/auto-approver turnaround, that assumption breaks.

Sync-base-before-tick (merged 2026-11-14) closed the "stale local
`main`" variant of this bug. The remaining variant — "no local staleness,
the proposal just isn't on `main` yet" — survived.

## How to apply

- **Reviewing weekly ticks:** If the ledger shows the same
  `propose-<area>-<signature>` task_id firing twice, it's almost always
  this pattern, not a bug in the gap detector. Check whether the first
  dispatch's PR was still open when the second dispatch fired.
- **When drafting a fix proposal:** the smallest sufficient change is
  extending `build_repo_backlog` (or the picker's gap-filter step in
  `services/coder/backlog.py` around the `covered_gap_ids` loop) to
  also scan open PRs for proposal files. Options in rough order of
  cost:
    1. `gh pr list --state open --search "auto-coder: propose-"` and
       `gh pr view <n> --json files` to extract any
       `proposals/<repo>/*.md` and parse their `gap_ids`.
    2. `git ls-remote origin "refs/heads/auto/coder/propose-*"` + fetch
       just the proposal file blob (`git show
       origin/<branch>:<proposal>`).
    3. Persist a `.dolios/propose-cooldown.json` keyed by
       `gap_signature` (not by proposal filename, since each dispatch
       picks its own filename slug) and refuse to re-propose within N
       hours. Weakest guarantee but cheapest to ship.
- **When reviewing propose-* PRs:** if two auto-coder PRs reference
  the same gap signature in their branch name, close the later one
  rather than the earlier — the earlier is usually more thoroughly
  reviewed and its CI history is already warm. The dispatcher doesn't
  care which one lands.
- **Collateral risk — the `infra/hermes/memories/NNNN-*.md` sequence.**
  Any propose-* PR that writes a new memory claims the next unused
  NNNN by reading the working tree. Two concurrent propose dispatches
  will both pick the same NNNN. If both land, the later merge conflicts
  on the memory file path. This is how PR #38 is going to fail when
  someone tries to merge it — memory 0006 is already taken.

## Apply to

- The follow-up proposal that fixes the race (likely a new chunk in a
  `fix-propose-dedup-open-prs.md` proposal, filed off the `ops.*` gap
  class once a few more duplicates show up in the ticker).
- Reviewers triaging stuck/OPEN auto-coder `propose-*` PRs: before
  investigating CI, check whether a sibling PR against the same gap
  signature already merged — if so, the open PR is dead weight; close
  it.
- Future dispatcher work that adds *any* kind of auto-numbered
  artefact (memories, numbered chunks, date-stamped proposal
  filenames on the same calendar day): the same race exists for the
  numbering. The fix above (consult open PRs, or cool down by
  signature) covers all of them.

Related: [[0004-ops-cutoff-resets-on-loop-code-merge]] — same
underlying theme that the sync-base proposal addressed part of but
not all of. Also related to
[[0003-gh-actions-api-branch-filter-hides-pr-runs]] in the general
"unit tests pass, the live integration is still wrong" sense: a unit
test of `build_repo_backlog` that stubs out `_load_proposals_for_repo`
cannot catch this — the bug lives at the boundary between the picker
and the external GitHub state that isn't in the working tree.
