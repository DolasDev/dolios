---
id:     dolios/2026-11-15-adopt-coverage-measurement
status: proposed
repo:   dolios
audit:  .dolios/metrics/dolios/history.jsonl#L7@2026-11-15T03:30:56Z
gap_ids:
  - testing-b2bebce2d9
metrics:
  - testing.coverage_measured
  - testing.coverage_percent
frameworks:
  - "DORA: Test automation"
opened:    2026-11-15
approved:  null
done:      null
---

# Measure test coverage with coverage.py and publish it through CI

## Hypothesis

> Running the existing test suite under **coverage.py** in CI, uploading the
> resulting `coverage.json` as a workflow artifact, and teaching the auditor
> to read it should move **`testing.coverage_measured`** from baseline
> **`false`** to **`true`** and populate **`testing.coverage_percent`** with
> a real number within **one audit cycle**, because the auditor's current
> `null` reading is hardcoded in `audit_testing()` for lack of a test-run
> integration — not for lack of a measurable suite — and `coverage.py` is
> the standard, framework-independent tool that already drops into the
> `python3 test_*.py` invocation pattern this repo uses.

What's being tested is specifically: is the "no coverage" gap a tooling
problem (we need to adopt coverage.py) or a suite problem (the tests don't
actually exercise much)? The hypothesis is the former. The falsification
case is covered in the Measurement plan: if the first number we publish is
abnormally low or structurally wrong (e.g. 0% because `coverage run` didn't
see the right source paths), the fix is iterative, not abandonment.

## Audit citation

- **Audit row:** `.dolios/metrics/dolios/history.jsonl` line 7
  (`audited_at: 2026-11-15T03:30:56Z`, `git_head: 83b4833…`). The row
  shows `testing.coverage_measured: false`, `testing.coverage_percent:
  null`, and a `_note` that explicitly flags this as "planned as a
  proposal output".
- **Gap targeted:** `testing` / "No test-coverage measurement" (severity:
  `medium`, `gap_id: testing-b2bebce2d9`). The gap's proposed_action is
  literal: *"Add coverage.py to the pytest runs in CI; publish a per-PR
  summary; track median over time."* This proposal operationalizes that.
- **Frameworks:**
  - `DORA: Test automation` — the four-key capability frames test
    automation as a continuous practice, not a one-time setup. From
    *Accelerate* (Forsgren/Humble/Kim, Ch. 4, "Technical Practices"):
    "Teams who did well at continuous delivery … had automated tests
    that were reliable, and developers trusted them." A coverage %
    isn't a direct measure of test quality, but a *missing* coverage
    number means we can't see drift at all — adopting the measurement
    is a prerequisite to the capability, not the capability itself.
  - OpenSSF Scorecard does not currently award coverage points
    directly, so no Scorecard anchor is claimed; the gap's framework
    list is the single-anchor `DORA: Test automation` and this proposal
    matches it.

## Baseline

Taken from the cited audit row (line 7).

| Metric | Current | Source |
|---|---|---|
| `testing.coverage_measured` | `false` | audit row above |
| `testing.coverage_percent` | `null` | audit row above |

Context from the same row: `testing.test_files: 9`,
`testing.source_files: 14`, `testing.test_to_source_ratio: 0.643`,
`testing.pytest_config_present: true`, and `ci.github_actions_present:
true` with one workflow at `.github/workflows/ci.yml`. The suite today
runs via `make audit-test`, `make usage-test`, `make coder-test` —
each of which invokes `python3 test_*.py` directly inside the
corresponding `services/<name>/` directory — so the integration point
for coverage.py is well-defined (three script invocations under one
umbrella).

## Intervention

- [ ] **Chunk 1 — Add `coverage.py` locally with a `make coverage` target.**
  (a) Add a `[project.optional-dependencies].dev = ["coverage>=7.6"]` (or
  similar, matching whatever the repo convention evolves to —
  `pyproject.toml` currently only has `[tool.ruff]` blocks, so this chunk
  may add a minimal `[project]` table solely to park the dev dep; if that
  would conflict with the host installer, document the install command in
  the README and skip the `[project]` block). (b) Add a `[tool.coverage.run]`
  block (`branch = true`, `source = ["services"]`, `parallel = true`,
  `data_file = ".coverage"`) and a `[tool.coverage.report]` block
  (`skip_empty = true`, `exclude_also = ["if __name__ == .__main__.:",
  "raise NotImplementedError"]`) to `pyproject.toml`. (c) Add a `coverage`
  target to the Makefile that: (i) deletes any stale `.coverage*`,
  (ii) runs each `services/<svc>/test_*.py` under
  `python3 -m coverage run --rcfile=pyproject.toml --append <script>`
  so the three test invocations merge into one `.coverage` database,
  (iii) emits `coverage.json` and a `coverage.xml` at the repo root
  (keep both under `.gitignore` — this chunk also updates `.gitignore`),
  (iv) prints `coverage report` on stdout with a non-zero exit if
  anything below a conservative `--fail-under=0` threshold (deliberately
  0 for now; the follow-up proposal will raise it once we know what the
  actual number is — see memory 0003: don't ship a number we haven't
  seen on a real run). No CI change in this chunk; the point is to have
  the local invocation working and the config stable before wiring it
  into the build.

