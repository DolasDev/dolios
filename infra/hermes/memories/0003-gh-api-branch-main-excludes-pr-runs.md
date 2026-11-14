# `GET /actions/runs?branch=main` excludes `pull_request`-triggered runs

## Context

Remeasure of `proposals/dolios/2026-05-28-adopt-github-actions-ci.md` on
2026-11-14 found `ci.test_runs_on_pr = false` even though CI workflow runs
had demonstrably fired on PRs #15–#18 in the lookback window. The workflow
file (`.github/workflows/ci.yml`) triggers on `pull_request` against main
AND `push` to main, so pull-request-triggered runs do exist.

Root cause: `services/auditor/ci_api.py::_fetch_runs` builds the request URL
as `?branch=main&per_page=100`. The GH REST API documents `branch` as
filtering workflow runs "associated with a branch" — and for
`pull_request`-triggered runs that is the **head (feature) branch of the
PR**, not `main`. Combined, `?branch=main` returns only `push`-to-main runs
and merge-commit runs, systematically excluding every `pull_request` event.
The downstream loop in `_compute` then never sees an `event == "pull_request"`
record and `test_runs_on_pr` stays `False`.

`median_runtime_seconds` and `success_rate_30d` were not affected because
the push-to-main runs after merge are themselves completed workflow_runs
and populate both of those fields correctly — only the PR-triggered flag
was silently wrong.

## Lesson

Two options for the fix, pick based on quota:

1. Drop the `branch=` filter entirely from `_fetch_runs` and do all the
   partitioning client-side in `_compute`. Simplest; costs one page of
   extra rows at most (per_page=100 is fine for weekly cadence).
2. Issue two queries — one `?branch=main` for the main-branch perf numbers,
   one `?event=pull_request&per_page=100` for the PR flag — and merge. Keeps
   the main-branch page small but doubles the API calls.

Either way: any metric whose definition is "did event X happen anywhere"
cannot be measured by a `branch=`-filtered query. More generally, when
mapping an audit metric to a GH API endpoint, check whether the audited
property can occur on branches the filter will exclude.

Falsifiability guardrail the proposal missed: a measurement whose value is
a boolean should be covered by a test that forces both polarities
(`true` + `false`), not just the "happy path." The chunk-3 mocked test only
exercised a positive `pull_request` run — a mock returning only
`branch=main`-passing events would have caught this by always returning
`test_runs_on_pr = false` regardless of what events were present.

## Apply to

- Any future proposal that adds a new GH-Actions-API-derived audit field —
  before trusting the number in an Outcome table, verify the API query
  does not filter out the event class the field measures.
- Any auditor change that introduces a new boolean metric — require the
  accompanying test to cover both polarities, not just one.
- Remeasure cycles in general: when a boolean flips the "wrong" way, check
  whether the measurement is wrong before concluding the intervention is
  wrong.

Related: [[0002-chunk-mode-claude-must-not-touch-proposal]] — the chunk-3
dispatcher wrote the (buggy) ci_api module without the proposal's falsify-
both-polarities guardrail being visible in the chunk prompt. Future
`--proposal-mode` prompts should cite this memory when the chunk introduces
a new metric.
