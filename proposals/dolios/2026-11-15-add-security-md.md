---
id:     dolios/2026-11-15-add-security-md
status: proposed
repo:   dolios
audit:  .dolios/metrics/dolios/history.jsonl#L7@2026-11-15T03:30:56Z
gap_ids:
  - security-629ad05d83
metrics:
  - docs.security_md_present
frameworks:
  - "OpenSSF Scorecard: Security-Policy"
  - "NIST SSDF: PO.1 — define the security & compliance requirements"
opened:    2026-11-15
approved:  null
done:      null
---

# Add a root `SECURITY.md` with a reporting channel and a 90-day SLA

## Hypothesis

Adding a top-level `SECURITY.md` that names a vulnerability-reporting channel
(email + GitHub private advisory URL), a supported-versions statement, and an
explicit 90-day coordinated-disclosure SLA should move
**`docs.security_md_present`** from **`false`** to **`true`** in the **next
weekly audit cycle**, because:

- OpenSSF Scorecard's **Security-Policy** check scores a repo on whether a
  `SECURITY.md` is published at a well-known location, whether it contains at
  least one valid email or HTTP URL for reporting, whether it contains free-form
  text beyond those links, and whether it mentions disclosure terminology with
  timeframe numbers — all three tiers are satisfied by one file.
- NIST SSDF **PO.1** (Define Security Requirements for Software Development)
  requires that software's vulnerability-handling procedures be *documented
  and communicated* to internal and external parties; a `SECURITY.md`
  committed to the repo is the canonical artefact.

The auditor's operational proxy for both is a bare `SECURITY.md` at repo root
(`services/auditor/audit.py:277` — the only path checked is `repo /
"SECURITY.md"`; no `.github/`, no `docs/`). Presence flips the metric; the
*content* of the file is what makes the policy useful to a real reporter, so
the chunk specifies both.

## Audit citation

- **Audit row:** `.dolios/metrics/dolios/history.jsonl` line 7,
  `audited_at: 2026-11-15T03:30:56Z` (`git_head: 83b4833`) — the most recent
  row at proposal time, the one the picker's dispatch cited.
- **Gap targeted:** `gap_id: security-629ad05d83` — `security` / "No
  SECURITY.md" (severity: **medium**). Verbatim: *"No vulnerability-disclosure
  policy — researchers have nowhere documented to report findings."*
  Auditor's suggested action: *"Add SECURITY.md naming a reporting channel
  and a response SLA."* (`services/auditor/audit.py:533`.)
- **Frameworks:**
  - **OpenSSF Scorecard: Security-Policy.** The check awards 6/10 points for
    a valid email or URL for reporting, 3/10 for free-form text beyond those
    links, and 1/10 for disclosure-specific terminology (`vuln`, `disclos`,
    or timeframe numbers like "90 days"). All three are hit by the file this
    chunk writes. See
    <https://github.com/ossf/scorecard/blob/main/docs/checks.md#security-policy>.
  - **NIST SSDF: PO.1.** PO.1.1 "identify and document all security
    requirements for the organization's software development" and PO.1.3
    "communicate requirements to all third parties." The vulnerability-report
    contract is the piece of PO.1 that `SECURITY.md` carries. See
    `docs/metrics.md:45` for the mapping of "SECURITY.md present" to OpenSSF
    Scorecard *Security-Policy* in this repo's audit model.
- **Why this gap.** Two `medium`-severity `security` gaps are open in the
  cited row (`security-629ad05d83` — no SECURITY.md; `security-2fdc3f14c1`
  — no secrets scanner). SECURITY.md is the lower-friction unblock — a
  single static markdown file at repo root with no runtime surface, no CI
  wiring, no tuning — and it is a gating prerequisite for the Scorecard
  workflow proposal (`security-e8dffa5d30`, low severity) that will want a
  pre-existing policy to score against. The gitleaks proposal (chunked tool
  adoption, CI job, tuning) is independently valuable but lives in its own
  larger PR; sequencing the cheap one first mirrors the LICENSE-before-rest
  ordering from `2026-11-14-add-license-file.md`.

## Baseline

The cited audit row gives:

| Metric | Current | Source |
|---|---|---|
| `docs.security_md_present` | `false` | audit row above |

The metric is already measured (`audit_docs()` filesystem check); this is a
single-arm hypothesis.

## Intervention

One execution-PR-sized chunk. One new file, ~40 lines of markdown.

