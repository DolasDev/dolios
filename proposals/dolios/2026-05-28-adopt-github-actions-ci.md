---
id:     dolios/2026-05-28-adopt-github-actions-ci
status: approved
repo:   dolios
audit:  .dolios/metrics/dolios/history.jsonl#L2@2026-05-28T21:17:28Z
gap_ids:
  - ci-14fbad1f48
metrics:
  - ci.github_actions_present
  - ci.workflow_count
  - ci.test_runs_on_pr
  - ci.median_runtime_seconds
  - ci.success_rate_30d                # new metric introduced by chunk 3
frameworks:
  - "DORA: Continuous Integration"
  - "DORA: Deployment Automation"
  - "DORA: Test automation"
  - "OpenSSF Scorecard: CI-Tests"
  - "OpenSSF Scorecard: Pinned-Dependencies"
opened:    2026-05-28
approved:  null
done:      null
---

# Adopt GitHub Actions CI (and make CI itself measurable)

## Hypothesis

Adopting **GitHub Actions** as the per-PR CI signal — with the existing
`make audit-test usage-test coder-test` targets plus a `ruff check` lint pass —
should move **`ci.github_actions_present`** from **false** to **true** and
**`ci.workflow_count`** from **0** to **≥ 1** within **one audit cycle** (the
first weekly run after the first execution PR lands), because DORA's
*Continuous Integration* capability is operationally defined as "developers
integrate all their work into the main version of the code base on a regular
basis" with automated tests gating each integration — and the auditor measures
that capability by the presence and exercise of CI workflows on PRs. The
second arm of the hypothesis: extending the auditor to consult the GitHub
Actions API moves **`ci.median_runtime_seconds`** and
**`ci.test_runs_on_pr`** out of `not_measured: true` within one audit cycle of
the third chunk landing, so subsequent proposals (coverage, scorecard, secrets
scanning) have a real CI surface to attach to and a real per-PR feedback
budget to defend.

## Audit citation

- **Audit row:** `.dolios/metrics/dolios/history.jsonl` line 2,
  `audited_at: 2026-05-28T21:17:28Z` — the first row to carry the structured
  `gap_id` and `not_measured` fields (row 1 from the initial baseline carries
  identical findings without the structured ids, as it predates the scaffold
  fix). Citing the structured row so the `gap_ids:` reference resolves.
- **Gap targeted:** `gap_id: ci-14fbad1f48` — `ci` / "No CI workflows
  detected" (severity: **high**). Verbatim from the audit row: *"No
  .github/workflows/\*.yml and no other CI config — there is no automated
  test/lint/security signal on PRs."*
- **Frameworks:**
  - **DORA: Continuous Integration.** dora.dev defines CI as the practice
    that drives "higher deployment frequency, more stable systems, and higher
    quality software" via "rapid feedback loops and ensuring that developers
    work in small batches." (See `docs/metrics.md` mapping.)
  - **DORA: Deployment Automation.** A working CI is the precondition for
    automating any later deploy/release pipeline; the auditor lists both as
    the frameworks for this gap.
  - **DORA: Test automation.** The existing `*-test` targets (`audit-test`,
    `usage-test`, `coder-test`) are already test automation by construction —
    CI converts them from "runs when a human remembers" to "runs on every
    push."
  - **OpenSSF Scorecard: CI-Tests** (project runs tests in CI before merge)
    and **Pinned-Dependencies** (workflow `uses:` lines pinned by full SHA,
    not floating tags) are the supply-chain anchors. Pinning from PR #1
    avoids retrofit churn — the 2026 GH Actions roadmap is moving toward
    SHA-pinning as enforceable policy.
- **Why this gap first.** It is the only `severity: high` item in the audit;
  every other proposal in this repo (coverage, gitleaks, scorecard,
  dependabot) depends on a CI surface existing first. The auditor's other
  `_note: deferred` rows for `ci.*` can only be resolved by *having a CI
  pipeline whose runs can be queried* — so this is also the gate for moving
  CI metrics from `not_measured` to measured.

## Baseline

The cited audit row gives:

| Metric | Current | Source |
|---|---|---|
| `ci.github_actions_present` | `false` | audit row above |
| `ci.workflow_count` | `0` | audit row above |
| `ci.workflow_files` | `[]` | audit row above |
| `ci.other_ci_detected` | `false` | audit row above |
| `ci.test_runs_on_pr` | `null` (`not_measured`) | audit row above |
| `ci.median_runtime_seconds` | `null` (`not_measured`) | audit row above |

`ci.test_runs_on_pr` and `ci.median_runtime_seconds` are currently
`not_measured` per the auditor's `_note` ("runtime + flake rate need CI log
access (GH Actions API); planned as a proposal output"). Per
`proposals/README.md`, the first chunk that needs to flip them to measured is
written into the Intervention below.

