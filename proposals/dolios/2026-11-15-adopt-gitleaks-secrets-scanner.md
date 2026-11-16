---
id:     dolios/2026-11-15-adopt-gitleaks-secrets-scanner
status: approved
repo:   dolios
audit:  .dolios/metrics/dolios/history.jsonl#L7@2026-11-15T03:30:56Z
gap_ids:
  - security-2fdc3f14c1
metrics:
  - security.gitleaks_config_present
frameworks:
  - "DORA: Shift-left security"
  - "OpenSSF Scorecard: Token-Permissions / Pinned-Dependencies"
opened:    2026-11-15
approved:  2026-11-16
done:      null
---

# Adopt gitleaks with a tuned config, a CI job, and a pre-commit hook

> **Decision (human, 2026-11-16): approved.** The repo is public, so secret scanning is the highest-value control in this batch. Per memory 0005, use `gitleaks/gitleaks-action@v3`, not v2.

## Hypothesis

Adopting **gitleaks v8.30.x** — a committed `.gitleaks.toml` at repo root, a
dedicated GitHub Actions job that runs it on every push and pull request,
and a `.pre-commit-config.yaml` that runs it locally on staged diffs — should
move **`security.gitleaks_config_present`** from **`false`** to **`true`** in
the **next weekly audit cycle**, because:

- The auditor's operational proxy for "a secrets scanner is configured" is
  the filesystem presence of `.gitleaks.toml` or `.gitleaksignore` at repo
  root (`services/auditor/audit.py:292`). Writing the config flips the
  metric by construction; the CI job and pre-commit hook are what make the
  scanner actually *run*.
- **DORA — Shift-left security:** detection of credentials must happen as
  close to the author as practical. A pre-commit hook blocks the commit on
  the developer's machine; a CI job is the second line so that a developer
  who bypasses the hook (new clone, `--no-verify`, web-UI edit) still hits
  a blocking gate before merge.
- **OpenSSF Scorecard — Token-Permissions / Pinned-Dependencies:** the
  check that cares about least-privilege GitHub tokens presumes those
  tokens aren't exfiltrated via the repo in the first place; gitleaks is
  the standard open-source tool to enforce that invariant.

The hypothesis is single-arm against the metric (`gitleaks_config_present`
is a filesystem presence check, not a run-count), but the three-chunk
intervention also delivers the enforcement the gap's `proposed_action`
asked for, so the downstream Scorecard-workflow proposal
(`security-e8dffa5d30`) inherits a real signal rather than a shim.

## Audit citation

- **Audit row:** `.dolios/metrics/dolios/history.jsonl` line 7,
  `audited_at: 2026-11-15T03:30:56Z` (`git_head: 83b4833`) — the most
  recent row at proposal time, the one the picker's dispatch cited.
- **Gap targeted:** `gap_id: security-2fdc3f14c1` — `security` / "No
  secrets scanner configured" (severity: **medium**). Verbatim:
  *"V0 audit's regex sweep is a placeholder; a real scanner
  (gitleaks/trufflehog) must run pre-commit and in CI."* Auditor's
  suggested action: *"Adopt gitleaks; add a pre-commit hook and a CI job.
  Tune .gitleaks.toml for this repo's patterns."*
  (`services/auditor/audit.py:558`.)
- **Frameworks:**
  - **DORA — Shift-left security.** DORA's security capability names
    "integration of security practices into the software supply chain"
    and specifically calls out *detecting* vulnerabilities as early in
    the authoring/CI loop as practical. Secret detection is the
    canonical pre-commit shift-left control.
  - **OpenSSF Scorecard — Token-Permissions / Pinned-Dependencies.**
    These two Scorecard checks presume that credentials in the repo are
    scoped-and-pinned; gitleaks is the complementary control that
    catches the case where a real (not scoped) token leaks in. See
    <https://github.com/ossf/scorecard/blob/main/docs/checks.md#token-permissions>
    and <https://github.com/ossf/scorecard/blob/main/docs/checks.md#pinned-dependencies>.
  - `docs/metrics.md:48` maps "gitleaks config present" to *DORA
    Shift-left security* in this repo's audit model.
- **Why this gap.** One remaining `medium` `security`-area gap after
  `security-629ad05d83` (SECURITY.md, now in flight). The other `security`
  item in the row is `security-e8dffa5d30` (OpenSSF Scorecard workflow,
  **low** severity) which is better sequenced *after* gitleaks lands —
  Scorecard will then have a real scanner to score against rather than
  the V0 regex placeholder. Picking this one next continues the sequencing
  pattern used by the LICENSE → SECURITY.md chain.

