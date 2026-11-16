---
id:     dolios/2026-11-15-adopt-openssf-scorecard-workflow
status: proposed
repo:   dolios
audit:  .dolios/metrics/dolios/history.jsonl#L7@2026-11-15T03:30:56Z
gap_ids:
  - security-e8dffa5d30
metrics:
  - security.openssf_scorecard_present
frameworks:
  - "OpenSSF Scorecard"
  - "NIST SSDF: PO.1"
pitch: >-
  Adds the OpenSSF Scorecard GitHub workflow, which scores the repo weekly
  on about 18 security practices (branch protection, pinned actions, and
  so on) and publishes the result. It replaces several one-off yes/no
  audit checks with one trend line. One workflow file, but it publishes a
  public score and needs your merge (.github/).
opened:    2026-11-15
approved:  null
done:      null
---

# Adopt the official OpenSSF Scorecard GitHub Actions workflow

## Hypothesis

Adopting **`ossf/scorecard-action` v2.5.0** — a dedicated workflow at
`.github/workflows/scorecard.yml` that runs on every push to `main` and
once weekly, uploads SARIF to GitHub Code Scanning, and publishes to the
OpenSSF Scorecard API — should move
**`security.openssf_scorecard_present`** from **`false`** to **`true`** in
the **next weekly audit cycle**, because:

- The auditor's operational proxy for "a Scorecard workflow is configured"
  is the filesystem presence of `.github/workflows/scorecard.yml` at the
  exact path (`services/auditor/audit.py:310`). Writing the workflow flips
  the metric by construction; the action running on `main` is what makes
  the signal downstream real.
- **OpenSSF Scorecard** is the explicit framework this gap cites. Scorecard
  is a self-measurement: once the workflow runs, every check it produces
  (Branch-Protection, Token-Permissions, Pinned-Dependencies, CI-Tests,
  Dependency-Update-Tool, Security-Policy, Vulnerabilities, …) becomes a
  continuous, comparable score for the fleet. That turns the existing
  one-off presence metrics (`security.gitleaks_config_present`,
  `docs.security_md_present`, `docs.codeowners_present`,
  `dependencies.dependabot_config`) from boolean trip-wires into a single
  quantitative posture trend.
- **NIST SSDF — PO.1** calls out continuous self-assessment of the
  development environment's security posture; Scorecard is the canonical
  open-source implementation and the only tool in the ecosystem that
  publishes to a public, queryable REST API.

The hypothesis is single-arm against the metric
(`openssf_scorecard_present` is a presence check), but the single-chunk
intervention also delivers the first real downstream signal — a SARIF
feed into GitHub Code Scanning and a published score at
<https://api.scorecard.dev/projects/github.com/...>. Both are the actual
reasons the gap was filed, not just the metric flip.

## Audit citation

- **Audit row:** `.dolios/metrics/dolios/history.jsonl` line 7,
  `audited_at: 2026-11-15T03:30:56Z` (`git_head: 83b4833`) — the row the
  picker cited for this dispatch.
- **Gap targeted:** `gap_id: security-e8dffa5d30` — `security` / "No
  OpenSSF Scorecard workflow" (severity: **low**). Verbatim:
  *"Without Scorecard there's no continuous, comparable security-posture
  score."* Auditor's suggested action: *"Add the official scorecard-action
  workflow once basic CI exists."* (`services/auditor/audit.py:596`.)
- **Sequencing precondition met.** The gap's `proposed_action` names
  "once basic CI exists" as a precondition. The current audit row has
  `ci.github_actions_present: true` and `ci.workflow_count: 1`
  (`ci.yml`, pass rate `1.0`, median 17s) — the precondition is
  satisfied. The LICENSE / SECURITY.md / gitleaks proposals that are
  further along the `security`/`docs` queue remain independent of this
  one; Scorecard reads the repo state at run-time, so any of those
  landing before or after this one only changes individual check
  scores, never this proposal's success criterion.