## Intervention

Three execution-PR-sized chunks, landing in order. Each chunk is small enough
that one dispatcher run can produce it. Each execution PR flips its checkbox
below as part of the same commit, so a human reviewer sees the implementation
*and* the chunk-done state change in one diff.

- [x] **`.github/workflows/ci.yml` — the minimal first workflow.**
   - Path: `.github/workflows/ci.yml`.
   - Triggers: `pull_request` against `main`; `push` to `main`.
   - Concurrency group: `ci-${{ github.ref }}` with `cancel-in-progress: true`
     so superseded runs don't burn minutes.
   - One job, `test`, matrix `python-version: ["3.12", "3.13"]`,
     `runs-on: ubuntu-latest`.
   - Steps (each `uses:` pinned by full 40-char commit SHA, with the
     human-readable tag in a trailing comment per
     `docs.github.com/en/actions/reference/security/secure-use`):
     1. `actions/checkout@<sha> # v5`
     2. `actions/setup-python@<sha> # v6` with the matrix version.
     3. `pip install pytest ruff` (the repo is stdlib + pyyaml; no
        requirements file yet, so install the two dev tools inline).
     4. Run the three existing test targets verbatim:
        `make audit-test`, `make usage-test`, `make coder-test`.
     5. `ruff check services/` (linter only; no autofix in CI).
   - **Permissions:** top-level `permissions: { contents: read }` — least
     privilege, OpenSSF *Token-Permissions* satisfied by construction.
   - File-only PR; no code changes outside `.github/`.

- [x] **Minimal `pyproject.toml` for ruff config + tighten the `services/`
   lint.**
   - Path: `pyproject.toml` (new file at repo root).
   - Only the `[tool.ruff]` section: `line-length = 100`,
     `target-version = "py312"`, `[tool.ruff.lint] select = ["E", "F", "W",
     "I", "UP", "B"]` (errors, pyflakes, warnings, isort, pyupgrade,
     bugbear — the conservative starter set).
   - **Important:** also `extend-exclude = [".dolios", "infra/ollama"]` so the
     audit history and the model-puller artifacts don't get linted.
   - Run `ruff check services/` locally before opening the PR; if any rule
     trips on existing code, fix it in the same PR (so chunk 1 stays green on
     merge) — these will be tiny edits, not refactors. If a rule wants a
     non-trivial change, drop the rule from `select` and file a follow-up
     proposal instead.
   - Side benefit: `audit_dependencies()` will now see
     `python_pyproject_toml: true`, which closes a downstream
     `OpenSSF Scorecard: Pinned-Dependencies` doorway for later
     `[project.dependencies]` work.

- [x] **`services/auditor/ci_api.py` — flip the `ci.*` `not_measured` fields to
   measured.**
   - New module: `services/auditor/ci_api.py`. Function:
     `gh_ci_metrics(owner: str, repo: str, *, token: str | None,
     lookback_days: int = 90) -> dict`.
   - When `token` is `None` (offline / local-only audit run), return the
     same `null`-with-`_note` shape `audit_ci()` returns today — no
     behaviour change for unauthenticated runs.
   - When `token` is set, GET
     `https://api.github.com/repos/{owner}/{repo}/actions/runs?branch=main&per_page=100`
     (paginate one page; 100 is enough for weekly cadence) and compute:
     - `median_runtime_seconds`: median of
       `(updated_at − run_started_at)` across `completed` runs.
     - `success_rate_30d`: `success` / `completed` over the last 30 days.
     - `test_runs_on_pr`: `true` iff any `pull_request`-triggered run
       exists in the window.
   - Wire it into `audit_ci()`: read `GH_TOKEN` from env, owner/repo from
     `git remote get-url origin` parsing (or `--gh-repo OWNER/REPO` CLI
     flag if no remote — local-checkout-only case). Merge the returned
     dict into the existing return value.
   - Extend `derive_gaps()`: if `success_rate_30d` is measured and
     `< 0.80`, add a new gap `(area=ci, severity=high, frameworks=["DORA:
     Test reliability"])`. (Threshold derived from DORA's "elite"
     change-failure-rate band, conservatively floored.)
   - Add a `test_audit.py` case that mocks the API response and asserts
     the merged shape.

After chunk 3 merges, the dispatcher should manually trigger one audit run
against `dolios` with `GH_TOKEN` set, append the resulting row, and open the
Outcome-section PR against this proposal.

## Measurement plan