## Baseline

The cited audit row gives:

| Metric | Current | Source |
|---|---|---|
| `security.gitleaks_config_present` | `false` | audit row above |

The metric is already measured (filesystem presence check); this is a
single-arm hypothesis. `security.regex_secret_finding_count` is `0` at
baseline — the V0 regex sweep has found no plausible secrets, so the
transition to gitleaks is not expected to surface a backlog of findings
to triage (see risks below).

## Intervention

Three execution-PR-sized chunks, landing in order. Chunk 1 alone flips
the metric; chunks 2–3 deliver the enforcement the gap's `proposed_action`
asked for. Each chunk is independently useful — if chunks 2 or 3 stall
for any reason, the proposal has still moved the audit.

- [ ] **Chunk 1 — Add `.gitleaks.toml` at repo root with tuned defaults
      and an allowlist for this repo's placeholders.**
   - Path: **`.gitleaks.toml`** (bare, dotfile at repo root — case-sensitive
     on Linux). `services/auditor/audit.py:292` matches exactly
     `.gitleaks.toml` or `.gitleaksignore`; nothing else (no
     `.github/.gitleaks.toml`, no `configs/.gitleaks.toml`). Same
     case-sensitivity trap the SECURITY.md chunk already flagged.
   - Content: extend the gitleaks built-in rule set
     (`[extend] useDefault = true`) rather than redefining rules from
     scratch. The default rule set covers AWS, GCP, GitHub tokens, Slack,
     Stripe, private keys, JWTs, etc. and is maintained upstream.
   - `[allowlist]` entries (justified in Research below):
     - `paths` — regex: `^\.env\.example$`, `^employees/.*/env\.example$`,
       `^services/auditor/(audit|test_audit)\.py$`. The first two carry
       the string `POSTGRES_PASSWORD=changeme` — obviously a placeholder
       but a `generic-api-key` rule can match the literal; the third holds
       `SECRET_PATTERNS` and test fixtures (`AKIA…`, `ghp_…`, etc.) that
       are *intentional* literals to drive the V0 regex sweep (see the
       pre-existing `# don't self-match` comment at `audit.py:295`).
     - `stopwords` — `["changeme", "example", "placeholder"]`.
     - `regexes` — one entry: `(?i)CHANGEME` as a defensive catch-all
       for the `.env` placeholder convention.
   - Pin gitleaks' expectation of its own metadata via the file's
     leading comment: version string `# gitleaks >= v8.30` so a reader
     knows what config schema this file targets. No runtime behaviour
     depends on the comment.
   - **No other files in this chunk.** No CI edits, no pre-commit edits,
     no scripts. The chunk is a two-file add (the `.gitleaks.toml` plus
     the `[x]` flip in the proposal), nothing else.

- [ ] **Chunk 2 — Add a gitleaks CI job via a dedicated workflow
      `.github/workflows/gitleaks.yml`.**
   - Separate workflow file (not a job in `ci.yml`) for two reasons:
     (1) the existing `ci.yml` runs a Python test matrix with a specific
     setup — gitleaks has no Python dependency, lives in its own
     lifecycle, and merging it in would force both matrices to re-run
     on every change to either; (2) a dedicated file with its own
     concurrency group makes the job easy to disable if it ever becomes
     a chronic blocker, without risking a re-roll of the entire test
     matrix.
   - Triggers: `pull_request: {branches: [main]}` + `push: {branches: [main]}`
     — mirror `ci.yml`'s triggers so the two gates fire together on the
     same PRs.
   - Permissions: `contents: read` only (least-privilege; the job does
     not write or need to write anything). Explicitly **no**
     `security-events: write` in this chunk — SARIF upload to GitHub
     Code Scanning is a separate, deliberately-scoped follow-up (see
     Research), and granting the permission here would silently enlarge
     the token's blast radius.
   - Action: **`gitleaks/gitleaks-action@v3`**, pinned by commit SHA in
     the same style as `ci.yml`'s `actions/checkout@08c6903…` and
     `actions/setup-python@e797f83…`. Why v3 and not v2: see memory
     candidate below — gitleaks-action **v2 stopped working on
     GitHub-hosted runners on 2026-09-16** when Node 20 was removed
     from the runner image. Any copy-pasted "add gitleaks to CI"
     guide written before mid-2026 pins `@v2` and will fail out of the
     box today.
   - `fetch-depth: 0` on the `checkout` step so gitleaks scans the full
     git history on `push`-to-main; on `pull_request` the action itself
     only inspects the PR's diff regardless of fetch depth (upstream
     docs), so the deep fetch cost lands on `push` only.
   - Fail-closed: the action exits non-zero on any finding, which fails
     the job and blocks a merge once the branch-protection reviewers
     require this check.
   - **No `.gitleaks.toml` edits in this chunk.** Chunk 1's config is
     the config; chunk 2 only wires it up.

