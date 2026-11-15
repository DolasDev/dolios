---
id:     dolios/2026-11-15-fix-ci-pr-runs-measurement
status: proposed
repo:   dolios
audit:  .dolios/metrics/dolios/history.jsonl#L7@2026-11-15T03:30:56Z
gap_ids:
  - ci-5967d1e056
metrics:
  - ci.test_runs_on_pr
  - ci.median_runtime_seconds
  - ci.success_rate_30d
frameworks:
  - "DORA: Continuous Integration"
  - "OpenSSF Scorecard: CI-Tests"
opened:    2026-11-15
approved:  null
done:      null
---

# Drop the `branch=main` filter so the auditor can see PR-triggered CI runs

## Hypothesis

> Removing the `?branch=main` query parameter from the GitHub Actions runs
> fetch in `services/auditor/ci_api.py` should move **`ci.test_runs_on_pr`**
> from baseline **`false`** to **`true`** within **one audit cycle** because
> `workflow_run.branch` is set to the PR's head ref (not `main`) for
> `pull_request`-triggered runs, so the branch filter deterministically
> excludes the exact event class the metric is trying to detect — and the
> `pull_request` trigger is already configured in `.github/workflows/ci.yml`
> and firing on every autonomous-coder PR, so unfiltered data will contain
> ample positive examples.

