# proposals

Centralized initiative tracker for the autonomous-coder. Every improvement —
to a target repo, to this repo, or to a fleet agent — starts here as a
**markdown PR** and ends with a measured outcome appended to the same file.
Nothing in the discovery loop executes without a merged proposal.

```
proposals/
  README.md             ← lifecycle + conventions (this file)
  _template.md          ← required structure for every new proposal
  <repo-slug>/          ← one dir per audited repo (`dolios`, `pegasus`, …)
    YYYY-MM-DD-<slug>.md
```

This sits centralized in **dolios** rather than in each target repo because
the agent's queue and metric history live here too — keeping proposals next
to them means one PR review captures the whole change (hypothesis ↔ baseline
↔ plan), and the agent's audit history can update the same file.

## Lifecycle

Four explicit states encoded in YAML frontmatter at the top of each proposal:

```yaml
---
status: proposed | approved | implementing | done | abandoned
repo:   dolios
audit:  .dolios/metrics/dolios/history.jsonl#<git-sha-of-source-audit>
metrics: [test_coverage_percent, ci_test_duration_seconds]
frameworks: ["DORA: Test automation", "SPACE: Efficiency"]
opened:    2026-05-28
approved:  null
done:      null
---
```

| State | Set by | What it means |
|---|---|---|
| `proposed` | the audit + Claude-Code research step | PR opened with the proposal body. Awaits human review. |
| `approved` | **human** (merging the proposal PR) | Plan accepted; execution PRs may now be opened against it. |
| `implementing` | the dispatcher (when it opens an execution PR linked to this proposal) | At least one execution PR has been opened (open or in-review). |
| `done` | the re-measure step (after execution PR(s) merge + follow-up audit) | Outcome row appended to the proposal; status flipped; metrics moved (or didn't — both honest outcomes). |
| `abandoned` | **human** | Reviewed and decided not to pursue. The reason goes in the file before flipping the status. |

Status transitions are themselves PRs (the agent never edits `main` directly,
including its own proposals).

## Hard cap: 3 active per repo

The autonomous-coder may have *any number* of proposals in **`proposed`** state
(the human controls the funnel by approving them). But the **`implementing`**
state is capped at **3 per repo at any one time**, so:

- No more than 3 concurrent open-execution-PR streams against a single repo.
- The dispatcher checks this before opening an execution PR; if at the cap,
  it picks a different repo or holds the tick.

This came out of the design discussion: small concurrent batch sizes keep
review load human-scale and let measurement attribute outcomes cleanly.

## Approval = merging the PR

There is no separate "approval" label, no separate workflow, no separate
button. **Merging the proposal PR onto `main` flips it to `approved`** (the
status field in the front-matter is updated *in* the merge commit, by the
human who's merging — or by the agent's follow-up commit before merge,
matching the human's review comments).

This keeps the agent honest: every approved plan exists at a specific commit
on `main`, citing the specific audit it was generated from, with the
framework anchor and measurement plan reviewed together.

## What a proposal looks like

Use [`_template.md`](_template.md). The required sections, in order:

1. **YAML frontmatter** (status, repo, audit ref, metrics, frameworks, dates).
2. **Hypothesis** — one paragraph. "Adopting X should move metric M from B to ≥T."
3. **Audit citation** — which audit row, which gap, the frameworks it falls under.
4. **Baseline** — current measured value, or "establish measurement" if `not_measured`.
5. **Intervention** — the concrete change. Bullet list of execution-PR-sized chunks.
6. **Measurement plan** — same metric, cadence, success threshold, when to call it.
7. **Research / prior art** — links to tools the research step considered, with rationale for the pick.
8. **Effort & risk** — rough order-of-magnitude, what could go wrong.
9. **Outcome** — *appended at `done` time only.* What actually moved; the
   audit rows pre / post; whether the hypothesis held.

A proposal that doesn't cite a framework capability isn't valid. A proposal
that doesn't have a measurement plan isn't valid — the audit must be able to
*tell us* whether it worked, or we don't ship it.

## How proposals get generated

The deterministic auditor produces ranked `gaps`. The supervisor cron, when
it's time to open a new proposal, dispatches a Claude Code run with:

- the latest audit JSON (or just the top-ranked gap not yet covered by an
  open proposal),
- read access to the target repo (mounted in the agent container),
- web access for researching current best-practice tooling,

…with instructions to produce **one** proposal file under `proposals/<repo>/`
following this template, then open the PR. The proposal IS the artifact;
nothing executes from the agent's reasoning that isn't captured in the file
on `main` once approved.

## How proposals get executed

Once a proposal is `approved` (merged), each chunk in its **Intervention**
section becomes one or more dispatcher tasks. The dispatcher
([`services/coder/`](../services/coder/)) opens an execution PR per chunk,
tagged with the proposal id in the PR body and branch name
(`auto/coder/<proposal-slug>-<chunk>-<ts>`). Merging an execution PR keeps the
proposal in `implementing`; the **last** execution PR merging triggers the
re-measure step and the `done` flip.

## How proposals get re-measured

After execution, the supervisor runs an audit against the target repo and
appends an outcome row to the proposal's history.jsonl reference. The
proposal's "Outcome" section gets populated (as a follow-up PR) with the
before/after numbers, whether the hypothesis held, and any unexpected
movement in unrelated metrics. The status flips to `done` (or stays
`implementing` if the threshold wasn't met and the proposal calls for
iteration).

This closes the loop: the audit fed the proposal, the proposal fed the
execution, the execution fed back to the audit, the audit confirms.
