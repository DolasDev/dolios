---
id:     dolios/2026-11-15-add-codeowners
status: proposed
repo:   dolios
audit:  .dolios/metrics/dolios/history.jsonl#L7@2026-11-15T03:30:56Z
gap_ids:
  - review-e401f3007f
metrics:
  - docs.codeowners_present
frameworks:
  - "DORA: Streamlining change approval"
pitch: >-
  Adds a CODEOWNERS file so GitHub automatically requests your review on
  every PR. With you as the only maintainer it mostly checks an audit box;
  it matters once a second person (or bot) starts reviewing. One small
  file, very low risk.
opened:    2026-11-15
approved:  null
done:      null
---

# Add `.github/CODEOWNERS` to auto-route review requests

## Hypothesis

> Adopting a `.github/CODEOWNERS` file should move `docs.codeowners_present`
> from `false` to `true` within **one audit cycle** because
> `services/auditor/audit.py:audit_docs` resolves presence by checking for a
> file at `CODEOWNERS` (root) or `.github/CODEOWNERS` — a stable
> filesystem probe — and GitHub honours the same two locations for its
> native review-routing (DORA: *Streamlining change approval* — route
> reviews to the right humans without asking authors to remember).

This is the LICENSE-shaped easy case: a single-file, presence-metric
intervention where the auditor's detection check is deterministic, the
PR→metric mapping is 1:1, and there is no measurement window to wait out.

## Audit citation

- **Audit row:** `.dolios/metrics/dolios/history.jsonl` line 7 at
  `git_head: 83b4833e0ec68edc6db54f90a97bd97daa6f6965`
  (`audited_at: 2026-11-15T03:30:56Z`).
- **Gap targeted:** `review` / "No CODEOWNERS" (severity: `low`).
- **Frameworks:** `DORA: Streamlining change approval`. The DORA
  programme identifies **streamlining change approval** as a
  throughput-positive capability — a lightweight, pre-arranged review
  structure (as opposed to ad-hoc "who should look at this?" routing)
  is one of its canonical instantiations. GitHub's CODEOWNERS is the
  platform-native implementation of that pre-arrangement: a PR that
  touches a path auto-requests review from the owner(s) declared for
  that path, eliminating the manual routing step.

## Baseline

| Metric | Current | Source |
|---|---|---|
| `docs.codeowners_present` | `false` | audit row above (`metrics.docs.codeowners_present`) |

Relevant context from the same row (useful for the Measurement plan but
not targeted directly):

- `docs.license_present: true` — gap `compliance-f6003ab812` closed by
  the 2026-11-14 LICENSE proposal; same single-file, presence-metric
  shape as this one.
- `ci.github_actions_present: true`, `workflow_count: 1`,
  `success_rate_30d: 1.0` — the auditor's hint said "add CODEOWNERS
  once CI is in place"; CI *is* in place. Prerequisite met.
- `commits.distinct_authors: 1` — the repo is effectively single-owner
  today. See Effort & risk for why this shapes the file we write (one
  rule, not an elaborate per-path map).

## Intervention

Single chunk. One execution PR, one new file.

- [ ] **Add `.github/CODEOWNERS`** — create a new, UTF-8, no-extension
  file at `.github/CODEOWNERS` with a single catch-all rule routing
  review of every path to `@steve-dolo` (the repo's sole human
  committer today; GitHub login derived from the `91444138+steve-dolo`
  noreply address on existing commits — verify the handle resolves on
  github.com before the PR merges). File body:

  ```
  # CODEOWNERS — GitHub auto-requests review from the listed owners whenever
  # a PR changes a matching path. See:
  # https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners
  #
  # Last-match-wins semantics: put more-specific rules below the default.
  # Invalid lines are SILENTLY skipped (no CI warning), so changes here
  # should be eyeballed carefully.

  *  @steve-dolo
  ```

  Placement: `.github/CODEOWNERS`, not root or `docs/`. GitHub checks
  the three valid locations in the order `.github/` → root → `docs/`
  and the auditor accepts root or `.github/`; co-locating with
  workflows keeps repo-level metadata consolidated.

