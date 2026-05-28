# Metrics — what we track and why

The autonomous-coder picks its initiatives from *measured* gaps, not vibes. To
keep that selection grounded, every metric in the audit ([`services/auditor/`](../services/auditor/))
maps to a published leading indicator from one of three frameworks. A
proposal that doesn't cite at least one of these capabilities isn't a valid
proposal — see [`proposals/_template.md`](../proposals/_template.md).

## The three anchors

- **DORA** (Forsgren, Humble, Kim — *Accelerate*, and the annual *State of
  DevOps* reports). Four outcome metrics plus **24 technical/cultural
  capabilities** shown to drive them. We anchor most code-quality, testing,
  and devops metrics here.
- **SPACE** (Forsgren, Storey, Maddila, Zimmermann, Houck, Butler — 2021).
  Broader than DORA: Satisfaction, Performance, Activity, Communication,
  Efficiency. Useful where DORA undersells developer experience / flow.
- **OpenSSF Scorecard + NIST SSDF**. The supply-chain / security /
  compliance side: signed releases, branch protection, dependency pinning,
  vulnerability disclosure, etc. We anchor the security and supply_chain
  audit sections here.

A proposal can cite more than one anchor — usually does.

## The starter metric set (V0)

Cheap to compute (mostly git + filesystem), spread deliberately across the
focus areas the autonomous-coder is asked to improve (code quality,
testability, devops/infra, security/compliance).

| Audit section | Metric | Anchor | V0 source |
|---|---|---|---|
| **commits** | Count / lookback | DORA *Activity* (SPACE) | `git log --since=…` |
| | Median lines changed | DORA *Working in small batches* (proxy for PR size) | `git log --shortstat` |
| | p95 lines changed | DORA *Working in small batches* (tail) | `git log --shortstat` |
| | Distinct authors | DORA *Team capability*; SPACE *Communication* | `git log --pretty=%ae` |
| **ci** | GitHub Actions present | DORA *Continuous Integration* | `.github/workflows/*.yml` |
| | Workflow count / runtime / flake rate | DORA *CI / Test reliability* | **deferred** — needs GH API |
| **testing** | Test files / source files | DORA *Test automation* (presence proxy) | filename pattern |
| | pytest config present | DORA *Test automation* | `pytest.ini`, `pyproject.toml`, … |
| | Coverage % | DORA *Test automation* (quality signal) | **deferred** — needs `coverage.py` |
| | Flake / mutation score | DORA *Test reliability* | **deferred** — `mutmut`/CI integration |
| **docs** | README present + length | SPACE *Communication / Efficiency* | filesystem |
| | LICENSE present | NIST SSDF *PO.1*; compliance hygiene | filesystem |
| | SECURITY.md present | OpenSSF Scorecard *Security-Policy* | filesystem |
| | CODEOWNERS present | DORA *Streamlining change approval* | filesystem |
| | Public-API doc coverage | SPACE *Efficiency* (cognitive load) | **deferred** — `interrogate` |
| **security** | gitleaks config present | DORA *Shift-left security* | filesystem |
| | Regex secret sweep findings | DORA *Shift-left security* (V0 placeholder) | regex |
| | OpenSSF Scorecard workflow | OpenSSF Scorecard | filesystem |
| | osv-scanner config | OpenSSF Scorecard *Vulnerabilities* | filesystem |
| **dependencies** | Manifest presence (`pyproject.toml`, `requirements.txt`, …) | OpenSSF Scorecard *Pinned-Dependencies* | filesystem |
| | Dependabot / Renovate config | OpenSSF Scorecard *Dependency-Update-Tool* | filesystem |
| | Vulnerable-dep count | DORA *Shift-left security* | **deferred** — `osv-scanner` |
| **iac** | Dockerfile / compose present | DORA *Deployment automation* | filesystem |
| | Terraform / Helm / Ansible | DORA *Version control of production artifacts* | filesystem |
| | Makefile present | SPACE *Efficiency* (low-friction commands) | filesystem |
| **shape** | Total tracked files; language mix | Context for every other metric | filesystem |

**Deferred ≠ unimportant.** Every `deferred` row is an explicit gap the auditor
will surface in its output (as `_note` + a `not_measured` flag), so the
proposal step picks it up and proposes the tool that should measure it.

## How metrics are stored

```
.dolios/metrics/<repo>/history.jsonl     # one full snapshot per line, schema-versioned
```

Append-only. Schema version bumps require a one-time migration script committed
alongside the bump (Phase 5 may move this to Postgres; the JSONL stays as the
canonical export).

## What a proposal does with this

A proposal is a markdown PR ([`proposals/_template.md`](../proposals/_template.md))
that must include:

1. **The metric(s) it targets** and the audit row(s) it cites.
2. **The framework capability** it improves (DORA / SPACE / OpenSSF / NIST).
3. **Baseline** — current measured value (or "establish measurement" if the
   metric is currently `not_measured`).
4. **Intervention** — what concrete change is proposed.
5. **Measurement plan** — how we'll know it worked (same metric, sampling
   cadence, threshold for "succeeded").
6. **Effort & risk** estimate.

So every initiative is a falsifiable hypothesis: *adopting X should move
metric M from baseline B to ≥ T within W audit cycles.*

## Reading

- Forsgren, Humble, Kim — *Accelerate: The Science of Lean Software and DevOps* (IT Revolution, 2018).
- Forsgren, Storey, Maddila, Zimmermann, Houck, Butler — *The SPACE of Developer Productivity* (ACM Queue, 2021).
- Google Cloud — annual *State of DevOps Report* (DORA).
- OpenSSF — *Scorecard* checks reference (`github.com/ossf/scorecard`).
- NIST — *Secure Software Development Framework (SSDF) — SP 800-218*.