- [ ] **Add `SECURITY.md` at repo root with a reporting channel and SLA.**
   - Path: `SECURITY.md` (bare, no `.github/` or `docs/` prefix — the
     auditor matches `repo / "SECURITY.md"` exactly at
     `services/auditor/audit.py:277`, so any other path leaves the metric
     `false`). Same lesson as the LICENSE chunk: case-sensitive on Linux,
     filename exactly `SECURITY.md`.
   - Structure the content to satisfy all three OpenSSF Scorecard
     Security-Policy tiers in one pass:
     1. **Supported versions** — a short table stating that this repo
        tracks `main` only and supports the latest commit; no backported
        branches. Satisfies the "free-form text" tier and contributes the
        numeric/version content the tier-3 pattern match looks for.
     2. **Reporting a vulnerability** — two channels, in preference order:
        - GitHub Private Vulnerability Reporting (the "Report a
          vulnerability" button on the Security tab) — link to the repo's
          `/security/advisories/new` endpoint. This is the OpenSSF-preferred
          path because it keeps the report private between reporter and
          maintainer until a coordinated disclosure.
        - Email: **`dolasllc@gmail.com`** — the maintainer address of
          record (see risk section; a dedicated alias is a sensible
          follow-up once DNS/MX is set up for the LLC, but the metric
          flips on *presence of any valid email*, not on the shape of the
          mailbox). Satisfies the tier-1 "valid email or URL" requirement
          (both are supplied).
     3. **Response SLA** — "We aim to acknowledge reports within **7
        days** and provide a remediation plan within **30 days**; absent
        maintainer-reporter agreement to extend, we target coordinated
        public disclosure within **90 days** of initial report, per
        industry norm." Satisfies tier-3 (`vuln`/`disclos` keywords + the
        timeframe numbers `7`, `30`, `90`).
     4. **Scope** — one sentence noting what counts as a security issue
        (code in this repo + the `services/` MCP servers) vs out-of-scope
        (third-party services the fleet integrates with — Pegasus,
        Anthropic, OpenRouter — should be reported to their respective
        providers).
     5. **Safe-harbor sentence** — "We will not pursue legal action
        against researchers who make a good-faith effort to comply with
        this policy," single line, lifted from the common pattern (see
        disclose.io's template language).
   - No other files. No `.github/SECURITY.md` duplicate (would be dead
     weight — GitHub treats the root file as canonical and the auditor
     doesn't look there). No source headers, no CI/workflow change, no
     dependency change, no runtime surface touched.
   - Enabling GitHub's Private Vulnerability Reporting toggle on the
     `DolasDev/dolios` repo settings page is a human one-click action and
     is **out of scope for this chunk** — the policy references the URL
     and will route correctly once enabled; the metric flips regardless.
     Flag this in the chunk's PR body as a reviewer-side follow-up so the
     link isn't a 404 in practice.

## Measurement plan

- **Metric(s) to watch:**
  - **Primary:** `docs.security_md_present` (must flip to `true`).
  - **Gap presence:** the audit row's `gaps:` array must no longer contain
    an entry with `gap_id: security-629ad05d83` after the chunk merges.
  - **Guard metrics:** none mechanical. A 40-line static markdown file at
    repo root has no plausible causal path to `ci.*`, `commits.*`,
    `security.*` (the policy is a doc, not a scanner config), or any other
    `docs.*` field. Carrying the LICENSE proposal's absence-of-guards
    note forward: other-field movement in the post-audit row is
    attributable to concurrent work, not this PR.
- **Sampling cadence:** every weekly audit run; `make audit` in the
  dispatcher's existing cron picks it up.
- **Success threshold:** after the chunk's execution PR merges, the next
  audit row must have `docs.security_md_present: true` **and** must not
  include a gap with `gap_id: security-629ad05d83` in its `gaps:` array.
  Both conditions, not one — second guards against an auditor bug where
  the flag flips but `derive_gaps()` doesn't drop the entry.
- **When to call it:** the dispatcher runs an audit immediately after the
  execution PR merges and appends the Outcome section. This is a
  presence check, not a trend; no multi-cycle window needed.
- **What would falsify it:**
  - `docs.security_md_present` stays `false` — the auditor isn't
    detecting the file. Check: is it at repo root (not `.github/`,
    not `docs/`), named exactly `SECURITY.md`, committed (not just
    staged)? If all three check out, file an auditor bug against
    `services/auditor/audit.py:277`.
  - `docs.security_md_present` flips to `true` but the gap re-appears
    with the same `gap_id` — `derive_gaps()` is not reading
    `docs["security_md_present"]` correctly. File a bug against
    `services/auditor/audit.py:533`.
  - A follow-up `security`-area proposal (Scorecard workflow) remains
    gated on the SECURITY.md wording — treat as scope creep on this PR,
    file as its own proposal. The wording is a defensible default, not
    a legal document.

## Research / prior art

The research step considered what OpenSSF Scorecard and GitHub actually
require of a security policy, and what the common industry templates
include, before landing on the content above.

- **Considered:** **OpenSSF Scorecard Security-Policy check** —
  <https://github.com/ossf/scorecard/blob/main/docs/checks.md#security-policy>.
  Confirms the three-tier scoring: (1) a valid email or HTTP URL for
  reporting = 6/10, (2) free-form text beyond those links = 3/10,
  (3) ≥2 matches of disclosure-specific terms (`vuln`, `disclos`, timeframe
  numbers like "30 days") = 1/10. The policy drafted above hits all three
  by construction.
- **Considered:** **GitHub's "Adding a security policy to your repository"
  docs** — <https://docs.github.com/en/code-security/getting-started/adding-a-security-policy-to-your-repository>.
  GitHub recommends two elements: supported versions and reporting
  instructions. Light on specifics (no SLA, no scope) — we take those from
  industry norm.
- **Considered:** **GitHub Private Vulnerability Reporting (PVR)** —
  <https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability>.
  OpenSSF's recommended intake path for public repos because it keeps the
  initial report private between reporter and maintainer until a GHSA is
  issued. Linking to `/security/advisories/new` in SECURITY.md makes the
  "Report a vulnerability" button visible on the Security tab once the
  repo-level toggle is enabled by a human maintainer.
- **Considered:** **disclose.io** safe-harbor template language —
  <https://github.com/disclose/dioterms>. Lifted one sentence (safe harbor
  for good-faith research) to improve the policy's usefulness without
  expanding scope.
