---
id:     dolios/2026-11-15-enable-dependabot
status: approved
repo:   dolios
audit:  .dolios/metrics/dolios/history.jsonl#L7@2026-11-15T03:30:56Z
gap_ids:
  - supply_chain-81adaf8216
metrics:
  - dependencies.dependabot_config
frameworks:
  - "DORA: Shift-left security"
  - "OpenSSF Scorecard: Dependency-Update-Tool"
opened:    2026-11-15
approved:  2026-11-16
done:      null
---

# Enable Dependabot with a grouped, weekly config for github-actions and pip

> **Decision (human, 2026-11-16): approved, with two amendments to Chunk 1.** (1) The `github-actions` stanza MUST use `directory: "/"`; Dependabot looks for workflows in `<directory>/.github/workflows`, so pointing it at `.github/workflows/` scans a path that doesn't exist (lesson from the superseded PR #38). (2) Use `timezone: "America/Chicago"`, the maintainer's timezone. Touches `.github/`, so the execution PR is held for a human merge.

## Hypothesis

Adopting **GitHub-native Dependabot v2** — a committed
`.github/dependabot.yml` enabling the `github-actions` and `pip`
ecosystems, with weekly cadence and grouped updates to avoid noise —
should move **`dependencies.dependabot_config`** from **`false`** to
**`true`** in the **next weekly audit cycle**, because:

- The auditor's operational proxy for "a dependency-update tool is
  configured" is the filesystem presence of
  `.github/dependabot.yml` **or** `.github/dependabot.yaml` at the repo
  root (`services/auditor/audit.py:326-329`). Writing the config flips
  the metric by construction; Dependabot's PR-opening behaviour is what
  makes the config *useful* once GitHub picks it up server-side.
- **DORA — Shift-left security:** detection of vulnerable transitive
  dependencies has to happen on a cadence that is independent of the
  team remembering to upgrade. Dependabot's weekly schedule is the
  canonical automated expression of this capability for GitHub repos.
- **OpenSSF Scorecard — Dependency-Update-Tool:** this specific
  Scorecard check passes when the repo has either a Dependabot or
  Renovate config at a recognised path; a weekly scan with grouped PRs
  is the recommended minimum configuration
  (<https://github.com/ossf/scorecard/blob/main/docs/checks.md#dependency-update-tool>).

The hypothesis is single-arm against a filesystem-presence metric, the
same shape as the LICENSE and SECURITY.md proposals. Unlike those, this
proposal's single artefact (the `dependabot.yml` file) also starts
doing real work on the first Monday after merge — GitHub begins opening
grouped update PRs automatically, with no additional wiring.

## Audit citation

- **Audit row:** `.dolios/metrics/dolios/history.jsonl` line 7,
  `audited_at: 2026-11-15T03:30:56Z` (`git_head: 83b4833`) — the most
  recent row at proposal time, the one the picker's dispatch cited.
- **Gap targeted:** `gap_id: supply_chain-81adaf8216` —
  `supply_chain` / "No dependency-update tool configured" (severity:
  **medium**). Verbatim: *"No Dependabot or Renovate config —
  vulnerable transitive updates won't be flagged automatically."*
  Auditor's suggested action: *"Enable Dependabot (free for GitHub
  repos); grouping rules to avoid noise."*
  (`services/auditor/audit.py:606-622`.)
- **Frameworks:**
  - **DORA — Shift-left security.** DORA's security capability names
    automated detection of known-vulnerable dependencies as a leading
    indicator; a dependency-update tool is the operational mechanism
    that makes "shift-left" continuous rather than annual.
  - **OpenSSF Scorecard — Dependency-Update-Tool.** Scorecard check
    lives at
    <https://github.com/ossf/scorecard/blob/main/docs/checks.md#dependency-update-tool>;
    it passes on Dependabot *or* Renovate config presence.
  - `docs/metrics.md:53` maps "Dependabot / Renovate config" to
    *OpenSSF Scorecard: Dependency-Update-Tool* in this repo's audit
    model.