- **Metric(s) to watch:**
  - **Primary:** `ci.github_actions_present`, `ci.workflow_count`,
    `ci.test_runs_on_pr`, `ci.median_runtime_seconds`,
    `ci.success_rate_30d` (newly introduced).
  - **Guard metrics** (we do *not* want these to move adversely):
    `commits.median_lines_changed` (CI shouldn't push us to bundle changes;
    DORA "Working in small batches"), `commits.count` (CI shouldn't drop our
    activity — if it does, the workflow is gating too aggressively).
- **Sampling cadence:** every audit run. Current cadence is weekly per repo
  (`make audit` invoked from the supervisor cron); this proposal does not
  change that.
- **Success threshold:**
  - **After chunks 1 + 2 merge** (one audit cycle): `github_actions_present
    == true`, `workflow_count >= 1`, workflow has run on at least one PR
    against `main`. Strict.
  - **After chunk 3 merges** (one audit cycle): `test_runs_on_pr == true`,
    `median_runtime_seconds` is a number (not `null`) and is `< 300`
    (5 minutes — comfortable in the free tier and fast enough not to slow
    review). `success_rate_30d` populated.
  - **After 4 weeks of CI being live** (the "anti-test"): at least one PR
    has been blocked from merging by a failing CI run (evidence the gate
    actually gates — not just decoration). Soft signal: report it in
    Outcome, don't fail the proposal if no breakage occurred organically.
- **When to call it:** the dispatcher runs an audit immediately after the
  last chunk's execution PR merges and another at the next regular weekly
  cadence; both rows go into the Outcome table. Hypothesis "held" only if
  the strict thresholds above are met.
- **What would falsify it:**
  - Chunks 1 + 2 merge but `github_actions_present` is still `false` in the
    next audit (workflow path wrong, or auditor regression) — iterate, file
    a bug.
  - `median_runtime_seconds >= 300` — the workflow is too slow for its job;
    iterate by trimming the matrix (drop 3.13 until needed) or splitting
    `audit-test` off as its own job.
  - `success_rate_30d < 0.80` once measured — the tests are flaky or the
    main branch is broken on landing. Stop opening unrelated proposals
    until the green-main invariant is restored.
  - Guard breach: `commits.median_lines_changed` increases by `> 25 %` over
    the 4 weeks following adoption — CI is encouraging us to batch. Iterate.

## Research / prior art

The research step compared CI platforms, then Python linters, then per-PR
test runners. Sources consulted are listed inline.

**CI platform**