- **Considered:** **Alternative placement** at `.github/SECURITY.md` or
  `docs/SECURITY.md`. OpenSSF Scorecard matches all three locations
  (case-insensitive), but our local auditor only looks at repo-root
  `SECURITY.md`. Root wins on both counts; no reason to split.
- **Picked:** **Bare `SECURITY.md` at repo root**, ~40 lines, structured
  as above. Satisfies the local auditor on the first try, hits a 10/10
  Scorecard Security-Policy score for when the Scorecard workflow lands
  (`security-e8dffa5d30`), and gives a real human reporter a clear
  contract.

## Effort & risk

- **Effort:** **1 PR, ~15 minutes of dispatcher time.** One new file, ~40
  lines of markdown, no tests to write (the auditor's filesystem check is
  the test; `services/auditor/test_audit.py:272` already asserts
  `security_md_present: True` as a passing state), no runtime surface
  touched, no CI matrix to adjust.
- **Risk — reporting-channel mailbox mismatch.** `dolasllc@gmail.com` is
  the maintainer address of record but may not be the right permanent
  home for security reports; a dedicated `security@dolas.dev` alias is
  the more typical pattern once a domain is configured. **Mitigation:**
  the metric flips on *presence of a valid email or URL*, not on which
  address. A follow-up PR can swap the email in-place without reopening
  the gap. The chunk's PR body flags this as a reviewer-visible choice.
- **Risk — the GHSA link is a 404 because Private Vulnerability
  Reporting isn't toggled on at the repo level.** **Mitigation:** the
  chunk's PR body explicitly flags the one-click repo-settings toggle as
  a human follow-up. Even if a reporter hits the link and it 404s,
  the email channel is a working fallback, and the metric still flips.
- **Risk — the 7/30/90-day SLA is more aggressive than Dolas LLC can
  sustain.** **Mitigation:** 90-day coordinated disclosure is the
  industry norm (Google Project Zero, CERT/CC); 30-day remediation plan
  is a plan, not a fix; 7-day acknowledgement is deliberately short
  because the fleet dispatcher is always-on. A real counsel/ops review
  can widen the numbers in a follow-up PR; the metric doesn't care about
  the exact values, only that disclosure-terminology-with-numbers is
  present (Scorecard tier 3).
- **Risk — the auditor's detection check is case-sensitive and a
  reviewer renames the file.** `audit.py:277` checks exactly
  `SECURITY.md` — case-sensitive on Linux. **Mitigation:** the chunk
  specifies `SECURITY.md` (bare, all-caps stem + lowercase extension);
  rename to `security.md` or `Security.md` leaves the metric `false`.
  The post-merge audit catches this; fix in a follow-up.
- **Risk — the auditor regresses between this proposal and the
  post-merge audit.** Low; `audit_docs()` is stable and
  `test_audit.py:272` covers `security_md_present: True`.
  **Mitigation:** the post-merge audit is the oracle; if the metric
  doesn't flip, debug the auditor, not the SECURITY.md.

## Outcome

> *TBD — appended after the re-measure step.*

| Metric | Baseline | Post-execution | Δ | Target | Verdict |
|---|---|---|---|---|---|
| `docs.security_md_present` | `false` | — | — | `true` | — |

- **Did the hypothesis hold?** —
- **Unexpected movement** in other metrics (intended or otherwise). —
- **What we learned**, for the next proposal of this kind. —