- **Why this gap.** One of the five remaining `medium`-severity gaps
  on the row (`ci-5967d1e056`, `security-629ad05d83`,
  `security-2fdc3f14c1`, `supply_chain-81adaf8216`,
  `testing-b2bebce2d9`). The `security-*` chain has two proposals in
  flight (SECURITY.md, gitleaks). Picking the supply-chain one next
  keeps the "one-presence-flip per proposal" pattern running in
  parallel to the security chain and unlocks the downstream Scorecard
  workflow proposal (`security-e8dffa5d30`): once Dependabot and
  gitleaks are both configured, Scorecard has two more real
  check-passes to score against instead of zero.

## Baseline

The cited audit row gives:

| Metric | Current | Source |
|---|---|---|
| `dependencies.dependabot_config` | `false` | audit row above |

The metric is already measured (filesystem presence check);
`dependencies.renovate_config` is also `false` — neither update tool is
configured today. This is a single-arm hypothesis.

## Intervention

One execution-PR-sized chunk. Following the LICENSE /
SECURITY.md single-file-flip pattern: one new YAML file, the metric
flips, the gap drops out of `derive_gaps()`. No CI wiring, no
code changes, no new dependencies.

- [ ] **Chunk 1 — Add `.github/dependabot.yml` enabling `github-actions`
      and `pip` ecosystems on a weekly schedule, with grouped updates.**
   - Path: **`.github/dependabot.yml`** (not `.yaml`, not
     `dependabot.yml` at repo root). `services/auditor/audit.py:326-329`
     accepts either `.yml` or `.yaml`, but GitHub's docs standardise on
     `.yml` and every production example uses it — keep the fleet
     consistent. Same case-sensitivity trap the LICENSE / SECURITY.md /
     gitleaks chunks already flagged: exact filename on Linux.
   - **`version: 2`** at the top — version 1 has been deprecated since
     2020 and is the most common "copy-pasted from a stale guide"
     failure mode.
   - **Ecosystem 1 — `github-actions`, `directory: "/"`** (never
     `.github/workflows/` — see Decision note). Scan the `.github/workflows/`
     tree for action references and open a PR when a newer version is
     released. This is where the config *immediately* earns its keep:
     `.github/workflows/ci.yml` already pins
     `actions/checkout@08c6903…` and `actions/setup-python@e797f83…`
     by SHA; Dependabot's `github-actions` ecosystem is specifically
     designed to roll SHA pins forward with a tag comment. Chunk 2 of
     the sibling gitleaks proposal will add
     `gitleaks/gitleaks-action@v3` by SHA, which inherits the same
     monitoring the moment both proposals land. This covers the
     `gitleaks-action@v2` class of failure codified in
     [[0005-gitleaks-action-v2-dead-use-v3]] for every future action
     added to the fleet.
   - **Ecosystem 2 — `pip`, rooted at `/`.** `pyproject.toml` currently
     declares only `[tool.ruff]` — there is no `[project]` section, no
     `[project.dependencies]`, no `requirements.txt`, no lockfile. The
     `pip` ecosystem entry is therefore **vacuous today** (nothing to
     track) but costs nothing to include, and the moment this repo
     declares a dependency — likely soon, since `make coder-test`
     currently relies on `pip install pytest ruff pyyaml` in CI — the
     monitor is already wired. Including it now is cheaper than
     remembering to add it later. See Risk section for the alternative
     (ship pip-less, add it in the follow-up proposal that declares
     deps); on balance we include it.
   - **Schedule:** `interval: "weekly"`, `day: "monday"`, `time:
     "06:00"`, `timezone: "America/Chicago"` — align with when the
     dispatcher's audit cron already runs, so a maintainer reviewing
     Monday-morning PRs sees the fresh audit row and the fresh
     Dependabot PRs in the same session. Not daily — the gap's
     `proposed_action` explicitly flags noise as a risk; weekly is
     the Scorecard-recommended minimum.
   - **Grouping — `groups:`.** For each ecosystem:
     - A single group named `all-updates` with a wildcard pattern
       (`patterns: ["*"]`) applied to both `minor` and `patch` updates
       (`update-types: ["minor", "patch"]`). Combines many small
       bumps into one PR per ecosystem per week. Major upgrades fall
       outside the group by default and open their own PRs, which is
       the right behaviour — majors need human judgement.
   - **`open-pull-requests-limit: 5`** per ecosystem (default is 5
     anyway; stated explicitly so a future reader sees the ceiling
     without consulting GitHub docs). With grouping, five is a
     generous ceiling we are unlikely to hit on a repo this small.
   - **Labels:** `labels: ["dependencies"]` on each ecosystem block,
     so the inevitable future `gh pr list --label …` queries work.
   - **No other files in this chunk.** No README edits, no CI edits,
     no new scripts. This is a one-file add plus the `[x]` flip in
     this proposal — mirrors the LICENSE / SECURITY.md shape exactly.