- [ ] **Chunk 3 — Add `.pre-commit-config.yaml` with the official
      gitleaks hook, plus a CONTRIBUTING note.**
   - Path: **`.pre-commit-config.yaml`** at repo root. Hook:
     `repos: [{repo: https://github.com/gitleaks/gitleaks, rev: v8.30.1,
     hooks: [{id: gitleaks}]}]`. Pin an exact rev, not a floating tag.
   - Scope: `stages: [pre-commit]` only. Explicitly not `pre-push` —
     pre-push is redundant with the CI job (chunk 2) and would add
     perceived slowness to `git push` for no additional protection
     over "CI will catch it anyway."
   - Dev-only dependency on the `pre-commit` framework itself. Add a
     short section to `README.md` (not `CONTRIBUTING.md` — not present
     in the repo yet and not worth creating in this chunk) under a
     "Local development" or similarly-named heading, with the three
     lines a developer needs:
     ```
     pip install pre-commit
     pre-commit install
     pre-commit run --all-files   # first-time sanity sweep
     ```
     Keep it to five lines of new prose; do not restructure the README.
   - **No CI edit in this chunk** — pre-commit is a *local* enforcement;
     the CI gate from chunk 2 is the authoritative check.
   - The chunk's PR body should flag that developers who never install
     pre-commit still get coverage via chunk 2's CI job. The hook is an
     ergonomic, not-security, improvement over the CI-only setup.

