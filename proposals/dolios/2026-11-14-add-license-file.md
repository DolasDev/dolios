---
id:     dolios/2026-11-14-add-license-file
status: proposed
repo:   dolios
audit:  .dolios/metrics/dolios/history.jsonl#L5@2026-11-14T09:00:59Z
gap_ids:
  - compliance-f6003ab812
metrics:
  - docs.license_present
frameworks:
  - "NIST SSDF: PO.1 — define the security & compliance requirements"
  - "OpenSSF Scorecard: License"
opened:    2026-11-14
approved:  null
done:      null
---

# Adopt Apache-2.0 as the explicit repo license

## Hypothesis

> Adding an **Apache-2.0 `LICENSE`** file at the repo root should move
> **`docs.license_present`** from **`false`** to **`true`** within **one audit
> cycle** (the first weekly run after the execution PR lands), because NIST
> SSDF **PO.1** operationally requires projects to "define and document the
> security and compliance requirements for the software" — of which the
> licensing posture is the legal-reuse foundation, and the auditor measures
> that posture by the presence of `LICENSE` / `LICENSE.md` / `LICENSE.txt` at
> the repo root (`services/auditor/audit.py:audit_docs`).

The choice of **Apache-2.0** specifically (over MIT or a proprietary "All
Rights Reserved" notice) is the one judgement call this proposal asks the
human reviewer to confirm at approval time — the Intervention is written so
that a redirect to MIT or to a proprietary text is a one-line comment, not a
rewrite. See *Research / prior art* for the comparison.

## Audit citation

- **Audit row:** `.dolios/metrics/dolios/history.jsonl` line 5,
  `audited_at: 2026-11-14T09:00:59Z` — the most recent audit, which still
  carries `docs.license_present: false` after the CI proposal
  (`dolios/2026-05-28-adopt-github-actions-ci`) closed.
- **Gap targeted:** `gap_id: compliance-f6003ab812` — `compliance` / "No
  LICENSE file" (severity: **medium**). Verbatim from the audit row:
  *"Repo has no LICENSE/LICENSE.md/LICENSE.txt — legally ambiguous reuse
  posture."* Proposed action from the auditor: *"Add an explicit LICENSE
  (Apache-2.0 / MIT / proprietary, per the project's intent)."*
- **Frameworks:**
  - **NIST SSDF PO.1** — "define and document the security and compliance
    requirements for the software, including … legal requirements."
    (NIST SP 800-218, *Define Security Requirements for Software
    Development*.) Without a `LICENSE`, the project has no defined legal
    requirements at all; any external contributor or downstream reader is
    left to guess intent, which is the exact gap SSDF PO.1 is written to
    close.
  - **OpenSSF Scorecard: License** — the *License* check gives a passing
    score iff a `LICENSE*` file is present at the repo root with recognised
    content. Any future Scorecard proposal (currently gap
    `security-*-no-scorecard-workflow`, severity low) will fail this check
    until the LICENSE lands; this proposal removes that downstream blocker.
- **Why this gap next.** After the CI proposal closed on 2026-11-14 the
  remaining open gaps are: `compliance` / no LICENSE (medium),
  `security` / no SECURITY.md (medium), `security` / no secrets scanner
  (medium), `supply_chain` / no Dependabot (medium), `testing` / no coverage
  (medium), `review` / no CODEOWNERS (low), `security` / no Scorecard
  workflow (low). The LICENSE gap is the only one with **zero technical
  dependencies** — it needs no CI surface, no scanner config, no tool
  install — and unblocks the Scorecard follow-up. It is the smallest
  possible "measurable, independent outcome" to run next, in the
  two-arm-structure pattern [[2026-05-28-adopt-github-actions-ci]]
  validated.

## Baseline

The cited audit row gives:

| Metric | Current | Source |
|---|---|---|
| `docs.license_present` | `false` | audit row above |

No `LICENSE`, `LICENSE.md`, or `LICENSE.txt` exists at the repo root (verified
by inspection at the time this proposal was drafted). The `README.md` does
not declare a license either, so there is no fallback signal.

## Intervention

One execution-PR-sized chunk. The proposal is intentionally single-chunk —
the metric depends only on file presence, and splitting a one-file commit
across PRs would add dispatcher overhead with no measurable benefit.

- [ ] **`LICENSE` — add the Apache-2.0 text verbatim at repo root.**
   - Path: `LICENSE` (no extension, matching the convention the auditor
     checks first and the one GitHub's repo UI auto-renders).
   - Content: the Apache License, Version 2.0 text verbatim from
     [apache.org/licenses/LICENSE-2.0.txt](https://www.apache.org/licenses/LICENSE-2.0.txt)
     (the canonical plain-text form; ~11 KB, 202 lines). No modifications to
     the license body itself — modifying it would invalidate the SPDX match
     and break Scorecard / GitHub license detection.
   - The trailing "APPENDIX: How to apply the Apache License to your work"
     block names the copyright holder and year. Fill it with:
     - Year: `2026`
     - Copyright holder: `Dolas LLC`
     (Matches the `dolasllc@gmail.com` git identity already in use on this
     repo; the human reviewer should correct the holder name to the
     formally-registered legal entity if "Dolas LLC" is not it.)
   - **No other files touched.** No `README.md` edit, no `pyproject.toml`
     edit (the file carries no `[project]` metadata table — it is tool-config
     only — so there is nothing to synchronise). Any cross-reference from
     README is intentionally a separate, out-of-scope cosmetic change.
   - Dispatcher preamble per [[0002-chunk-mode-claude-must-not-touch-proposal]]
     applies: the execution-PR chunk flips its own `[ ]` → `[x]` as part of
     the same commit; claude must not touch anything else in this proposal
     file.

**If the human reviewer wants MIT or proprietary instead.** The decision is
reversible before merge of the proposal PR: leave a review comment naming
the alternative and the chunk body above is overwritten with the chosen
license text. The rest of the proposal (hypothesis, baseline, measurement
plan) stands unchanged — the metric is license-text-agnostic.

## Measurement plan

- **Metric(s) to watch:**
  - **Primary:** `docs.license_present` — must flip from `false` to `true`.
- **Guard metrics:** none. Adding a static top-level file cannot affect
  commit cadence, CI runtime, test coverage, or any other metric the
  auditor tracks. Explicitly: `commits.median_lines_changed` *will* bump
  upward by ~200 lines on the week the chunk lands (Apache-2.0's own text
  size) — this is cosmetic noise and should not be treated as a regression.
- **Sampling cadence:** every audit run (currently weekly per repo).
- **Success threshold:** after the execution PR merges, the next audit row
  reports `docs.license_present: true`. Strict.
- **When to call it:** one audit cycle after merge is sufficient — presence
  of a static file is deterministic, not statistical. The dispatcher's
  post-merge audit will append the outcome row.
- **What would falsify it:**
  - `docs.license_present` is still `false` in the next audit row. Causes
    would be: file committed to a non-root path (the auditor only looks at
    the repo root), filename typo (`LICENCE` with British spelling — the
    auditor does not match it), or committed with an unusual extension the
    `audit_docs()` lookup list doesn't cover. Iterate by renaming.
  - The file is present but Scorecard's downstream *License* check (not yet
    wired, future proposal) fails because the text is malformed. Iterate by
    restoring the verbatim Apache-2.0 text.

## Research / prior art

The research step compared three license postures and chose Apache-2.0 as
the default recommendation, with MIT and proprietary as one-line redirects
the human reviewer can request.

**Shortlisted licenses**

- **Considered:** [MIT License](https://opensource.org/license/mit/) —
  permissive, 170 words, no patent grant. Suits small single-file utilities
  and prototypes. **Why not (default):** this repo wires up MCP tool
  invocations and may, as the `autonomous-coder` matures, incorporate novel
  technique (patent-grantable). MIT's silence on patents leaves implicit
  patent licensing to local law, which is weaker and jurisdiction-dependent.
  Still a perfectly reasonable redirect if the reviewer wants the shortest
  possible text.
- **Considered:** Proprietary / All Rights Reserved — e.g. the GitHub-hosted
  [Choose A License "no license" guidance](https://choosealicense.com/no-permission/)
  template, or a short "Copyright (c) 2026 Dolas LLC. All rights reserved."
  notice. **Why not (default):** the repo is already **public on GitHub**
  (the autonomous-coder dispatcher uses `gh` to open PRs from branches named
  `auto/coder/…`, and this proposal file itself will land on a public
  branch). A public repo with "All Rights Reserved" sends a mixed signal —
  the code is visible and forkable by GitHub ToS but has no granted license
  to use it. Pick this only if the intent is to make the repo private soon;
  if so, the proposal still works unchanged, with the text swapped.
- **Picked:** [Apache License, Version 2.0](https://www.apache.org/licenses/LICENSE-2.0)
  — permissive, explicit patent grant (§3), trademark carve-out (§6),
  contribution clause (§5). The default choice for infrastructure and
  tooling at the Apache Software Foundation, Google, Microsoft (most of
  `.NET`), Kubernetes, Terraform-pre-BSL, hermes-agent itself
  ([Nous Research / hermes-agent](https://github.com/NousResearch/hermes-agent)
  ships under Apache-2.0), and the Python `requests`/`cryptography` family.
  Rationale for this repo specifically:
  1. **Patent grant.** The repo contains novel-ish orchestration around
     autonomous coding (dispatcher + capacity gate + proposal loop). An
     explicit §3 grant is strictly stronger than MIT's silence on the
     question.
  2. **Upstream compatibility.** hermes-agent, which this repo wraps and
     ships via Docker, is Apache-2.0. Matching the upstream licence
     eliminates any inbound-compatibility question for downstream consumers
     and for future Nous Research collaboration.
  3. **Scorecard default.** The OpenSSF Scorecard *License* check
     ([scorecard.dev / License](https://github.com/ossf/scorecard/blob/main/docs/checks.md#license))
     treats Apache-2.0 as a recognised SPDX identifier; no custom
     configuration is needed to make it pass.
  4. **SPDX identifier**: `Apache-2.0`. Use the verbatim identifier string
     wherever a one-line license tag is needed (Python `[project] license
     = "Apache-2.0"` once a `[project]` table exists; future SBOM / OSV
     scanner output).

**Not shortlisted** (and why, briefly)

- **GPL-3.0 / AGPL-3.0** — copyleft. The project's downstream users may want
  to combine it with proprietary SaaS integrations (Pegasus, OpenRouter),
  which copyleft frustrates. Out of posture for this repo.
- **BSD-2-Clause / BSD-3-Clause** — permissive but no patent grant (same
  reasoning as MIT, with marginally more boilerplate).
- **ISC** — functionally equivalent to MIT, uncommon outside OpenBSD.
- **MPL-2.0** — file-level copyleft. Interesting middle ground but
  ergonomically annoying for mixed codebases; not worth the compliance
  overhead for a repo this small.

**Supporting references**

- [Choose A License (GitHub)](https://choosealicense.com/) — the GitHub /
  Open Source Guides decision tree; its "I want it simple and permissive"
  path routes to MIT, its "I'm concerned about patents" path routes to
  Apache-2.0.
- [SPDX License List](https://spdx.org/licenses/) — canonical identifiers
  (`Apache-2.0`, `MIT`, `BSD-3-Clause`, …); use the SPDX string anywhere a
  license tag is needed by tooling.
- [OpenSSF Scorecard checks — License](https://github.com/ossf/scorecard/blob/main/docs/checks.md#license)
  — the specific downstream check this proposal unblocks.
- [NIST SP 800-218 (SSDF v1.1), PO.1](https://csrc.nist.gov/pubs/sp/800/218/final)
  — the "define security and compliance requirements" practice this
  proposal operationalises.

## Effort & risk

- **Effort:** **1 PR, ~1 dispatcher-hour elapsed.** Chunk 1 is one new file
  of ~200 lines of license text — literally a `curl` of
  `apache.org/licenses/LICENSE-2.0.txt`, plus a two-line copyright block
  fill-in. No dependency installs, no tests to update, no Makefile targets
  to add.
- **Risk — wrong legal entity on the copyright line.** The dispatcher is
  filling the holder field from the repo's existing `dolasllc@gmail.com` git
  identity ("Dolas LLC"); the actual registered legal entity may use a
  different formal name. **Mitigation:** the human reviewer corrects the
  single `Copyright [yyyy] [name of copyright owner]` line in review; this
  is a two-token edit, not a re-architecture. The license body itself must
  not be changed.
- **Risk — wrong license choice.** If the reviewer wants MIT or proprietary
  instead, the whole intervention is one file-content swap.
  **Mitigation:** explicit in the Intervention section; the hypothesis,
  measurement plan, and metric all stand unchanged under any of the three
  license choices. The proposal does not need to be rewritten for a
  redirect.
- **Risk — Scorecard "License" check still fails after this lands.** The
  check uses [`scorecard`'s own detection logic](https://github.com/ossf/scorecard/blob/main/checks/license.go),
  which tolerates `LICENSE` / `LICENSE.md` / `LICENCE` / `COPYING` at the
  repo root with recognised SPDX content. Using the verbatim Apache-2.0
  text at `LICENSE` is the lowest-risk path. **Mitigation:** regression
  test when the future Scorecard proposal lands — if this check still
  fails, iterate on filename or encoding then.
- **Risk — Guard-metric noise on `commits.median_lines_changed`.** The
  commit will show +~200 lines (license text), which could artificially
  inflate the next audit's `median_lines_changed` for a week.
  **Mitigation:** per [[2026-05-28-adopt-github-actions-ci]]'s Outcome
  lesson #2 on confounders, flag it in the Outcome section rather than
  treating it as a regression. The window is 90 days; a single +200-line
  commit does not materially shift the median across that window.
- **Risk — none to runtime.** `LICENSE` is a static top-level file; it is
  not imported, loaded, or executed by any code path in `services/`,
  `scripts/`, `employees/`, or `infra/`. There is no behaviour-change
  surface.

## Outcome

> *TBD — appended after the re-measure step.*

| Metric | Baseline | Post-execution | Δ | Target | Verdict |
|---|---|---|---|---|---|
| `docs.license_present` | `false` | *tbd* | *tbd* | `true` | *tbd* |

- **Did the hypothesis hold?** *tbd*
- **Unexpected movement** in other metrics: *tbd* (expect a cosmetic bump in
  `commits.median_lines_changed` from the license text itself; not a
  regression).
- **What we learned**, for the next proposal of this kind: *tbd*