One chunk is well under the proposal template's "~5 means too big"
ceiling; the intervention is small enough that splitting it would be
pure ceremony.

## Measurement plan

- **Metric(s) to watch:**
  - **Primary:** `dependencies.dependabot_config` must flip to `true`
    after chunk 1 merges.
  - **Gap presence:** the audit row's `gaps:` array must no longer
    contain an entry with `gap_id: supply_chain-81adaf8216` after
    chunk 1 merges. `derive_gaps()` at
    `services/auditor/audit.py:606` is a straight
    `if not deps["dependabot_config"] and not deps["renovate_config"]`
    check, so this follows from the primary metric moving, but we
    verify both — the LICENSE post-mortem's two-condition pattern
    (post row `license_present: true` AND gap absent). If the metric
    flips but the gap re-appears, that's an auditor bug worth filing
    against `services/auditor/audit.py:606` rather than a proposal
    failure.
  - **Guard — `ci.success_rate_30d`:** does not drop below 0.90 over
    the next 30 days. A Dependabot PR failing CI is a *successful*
    outcome (the whole point is catching regressions); but a flood
    of failing PRs would drag the number. With grouping and a weekly
    cadence on a two-ecosystem config, we expect ≤2 PRs/week, which
    is well within noise.
  - **Guard — `commits.count`:** the 90-day commits window may rise
    modestly from the Dependabot PRs themselves. The CI-adoption
    post-mortem specifically called out *regime-change* confounders
    for `commits.count`; Dependabot PRs are a regime change in the
    same direction, so interpret any rise there as expected activity,
    not a signal.
  - **Non-guard, mentioned for transparency:**
    `dependencies.renovate_config` stays `false` — we are not adding
    Renovate; the Scorecard check passes on either one.
- **Sampling cadence:** every weekly audit run; the dispatcher's
  existing cron picks it up.
- **Success threshold:** after chunk 1's execution PR merges, the
  next audit row must have `dependencies.dependabot_config: true`
  **and** must not include a gap with `gap_id:
  supply_chain-81adaf8216` in its `gaps:` array. Both conditions,
  not one.
- **When to call it:** the dispatcher runs an audit immediately after
  chunk 1's execution PR merges; that single post-row is enough to
  call the metric arm. Follow-up observation (not a success
  threshold): check whether GitHub has actually opened grouped PRs
  within ~7 days of merge — the config can be syntactically valid
  but subtly mis-routed (wrong ecosystem, wrong directory). If no PR
  shows up and the workflow-pins log on the Dependabot tab says
  "nothing to update", everything is fine; if it reports an error,
  fix in a follow-up PR. This is a presence check, not a trend — no
  multi-cycle window needed. (No `ops.*` in `metrics:`, so the
  `code_cutoff` self-reset issue from
  [[0004-ops-cutoff-resets-on-loop-code-merge]] does not apply.)