- [ ] **Chunk 2 — Wire `make coverage` into `.github/workflows/ci.yml`
  and upload a `coverage-json` artifact.** (a) Add `coverage>=7.6` to
  the `pip install` step. (b) Replace the three `make X-test` steps on
  the Python 3.13 matrix entry with a single `make coverage`
  invocation; keep the 3.12 entry on the existing non-coverage steps so
  the matrix still tests the pre-coverage invocation path and we don't
  pay the coverage instrumentation cost twice (coverage data from a
  matrix build is ambiguous without `coverage combine` across cells —
  this is a known trap worth avoiding, since mixing 3.12 and 3.13
  `.coverage` files is safe but doubles the artifact and halves the
  clarity). Guard the coverage-producing step with
  `if: matrix.python-version == '3.13'`. (c) After `make coverage`,
  append `coverage report --format=markdown` to `$GITHUB_STEP_SUMMARY`
  so a per-PR summary surfaces in the GitHub UI (this is the "publish
  a per-PR summary" clause from the gap's proposed_action). (d) Upload
  `coverage.json` as a workflow artifact via
  `actions/upload-artifact@<SHA> # v4`, name `coverage-json`,
  retention-days ≈ 30 (matches the push-to-main lookback used by the
  other CI metrics). Pin the action by commit SHA in the same
  `actions/checkout@<sha> # v5` style the rest of this workflow uses;
  per `[[0005-gitleaks-action-v2-dead-use-v3]]`, never ship a bare
  `@vN` on a Node-based action.

- [ ] **Chunk 3 — Teach the auditor to read coverage from the latest
  successful main-branch CI run.** (a) New file
  `services/auditor/coverage_api.py`, modeled on `ci_api.py`: given a
  resolved `(owner, repo)` and a token, GET
  `/repos/{o}/{r}/actions/workflows/ci.yml/runs?branch=main&status=success&per_page=5`,
  take the newest `workflow_run.id`, GET
  `/repos/{o}/{r}/actions/runs/{id}/artifacts`, locate the
  `coverage-json` artifact, download the zip via
  `archive_download_url`, unzip in-memory (`zipfile.ZipFile` on a
  `BytesIO`), parse the first `*.json` entry, and return
  `{"coverage_percent": round(totals.percent_covered, 1),
  "coverage_measured": True, "coverage_source_run_id": <id>}`. Return
  `{"coverage_measured": False, "coverage_percent": None, "_note":
  "..."}` on any failure (no token, no successful run in window, no
  artifact on the run, zip parse error, 404/403). (b) Update
  `audit_testing()` in `audit.py` to call this when `GH_TOKEN` is
  available and merge the result into the returned dict. (c) Remove
  `testing.coverage_percent` from the `NOT_MEASURED` list. (d) In
  `derive_gaps()`, change the condition that emits
  `testing-b2bebce2d9` from `if not tests["coverage_measured"]:` to
  one that continues emitting the same gap when the artifact is
  missing but phrases the detail as "CI didn't produce a coverage
  artifact on the most recent main-branch run" vs the current "V0
  audit only counts test files" — so the gap stays stable but
  becomes self-healing once the artifact is in place. (e) Unit
  tests in `services/auditor/test_coverage_api.py` mocking
  `urllib.request.urlopen` end-to-end: one happy-path case (returns
  `{"totals": {"percent_covered": 73.4}}`), one no-artifact case,
  one no-token case, one zip-corrupt case. Important: per memory
  `[[0003-gh-actions-api-branch-filter-hides-pr-runs]]`, unit-test
  coverage of the reducer is not sufficient — the measurement plan
  below requires a live audit run as the definition-of-done for this
  chunk.

Three chunks is near the ~5-chunk ceiling in `_template.md`; splitting
chunk 3 further (e.g. "add coverage_api.py" + "wire it into audit.py") is
tempting but would leave an intermediate commit in which the file exists
but is unused, which doesn't buy anything.

## Measurement plan

- **Metrics to watch:** `testing.coverage_measured`,
  `testing.coverage_percent`.
- **Guard metrics:**
  - `ci.median_runtime_seconds` — coverage instrumentation adds
    overhead; the current 17 s median gives plenty of headroom for a
    low-double-digit-percent increase before the `>= 300 s` soft
    ceiling the original CI proposal set is at risk. Treat a >25%
    adverse rise as a signal that the instrumented matrix cell should
    switch from `--branch` to line-coverage-only, or that the
    `services` source filter is too broad (e.g. pulling in generated
    files).
  - `ci.success_rate_30d` — must stay `>= 0.80` (the original CI
    proposal's floor). If the coverage-producing step itself starts
    flaking the build, that's a worse outcome than not measuring
    coverage at all, and the fix is to switch the coverage step to
    `continue-on-error: true` while the root cause is diagnosed.
  - `testing.test_to_source_ratio` — should not materially drop; this
    proposal adds no new source files unrelated to the measurement
    integration (`coverage_api.py` is counted as source, its test as
    test, so the ratio moves ≈ 0 by construction). A visible drop
    would mean something unexpected landed; investigate before calling
    the outcome.
- **Sampling cadence:** one audit immediately after chunk 3's PR merges
  (the remeasure dispatcher fires this; it will be the first audit run
  where chunk 2's uploaded artifact exists for chunk 3 to read), plus
  the next regular weekly audit. Both rows appended to the Outcome
  section.
- **Success threshold:**
  1. `testing.coverage_measured == true` in the post-merge audit row
     — strict boolean.
  2. `testing.coverage_percent` is a real number in `[0.0, 100.0]`
     (not `null`). We deliberately **do not** require the first-seen
     coverage number to exceed any threshold. The point of this
     proposal is to establish measurement; raising coverage to a
     target is a separate follow-up proposal once we know the
     baseline.
- **What would falsify it:** post-audit still reads
  `coverage_measured: false` or `coverage_percent: null`. Possible
  causes, ordered by likelihood (and all actionable without
  abandonment):
  1. The CI artifact upload failed on the chunk-3 merge PR
     specifically (chunk 3's own PR doesn't produce an artifact if
     the matrix 3.13 cell is red for an unrelated reason). The fix
     is to re-run CI and re-remeasure, not to abandon.
  2. `coverage_api.py` can't locate the artifact because the most
     recent successful main-branch CI run is older than the
     retention window. The retention-days setting in chunk 2 is set
     to ~30 to make this unlikely, but if it bites, extend
     retention.
  3. `urllib.request`'s zip handling can't decode the artifact zip
     — fallback is to try `response.read()` as a tarball or to
     fetch the `logs_url` and parse `coverage report` output.
     Documented in `coverage_api.py`'s `_note`.
  4. Token scope insufficient for `actions/artifacts` — surfaces as
     403 with a specific response body; the function already
     degrades gracefully in that case, and a mis-scoped token will
     be flagged by the existing `_not_measured()` `_note` path
     rather than silently reading `null`. This is a measurement
     fault, not a suite fault, so iterate on the fetcher.
  Abandon only if the whole coverage.py pathway proves
  incompatible with the standalone-script test runner (unlikely —
  `coverage run <script>` is coverage.py's oldest invocation).
- **Dogfood clause** (per
  `[[0003-gh-actions-api-branch-filter-hides-pr-runs]]`): chunk 3's
  definition-of-done requires one end-to-end audit against this very
  repo with `GH_TOKEN` set, reading a real artifact from a real
  chunk-2 CI run — unit tests alone pass the branch audit but can't
  catch a URL-construction or zip-layout bug. The remeasure
  dispatcher's audit run after chunk 3 merges *is* that dogfooding
  — a green remeasure row is the signal, a `null`-with-`_note`
  remeasure row is the fail.

## Research / prior art

- **Considered:** `pytest-cov` (<https://pytest-cov.readthedocs.io/>).
  The ergonomic default when the test runner is pytest. Rejected:
  this repo invokes test files as standalone scripts
  (`python3 test_<svc>.py`), not via `pytest` the entry point — so
  `pytest-cov`'s pytest-plugin hook never fires. `coverage.py`
  directly supports `coverage run <script>` with `--append` across
  multiple invocations, which maps 1:1 onto the Makefile shape.
  Switching the runner to pytest just to use pytest-cov is a
  separate (and probably desirable but out-of-scope) change.
- **Considered:** Codecov / Coveralls service integration
  (<https://docs.codecov.com/>, <https://coveralls.io/>).
  Rejected: adds a third-party dependency and account, and the
  auditor-reads-GH-artifact path already matches the pattern
  `ci_api.py` set. If a future proposal wants prettier PR
  comments and trend charts, upgrading to Codecov is a cheap
  additive change on top of this — `coverage.json` is the format
  both tools consume.
- **Considered:** `slipcover` (<https://github.com/plasma-umass/slipcover>).
  Faster than coverage.py but less universally supported and the
  JSON output format is coverage.py-compatible-but-not-identical.
  Rejected on maturity — the CI delta here is 15 → ~20 s even in
  the worst case; the extra engineering isn't paying for
  anything measurable.
- **Picked:** `coverage.py` 7.6.x
  (<https://coverage.readthedocs.io/>) — the de-facto standard
  for Python coverage, zero-dep beyond itself, directly supports
  `coverage run --append <script>`, emits JSON (`coverage json`)
  and markdown (`coverage report --format=markdown` since 7.0),
  and is what the gap's `proposed_action` names verbatim.
- **GitHub Actions references consulted:**
  - `actions/upload-artifact@v4` migration notes
    (<https://github.com/actions/upload-artifact#v4-what-is-new>)
    — v3 is deprecated; v4 is the current live line.
  - Job summary via `$GITHUB_STEP_SUMMARY`
    (<https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions#adding-a-job-summary>)
    — renders Markdown in the Actions UI and on PRs with the
    "View summary" link, which is "a per-PR summary" that
    doesn't require posting a bot comment.
  - `GET /actions/runs/{id}/artifacts` + `archive_download_url`
    (<https://docs.github.com/en/rest/actions/artifacts>) — the
    endpoint `coverage_api.py` will use.

## Effort & risk

- **Effort:** 3 PRs, ~3–5 hours dispatcher time total. Chunk 1 is a
  pyproject + Makefile edit plus a trivial `.gitignore` entry.
  Chunk 2 is a workflow YAML edit — one new matrix conditional,
  one upload step. Chunk 3 is the fattest: new module (~80 LOC)
  plus the test file, plus the integration into `audit_testing`.
- **Risk:**
  1. **Instrumentation inflates CI runtime** (addressed by guard
     metric above). The `--branch` flag is the most expensive;
     if the guard trips, dropping to line-only is a one-line
     revert.
  2. **Matrix ambiguity** — running coverage on both 3.12 and
     3.13 would produce two artifacts and a "which one does the
     auditor read" question. Chunk 2's `if: matrix.python-version
     == '3.13'` guard avoids this; the 3.12 cell still runs the
     non-coverage test steps so it isn't a wasted matrix entry.
  3. **Coverage source-path drift** — the `source = ["services"]`
     filter is tied to the current repo layout. If services move
     (e.g. a future monorepo split), the config needs a
     corresponding change. Low-frequency risk, but worth a
     comment in `pyproject.toml` noting the coupling.
  4. **Artifact-based measurement is lossy** — if someone
     force-pushes to main or deletes a workflow run, the
     artifact goes with it. The retention-days setting + the
     auditor's `_not_measured()` fallback bound the blast
     radius; the worst case is a weekly audit cycle that reads
     `null` for coverage, which is the current baseline
     anyway.
  5. **Per memory `[[0005-gitleaks-action-v2-dead-use-v3]]`**: a
     stale `@v3` pin on `actions/upload-artifact` could silently
     break if the runner image drops the required Node version.
     This is a low-but-real failure mode; pinning by SHA and
     noting the Node-runtime assumption in the workflow comment
     is the mitigation.
- **Mitigations:**
  - All three chunks are strictly additive to CI — the
    pre-coverage `make X-test` steps remain on the 3.12 matrix
    cell, so a coverage-side break can't take the whole gate
    down.
  - Chunk 3's auditor integration is behind a token-gate (no
    `GH_TOKEN` → the function returns the current `null`
    reading), so the weekly offline audit path remains
    unchanged.
  - The `--fail-under=0` in chunk 1 is deliberate: no
    optimistic threshold shipped before we've seen a real
    number. A follow-up proposal raises it against a known
    baseline, matching the pattern the CI proposal set.

## Outcome

> *TBD — appended after the re-measure step.*

| Metric | Baseline | Post-execution | Δ | Target | Verdict |
|---|---|---|---|---|---|
| `testing.coverage_measured` | `false` | | | `true` | |
| `testing.coverage_percent` | `null` | | | real number in `[0, 100]` | |
| `ci.median_runtime_seconds` *(guard)* | `17` | | | no adverse >25% rise | |
| `ci.success_rate_30d` *(guard)* | `1.0` | | | `>= 0.80` | |
| `testing.test_to_source_ratio` *(guard)* | `0.643` | | | not materially down | |
