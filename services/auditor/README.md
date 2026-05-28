# auditor

The deterministic half of the discovery loop. Audits a repo and emits a
structured JSON snapshot of code/architecture quality metrics — ranked **gaps**
included — that the proposal-generation step (Claude Code) reads to produce
intervention plans. Anchored in DORA / SPACE / OpenSSF so nothing is arbitrary.

See [`docs/metrics.md`](../../docs/metrics.md) for the full metric set + the
literature anchors; [`proposals/README.md`](../../proposals/README.md) for the
lifecycle the audit feeds.

## Run it

```sh
make audit                                              # audits this repo, appends history
python3 services/auditor/audit.py --repo <path> --name <slug>
python3 services/auditor/audit.py --repo <path> --name <slug> --gaps   # just the ranked gaps
python3 services/auditor/audit.py --repo <path> --name <slug> \
    --history .dolios/metrics/<slug>/history.jsonl       # append a history row
```

Snapshots accumulate at `.dolios/metrics/<slug>/history.jsonl` — one JSON line
per audit. The schema is versioned (`schema_version` in every row) so older
rows stay readable across changes.

## V0 scope — and what's *deliberately* "not_measured"

V0 uses **git + filesystem only**. No new install footprint, runs anywhere,
the first audit lands in a clean PR. That means a chunk of the metric set is
intentionally reported as `not_measured` with a `_note` pointing at the tool
that would measure it properly:

| Area | Tool the proposal will adopt | Why deferred |
|---|---|---|
| Test coverage % / flake rate | `coverage.py`, CI re-run analysis | Needs running tests + CI log access |
| Public-API doc coverage | `interrogate` | New dep + per-language tuning |
| Cyclomatic complexity, duplication | `radon`, `jscpd` | New deps; output schema tuning |
| Real secrets scan | `gitleaks` | Replaces V0's regex placeholder |
| Vulnerable dependencies | `osv-scanner` / Dependabot | Needs network + per-ecosystem manifests |
| OpenSSF Scorecard score | `scorecard-action` workflow | Needs CI to host the workflow first |
| Deploy freq / lead time / change-failure rate (DORA outcomes) | GH API + deploy log | Needs CI history first |

This is **the point**: V0's first audit will identify "no CI", "no coverage",
"no real secrets scanner", "no Dependabot" — and each becomes its own proposal
to adopt the proper tool. The auditor improves *itself* through the proposal
pipeline it feeds.

## Output shape (truncated)

```json
{
  "schema_version": 1,
  "audited_at": "2026-05-28T...",
  "repo": "dolios",
  "git_head": "07c9a5b...",
  "git_branch": "main",
  "metrics": {
    "commits":      { "count": 25, "median_lines_changed": 47, ... },
    "ci":           { "github_actions_present": false, ... },
    "testing":      { "test_files": 3, "source_files": 5, "coverage_measured": false, ... },
    "docs":         { "license_present": false, "security_md_present": false, ... },
    "security":     { "gitleaks_config_present": false, "regex_secret_finding_count": 0, ... },
    "dependencies": { "dependabot_config": false, ... },
    "iac":          { "dockerfile_present": true, "compose_present": true, ... },
    "shape":        { "files_by_language": {"python": 6, "yaml": 5, ...} }
  },
  "gaps": [
    {
      "area": "ci",
      "severity": "high",
      "frameworks": ["DORA: Continuous Integration", "DORA: Deployment Automation"],
      "summary": "No CI workflows detected",
      "detail": "...",
      "proposed_action": "..."
    },
    ...
  ]
}
```

Every `gap` cites at least one framework capability (DORA / OpenSSF / NIST
SSDF / SPACE) so the proposal step always has a leading-indicator anchor to
quote — proposals justify themselves by pointing at the research.

## Tests

```sh
cd services/auditor && python3 test_audit.py
```

Fixture-based, no network, no external tools. 7/7 cover the section outputs,
the gap-ranking, the framework-citation requirement, and the history append.