- **What would falsify it:**
  - `dependencies.dependabot_config` stays `false` after chunk 1
    merges. Check: is the file at `.github/dependabot.yml`
    (case-sensitive), actually committed (not staged, not in a
    different branch), and *is `.github/` even in the tracked tree*?
    If all three check out, file an auditor bug against
    `services/auditor/audit.py:326-329`.
  - Metric flips to `true` but the gap re-appears with the same
    `gap_id`. The combined-AND in `derive_gaps()` at `audit.py:606`
    requires both `dependabot_config` and `renovate_config` to be
    false; if one flipped true, the gap must drop. File an auditor
    bug.
  - Dependabot opens a storm of PRs — i.e. grouping didn't kick in.
    Likely a typo in the `groups:` stanza (YAML indentation is
    unforgiving for this schema). Response: fix the grouping in a
    follow-up PR, do not revert the whole config. The Scorecard
    check passes either way; this is a usability regression, not a
    metric regression.
  - GitHub opens zero PRs ever. Two sub-cases:
    (a) nothing to update, which is fine (and is in fact the current
    state for `pip` — no declared deps);
    (b) misconfigured ecosystem/directory, which the Dependabot tab
    in the GitHub UI will flag explicitly. Fix in a follow-up.

## Research / prior art

The research step verified the current Dependabot v2 schema, the
grouping-rules syntax (stable since 2023, GA since early 2024), and
weighed the Renovate alternative before settling on Dependabot.

- **Considered:** **Renovate**
  (<https://docs.renovatebot.com/>). More configurable than
  Dependabot, groups by regex, supports more ecosystems (poetry,
  pdm, uv, docker-compose, terraform, helm, …), free for open
  source. Not picked for **two** reasons: (1) it requires either the
  Renovate GitHub App (another SaaS consent, another thing to
  manage org-wide) or a self-hosted runner workflow (operational
  tax). Dependabot is native to GitHub and requires no app
  installation. (2) The gap's `proposed_action` explicitly names
  Dependabot and the OpenSSF Scorecard check accepts either tool —
  there's no Scorecard uplift from picking the harder-to-configure
  option. Revisit if Dolios ever needs ecosystem coverage Dependabot
  lacks (e.g. docker-compose version bumps, terraform modules);
  neither applies today.
- **Considered:** **Daily cadence** (`interval: "daily"`). Not
  picked: the gap's `proposed_action` explicitly flags "grouping
  rules to avoid noise", and daily on a near-dependency-free repo
  would generate churn out of proportion to its signal. Weekly is
  the Scorecard-recommended minimum and matches how often a
  one-maintainer repo can realistically review.
- **Considered:** **Node ecosystem (`npm`).** Not applicable —
  `package.json` is absent per the audit row (`node_package_json:
  false`). Adding an unused ecosystem is harmless but pointless.
- **Considered:** **Ecosystem-specific registries / private
  indexes.** Not applicable — no private PyPI, no GitHub Packages.
  The default configuration is correct.
- **Considered:** **Opening the PRs against a custom base branch.**
  Not applicable — this repo's main development branch is `main`
  and Dependabot targets it by default.
- **Picked:** **Dependabot v2** with the two-ecosystem, weekly,
  grouped config described in Chunk 1. Upstream docs at
  <https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuration-options-for-the-dependabot.yml-file>;
  the `groups` key is documented at
  <https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/controlling-dependencies-updated#groups>.
  Free, native, auditor-recognised, no SaaS consent required, zero
  runtime surface.
- **Known operational gotcha — ecosystem names are strict.**
  `pip` (not `python`, not `pypi`), `github-actions` (not
  `gh-actions`, not `actions`). YAML will happily accept wrong
  names; GitHub will silently ignore the stanza. Verified against
  the upstream `package-ecosystem` enum in the docs link above.
- **Known operational gotcha — the auditor's filesystem check is
  case-sensitive on Linux.** Same class of trap as LICENSE /
  SECURITY.md / `.gitleaks.toml`: exact filename or the metric
  stays `false`. Not writing a memory for this — it's a direct
  consequence of `audit.py:326-329` being `Path.exists()` calls,
  and the LICENSE post-mortem and gitleaks proposal already have
  the general lesson on record.
- **Known operational gotcha — the `pip` ecosystem is vacuous on
  this repo today.** `pyproject.toml` declares no deps; the three
  dev tools (`pytest`, `ruff`, `pyyaml`) are installed by raw
  `pip install` in CI, not declared anywhere. Dependabot `pip` scan
  will find nothing until those are either (a) added to a
  `[project.optional-dependencies.dev]` block in `pyproject.toml`,
  or (b) listed in a new `requirements-dev.txt`. Not blocking —
  including the empty-today `pip` stanza is cheaper than
  remembering to add it later, and the `github-actions` stanza
  alone earns the metric flip and the Scorecard check pass.

## Effort & risk

- **Effort:** **1 PR, ~30–45 min of dispatcher time.** A single
  ~40-line YAML add, no tests to write (presence check is the test;
  `services/auditor/test_audit.py:276` already covers the `True`
  case for `dependabot_config`), no runtime surface touched, no
  Python dependencies added, no CI edits. The sibling gitleaks
  proposal rightly budgeted 3 PRs because it had CI-wiring and a
  pre-commit hook to install; this proposal has neither, because
  Dependabot's enforcement is handled server-side by GitHub itself.
- **Risk — noise flood.** Dependabot without grouping can open
  one PR per bumped version. **Mitigation:** chunk 1's config
  bundles minor+patch into a single weekly group per ecosystem;
  majors stay separate (which is correct — majors need human
  judgement). On this repo the realistic upper bound is ≤2 PRs
  per week.
- **Risk — Dependabot stops opening PRs silently.** Server-side
  errors show up on the repo's Dependabot tab (Insights →
  Dependency graph → Dependabot) but not in the audit metric.
  **Mitigation:** the Measurement plan's "GitHub opens zero PRs
  ever" clause makes this visible; if the config is invalid,
  GitHub reports it explicitly. Not escalating to a scheduled
  follow-up check — a weekly maintainer review catches it.
