# `?branch=main` on the Actions runs API excludes pull_request-triggered runs

## Context

Remeasure of `proposals/dolios/2026-05-28-adopt-github-actions-ci.md`
(2026-11-14) showed `ci.test_runs_on_pr == false` even though every merged
chunk (#14–#18) had been built via a PR with the `pull_request` trigger in
`.github/workflows/ci.yml`. `median_runtime_seconds` and `success_rate_30d`
populated correctly from the same API response, so the token and parsing
were fine. The miss traced to `services/auditor/ci_api.py:_fetch_runs`:

```python
url = f"{GH_API}/repos/{owner}/{repo}/actions/runs?branch=main&per_page=100"
```

GitHub records a `workflow_run`'s `branch` as the ref the workflow checked
out. For `pull_request` events that's the PR's **head** ref
(`auto/coder/...` on this repo), not `main`. So `?branch=main` returns
`push`-to-main runs *only* — the exact event class `test_runs_on_pr` is
trying to detect is filtered out before `_compute` ever sees it.

The chunk-3 unit test mocked `_compute`'s input directly, so it never
exercised the `_fetch_runs` URL and never caught the bug.

## Lesson

When measuring "did this CI fire on PRs?", either:

1. Drop the `branch=` filter entirely and let `_compute` filter by event
   (safer: the lookback window already bounds the response size).
2. Make two calls — one unfiltered for the `pull_request` scan, one
   `branch=main` for the push-to-main runtime/success stats — and merge.

Option 1 is simpler for the current page-size (100 runs covers weekly
cadence easily).

Separately: any PR that claims to "flip a metric from `not_measured` to
measured" should include a proof-of-life audit run against a real repo,
not just a mocked unit test. Mocks verify the reducer; they can't catch a
wrong API query.

## Apply to

- The follow-up proposal that fixes `ci_api.py` (expected to be filed
  shortly after this remeasure lands).
- Any future auditor extension that adds a new `not_measured` → measured
  flip: the chunk's definition-of-done must include one end-to-end audit
  against a real repo with the needed credentials, not just a mocked test.
- Related anti-pattern to watch: `?branch=main` on any GH REST endpoint
  where the event of interest is `pull_request` (`/commits`,
  `/check-runs`, `/actions/runs`). All follow the same head-ref rule.

Related: [[0002-chunk-mode-claude-must-not-touch-proposal]] — same family
of "unit tests passed, integration didn't" lessons.
