---
id:     <repo-slug>/YYYY-MM-DD-<slug>   # canonical id; must match the filename stem.
                                        # Written explicitly so renaming the file
                                        # doesn't orphan execution PRs that cite it.
status: proposed              # proposed | approved | implementing | done | abandoned
repo:   <repo-slug>            # e.g. dolios, pegasus
audit:  .dolios/metrics/<repo-slug>/history.jsonl#L<n>@<audited_at>
                              # <n>           — 1-based JSONL line number of the row
                              # <audited_at>  — that row's `audited_at` ISO-8601 timestamp
                              # both for human readability and so a future audit
                              # row appended to the same file is unambiguously a
                              # different reference.
gap_ids:                      # which specific audit gaps this targets (stable ids
  - <gap_id>                  #  emitted by the auditor; e.g. ci-7a3f9b2c1d)
metrics:                      # which metrics from the audit this targets
  - <metric_path>             # e.g. ci.github_actions_present, testing.coverage_percent
frameworks:                   # at least one — see docs/metrics.md
  - "DORA: <capability>"
  - "OpenSSF Scorecard: <check>"
opened:    YYYY-MM-DD
approved:  null               # date the proposal PR merged
done:      null               # date the outcome was appended
---

# <One-line title — the change, not the metric>

## Hypothesis

> One paragraph. "Adopting **X** should move **metric M** from baseline **B**
> to **≥ T** within **W audit cycles** because of **<mechanism, cite framework
> evidence>**."

This sentence is the falsifiable thing the proposal is testing. Every later
section serves it.

## Audit citation

- **Audit row:** `.dolios/metrics/<repo>/history.jsonl` at git sha `…`
  (`audited_at: …`).
- **Gap targeted:** `<area>` / `<summary>` (severity: `<high|medium|low>`).
- **Frameworks:** `DORA: <capability>`, `OpenSSF Scorecard: <check>`, …
  Quote the specific claim from the literature this rests on.

## Baseline

Current measured value of each target metric, taken from the cited audit row.
If the metric is currently `not_measured`, **the first chunk of the
intervention is to establish measurement** — proposal still valid, baseline
section says "to be established as part of this proposal."

| Metric | Current | Source |
|---|---|---|
| `<metric_path>` | <value> | audit row above |

## Intervention

Concrete change, **decomposed into execution-PR-sized chunks** as a
checkbox list. Each chunk is small enough that one dispatcher run can land it;
chunks land in order. Each execution PR flips its chunk's `[ ]` → `[x]` as
part of the same commit, so the human reviewer sees the implementation AND
the chunk-done state change in one diff — and the picker can read the boxes
to know what's next.

- [ ] **<chunk 1 title>** — what changes, which files, which tool. Detail.
- [ ] **<chunk 2 title>** — …
- [ ] **<chunk 3 title>** — …

Keep chunks small; more than ~5 means the proposal is too big — split it.
Each chunk maps to one execution PR opened by the dispatcher with branch
`auto/coder/<proposal-id>-chunk-<n>` and body cross-linking back here.

## Measurement plan

- **Metric(s) to watch:** `<metric_path>`, plus any guard metrics (things
  we *don't* want to move).
- **Sampling cadence:** every audit run (currently weekly per repo).
- **Success threshold:** `<metric>` ≥ `<value>`, or moved by `<delta>` over
  `<window>`.
- **When to call it:** after the last execution PR merges, run an audit
  immediately + a follow-up at the next regular cadence; append both to the
  Outcome section.
- **What would falsify it:** explicit. If the metric *doesn't* move, do we
  iterate or abandon?

## Research / prior art

What did the research step consider? Rationale for the chosen tool/practice
over alternatives. Cite the specific URLs / docs / scorecards consulted.

- **Considered:** `<tool A>` (link) — why not.
- **Considered:** `<tool B>` (link) — why not.
- **Picked:** `<tool C>` (link) — why.

## Effort & risk

- **Effort:** rough order ("one PR, ~2h dispatcher time" / "3-5 PRs, ~1 week
  elapsed if reviews are prompt").
- **Risk:** specific things that could go wrong (CI breaks, false-positive
  flood, maintenance burden, vendor lock).
- **Mitigations:** how each risk is bounded.

## Outcome

> *Populated at `done` time, as a follow-up PR. Until then, this section
> reads: "TBD — appended after the re-measure step."*

The Outcome table has **one row per `metrics:` frontmatter entry, in the same
order** — so a parser can zip the two lists. Add rows for guard metrics if the
Measurement plan calls them out, marked `(guard)`.

| Metric | Baseline | Post-execution | Δ | Target | Verdict |
|---|---|---|---|---|---|
| `<metric_path>` | <b> | <p> | <±> | <t> | met / missed / partial |

- **Did the hypothesis hold?** Yes / No / Partially. Why.
- **Unexpected movement** in other metrics (intended or otherwise).
- **What we learned**, for the next proposal of this kind.