- **Risk — Dependabot-opened PRs can't pass CI.** A grouped update
  might bump an action version that the `ci.yml` matrix breaks on.
  **Mitigation:** this is the whole point of the tool — a failing
  Dependabot PR is a surface for a real regression. Triage the
  failure on its merits; do not add a blanket CI exception.
  Separately: this is also why we picked weekly and not daily — if
  a bad release lands, the one weekly PR gives time to react before
  a flood of successor PRs builds on top of it.
- **Risk — the `pip` stanza is vacuous today and a reader
  mistakes it for a bug.** **Mitigation:** add a brief YAML
  comment in the file itself (not just in this proposal) noting
  that `pip` monitors `pyproject.toml` and will become active once
  this repo declares dependencies. Costs one line; prevents
  future confusion.
- **Risk — Dependabot config schema drifts.** Low; GitHub has
  shipped exactly one breaking schema change (v1 → v2) in the
  product's lifetime. Pin `version: 2` explicitly. **Mitigation:**
  the auditor presence check is schema-agnostic — a stale schema
  still passes the metric.
- **Risk — guard metrics move around.** Discussed in the
  Measurement plan; carrying forward the **CI-proposal guard-metric
  lesson** (`2026-05-28-adopt-github-actions-ci` outcome): pair
  each guard with a "what else could cause this?" line rather than
  a bare threshold. Both guards above have that annotation.
- **Risk — auditor regresses between this proposal and the
  post-merge audit.** Low; `audit_dependencies()` has been stable
  since repo inception and `test_audit.py:276,302` cover the
  `True` case.

## Outcome

> *TBD — appended after the re-measure step.*

| Metric | Baseline | Post-execution | Δ | Target | Verdict |
|---|---|---|---|---|---|
| `dependencies.dependabot_config` | `false` | — | — | `true` | — |

- **Did the hypothesis hold?** —
- **Unexpected movement** in other metrics (intended or otherwise). —
- **What we learned**, for the next proposal of this kind. —
