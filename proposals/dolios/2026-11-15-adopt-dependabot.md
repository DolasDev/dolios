---
id:     dolios/2026-11-15-adopt-dependabot
status: proposed
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
approved:  null
done:      null
---

# Adopt Dependabot with grouped weekly updates for github-actions and docker

## Hypothesis

Adopting **GitHub Dependabot** — a single committed `.github/dependabot.yml`
covering the two package ecosystems this repo actually uses
(`github-actions` at repo root and `docker` under `infra/hermes/`), on a
**weekly** schedule with grouped minor+patch updates — should move
**`dependencies.dependabot_config`** from **`false`** to **`true`** in the
**next weekly audit cycle**, because:

- The auditor's operational proxy for "a dependency-update tool is
  configured" is the filesystem presence of `.github/dependabot.yml` or
  `.github/dependabot.yaml` (`services/auditor/audit.py:326`). Writing
  the file flips the metric by construction; the ecosystem/schedule/group
  stanzas are what make Dependabot actually *do* something useful.
- **DORA — Shift-left security:** DORA names "integration of security
  practices into the software supply chain," and specifically the
  *continuous* flavour — vulnerable transitive updates should be *flagged
  automatically* rather than waiting for a quarterly audit. Dependabot
  opens PRs within hours of a GHSA advisory touching a pinned dependency,
  which is the earliest-feedback option available for free on GitHub.
- **OpenSSF Scorecard — Dependency-Update-Tool:** Scorecard's
  `Dependency-Update-Tool` check awards full credit when either a
  `.github/dependabot.yml` or a Renovate config is present; it's a
  binary presence check against this exact file. Adopting Dependabot
  here therefore also pays forward the follow-up Scorecard-workflow
  proposal (`security-e8dffa5d30`): when that lands, this check will
  score on day one without a second intervention.

Single-arm hypothesis against the metric; the three-ecosystem stanza
plus grouping rules are what make it useful, not what flips the bit.

## Audit citation

- **Audit row:** `.dolios/metrics/dolios/history.jsonl` line 7,
  `audited_at: 2026-11-15T03:30:56Z` (`git_head: 83b4833`) — the most
  recent row at proposal time, the one the picker's dispatch cited.
- **Gap targeted:** `gap_id: supply_chain-81adaf8216` — `supply_chain` /
  "No dependency-update tool configured" (severity: **medium**).
  Verbatim: *"No Dependabot or Renovate config — vulnerable transitive
  updates won't be flagged automatically."* Auditor's suggested action:
  *"Enable Dependabot (free for GitHub repos); grouping rules to avoid
  noise."* (`services/auditor/audit.py:606`.)
