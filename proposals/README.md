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
id:     dolios/2026-05-28-adopt-github-actions-ci   # canonical id; matches the filename stem
status: proposed | approved | implementing | done | abandoned
repo:   dolios
audit:  .dolios/metrics/dolios/history.jsonl#L1@2026-05-28T20:16:11Z
gap_ids: [ci-7a3f9b2c1d]
metrics: [ci.github_actions_present, ci.workflow_count]
frameworks: ["DORA: Continuous Integration", "DORA: Test automation"]
opened:    2026-05-28
approved:  null
done:      null
---
```

### Field semantics

- **`id`** — canonical identifier, format `<repo>/<filename-stem>` (no `.md`).
  Written explicitly so renaming the file doesn't orphan execution PRs that
  cite it. The dispatcher tags every execution PR and branch with this id.
- **`audit`** — `<path>#L<n>@<audited_at>` where `<n>` is the 1-based JSONL
  line number of the audit row this proposal cites, and `<audited_at>` is the
  row's ISO-8601 timestamp. Both, so a future audit row appended to the same
  file is unambiguously a different reference. The previous "sha" form was
  ambiguous between the audited-HEAD sha and the introducing-commit sha.
- **`gap_ids`** — the stable `gap_id`s from the audit row's `gaps` array that
  this proposal targets. Lets the picker tell "this gap is now covered by an
  open proposal" without string-matching summaries.
- **`metrics`** — every metric the Outcome will report on, in the order the
  Outcome table will list them.

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

Chunks live in the **Intervention** section as a checkbox list:

```markdown
- [ ] **Chunk 1 — minimal CI workflow**
- [ ] **Chunk 2 — pyproject.toml for ruff**
- [ ] **Chunk 3 — auditor extension for the GH Actions API**
```

Once a proposal is `approved` (merged onto `main`), the picker
([`services/coder/backlog.py`](../services/coder/backlog.py)) reads the
checkboxes to find the next unchecked chunk and emits `kind: execute`. The
dispatcher then:

1. Opens an execution PR on branch `auto/coder/<proposal-id>-chunk-<n>`,
   with the PR body cross-linking back to the proposal.
2. **As part of the same commit**, flips that chunk's `[ ]` → `[x]` in the
   proposal markdown — so a human reviewer sees the implementation AND the
   chunk-done state change in one diff, and merging the PR atomically updates
   both.

This makes the proposal markdown the single canonical source of chunk state.
No sidecar required; the diff is self-describing.

While an execution PR is open, `main` still shows the chunk's box as `[ ]`,
so the picker would re-emit `execute` for the same chunk on the next tick.
The dispatcher prevents duplicates by checking for an existing
`auto/coder/<proposal-id>-chunk-<n>` branch before opening a new PR.

The proposal's **effective status** is computed from the chunk state:

| File `status:` | Chunks | Effective state |
|---|---|---|
| `proposed` | any | proposed (awaiting human merge) |
| `approved` | none `[x]` | approved (ready to start) |
| `approved` | some `[x]`, some `[ ]` | implementing (counts toward 3-cap) |
| `approved` | all `[x]`, no `done:` date | ready to remeasure |
| `approved` | all `[x]`, `done:` date set | done |
| `done` / `abandoned` | any | terminal |

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
