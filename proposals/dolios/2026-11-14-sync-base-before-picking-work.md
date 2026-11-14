---
id:     dolios/2026-11-14-sync-base-before-picking-work
status: done
repo:   dolios
audit:  .dolios/metrics/dolios/history.jsonl#L5@2026-11-14T09:00:59Z
gap_ids:
  - ops-3e9ea57d89
metrics:
  - ops.duplicate_pr_tasks
  - ops.repeated_failures            # guard
frameworks:
  - "SRE: Eliminating toil"
  - "DORA: Working in small batches"
  - "DORA: Monitoring and observability"
opened:    2026-11-14
approved:  2026-11-14
done:      2026-11-14
---

# Sync the base branch before every tick acts (stop acting on stale state)

> Hand-written by a human-supervised session as the loop's first
> **self-repair** proposal: the bug is in the coder's own loop, and the
> coder implements the fix. Both chunks touch protected paths
> (`services/coder/`), so each execution PR is auto-reviewed but waits for a
> human merge.

## Hypothesis

> Fast-forwarding the dolios checkout (and each target repo) to `origin/main`
> before the picker reads state and before the dispatcher branches should
> move **`ops.duplicate_pr_tasks`** from **2 tasks** (observed 2026-11-14) to
> **`[]`** over the next 14 days of ticks, because every duplicate observed so
> far came from the picker reading a checkout that hadn't pulled the PR the
> loop itself had just auto-merged.

## Audit citation