- **Frameworks:**
  - **OpenSSF Scorecard** itself. The Scorecard project ships both the
    checks reference (<https://github.com/ossf/scorecard/blob/main/docs/checks.md>)
    and the canonical GitHub Action to run them
    (<https://github.com/ossf/scorecard-action>). This proposal is
    literally the capability the framework prescribes.
  - **NIST SSDF — PO.1** ("Define Security Requirements for Software
    Development"). A continuous, external-tool self-assessment is the
    SSDF's PO.1.1 practice; Scorecard is one of the named
    implementations in NIST's SSDF mapping guide.
  - `docs/metrics.md:50` maps "OpenSSF Scorecard workflow" to the
    *OpenSSF Scorecard* anchor in this repo's audit model.

## Baseline

The cited audit row gives:

| Metric | Current | Source |
|---|---|---|
| `security.openssf_scorecard_present` | `false` | audit row above |

The metric is already measured (filesystem presence check); single-arm
hypothesis. The `not_measured` list also contains
`security.openssf_scorecard_score` (needs the workflow to have run at
least once) — chunk 1 unblocks that follow-on measurement but does not
try to flip it in this proposal's `metrics:` list, because scorecard
score is a 0–10 range, not a boolean, and setting a target without a
prior run is premature.

## Intervention

One execution-PR-sized chunk. The gap is a single-file add on a live-CI
repo; no reason to spread it.

- [ ] **Chunk 1 — Add `.github/workflows/scorecard.yml` using
      `ossf/scorecard-action@v2.5.0`, pinned by commit SHA.**
   - Path: **`.github/workflows/scorecard.yml`** (exact —
     `services/auditor/audit.py:310` does a bare
     `(.github / workflows / "scorecard.yml").exists()`; any other
     filename or location leaves the metric at `false`). Same
     case-sensitivity trap the gitleaks, LICENSE, and SECURITY.md
     chunks already flagged. Not `scorecards.yml` (plural) —
     `scorecard.yml` singular.
   - Mirror the upstream canonical workflow from
     `ossf/scorecard/.github/workflows/scorecard-analysis.yml` almost
     verbatim, because deviations from the upstream template are the
     most common failure mode for first-run Scorecard jobs. Only
     adapt: the workflow's `name:` field, and the `actions/checkout`
     pin (fleet-wide SHA conventions from `ci.yml` already pin this
     one at `08c6903cd8c0fde910a37f88322edcfb5dd907a8 # v5` — reuse
     that pin).
   - **Triggers:**
     - `push: {branches: [main]}` — Scorecard runs after every merge
       to main, which is the authoritative measurement.
     - `schedule: {cron: '30 1 * * 6'}` — weekly on Saturdays at
       01:30 UTC, same cadence as upstream. The workflow surviving
       a week of no merges is itself a Scorecard check
       (Maintained / Code-Review requires recent activity on the
       upstream action; our own `schedule:` keeps the signal fresh
       even in quiet weeks).
     - **No `pull_request:` trigger.** Scorecard measures the state
       of `main`, not a PR's hypothetical merged state; running it
       on PRs just doubles the SARIF uploads and burns CI time for
       no additional signal. This is also why memory 0003's
       `?branch=main` filter bug does not affect this metric —
       Scorecard runs are all push-to-main or scheduled, so
       `ci_api.py:_fetch_runs` sees them correctly today.
     - **No `workflow_dispatch:` trigger.** A reviewer with
       `contents: write` can trigger an ad-hoc run via GitHub's REST
       API or `gh workflow run` if needed, but adding the trigger
       to the YAML would (a) enable *any* repo admin to spam the
       OpenSSF API and (b) require the token-permissions hardening
       to grow a `workflow: write` bit for scheduled bots. Omit it.
   - **Permissions:** `permissions: read-all` at the workflow top
     level (upstream default — tightens every token the job can
     create unless a step explicitly re-grants). The single job
     re-grants two specific writes:
     - `security-events: write` — required for the
       `github/codeql-action/upload-sarif` step that populates the
       repo's Security → Code Scanning tab.
     - `id-token: write` — required for `publish_results: true` so
       the action can obtain an OIDC token and submit the score to
       the OpenSSF Scorecard API. **Not** granting this permission
       leaves `publish_results: true` as a no-op; the SARIF upload
       still works.
   - **Action pins (all by SHA, in the fleet style):**
     - `actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8 # v5`
       — same SHA `.github/workflows/ci.yml` already uses. Set
       `persist-credentials: false` per the upstream template (no
       need to keep the git credential after checkout).
     - `ossf/scorecard-action@fa7117db83c52d787ae5a89f350999701505d78e # v2.5.0`
       — the current `v2.5.0` tag (2026-10-12), which internally
       runs Scorecard v5.6.0 on Node 22. v2.4.x and earlier are the
       risky generation: same Node-20-is-dead story as
       `gitleaks-action@v2` ([[0005-gitleaks-action-v2-dead-use-v3]])
       because Scorecard's action and gitleaks' action share the
       GitHub-hosted runner's Node version. v2.5.0 runs Node 22 and
       is the only safe pin today.
     - `actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9`
       — upstream pin, retains the SARIF for 5 days as audit backup.
     - `github/codeql-action/upload-sarif@33d7b85da1a04171e211befe2c739303b9a4c066`
       — upstream pin, pushes SARIF into the Security → Code
       Scanning tab.
   - **Scorecard-action inputs:**
     - `results_file: results.sarif`
     - `results_format: sarif`
     - `publish_results: true` — this is the critical switch. With
       `true`, the action signs the result via the OIDC token
       granted by `id-token: write` and submits it to
       <https://api.scorecard.dev>, making the badge
       `https://api.scorecard.dev/projects/github.com/<owner>/<repo>/badge`
       and the REST query `GET /projects/github.com/<owner>/<repo>`
       both return a real score. With `false`, SARIF still lands in
       Code Scanning but no external publication happens.
     - **Dolios is a public GitHub repo** (the fleet's
       auto-coder PRs are all public, e.g. #14–#41), so
       `publish_results: true` is both permitted and useful. If
       this ever ran on a private mirror, the switch must be
       flipped to `false` (the API rejects private submissions).
   - **No README changes in this chunk.** Adding the Scorecard
     badge to README is ergonomic polish, not the metric. A
     second proposal can do that after the first run produces a
     score worth linking to.

One chunk is enough. More than one would be padding — this is a
single-file add on an already-live CI surface.

## Measurement plan

- **Metric(s) to watch:**
  - **Primary:** `security.openssf_scorecard_present` must flip to
    `true` after chunk 1 merges. This is a filesystem presence
    check; the auditor runs it on the post-merge commit.
  - **Gap presence:** the audit row's `gaps:` array must no longer
    contain an entry with `gap_id: security-e8dffa5d30` after chunk
    1 merges. `derive_gaps()` at `services/auditor/audit.py:596` is
    a straight `if not sec["openssf_scorecard_present"]` check, so
    this follows from the primary metric moving, but we verify
    both — same two-condition pattern as the LICENSE post-mortem.
  - **Content check (per [[0006-presence-metrics-hide-broken-content]]):**
    the metric is presence-only, so a syntactically-valid but
    functionally-broken workflow would flip the boolean green while
    Scorecard silently never produced a score. **The chunk's
    definition-of-done requires that the first post-merge run of
    the workflow on `main` finishes green** (no `actionlint` failure,
    no action-pin resolution failure, no OIDC permission failure).
    The dispatcher's remeasure step checks:
    `gh run list --workflow=scorecard.yml --branch=main --limit=1 --json conclusion`
    and asserts `conclusion == "success"` before calling the
    outcome "met". A red first run is a successful falsification
    of the "workflow runs" sub-hypothesis, not evidence against the
    metric — triage the failure, don't silence it.
  - **Guard — `ci.success_rate_30d`:** must not drop below `0.80`
    over the next 30 days. The new workflow is a *second* workflow
    file and `ci_api.py` averages conclusion across all runs in the
    lookback. A single red Scorecard run would cost ~1/N of the
    pass rate; on N≈15 runs that is still > 0.90. Only sustained
    Scorecard failures would push below 0.80.
  - **Guard — `ci.workflow_count`:** expected `1 → 2`. This is
    *intended*, not a regression, and the proposal should not call
    it a surprise on remeasure — note it in the Outcome as expected.
  - **Guard — `ci.median_runtime_seconds`:** `17s → unknown`.
    Scorecard's job typically runs 90–180s on a repo this size. The
    median across the two workflows will likely rise 30–60s; that
    is intended and not a regression. The proposal's success does
    not depend on CI staying fast, only on CI staying green.
    (See the 2026-05-28 CI proposal's guard-metric lesson:
    annotate guards with "what else could cause this?" rather than
    a bare threshold.)
- **Sampling cadence:** every weekly audit run (`make audit` under
  the dispatcher's cron). The content check is a one-shot
  `gh run list` post-merge, not a recurring sample.
- **Success threshold:** after chunk 1's execution PR merges, the
  next audit row must have
  `security.openssf_scorecard_present: true` **and** must not
  include a gap with `gap_id: security-e8dffa5d30` in its `gaps:`
  array **and** the first `.github/workflows/scorecard.yml` run on
  `main` must conclude `success`. All three, not any one.
- **When to call it:** the dispatcher runs an audit immediately
  after chunk 1's execution PR merges and appends the Outcome row
  once the first scheduled/push run completes (up to 5 minutes for
  the push-triggered run). No multi-cycle window needed — presence
  check is stable; the content check binds to a single CI run.
  (No `ops.*` in the `metrics:` list, so memory 0004's
  `code_cutoff` self-reset issue does not apply; this proposal
  touches no `services/coder/` code.)
- **What would falsify it:**
  - `security.openssf_scorecard_present` stays `false` after merge.
    Check: is the file at exactly `.github/workflows/scorecard.yml`
    (case-sensitive), actually committed, in the merge commit on
    `main` (not a stale branch)? If all three check out, file an
    auditor bug against `services/auditor/audit.py:310`.
  - Metric flips but gap re-appears with the same `gap_id` —
    `derive_gaps()` is misreading
    `sec["openssf_scorecard_present"]`. File a bug against
    `services/auditor/audit.py:596`.
  - **Workflow runs red on first merge.** The most likely cause is
    a Scorecard check that can't complete against this repo's
    state (e.g. the branch-protection probe needs a permission the
    `GITHUB_TOKEN` lacks). Triage: inspect the run's SARIF output
    in Security → Code Scanning and either (a) adjust the
    workflow's `permissions:` block, or (b) accept the specific
    check as "informational, not fatal". Do not disable the
    workflow — the metric is boolean but the dispatcher's content
    check treats red as failure of the hypothesis, so a
    follow-up PR (same `gap_id`) is appropriate.
  - **`publish_results: true` fails to publish.** The OIDC token
    exchange with `api.scorecard.dev` is the single external
    integration this proposal has. If it fails, the SARIF upload
    to Code Scanning still works, so the *internal* value of the
    workflow is intact; the metric flip is unaffected. Follow-up:
    check `id-token: write` is granted on the job (not just the
    workflow top-level) and that the repo is public.

## Research / prior art

The research step verified current best-practice tooling for
continuous security self-measurement before settling on the above
intervention.

- **Considered:** **OpenSSF Scorecard CLI (standalone)**
  (<https://github.com/ossf/scorecard>, v5.6.0 as of Nov 2026). Runs
  locally or in any CI system, same ruleset. Not picked as the
  primary form because the gap's `proposed_action` names
  *scorecard-action* specifically, because the Action handles OIDC
  identity for `publish_results` (the CLI needs an explicit token
  flow), and because the Action's `upload-sarif` step integrates with
  GitHub's Security tab natively. The CLI is a useful fallback for a
  developer who wants to dry-run against a branch — mention in
  CONTRIBUTING.md when that doc exists (currently it doesn't; out of
  scope here).
- **Considered:** **StepSecurity Harden-Runner**
  (<https://github.com/step-security/harden-runner>). Complementary,
  not alternative — Harden-Runner protects the *runner* during a
  CI job (egress policies, file-tamper detection). Scorecard measures
  the *repo*'s posture. The two often ship together, and
  Harden-Runner's docs explicitly recommend adding it to a Scorecard
  workflow. Deliberately out of scope for this proposal — adding it
  would double the chunk count, and the gap targets Scorecard
  specifically. Candidate for a follow-up proposal if we want to
  address Scorecard's own Token-Permissions check more aggressively.
- **Considered:** **Posting SARIF directly from the Scorecard CLI
  via a custom workflow.** Possible, but reinvents what the official
  Action already does and duplicates the SHA-pin burden onto a
  hand-rolled `curl` call to <https://api.scorecard.dev>. Not picked.
- **Considered:** **Not publishing results (`publish_results: false`)**
  for privacy. This is a public repo (see Audit citation above —
  every auto-coder PR is on github.com publicly). Scorecard's public
  API is the *point* of the tool for public projects — it enables
  the badge, the REST query, and comparison against the OpenSSF
  index. Not picked; `publish_results: true` is correct here.
- **Picked:** **`ossf/scorecard-action@v2.5.0`**
  (<https://github.com/ossf/scorecard-action/releases/tag/v2.5.0>,
  2026-10-12, pinned SHA `fa7117db83c52d787ae5a89f350999701505d78e`).
  The current stable, running on Node 22 (the only Node version
  present on GitHub-hosted runners today). Internally runs
  Scorecard v5.6.0. The upstream canonical workflow template
  (<https://github.com/ossf/scorecard/blob/main/.github/workflows/scorecard-analysis.yml>)
  is the authoritative shape; this proposal copies it almost
  verbatim.
- **Known operational gotcha — `scorecard-action` version pins
  below v2.5.0 may still run on Node 20.** Node 20 was removed from
  the GitHub-hosted runner image on **2026-09-16**; any pre-v2.5
  copy-paste of a Scorecard workflow fails job-start on
  `ubuntu-latest`. Same class of trap as
  [[0005-gitleaks-action-v2-dead-use-v3]]; different action, same
  runner-image rollover. Chunk 1 pins v2.5.0 by SHA.
- **Known operational gotcha — `.github/workflows/scorecard.yml`
  auditor match is case-sensitive and path-exact.** Same class of
  trap flagged for `.gitleaks.toml`, `LICENSE`, `SECURITY.md`,
  `CODEOWNERS`. `audit.py:310` is a bare `Path.exists()` call. Not
  writing a separate memory for this one — it's a repeated
  consequence of the V0 auditor's filesystem-presence strategy,
  already captured as a class in
  [[0006-presence-metrics-hide-broken-content]].
- **Known operational gotcha — a presence-metric flip without a
  content check is a known failure mode on this auditor.**
  [[0006-presence-metrics-hide-broken-content]] explicitly names
  `security.openssf_scorecard_present` as a member of the risky
  class: "the first run on `main` goes green, not red on an
  `actionlint`-class error." The Measurement plan above adopts the
  memory's prescription — a post-merge `gh run list` check is part
  of the definition-of-done, not an afterthought.

## Effort & risk

- **Effort:** **1 PR, ~1 hour dispatcher time.** Single-file add of
  a ~40-line workflow YAML, all pins already identified in this
  proposal. No tests to write (presence check is the test;
  `services/auditor/test_audit.py` already covers the opposite
  default). No runtime surface touched; no Python dependencies.
- **Risk — first run goes red because of a Scorecard check's
  token permissions.** Scorecard probes many repo attributes
  (branch protection, dependency manifests, workflow permissions).
  Some probes legitimately fail-closed when the `GITHUB_TOKEN`
  lacks the specific read scope. **Mitigation:** the upstream
  canonical workflow's `permissions:` block (job-level
  `security-events: write` + `id-token: write`, workflow-level
  `read-all`) is the de facto correct shape for a public repo and
  covers the overwhelming majority of first-run failures. If a
  specific check still fails, the SARIF output shows exactly
  which one; follow up in a same-gap PR to grant the missing
  read permission.
- **Risk — `scorecard-action@v2.5.0` or older pin runs on Node 20.**
  See research section: Node 20 is gone from GitHub-hosted runners.
  **Mitigation:** chunk 1 pins v2.5.0 by commit SHA
  `fa7117db83c52d787ae5a89f350999701505d78e`. Reviewers should
  verify the SHA matches the `v2.5.0` tag at
  <https://github.com/ossf/scorecard-action/releases/tag/v2.5.0>
  and not something older.
- **Risk — `publish_results: true` fails OIDC token exchange.**
  Low; the OIDC setup is the same as every other OIDC-enabled
  action (`permissions.id-token: write` on the job). **Mitigation:**
  Measurement plan treats a publish failure as non-fatal — SARIF
  still lands in Code Scanning, the metric flip is unaffected, and
  the fix is a scoped follow-up.
- **Risk — the SARIF upload step consumes GitHub Advanced Security
  or Code Scanning quota.** On public repos, Code Scanning is free.
  On private, it requires GitHub Advanced Security — dolios is
  public, so this is a non-issue. **Mitigation:** none needed for
  the current repo; flag if we ever mirror private.
- **Risk — Scorecard's weekly cron adds a small amount of noise to
  `ci.success_rate_30d` on every green run.** One extra run per
  week is ~0.3% of a 30-day sample; even a red run is bounded.
  Covered in the Measurement plan guard discussion. Carrying forward
  the **CI-proposal guard-metric lesson** from the
  `2026-05-28-adopt-github-actions-ci` outcome: guards pair with a
  "what else could cause this?" annotation, not a bare threshold.
- **Risk — `scorecard-action` publishes a low initial score and the
  low score is itself embarrassing on a public badge.** Scorecard
  v5.6.0 scores dolios somewhere in the 4–7 range on a cold repo
  (no SECURITY.md yet, no CODEOWNERS yet, no Dependabot yet, no
  signed releases). **This is the point.** The score is the
  continuous signal the auditor's framework-anchored metrics are
  pointing at; a low initial score motivates the downstream
  proposals (SECURITY.md, CODEOWNERS, Dependabot) that are already
  in the queue. Mitigation: do not add the badge to README in this
  proposal (noted above); add it in a follow-up once the score has
  stabilised after two or three downstream merges.
- **Risk — the auditor regresses between this proposal and the
  post-merge audit.** Low; `audit_security()` is covered by
  existing tests. **Mitigation:** post-merge audit is the oracle;
  if the metric doesn't flip, debug the auditor, not the workflow.

## Outcome

> *TBD — appended after the re-measure step.*

| Metric | Baseline | Post-execution | Δ | Target | Verdict |
|---|---|---|---|---|---|
| `security.openssf_scorecard_present` | `false` | — | — | `true` | — |

- **Did the hypothesis hold?** —
- **Unexpected movement** in other metrics (intended or otherwise). —
- **What we learned**, for the next proposal of this kind. —
