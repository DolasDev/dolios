# `ops.*` metrics reset to a zero-tick window whenever loop code merges

## Context

Remeasure of `proposals/dolios/2026-11-14-sync-base-before-picking-work.md`
on 2026-11-14 (POST row `audited_at: 2026-11-14T16:49:15Z`). Both chunks
landed earlier in the day: chunk 1 touched `services/coder/tick.py` + its
test; chunk 2 touched `services/coder/dispatch.py` + its test. Chunk 2
merged at 15:23Z and the remeasure fired at 16:49Z. The post audit showed
`ops.duplicate_pr_tasks == []` and `ops.repeated_failures == []` — which
would read as "hypothesis met" at a glance — but also `ops.ticks == 0`
with `code_cutoff: 2026-11-14T16:49:00Z`.

The auditor only counts ticks *after* `code_cutoff`, which is defined as
the newest commit that touched loop code. Chunk 2's own merge *was* that
commit, so the window the metric is computed over is trivially empty. The
`[]` is "no ticks happened", not "no duplicates happened".

The Measurement plan in the proposal anticipated this and required ≥3
auto-merged agent PRs in the window to call the result met, so we
correctly logged "inconclusive" rather than falsely claiming a win. But
without that explicit floor it would have been easy to misread.

## Lesson

Any proposal whose `metrics:` frontmatter includes `ops.*` AND whose
chunks modify `services/coder/` (or any other path that advances
`code_cutoff`) will produce a first-remeasure row with `ticks == 0` by
construction. The POST data is uninformative until a non-trivial number
of ticks accumulate past the final chunk's merge.

Options a proposal author / dispatcher has:

1. **Explicit inconclusive floor in the Measurement plan** (what this
   proposal did). Cheap, falsifiability-preserving, forces a second
   remeasure after enough ticks have run. Downside: the loop is
   currently remeasure-once per proposal; "let the next weekly audit
   decide" relies on a *subsequent* audit, not a scheduled follow-up
   remeasure. There's no mechanism yet to re-open the Outcome.
2. **Dispatcher-side deferral**. The `remeasure` dispatcher could
   inspect the proposal's `metrics:` list and, if any `ops.*` appears,
   defer the audit until `ticks` since `code_cutoff` reaches some
   minimum (e.g. 5). Needs plumbing but makes the metric meaningful on
   the first try.
3. **Lookback that straddles the cutoff**. The auditor could report two
   windows — "since cutoff" and "lookback_days raw" — and the proposal
   could reference either. Risky: pre-cutoff ticks may have been
   observing the broken behavior, which defeats the point of
   `code_cutoff`.

For now, option 1 is the pragma: *always* include the inconclusive-floor
clause in the Measurement plan when writing an `ops.*` proposal. Longer
term, option 2 is the cleanest fix and probably its own proposal.

## Apply to

- Any new proposal whose `metrics:` frontmatter names `ops.*` — require
  an explicit minimum-evidence floor in the Measurement plan ("call it
  inconclusive below N post-cutoff ticks"). Reject proposals that would
  report `[]` on a zero-tick sample as "met".
- Future dispatcher work on remeasure scheduling: option 2 above is the
  right mechanism if we want `ops.*` proposals to have decisive first
  remeasures. Pairs with any future "schedule follow-up remeasure"
  feature.
- Reviewers of `ops.*` remeasure outcomes: if the post row has
  `ops.ticks == 0`, treat `duplicate_pr_tasks == []` and
  `repeated_failures == []` as "no data", not as evidence.

Related: [[0002-chunk-mode-claude-must-not-touch-proposal]] — same family
of "the dispatcher and the loop state have a timing relationship that
can silently invalidate what the metric means".