- **Frameworks:**
  - **DORA — Shift-left security.** DORA's security capability names
    the "integration of security practices into the software supply
    chain" and the earliest-feedback requirement on vulnerability
    detection. Dependency updates driven by upstream advisories are the
    canonical form of this signal for library consumers.
  - **OpenSSF Scorecard — Dependency-Update-Tool.** The Scorecard check
    is a presence test for `.github/dependabot.yml` or a Renovate config
    (<https://github.com/ossf/scorecard/blob/main/docs/checks.md#dependency-update-tool>).
    The check is binary: present → 10/10; absent → 0/10.
- **Why this gap.** The last remaining `medium` gap in the
  `supply_chain` area, and the cheapest medium left overall in the cited
  row after SECURITY.md and gitleaks are both in flight: a single-file
  config add with no runtime surface and no tests to write. Sequencing
  this before the follow-on `security-e8dffa5d30` (Scorecard workflow)
  means Scorecard inherits a passing `Dependency-Update-Tool` check for
  free. The same pattern the LICENSE proposal used to unblock the
  downstream `compliance`/`docs.*` chain.

## Baseline

The cited audit row gives:

| Metric | Current | Source |
|---|---|---|
| `dependencies.dependabot_config` | `false` | audit row above |

The metric is already measured (filesystem presence check); this is a
single-arm hypothesis. For context on the surrounding row (not target
metrics, but relevant to ecosystem choice):
`dependencies.python_pyproject_toml: true` (but the file holds only
`[tool.ruff]` — no `[project.dependencies]`), `python_requirements_txt:
false`, `node_package_json: false`, `iac.dockerfile_present: true`
(`infra/hermes/Dockerfile`), `ci.workflow_count: 1`
(`.github/workflows/ci.yml`). The two ecosystems with *actual pinned
versions worth updating* are therefore `github-actions` and `docker` —
`pip` is intentionally omitted (see Research / "pip ecosystem skipped").

## Intervention

One chunk. This is deliberately a single-file add — mirroring the
LICENSE proposal's shape, which the outcome record flagged as "the easy
case" for presence-metric work. More chunks here would be ceremony, not
value: no CI edit is needed (ci.yml's existing `permissions: contents:
read` is already the right posture for Dependabot PRs), no tests to
write (presence check is the test;
`services/auditor/test_audit.py` covers the dependabot-config detector),
and no runtime surface is touched.

- [ ] **Chunk 1 — Add `.github/dependabot.yml` with `github-actions` and
      `docker` ecosystems, weekly schedule, grouped minor+patch updates.**
  - Path: **`.github/dependabot.yml`** at exactly that path
    (`services/auditor/audit.py:326–328` accepts `.github/dependabot.yml`
    OR `.github/dependabot.yaml`; use `.yml` for consistency with the
    existing `.github/workflows/ci.yml` extension on this repo).
  - `version: 2` (the only supported Dependabot config schema).
  - Two `updates:` entries:
    - **github-actions**, `directory: "/"`. **Not** `.github/workflows/`
      and **not** per-workflow — the `github-actions` ecosystem
      *requires* `directory: "/"` and auto-discovers every `uses:` pin
      under `.github/workflows/`. A directory like `.github/workflows/`
      silently discovers zero actions and the stanza becomes a no-op.
      See memory below.
    - **docker**, `directory: "/infra/hermes"` (the Dockerfile's
      directory, no trailing slash in the convention). This is the only
      Dockerfile in the tree today (`git ls-files | grep Dockerfile`
      returns the single path); if a second Dockerfile appears later, a
      follow-up PR adds a second `docker` stanza — Dependabot does not
      recurse.
  - `schedule: {interval: "weekly", day: "monday"}` on both. Daily was
    considered; the gap's `proposed_action` explicitly calls for
    "grouping rules to avoid noise," and Monday-weekly matches the
    fleet's weekly audit cadence so new Dependabot PRs and new audit
    rows surface on the same working day.
  - `open-pull-requests-limit: 5` on both (default is 5 for
    `version-updates`; made explicit so a future reader doesn't wonder
    whether this was deliberately set or merely inherited).
  - **`groups:`** key on both entries — the modern (post-2024)
    Dependabot grouping syntax, nested *inside* each `updates:` entry,
    not at the file top level. Two groups per ecosystem:
    - `minor-and-patch`: `update-types: [minor, patch]`, `patterns:
      ["*"]`. Bundles the quiet upgrades into one PR per ecosystem per
      week.
    - Majors stay un-grouped (no second group entry) — Dependabot's
      default is to open one PR per major bump, which is the right
      default: majors tend to need manual review anyway.
  - `commit-message: {prefix: "deps", prefix-development: "deps-dev",
    include: "scope"}` — matches the conventional-commits-ish style of
    existing commits in this repo (`auto-coder: propose-…`, `fix:`,
    etc.). Makes auto-merge rules easier to write later if we want
    them.
  - `labels: ["dependencies"]` on both — standard GitHub convention;
    the label does not need to pre-exist, Dependabot creates it.
  - **No CI edit, no code edit, no scripts.** The chunk is a two-file
    touch (the `.github/dependabot.yml` add plus the `[x]` flip in the
    proposal), nothing else.

Single-chunk is the ceiling here, not a worry about scope — the template
says "more than ~5 means the proposal is too big"; it says nothing
against single-chunk proposals, and the LICENSE one set the precedent.

## Measurement plan

- **Metric(s) to watch:**
  - **Primary:** `dependencies.dependabot_config` must flip to `true`
    after chunk 1 merges.
  - **Gap presence:** the audit row's `gaps:` array must no longer
    contain an entry with `gap_id: supply_chain-81adaf8216` after chunk
    1 merges. `derive_gaps()` at `services/auditor/audit.py:606` is a
    straight `if not deps["dependabot_config"] and not
    deps["renovate_config"]` check, so this follows from the primary
    metric moving, but we verify both. Two-condition check carries
    forward the LICENSE post-mortem's lesson: "the gap goes away" and
    "the metric flips" are distinct observations; a metric can flip
    without the derived gap dropping if `derive_gaps()` has a bug.
  - **Guard — `ci.success_rate_30d`:** does not drop below 0.90 over
    the next 30 days. Dependabot PRs *themselves* are not caused by
    this proposal (they'd come from upstream version bumps, which
    happen regardless); but once Dependabot is live, Dependabot PRs
    will start running `ci.yml`. If a Dependabot PR fails CI, that is
    *the point of the mechanism* — don't treat it as a guard breach,
    treat it as evidence the gate caught a bad upgrade.
  - **Guard — `commits.count`:** carrying forward the
    github-actions-CI outcome's confounder lesson. Dependabot PRs will
    bump `commits.count` (each merged bump is a commit on main).
    Direction: *up* — which is a favourable move for the activity
    story, not a regression. If `commits.count` is *down* on the
    first post-merge audit, that is unrelated to Dependabot; name
    the real confounder (fleet throughput, mid-week merge freeze,
    etc.) rather than attributing it here.
- **Sampling cadence:** every weekly audit run; `make audit` in the
  dispatcher's existing cron picks it up.
- **Success threshold:** after chunk 1's execution PR merges, the next
  audit row must have `dependencies.dependabot_config: true` **and**
  must not include a gap with `gap_id: supply_chain-81adaf8216` in its
  `gaps:` array. Both conditions.
- **When to call it:** the dispatcher runs an audit immediately after
  chunk 1's execution PR merges; because this is a stable filesystem
  presence check (not a trend, not an `ops.*` metric), the first
  post-cutoff audit is decisive. No multi-cycle window needed. (No
  `ops.*` in the `metrics:` list, so the `code_cutoff` self-reset
  issue from memory 0004 does not apply.)
- **What would falsify it:**
  - `dependencies.dependabot_config` stays `false` after chunk 1
    merges. Check, in order: is the file at *exactly*
    `.github/dependabot.yml` (not `.github/dependabot.yaml` with a
    typo, not `.github/workflows/dependabot.yml`, not
    `dependabot.yml` at repo root)? Case-sensitive on Linux —
    `.github/Dependabot.yml` won't match. If all three check out,
    file an auditor bug against `services/auditor/audit.py:326`.
  - Metric flips to `true` but the gap re-appears with the same
    `gap_id` — `derive_gaps()` is not reading
    `deps["dependabot_config"]` correctly. File a bug against
    `services/auditor/audit.py:606`.
  - **Dependabot opens zero PRs in the week after merge.** The metric
    says "configured," not "active." This is not a hypothesis
    falsification per se — the metric can be met while Dependabot is
    silently a no-op — but it IS evidence of a misconfigured
    `directory:` (see memory below). Check that `github-actions` is
    `directory: "/"` and that `docker` points at the Dockerfile's
    directory. The *presence* of Dependabot PRs on upstream
    actions (`actions/checkout@*`, `actions/setup-python@*`) within
    7 days of merge is the real-world validator; absence past that
    window implies a config bug, not an upstream silence.
  - A Dependabot PR fails CI *and* blocks merge of a legitimate
    dependency bump — if this becomes chronic (≥3 bumps/week stuck),
    revisit the grouping policy (maybe majors should NOT be
    auto-opened), not revert Dependabot.

## Research / prior art

The research step verified current best-practice tooling for automated
dependency updates on GitHub-hosted public repos as of Nov 2026,
along with the known operational gotchas before settling on the
single-config-file intervention.

- **Considered:** **Renovate** (<https://docs.renovatebot.com/>). More
  flexible rule engine (per-manager presets, `packageRules`,
  dependency dashboards), supports many ecosystems Dependabot doesn't
  (Helm, Kustomize, Flux). Not picked for *this* repo because: (1)
  Dolios has only two ecosystems both of which Dependabot supports
  natively and well; (2) Renovate's hosted free tier is a separate
  GitHub App the org has to install, versus Dependabot which is
  built in; (3) the auditor accepts either (`renovate.json` is in the
  `renovate_config` detector at `audit.py:330`) so there is no
  framework reason to prefer one; (4) the gap's `proposed_action` text
  explicitly says "Enable Dependabot." If Dolios ever grows into a
  multi-language polyrepo with many ecosystems, Renovate is the
  escape hatch.
- **Considered:** **Daily schedule** rather than weekly. Pros: fastest
  surface of a new advisory. Cons: PR noise, especially with majors
  un-grouped. The gap's auditor text explicitly calls for "grouping
  rules to avoid noise," and the fleet is maintained by one person
  today — weekly batched is the right default. If a critical GHSA
  drops mid-week, GitHub emits a *security advisory alert* separately
  (not through Dependabot's scheduled runs); that notification path
  is unaffected by the schedule setting.
- **Considered:** **Including a `pip` ecosystem stanza anyway.**
  Rejected because `pyproject.toml` at repo root has only
  `[tool.ruff]` — no `[project.dependencies]`, no `[tool.poetry]`, no
  `requirements*.txt` anywhere in the tree. Dependabot's `pip`
  manager would find no manifest it understands and either (a) error
  on first run (Dependabot's `pip` manager treats "no dependencies
  declared" as a config error) or (b) silently emit nothing. Either
  way, including the stanza adds operational noise without any
  benefit. Separately: the CI workflow's inline `pip install pytest
  ruff pyyaml` is not a manifest Dependabot can parse — that is a
  shell command, not a declared dependency. If the project ever
  grows a real `[project.dependencies]` in `pyproject.toml`, add a
  `pip` stanza in a follow-up PR (one-line add).
- **Picked:** **GitHub Dependabot v2 config schema**
  (<https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuration-options-for-the-dependabot.yml-file>).
  Already available on every GitHub repo at no cost; configuration
  lives entirely in-repo (no app install, no org settings); supported
  by Scorecard's `Dependency-Update-Tool` check directly.
- **Known operational gotcha — `github-actions` directory MUST be
  `/`.** The Dependabot docs specify this explicitly for the
  `github-actions` package ecosystem, and misconfiguration is the #1
  "my Dependabot isn't opening PRs" symptom reported in the GitHub
  Dependabot community discussions over the last 18 months. A
  `directory: ".github/workflows/"` (which looks intuitive — "scan
  the workflows") produces zero PRs because Dependabot uses
  `directory:` as the *root* of its scan, and the auto-discovery of
  workflow files is hardcoded to look under
  `${directory}/.github/workflows/`, which with `directory:
  ".github/workflows/"` evaluates to
  `.github/workflows/.github/workflows/` — a path that does not
  exist. Chunk 1 pins `directory: "/"`. Codified in a new memory
  alongside this proposal (see below).
- **Known operational gotcha — the `.github/dependabot.yml` auditor
  match is case-sensitive on Linux.** Same class of trap as the
  LICENSE, SECURITY.md, and gitleaks chunks: `audit.py:326` is a
  straight `Path.exists()` call. Exact filename or the metric stays
  `false`. Not a separate memory; it's structural to the auditor.
- **Known operational gotcha — the modern `groups:` syntax is nested
  INSIDE each `updates:` entry.** Pre-2024 Dependabot grouping used a
  short-lived top-level `groups:` key; that is dead in the v2 schema
  as it stands today. Copy-pasted older configs will either fail to
  validate or silently not group. Chunk 1's `groups:` key is under
  each `updates:` entry, not at file top level.
- **Known operational gotcha — Dependabot PRs run CI with the token
  scoped READ-only by default** (GitHub changed this in Oct 2021 as a
  response to the `dependabot-core` supply-chain incident). This is
  the right default and chunk 1 does not alter it. Importantly,
  `.github/workflows/ci.yml`'s current `permissions: contents: read`
  is already compatible — Dependabot PR runs will get the same
  effective permissions the workflow needs anyway. If a future
  workflow needs write permissions, the `pull_request_target`
  pattern is the escape hatch, with the attendant security caveats.
  No action needed in this proposal; flagging here so a reviewer of
  the follow-on gitleaks or scorecard workflows doesn't re-discover
  the constraint.

## Effort & risk

- **Effort:** **1 PR, ~1 hour of dispatcher time elapsed.** Chunk 1 is
  a single ~35-line YAML add. No tests to write (presence check is the
  test; `services/auditor/test_audit.py` already covers the detector),
  no runtime surface touched, no dependencies added (Dependabot runs
  in GitHub's infra, not in CI). Shortest proposal on dolios after
  LICENSE.
- **Risk — Dependabot opens PRs that fail CI.** Fundamental to the
  mechanism, not a risk to avoid. **Mitigation:** the grouped weekly
  cadence bounds the PR volume (one minor+patch PR per ecosystem per
  week, plus one PR per major bump); reviewers can batch-triage. If
  a specific major bump breaks the audit matrix, the right fix is to
  investigate the breakage, not silence Dependabot.
- **Risk — zero Dependabot PRs open after merge** (silent misconfig).
  See the research / directory-must-be-`/` gotcha. **Mitigation:** the
  Measurement plan's falsification bullet makes this an explicit
  7-day check; the memory below codifies the fix.
- **Risk — PR flood on first run.** The `github-actions` ecosystem
  will inspect every pinned action in `ci.yml` (today:
  `actions/checkout`, `actions/setup-python`) and open PRs for any
  that have moved; `docker` will inspect
  `infra/hermes/Dockerfile`'s `FROM` lines and open PRs for any
  base-image tag that has moved. On a fresh repo this is usually
  1–3 PRs. **Mitigation:** the grouped-minor+patch config bundles
  the quiet bumps; `open-pull-requests-limit: 5` caps the burst.
  Document this in the chunk's PR body so the first wave isn't
  mistaken for a config error.
- **Risk — majors are un-grouped and open one PR each.** Deliberate:
  majors need human judgement. **Mitigation:** if any major becomes
  chronic (open > 30 days without triage), either merge or close
  with a `labels: [ignore]` entry in a follow-up PR; don't group
  majors with minors.
- **Risk — Scorecard follow-on proposal
  (`security-e8dffa5d30`) relies on this config existing.** Positive
  dependency, not a risk, but worth noting so sequencing is
  explicit. If this proposal is abandoned, Scorecard will still
  install; Scorecard will just log a 0/10 on
  `Dependency-Update-Tool` until Dependabot or Renovate ships. No
  blocker.
- **Risk — auditor regresses between this proposal and the
  post-merge audit.** Low; `audit_dependencies()` is stable and the
  test suite covers the detector. **Mitigation:** post-merge audit
  is the oracle; if the metric doesn't flip, debug the auditor,
  not the config.

## Outcome

> *TBD — appended after the re-measure step.*

| Metric | Baseline | Post-execution | Δ | Target | Verdict |
|---|---|---|---|---|---|
| `dependencies.dependabot_config` | `false` | — | — | `true` | — |

- **Did the hypothesis hold?** —
- **Unexpected movement** in other metrics (intended or otherwise). —
- **What we learned**, for the next proposal of this kind. —