- **Considered:** [CircleCI](https://circleci.com) — extra account & billing
  surface; no native GH PR status without a token; doesn't match the
  "$0 marginal spend" fleet posture
  ([`HOST_BRINGUP.md`](../../HOST_BRINGUP.md) §4).
- **Considered:** [GitLab CI](https://docs.gitlab.com/ee/ci/) — requires
  moving the repo or running gitlab-runner on `dolo-docker`; high friction
  for a polyrepo plan that will keep using GitHub.
- **Considered:** [Jenkins](https://www.jenkins.io) — self-hosted, heavy,
  contradicts the deliberately small `dolo-docker` runtime; would have to
  share the host with Postgres + the hermes containers.
- **Picked:** [GitHub Actions](https://docs.github.com/en/actions) — native
  to the SCM the repo already uses, free for the planned usage, the
  auditor already detects it as the canonical CI signal
  (`services/auditor/audit.py:audit_ci`), and the dispatcher's PR-opening
  flow (`gh` CLI) already targets GitHub. The 2025 DORA report continues
  to emphasize "CI/CD to ensure pipelines remain auditable, automated, and
  resilient to AI-generated changes" — exactly the autonomous-coder use
  case.

**Linter / formatter**

- **Considered:** [flake8](https://flake8.pycqa.org/) — viable but
  superseded for new projects; the 2026 consensus is that Ruff covers its
  rule set and 50+ plugins in a single Rust binary, 10–100× faster
  ([pythonspeed.com — "Goodbye to Flake8 and PyLint"](https://pythonspeed.com/articles/pylint-flake8-ruff/)).
- **Considered:** [pylint](https://pylint.readthedocs.io/) — deeper
  semantic analysis (type inference, inter-file checks); useful as a
  follow-on CI check, but its slowness and noisy default ruleset make it
  the wrong *first* linter to bolt onto the dispatcher's PRs. Defer to a
  later proposal if Ruff misses real bugs.
- **Considered:** [black](https://black.readthedocs.io) + [isort](https://pycqa.github.io/isort/)
  — replaced by Ruff's bundled formatter and import-sorter (`I` rule set),
  one config block instead of three.
- **Picked:** [Ruff](https://docs.astral.sh/ruff/) — drop-in Flake8 +
  Black + isort + pyupgrade + bugbear coverage, one binary, one
  `pyproject.toml` block, sub-second on a repo this size.

**Test runner / matrix**

- **Picked:** [pytest](https://docs.pytest.org/) — the auditor already
  checks for it (`pytest_config_present`), the existing `test_*.py` files
  are pytest-compatible (stdlib-`unittest`-style, runnable by either).
- **Picked:** Python 3.12 + 3.13 matrix — `target-version = "py312"`
  pins the floor; 3.13 is GA, prepping for a smooth bump later (per
  `actions/setup-python` advanced-usage docs).

**Action pinning**

- **Picked:** Full-SHA pinning from PR #1, per
  [GitHub's secure-use reference](https://docs.github.com/en/actions/reference/security/secure-use)
  and the
  [2026 Actions security roadmap](https://github.com/orgs/community/discussions/190621).
  Trailing tag comment so future Dependabot bumps work
  ([pydevtools handbook](https://pydevtools.com/handbook/how-to/how-to-pin-github-actions-by-sha-for-python-projects/)).
  This satisfies *OpenSSF Scorecard: Pinned-Dependencies* on day one rather
  than as a retrofit.

**Coverage, scorecard, gitleaks, dependabot**

- All four are separate gaps in the same audit row. **Out of scope for this
  proposal** by design — they each become their own proposal once this one
  is `done`, because they all need a CI surface to attach to. Per
  `proposals/README.md`'s "Hard cap: 3 active per repo", landing this one
  cleanly unblocks the rest in parallel.

## Effort & risk

- **Effort:** **3 PRs, ~4–6 dispatcher-hours total elapsed.** Chunk 1 is
  ~30 lines of YAML; chunk 2 is ~15 lines of TOML plus any tiny lint fixes
  Ruff demands; chunk 3 is ~80 lines of Python plus a mocked test. None
  require touching the runtime services (`usage-gate`, `coder`,
  `auditor.audit.py`'s existing code paths) except as additive imports.
- **Risk — CI breaks on first run.** The existing `test_*.py` files run via
  `cd services/X && python3 test_X.py` from the Makefile; they don't assume
  a `PYTHONPATH` and they don't touch the network. Risk is low.
  **Mitigation:** if the matrix red-lights on one Python version, narrow
  to 3.12 only in a follow-up PR and file the 3.13 break as its own
  proposal.
- **Risk — Ruff trips on existing code.** Likely produces some `I`
  (import-order) and `UP` (pyupgrade) findings on the existing 6 Python
  files. **Mitigation:** chunk 2 fixes them inline; if `B` (bugbear) flags
  something requiring a real change, drop `B` from `select` and reopen as
  its own proposal — keep the first CI green.
- **Risk — GH Actions minutes.** Free tier is 2,000 minutes/month for
  private repos; this workflow is ~2 min × 2 versions × ~20 PRs/month =
  ~80 min. **Mitigation:** the concurrency cancel-in-progress; the matrix
  is intentionally minimal.
- **Risk — Auditor API extension needs a token; nightly audit doesn't have
  one.** **Mitigation:** chunk 3 makes the GH-API call opt-in; without
  `GH_TOKEN` the fields stay `null` and the `_note` stays in the snapshot,
  exactly as today. The supervisor's cron can set `GH_TOKEN` from the
  existing dispatcher env once we trust the extension.
- **Risk — SHA pinning ages out.** Without Dependabot for actions, SHAs go
  stale. **Mitigation:** "Enable Dependabot" is an explicit gap in the
  same audit row; that proposal lands after this one (out of scope here).
- **Risk — the auditor's `derive_gaps()` is order-dependent.** Adding the
  new `success_rate_30d < 0.80` rule changes the gap order if it ever
  fires. **Mitigation:** the auditor already sorts by `(severity, area)`,
  so the order stays deterministic; the existing `test_audit.py` will
  catch shape drift.

## Outcome

> *TBD — appended after the re-measure step.*

| Metric | Baseline | Post-execution | Δ | Target | Verdict |
|---|---|---|---|---|---|
| `ci.github_actions_present` | `false` | TBD | TBD | `true` | TBD |
| `ci.workflow_count` | `0` | TBD | TBD | `>= 1` | TBD |
| `ci.test_runs_on_pr` | `null` | TBD | TBD | `true` | TBD |
| `ci.median_runtime_seconds` | `null` | TBD | TBD | `< 300` | TBD |
| `ci.success_rate_30d` *(new)* | n/a | TBD | TBD | `>= 0.80` | TBD |

- **Did the hypothesis hold?** TBD.
- **Unexpected movement** in guard metrics: TBD.
- **What we learned**, for the next proposal of this kind: TBD.