- **Audit row:** `.dolios/metrics/dolios/history.jsonl` line 5
  (`audited_at: 2026-11-14T09:00:59Z`). That row predates the `ops` metric
  (added in #26), so the baseline below comes from the tick log the metric
  is computed from.
- **Gap targeted:** `ops` / `Autonomous-coder loop opened duplicate PRs for
  one task` (severity: `high`, `gap_id: ops-3e9ea57d89`).
- **Frameworks:** SRE "Eliminating toil" — every duplicate is a manual
  close-and-clean-up for a human; DORA "Working in small batches" — duplicate
  in-flight PRs for one change defeat small, independent batches.

## Baseline

| Metric | Current | Source |
|---|---|---|
| `ops.duplicate_pr_tasks` | 2 tasks: `remeasure-…-adopt-github-actions-ci` → #19, #20; `propose-compliance-f6003ab812` → #21, #22, #23 | `.dolios/tick-log.jsonl`, 2026-11-14 09:00–11:30Z |
| `ops.repeated_failures` (guard) | `[]` since the latest loop-code commit | audit `metrics.ops` |

Mechanism (verified by hand on 2026-11-14): the loop auto-merges its PRs on
GitHub but never pulls them into its own checkout
(`/opt/data/repos/dolios`, bind-mounted from the host). After #19 merged,
the checkout still read the CI proposal as `status: approved`, so the 10:00Z
tick remeasured again (#20). After #21 merged, the gap still looked
uncovered, so 11:00Z and 11:30Z proposed it again (#22, #23). A human
fast-forwarded the checkout and closed the duplicates.

## Intervention

- [x] **Tick: fast-forward the dolios checkout before picking work.** In
  `services/coder/tick.py` `run_tick`, after a successful preflight and
  BEFORE running `backlog.py --next`, sync `self.root` to `origin/<base>`
  (base = `main`): `git fetch origin main`, then `git merge --ff-only
  origin/main`, all through `self._runner` so tests can fake it. Preconditions
  and failure handling: if HEAD is not `main`, or the tree has dirty paths
  OTHER than under `.dolios/metrics/` (reuse the exemption idea from
  `dispatch.EXEMPT_DIRTY_PREFIXES`), or the fetch/merge fails, do NOT pick
  work — log the tick as `kind: "sync_error"` with an `error` field and
  return (the watchdog pages on repeats). Pending local audit rows: dirty
  `.dolios/metrics/<repo>/history.jsonl` files would block the ff-merge, so
  before merging read each such file, `git checkout --` it, ff-merge, then
  re-append every local row whose `audited_at` is not already present in the
  updated file (order preserved). Record `synced_to` (the new HEAD sha) in the
  tick record on success. Add tests in `services/coder/test_tick.py` for:
  clean ff, not-on-main → sync_error, foreign dirt → sync_error, fetch failure
  → sync_error, and pending audit rows preserved across the sync. Keep
  `make coder-test` and `ruff check services/` green.
- [x] **Dispatch: branch from an up-to-date base in every target repo.** In
  `services/coder/dispatch.py` `dispatch()`, after the clean-tree check and
  before `git checkout -b <branch> <base>`, run `git fetch origin <base>` and
  `git merge --ff-only origin/<base>` in the target repo (only when HEAD is
  `<base>`; if HEAD is elsewhere, `git checkout <base>` first). A failure
  raises `GuardrailError` with the git stderr — never branch from a stale
  base. Extend `FakeRepo` in `services/coder/test_dispatch.py` to accept the
  new commands, and add tests: the fetch + ff happen before `checkout -b`, and
  a failed ff aborts before claude runs. Keep `make coder-test` and
  `ruff check services/` green.

## Measurement plan

- **Metric(s) to watch:** `ops.duplicate_pr_tasks` (target `[]`); guard
  `ops.repeated_failures` (a sync that keeps failing would show up here and
  in the watchdog as a repeated `sync_error`).
- **Sampling cadence:** every audit (weekly) — `ops` only counts ticks after
  the latest loop-code commit, so the window starts at the merge of the last
  chunk.
- **Success threshold:** `ops.duplicate_pr_tasks == []` with at least 3
  auto-merged agent PRs inside the measured window (otherwise there was
  nothing to go stale, and the result is inconclusive, not met).
- **When to call it:** at remeasure; if fewer than 3 merges have happened,
  record "inconclusive" and let the next audit decide.
- **What would falsify it:** any duplicate after both chunks merge → the
  staleness has another source (e.g. a merge landing mid-tick); iterate with
  a follow-up proposal.

## Research / prior art

- **Considered:** periodic `git pull` from a separate cron — racy with a
  running tick and duplicates scheduling; rejected.
- **Considered:** having the picker query GitHub (`gh pr list`) for in-flight
  work instead of trusting the checkout — useful as a second guard, but the
  checkout must be current anyway (proposals, chunk boxes and code all live
  in it); deferred.
- **Picked:** fetch + `--ff-only` at the two points that read state or create
  branches. `--ff-only` never creates merge commits or rewrites history, and
  refuses (loudly) when the checkout has diverged — the right failure mode
  for an unattended loop.

## Effort & risk

- **Effort:** two small execution PRs, ~5–10 min dispatcher time each, plus a
  human merge each (protected paths).
- **Risk — self-update mid-flight:** the dolios checkout is also the loop's
  code; a fast-forward can change `tick.py`/`dispatch.py` on disk. Python has
  already loaded the running modules, and subprocesses spawned after the sync
  run the new code — acceptable, and it is how merged loop fixes deploy.
- **Risk — the first merge doesn't sync itself:** after chunk 1's PR merges,
  the checkout is still stale until something pulls it once. **Mitigation:**
  the human merging chunk 1 runs `git -C ~/repos/dolios pull --ff-only` on
  dolo-docker once; from then on the loop syncs itself.
- **Risk — losing pending audit rows** on sync. **Mitigation:** chunk 1's
  re-append step + its test.

## Outcome

Post row: `.dolios/metrics/dolios/history.jsonl` last line, `audited_at:
2026-11-14T16:49:15Z` (`git_head: 731af0f`, chunk 2 merged). Baseline cited
in the frontmatter above; `ops.duplicate_pr_tasks` baseline counted from
`.dolios/tick-log.jsonl` (09:00–11:30Z window) because the audit row that
anchors the proposal predates the `ops` metric.

| Metric | Baseline | Post-execution | Δ | Target | Verdict |
|---|---|---|---|---|---|
| `ops.duplicate_pr_tasks` | 2 tasks (`remeasure-…-adopt-github-actions-ci` → #19, #20; `propose-compliance-f6003ab812` → #21, #22, #23) | `[]` | `2 → 0` tasks | `[]` | ⚠️ inconclusive — see below |
| `ops.repeated_failures` *(guard)* | `[]` | `[]` | unchanged | no new sync_error repeats | ✅ ok |

- **Did the hypothesis hold?** Not yet proven. The post row shows
  `ops.duplicate_pr_tasks == []`, but it also shows `ops.ticks == 0`: the
  `code_cutoff` (`2026-11-14T16:49:00Z`) was reset by chunk 2's own merge
  (`services/coder/dispatch.py` and `test_dispatch.py` are both loop code),
  and the remeasure ran immediately afterwards. Zero post-cutoff ticks
  means the `[]` is *trivially* empty, not *observationally* empty. The
  Measurement plan required at least 3 auto-merged agent PRs inside the
  measured window to call it met; with 0 we must record **inconclusive**
  and let the next weekly audit decide. The guard metric
  `ops.repeated_failures` stayed `[]`, so the new `sync_error` kind has
  not fired at all — but again, that's on 0 ticks post-cutoff, so it is
  no evidence either way.
- **Unexpected movement** in non-target metrics (worth flagging, nothing
  to escalate):
  - `commits.count` (90-day): `9 → 18` (+9). Explained by the autonomous
    loop merging two chunks of this proposal plus adjacent coder work in
    the intervening hours; expected direction for an active dolios day.
  - `commits.median_lines_changed`: `50 → 135` (+170%). Driven by two
    chunk-shaped PRs (tick.py + tests for chunk 1, dispatch.py + tests
    for chunk 2) landing today; well under the proposal's rejected-size
    bar and nowhere near the "adverse ≥25% rise with no explanation"
    bar we usually apply, because the cause is obvious (the chunks
    themselves).
  - `testing.test_to_source_ratio`: `0.667 → 0.643`. Slight dip because
    chunk 1 and 2 each added a source file plus modest test additions
    in existing test files rather than new test files. Not a regression
    in testing discipline — the same test files gained new cases
    (`test_tick.py` and `test_dispatch.py` both saw substantive new
    scenarios). Not actionable.
- **What we learned**, for the next proposal of this kind:
  1. **`ops`-metric proposals need to account for cutoff self-reset.**
     Any proposal whose chunks touch `services/coder/` will reset
     `ops.code_cutoff` at merge time, which means the first remeasure
     after chunk completion will see `ticks == 0` by construction. The
     Measurement plan correctly anticipated this ("inconclusive if
     fewer than 3 merges"), but the proposal template could make it
     more prominent — perhaps a stock warning in the Effort & risk
     section whenever `ops.*` appears in `metrics:`. Alternative: the
     remeasure dispatcher could defer by N hours / N ticks when the
     proposal's own merge was the thing that reset the cutoff. See
     [[0004-ops-cutoff-resets-on-loop-code-merge]].
  2. **The two-point `--ff-only` approach is live and quiet.** Neither
     chunk broke anything on the way in: chunk 1's PR (#28) ran its new
     tests green under the pre-sync loop, chunk 2's PR (#30) was
     branched from the chunk-1 HEAD (post-merge sync worked — the tick
     record for #30 carries `synced_to: 529dc5b…`, i.e. the dispatcher
     fast-forwarded before branching, which is literally what chunk 2
     adds). That's a soft-but-real end-to-end signal: chunk 2 proves
     chunk 1 works, even though the metric row doesn't yet.
  3. **Falsifiability check held.** We didn't optimistically call this
     "met". The Measurement plan's minimum-evidence threshold prevented
     a cheap win, and the honest "inconclusive" is more useful than a
     fragile ✅ would have been: the next remeasure has a real chance of
     either confirming the fix on a non-trivial sample or surfacing a
     second staleness source, as the proposal's falsification clause
     describes.