That's the whole intervention. No branch-protection changes — see
Effort & risk / Research for why enforcement is out of scope for this
proposal.

## Measurement plan

- **Metric to watch:** `docs.codeowners_present`.
- **Guard conditions (non-targets we should see move the right way):**
  the `gaps[]` array in the next audit row should no longer contain an
  entry with `gap_id == review-e401f3007f`. This is the same
  derive-gaps transitive check the LICENSE remeasure used.
- **Sampling cadence:** one immediate remeasure after chunk merge,
  plus the next regular weekly audit. One cycle is enough for a
  presence check.
- **Success threshold:** `docs.codeowners_present == true` **and** the
  `review-e401f3007f` gap is absent from the post row's `gaps:` array.
- **When to call it:** append the Outcome table as soon as the first
  post-merge audit row lands.
- **What would falsify it:** post row still shows
  `docs.codeowners_present == false`. Only two plausible causes
  — (a) the file was committed to the wrong path (neither root nor
  `.github/`), or (b) the file was committed under a different name
  (e.g. `CODEOWNERS.md`, which the auditor does *not* accept — only
  bare `CODEOWNERS`). Both are observable at diff-review time; if we
  ship and the metric doesn't flip, open a follow-up chunk that
  renames/moves and remeasure. No design-level iteration path needed.

An explicit non-goal: this proposal does **not** try to move any
*review-quality* signal (time-to-first-review, approval rate, PRs
blocked by reviewer). The V0 auditor has no such metric, so there is
nothing to measure. The proposal is deliberately scoped to the one
field that exists.

## Research / prior art

GitHub's own documentation
([`about-code-owners`](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners))
pins down the mechanics this proposal relies on:

- **Valid locations:** root `CODEOWNERS`, `.github/CODEOWNERS`,
  `docs/CODEOWNERS`. Lookup order is `.github/` first. The auditor
  matches the first two; this proposal uses `.github/CODEOWNERS`.
- **File shape:** UTF-8, no extension, one rule per line, `#` for
  comments. Patterns follow a gitignore-like subset — critically,
  **`!` negation is not supported** and **character-range `[]` does
  not work**. Invalid lines are silently skipped (no CI warning), so
  the file needs to be eyeballed on review.
- **Semantics:** last-match-wins (reverse of gitignore, which is
  first-match). We only have one rule today, so this doesn't bite yet
  — but noting it here so future expansions don't reverse the file
  and break it.

Community guidance that shaped the chosen shape:

- Mergify — *A Guide to GitHub Code Owners*
  ([articles.mergify.com/github-code-owners](https://articles.mergify.com/github-code-owners/))
  recommends `.github/CODEOWNERS` for most repos (keeps repo-level
  metadata together), plus one global catch-all before any
  per-path rules.
- DEV Community — *CODEOWNERS Best Practices That Keep Reviews
  Honest* ([dev.to/pyor/codeowners-best-practices-…](https://dev.to/pyor/codeowners-best-practices-that-keep-reviews-honest-1boj))
  recommends a path-rule on `/.github/` itself ("protect the
  CODEOWNERS file"). Deliberately **not** adopted here: with a single
  owner and `*`, any CODEOWNERS edit already requires review from
  that same owner. The self-protection rule becomes load-bearing only
  when multiple owners exist; adding it now is decorative. Flag for
  the next proposal in this area (when `commits.distinct_authors > 1`).

**Alternatives considered and rejected:**

- **Fine-grained per-path CODEOWNERS** (e.g. `services/auditor/` to one
  owner, `services/coder/` to another, `infra/hermes/` to a third).
  Rejected: with `distinct_authors == 1`, every line resolves to the
  same handle. It's decoration pretending to be structure, and future
  owners would still have to rewrite it. Minimum viable file first;
  expand when ownership actually fractures.
- **Branch-protection "Require review from Code Owners"** on `main`.
  Rejected *for this proposal*: (a) it's a GitHub repo-setting change,
  not a file in the tree — the autonomous coder cannot land it via a
  file commit (needs the API or the UI); (b) with one owner, turning
  this on would block the autonomous coder's own PRs from merging
  (the same account can't author *and* approve). Noted as a logical
  follow-up when distinct owners > 1 and the coder operates under a
  different identity to the reviewer.
- **Root `CODEOWNERS`.** Rejected only to keep repo-level metadata
  consolidated under `.github/`. Functionally equivalent for both
  GitHub and the auditor.

## Effort & risk

- **Effort:** one PR, one file (~10 lines including comments), ~1h
  dispatcher time including the WebFetch/handle-verification step.
  Single-chunk, presence-metric — the cheapest proposal shape this
  fleet has landed, same class as `add-license-file`.
- **Risks:**
  1. **Invalid-handle silent failure.** If `@steve-dolo` doesn't
     resolve as a GitHub login (typo, deleted account, org-namespaced
     `@org/team` instead), GitHub silently drops the rule — no PR
     review will ever be auto-requested, but the metric *still* flips
     to `true` because the auditor only checks file presence. We'd
     get a green remeasure for a non-functional file.
  2. **Review-request churn.** Every autonomous-coder PR will now
     explicitly request review from the owner, surfacing as a
     notification on every dispatch. On a one-owner repo this is
     mild but worth noting; the reviewer is likely already watching
     the PR firehose, so the delta is near-zero.
  3. **Future-expansion trap: last-match-wins.** A later contributor,
     reading this proposal's one-line file and extending it by
     intuition, might reverse the order expecting first-match
     semantics (the gitignore model). Documented inline in the file's
     comment header to mitigate.
  4. **No enforcement mechanism yet.** Without the
     "Require review from Code Owners" branch-protection rule, this
     is routing only, not gating. That's a deliberate scope cut (see
     Research), but it means `docs.codeowners_present == true` by
     itself does **not** satisfy the stronger reading of DORA's
     *streamlining change approval* capability (pre-arranged *and
     enforced* routing). The gap is a `low`-severity routing gap,
     not a `missing-gate` gap, so this proposal's framing is honest.
- **Mitigations:**
  - For risk 1: verify `github.com/steve-dolo` resolves as a human
    user (not a 404, not an org) before merging the chunk. If the
    handle turns out to differ, correct in the same PR.
  - For risks 2 and 3: comment header on the file documents
    last-match-wins + the invalid-line-silently-skipped behaviour.
  - For risk 4: recorded as a follow-up prerequisite for a future
    proposal — when `commits.distinct_authors > 1`, open a sibling
    proposal that (i) adds per-path rules, (ii) adds the
    self-protection rule, (iii) turns on branch-protection
    enforcement via the GitHub API.
- **Falsifiability guardrail against cheap wins.** Per the LICENSE
  remeasure learning (post row 2026-11-15T03:30:56Z, line 7), simple
  presence-metric proposals are "near-tautologies" and shouldn't be
  used as a signal of broader review-health. This proposal's success
  verdict must be read narrowly: "the file exists in a
  GitHub-recognised location." Any claim beyond that would need a
  new measurable the V0 auditor doesn't currently produce.

## Outcome

> *TBD — appended after the re-measure step.*

| Metric | Baseline | Post-execution | Δ | Target | Verdict |
|---|---|---|---|---|---|
| `docs.codeowners_present` | `false` | _(tbd)_ | _(tbd)_ | `true` | _(tbd)_ |
| `gaps[gap_id=review-e401f3007f]` *(guard)* | present | _(tbd)_ | _(tbd)_ | absent | _(tbd)_ |

- **Did the hypothesis hold?** _(tbd)_
- **Unexpected movement** in other metrics (intended or otherwise). _(tbd)_
- **What we learned**, for the next proposal of this kind. _(tbd)_