The thing being tested is: is the `test_runs_on_pr: false` reading a
*measurement* defect (the API filter hides PR runs) or a *gating* defect
(CI doesn't actually run on PRs)? The workflow file says the former. If
after this fix the metric still reads `false`, the hypothesis is
falsified and the real cause is elsewhere (token scope, API pagination,
`_compute` lookback bounds, etc.) — see the Measurement plan.

## Audit citation

- **Audit row:** `.dolios/metrics/dolios/history.jsonl` line 7
  (`audited_at: 2026-11-15T03:30:56Z`, `git_head: 83b4833…`).
- **Gap targeted:** `ci` / "CI runs not observed on pull requests"
  (severity: `medium`, `gap_id: ci-5967d1e056`). The gap's own `detail`
  cites `[[0003-gh-actions-api-branch-filter-hides-pr-runs]]` as the
  likely cause, which is the hypothesis this proposal operationalizes.
- **Frameworks:**
  - `DORA: Continuous Integration` — the four-key capability requires
    that every change pass automated verification before merge; a
    metric that can't detect PR-time runs can't tell us whether we're
    doing that or not. The *Accelerate* book's Continuous Integration
    chapter is explicit that "developers should be checking in to
    trunk at least daily … and automated tests should run on every
    change."
  - `OpenSSF Scorecard: CI-Tests` — the check awards points based on
    whether tests run on pull requests. The Scorecard spec
    (<https://github.com/ossf/scorecard/blob/main/docs/checks.md#ci-tests>)
    describes probing recent PRs for a non-failing CI run, which is
    functionally the same question this metric asks.

## Baseline

Taken from the cited audit row (line 7).

| Metric | Current | Source |
|---|---|---|
| `ci.test_runs_on_pr` | `false` | audit row above |
| `ci.median_runtime_seconds` *(guard)* | `17` | audit row above |
| `ci.success_rate_30d` *(guard)* | `1.0` | audit row above |

Context from the same row: `ci.github_actions_present: true`,
`ci.workflow_count: 1`, `ci.workflow_files: [".github/workflows/ci.yml"]`.
The workflow file itself declares `on: { pull_request: { branches: [main] },
push: { branches: [main] } }`, and PRs #28, #30, #31, #33 all show green
CI runs in GitHub's UI — so the `false` reading is definitionally a
measurement artefact as long as the auditor can see those runs via
the API.

## Intervention

- [ ] **Drop the `?branch=main` filter in `_fetch_runs`** — in
  `services/auditor/ci_api.py`, change the request URL from
  `…/actions/runs?branch=main&per_page=100` to
  `…/actions/runs?per_page=100`. Update the docstring to drop the
  "filtered to the main branch" phrasing and briefly note that
  per-event classification happens in `_compute`. Add a new unit test
  in `services/auditor/tests/test_ci_api.py` (or the existing nearest
  equivalent) that:
  1. feeds `_compute` a payload with a `pull_request`-event run whose
     `head_branch` is `auto/coder/example` (not `main`) and asserts
     `test_runs_on_pr == True` — this catches the regression that
     would reappear if someone re-added a branch filter;
  2. uses `unittest.mock.patch("urllib.request.urlopen", …)` on
     `gh_ci_metrics` end-to-end and asserts the request URL does
     **not** contain `branch=` — i.e. the fix is encoded as a test
     invariant, not just a code change. This is the piece memory 0003
     explicitly asks every `not_measured → measured` flip to include:
     a test that exercises `_fetch_runs`'s URL construction rather
     than only `_compute`'s reducer.

One chunk is sufficient; the change is a two-character edit plus two
tests, well inside one dispatcher's PR budget, and there is no
intermediate state that benefits from splitting (either both land or
neither does).

## Measurement plan

- **Metric to watch:** `ci.test_runs_on_pr`.
- **Guard metrics:**
  - `ci.median_runtime_seconds` — may shift modestly because unfiltered
    runs now include PR builds, which run the same matrix as `push`
    builds; expect low single-digit seconds of movement in either
    direction. Treat >25% adverse rise (per our usual guard convention)
    as a signal that the extra runs are unrepresentative and worth
    investigating.
  - `ci.success_rate_30d` — similar reasoning. PR runs *could* include
    failed early-iteration attempts that were force-pushed over; expect
    this to stay near `1.0` given the autonomous coder's current clean
    track record, but a drop below `0.80` (the proposal that introduced
    the field set this as the floor) would warrant attention.
- **Sampling cadence:** one audit immediately after the chunk's PR
  merges (triggered by the remeasure dispatcher), and then the next
  regular weekly audit as a confirmation. Both rows appended to the
  Outcome section.
- **Success threshold:** `ci.test_runs_on_pr == true` in the
  post-merge audit row. Given the chunk's own PR will trigger a
  `pull_request` event on merge-queue entry, there is guaranteed to
  be at least one qualifying run inside the 90-day lookback window
  the moment the fix lands.
- **What would falsify it:** post-audit still reads `false`. Possible
  causes, ordered by likelihood:
  1. Pagination — 100 runs is the cap and this repo could in principle
     age PR runs out of the first page. Current 90-day commits count
     is 21 and workflow_count is 1, so the first page comfortably
     covers the window; if this reads false regardless, inspect
     `response["total_count"]` versus `per_page`.
  2. `_compute`'s `cutoff_lookback` discarding every PR run as too
     old — would require every PR-event run on the repo to be >90
     days old, which given the activity log is not the case.
  3. Token scope — the API returns runs for the auth'd token's
     visible repos; a mis-scoped token would surface as 404/403 and
     the function already returns `_not_measured()` with a `_note` in
     that case, which would be visible rather than silent.
  Any of these is interesting; iterate rather than abandon. Abandon
  only if the gap moves from "the metric is wrong" to "there is no
  PR-time CI happening at all", which we can rule out by hand from
  the GitHub UI before resorting to abandonment.

## Research / prior art

- **Considered:** fetching a separate paginated listing per workflow
  (`/repos/{o}/{r}/actions/workflows/{id}/runs`) and merging — more
  expensive, two-round-trip, and doesn't add signal the single
  unfiltered `actions/runs` call already provides on a repo with one
  workflow file. Rejected.
- **Considered:** the two-call approach from memory 0003's "Option 2"
  — one unfiltered call for the `pull_request` scan plus one
  `branch=main` call to preserve the push-to-main semantics of the
  runtime/success-rate fields. Rejected for the current page-size
  regime (per memory 0003: "100 runs covers weekly cadence easily");
  including PR runs in the runtime/success aggregates is arguably more
  faithful to the "typical CI time users experience" question anyway,
  and the guard thresholds above will flag if it introduces noise.
- **Picked:** Option 1 from memory 0003 — drop the `branch=` filter
  entirely and let `_compute`'s per-event logic do the classification.
  The reducer already filters by `created_at >= cutoff_lookback`, so
  the response-size risk is bounded by the lookback window, not by
  the branch filter.
- **GitHub REST reference consulted:**
  - `GET /repos/{owner}/{repo}/actions/runs` API —
    <https://docs.github.com/en/rest/actions/workflow-runs?apiVersion=2022-11-28#list-workflow-runs-for-a-repository>.
    The `branch` parameter is documented as filtering by the branch
    `workflow_run.head_branch`, which for `pull_request` events is the
    PR's head, not the base. This is the mechanism memory 0003
    diagnosed empirically; the docs confirm it is working as
    specified, so our filter was simply wrong.
  - OpenSSF Scorecard `CI-Tests` check doc —
    <https://github.com/ossf/scorecard/blob/main/docs/checks.md#ci-tests>.

## Effort & risk

- **Effort:** one PR, ~1h dispatcher time. Two-character URL edit plus
  one or two new tests; no new dependencies.
- **Risk:**
  1. The unfiltered page could include runs from feature branches
     users didn't intend to count in `median_runtime_seconds`. This is
     mostly a non-issue on this repo (one workflow file, all branches
     run the same matrix), but worth flagging; the guard thresholds
     catch the adverse case.
  2. Token-rate-limit pressure from the larger-returned page is
     negligible — the JSON page cap is still 100 runs, the request
     count is unchanged, and the audit runs weekly.
  3. Regression risk from editing a hot path in the auditor is low
     because the function is behind a token-gate (`if not token`
     short-circuits to `_not_measured`), and offline audits do not
     exercise this code path at all. The new URL-assertion test
     prevents the specific regression memory 0003 warned about.
- **Mitigations:**
  - URL-assertion unit test encodes the fix as a positive invariant,
    not just as the absence of `branch=main`.
  - If the post-audit shows an adverse guard move, a follow-up
    proposal can adopt memory 0003's Option 2 (two calls, merge); we
    don't need to pre-commit to it now.
  - The auditor's existing `_not_measured` fallback on `URLError` /
    `OSError` means a transient API failure after the change still
    degrades gracefully rather than aborting the audit.

## Outcome

> *TBD — appended after the re-measure step.*

| Metric | Baseline | Post-execution | Δ | Target | Verdict |
|---|---|---|---|---|---|
| `ci.test_runs_on_pr` | `false` | | | `true` | |
| `ci.median_runtime_seconds` *(guard)* | `17` | | | no adverse >25% rise | |
| `ci.success_rate_30d` *(guard)* | `1.0` | | | `>= 0.80` | |