Three chunks is the ceiling the proposal template recommends ("more than
~5 means the proposal is too big"); each chunk is a single file add plus
small adjacent edits, no chunk touches a runtime path.

## Measurement plan

- **Metric(s) to watch:**
  - **Primary:** `security.gitleaks_config_present` must flip to `true`
    after chunk 1 merges.
  - **Gap presence:** the audit row's `gaps:` array must no longer contain
    an entry with `gap_id: security-2fdc3f14c1` after chunk 1 merges.
    `derive_gaps()` at `services/auditor/audit.py:558` is a straight
    `if not sec["gitleaks_config_present"]` check, so this follows from
    the primary metric moving, but we verify both.
  - **Guard — `security.regex_secret_finding_count`:** stays at `0`.
    Chunk 1 adds the string `(?i)CHANGEME` as a literal inside the
    regex allowlist. The V0 regex sweep in `audit_security()` iterates
    `SECRET_PATTERNS` (`services/auditor/audit.py:76` ff., the global
    `SECRET_PATTERNS` list) over all source files, and
    `_walk_source()` skips dotfiles beginning with `.` (verify the
    exact filter before the chunk's PR lands; if dotfiles *are* walked,
    the `# don't self-match` carve-out pattern at `audit.py:295` is the
    precedent for excluding `.gitleaks.toml` too — add that line only if
    the sweep would otherwise match). If the guard metric rises, the
    fix is to extend the `audit.py:295` self-match carve-out, not to
    weaken the `.gitleaks.toml` allowlist.
  - **Guard — `ci.success_rate_30d`:** does not drop below 0.90 over the
    next 30 days. Chunk 2 introduces a new job on a clean baseline
    (`regex_secret_finding_count: 0`); gitleaks should find nothing and
    exit 0. If it exits non-zero, that is a *real* finding and the
    proposal has done its job on the very first run — triage the hit,
    don't disable the job.
  - **Guard — `ci.median_runtime_seconds`:** the dedicated workflow's
    runtime is reported alongside `ci.yml`'s. Because `ci_api.py`
    computes the median across *all* workflow runs in the lookback
    window, a very-fast gitleaks run (seconds) would pull the median
    down, which is a favorable direction; a very-slow one would push
    it up. Don't treat small movement here as a regression either way.
- **Sampling cadence:** every weekly audit run; `make audit` in the
  dispatcher's existing cron picks it up.
- **Success threshold:** after chunk 1's execution PR merges, the next
  audit row must have `security.gitleaks_config_present: true` **and**
  must not include a gap with `gap_id: security-2fdc3f14c1` in its
  `gaps:` array. Both conditions, not one — the second guards against
  an auditor bug where the flag flips but `derive_gaps()` doesn't
  drop the entry (the LICENSE post-mortem's two-condition pattern).
- **When to call it:** the dispatcher runs an audit immediately after
  chunk 1's execution PR merges and appends an interim Outcome row;
  final verdict after chunk 3 merges and one further audit confirms
  the pre-commit hook config coexists with the primary metric still
  at `true`. This is a presence check, not a trend; no multi-cycle
  window needed. (No `ops.*` in the `metrics:` list, so the
  `code_cutoff` self-reset issue from memory 0004 does not apply.)
- **What would falsify it:**
  - `security.gitleaks_config_present` stays `false` after chunk 1
    merges. Check: is the file at repo root (not `.github/`, not
    anywhere else), named exactly `.gitleaks.toml` (case-sensitive),
    actually committed (not just staged)? If all three check out,
    file an auditor bug against `services/auditor/audit.py:292`.
  - Metric flips to `true` but the gap re-appears with the same
    `gap_id` — `derive_gaps()` is not reading
    `sec["gitleaks_config_present"]` correctly. File a bug against
    `services/auditor/audit.py:558`.
  - Chunk 2's CI job finds real secrets on first run. This is a
    *successful* falsification of the implicit "the repo is clean"
    sub-hypothesis; the proposal's hypothesis about the *metric* still
    holds. Triage the hits (rotate, `git-filter-repo` if the secret
    hit history), don't silence the job.
  - Chunk 3's pre-commit hook false-positives on routine commits
    inside a week of merging — developers will start `--no-verify`-ing
    around it. Response: extend `[allowlist]` in the already-merged
    `.gitleaks.toml` (follow-up PR), not revert the hook.

## Research / prior art

The research step verified current best-practice tooling for Git
secret-scanning and the known operational gotchas before settling on
the above intervention.

- **Considered:** **TruffleHog**
  (<https://github.com/trufflesecurity/trufflehog>, v3.99.7 as of
  Oct 2026, actively maintained). Verifies whether a detected
  credential is *live* by testing it against the provider's API —
  the one feature gitleaks lacks. Not picked for the *pre-commit*
  role because the live-verify step is slower and depends on
  outbound network, which breaks developer ergonomics and
  air-gapped CI. The 2026 secrets-scanner benchmarks all land on
  the same split: *gitleaks pre-commit, trufflehog for deep history
  audits in CI*. Dolios is small; a single tool (gitleaks) in both
  slots is simpler for now. Trufflehog can be added as a second,
  slower CI job in a follow-up proposal if we ever care about live
  verification.
- **Considered:** **detect-secrets**
  (<https://github.com/Yelp/detect-secrets>). Older (Yelp), maintenance
  is spotty, uses a `secrets.baseline` file that has to be regenerated
  on every new finding — operational tax every team I know of has
  regretted. Not picked.
- **Considered:** **GitGuardian** (<https://www.gitguardian.com/>).
  SaaS, free tier is per-seat and bills on contributors. Possibly
  worth revisiting if Dolas LLC grows past three developers; today
  it is both overkill and vendor lock-in for one maintainer. Not
  picked.
- **Considered:** **GitHub Secret Scanning** (native). It exists, it
  runs on every public repo, and findings surface in the Security
  tab — but it only covers partner-verified token formats (GitHub,
  AWS, etc.), it is not configurable, and crucially it is **not**
  what OpenSSF Scorecard is checking for in the Token-Permissions /
  Pinned-Dependencies lane. Treat it as complementary (enabled at
  the org level), not as the proposal's implementation.
- **Picked:** **gitleaks v8.30.x**
  (<https://github.com/gitleaks/gitleaks>). v8.30.1 (released
  2026-03-21) is the current stable; upstream maintainer has
  signalled "feature complete, security patches only" as of
  2026-05-21. That is a feature, not a liability — the rule set
  is mature, rate of API churn is near zero, and pinning an exact
  rev in `.pre-commit-config.yaml` plus a SHA in CI is safe for
  a long window. Written in Go, single static binary, no
  Python/Node dependency, maintained regex rule set.
- **Known operational gotcha — `gitleaks-action` version pin.** The
  official **`gitleaks/gitleaks-action` v2** stopped working on
  GitHub-hosted runners on **2026-09-16** when Node 20 was removed
  from the runner image. v3 (Node 22) is the only live option on
  GitHub-hosted runners today; copy-pasting a pre-Sept-2026 CI
  guide that pins `@v2` fails on first run. Chunk 2 pins **v3 by
  SHA**, not `@v3` or `@v2`. Codified in a new memory alongside
  this proposal (see below).
- **Known operational gotcha — the `.gitleaks.toml` /
  `.gitleaksignore` auditor match is case-sensitive on Linux.** Same
  class of trap as the LICENSE and SECURITY.md chunks: exact dotfile
  name or the metric stays `false`. Not writing a separate memory
  for this one — it's a consequence of `audit.py:292` being a
  straight `Path.exists()` call, which is obvious once you open the
  file.
- **Known operational gotcha — the auditor's regex sweep could
  false-positive on `.gitleaks.toml`.** Chunk 1 explicitly contains
  example-style secret substrings (`AKIA…` prefixes etc. in the
  `[allowlist]` regex stanza). Before chunk 1's PR lands, verify
  `_walk_source()`'s inclusion filter — if dotfiles *are* walked,
  extend the `# don't self-match` carve-out at `audit.py:295` the
  same way the auditor already excludes its own source. The
  guard-metric check above makes this visible on first post-merge
  audit.

## Effort & risk

- **Effort:** **3 PRs, ~3–4 hours of dispatcher time elapsed.** Chunk 1
  is a single 40-line TOML add (~15 min). Chunk 2 is a single
  40-line workflow YAML add (~30 min — most of the time is choosing
  the right action SHA and verifying it exists). Chunk 3 is a single
  pre-commit YAML add plus a five-line README section (~20 min).
  No tests to write (presence check is the test;
  `services/auditor/test_audit.py:266` already covers
  `gitleaks_config_present: True`), no runtime surface touched, no
  Python dependencies added (pre-commit framework is a *dev-time*
  tool a developer installs locally, not a declared project
  dependency).
- **Risk — false-positive flood on first run.** Gitleaks' default rule
  set is broader than the V0 regex sweep (which found 0 findings).
  The `.env.example` file (`POSTGRES_PASSWORD=changeme`) is the most
  likely hit on a `generic-api-key` rule. **Mitigation:** chunk 1's
  `[allowlist]` explicitly lists `.env.example` and the auditor's own
  pattern-holding source files; chunk 1's PR body should include the
  output of a local `gitleaks detect --config .gitleaks.toml` dry
  run to demonstrate zero findings on the clean baseline. If the
  dry run surfaces hits, extend the allowlist in the same PR.
- **Risk — `gitleaks-action@v2` pin breaks CI.** See the research
  section: v2 is dead on GitHub-hosted runners. **Mitigation:** chunk 2
  pins v3 by commit SHA. Reviewers should verify the pin matches the
  latest v3 release tag.
- **Risk — pre-commit framework introduces a new developer
  dependency.** Developers who never ran `pip install pre-commit`
  will not see local protection. **Mitigation:** chunk 3 is *purely*
  ergonomic; chunk 2's CI job is the authoritative gate. The
  proposal's primary metric (`gitleaks_config_present`) flips on
  chunk 1; chunks 2–3 can land late or be reverted without failing
  the hypothesis.
- **Risk — new workflow pulls `ci.median_runtime_seconds` and
  `ci.success_rate_30d` around.** Discussed in the Measurement plan;
  neither direction of movement is a proposal failure. Carrying
  forward the **CI-proposal guard-metric lesson** from the
  `2026-05-28-adopt-github-actions-ci` outcome: pair each guard
  with a "what else could cause this?" line, rather than a bare
  threshold. Both guards above have that annotation.
- **Risk — auditor regresses between this proposal and the post-merge
  audit.** Low; `audit_security()` is stable and
  `test_audit.py:266` covers `gitleaks_config_present: True`.
  **Mitigation:** post-merge audit is the oracle; if the metric
  doesn't flip, debug the auditor, not the config.
- **Risk — the `.gitleaks.toml` file's own example-looking strings
  trigger the V0 regex sweep itself.** Covered in Research /
  "auditor's regex sweep could false-positive on `.gitleaks.toml`."
  Checked before chunk 1's PR lands.

## Outcome

> *TBD — appended after the re-measure step.*

| Metric | Baseline | Post-execution | Δ | Target | Verdict |
|---|---|---|---|---|---|
| `security.gitleaks_config_present` | `false` | — | — | `true` | — |

- **Did the hypothesis hold?** —
- **Unexpected movement** in other metrics (intended or otherwise). —
- **What we learned**, for the next proposal of this kind. —
