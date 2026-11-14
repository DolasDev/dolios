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
opened:    2026-11-14
approved:  null
done:      null
---

# Add an explicit LICENSE declaring Dolas LLC proprietary terms

## Hypothesis

Adding a top-level `LICENSE` file that explicitly declares the repository
proprietary to **Dolas LLC** — i.e. all-rights-reserved with internal-use carve-outs
for employees and agents working on behalf of the company — should move
**`docs.license_present`** from **`false`** to **`true`** in the **next weekly
audit cycle**, because NIST SSDF *PO.1* requires that the security & compliance
requirements of a software product be *explicitly defined and documented*, and
the auditor's operational proxy for that at the repo surface is the presence of
a `LICENSE`/`LICENSE.md`/`LICENSE.txt` file (`services/auditor/audit.py:272`).
Legally-ambiguous reuse posture — the current state, with no declaration — is
the specific hazard the gap is flagging; a written declaration (regardless of
which direction it points — OSS or proprietary) resolves the ambiguity by
construction.

## Audit citation

- **Audit row:** `.dolios/metrics/dolios/history.jsonl` line 5,
  `audited_at: 2026-11-14T09:00:59Z` — the most recent row at proposal time,
  the one the picker's dispatch cited.
- **Gap targeted:** `gap_id: compliance-f6003ab812` — `compliance` / "No LICENSE
  file" (severity: **medium**). Verbatim: *"Repo has no
  LICENSE/LICENSE.md/LICENSE.txt — legally ambiguous reuse posture."* The
  auditor's suggested action: *"Add an explicit LICENSE (Apache-2.0 / MIT /
  proprietary, per the project's intent)."*
- **Frameworks:**
  - **NIST SSDF: PO.1** — *Define Security Requirements for Software
    Development.* PO.1.1 asks organizations to "identify and document all
    security requirements for the organization's software development" and PO.1.3
    to "communicate requirements to all third parties who will provide commercial
    software components to the organization for reuse." The license is the
    primary written declaration of the reuse/distribution terms that PO.1 is
    defining. See `docs/metrics.md:44` for the mapping of "LICENSE present"
    to NIST SSDF PO.1 in this repo's audit model.
- **Why this gap.** It is the lowest-friction `medium`-severity item still open
  after the CI proposal landed (`gap_ids: compliance-f6003ab812` is the only
  `compliance`-area gap in the row). A single-file PR unlocks the broader
  `docs.*`/compliance-area proposals (SECURITY.md disclosure email, CODEOWNERS)
  without touching any runtime surface.

## Baseline

The cited audit row gives:

| Metric | Current | Source |
|---|---|---|
| `docs.license_present` | `false` | audit row above |

No other `docs.*` fields change as a result of this proposal; they remain at
their current values. The metric is already measured (the auditor's
filesystem check), so this is a single-arm hypothesis — unlike the CI
proposal that had to flip measurement itself.

## Intervention

One execution-PR-sized chunk. One file, ~15 lines.

- [ ] **Add `LICENSE` at repo root declaring Dolas LLC proprietary terms.**
   - Path: `LICENSE` (bare, no extension — matches both GitHub's "License"
     detection UI and `audit_docs()`'s first branch).
   - Content: a short proprietary / all-rights-reserved notice naming
     **Dolas LLC** as copyright holder, the current year (2026) as the
     copyright year, and an explicit internal-use carve-out for Dolas LLC
     employees and automated agents (the autonomous-coder, future hermes
     employees) working on behalf of the company. The goal is clarity for
     any future contributor/auditor/outside reader about what rights they
     do and do not have, not legal exotica.
   - Suggested text (reviewer may swap any wording; the point is the
     declaration, not this specific prose):

     ```
     Copyright (c) 2026 Dolas LLC. All rights reserved.

     This repository and its contents are proprietary to Dolas LLC.

     No license is granted to use, copy, modify, merge, publish, distribute,
     sublicense, or sell copies of the Software, except that Dolas LLC
     employees and automated agents operating on behalf of Dolas LLC
     (including the autonomous-coder and future hermes-agent profiles
     specified in this repository) are authorized to do so in the course of
     their work for Dolas LLC.

     The Software is provided "as is", without warranty of any kind, express
     or implied, including but not limited to the warranties of
     merchantability, fitness for a particular purpose, and
     noninfringement.
     ```

   - **Decision point for the reviewer.** If Dolas LLC's actual intent is
     open-source (Apache-2.0 for patent-grant coverage, MIT for maximal
     permissiveness), swap the file contents to the SPDX-identified text
     for that license in the same PR before merging — the metric flips
     regardless, and the only cost is reviewer time choosing. Default to
     proprietary because the signals (private GitHub remote
     `DolasDev/dolios`, commercial Pegasus SaaS backing, LLC-named operator
     email, no existing OSS declarations anywhere in the tree) point that
     direction; file-opening the proposal author's choice rather than
     deferring avoids an empty-shell PR.
   - No code changes outside the new `LICENSE` file. No frontmatter / tool /
     dependency changes; no runtime surface touched.

## Measurement plan

- **Metric(s) to watch:**
  - **Primary:** `docs.license_present` (must flip to `true`).
  - **Gap presence:** the audit row's `gaps:` array must no longer contain
    `gap_id: compliance-f6003ab812` after the chunk merges.
  - **Guard metrics:** none mechanical. Adding a 15-line static LICENSE
    file cannot plausibly move `ci.*`, `commits.*`, `security.*`, or any
    `docs.*` field other than `license_present`. The CI proposal's
    retrospective learning #2 — *"guard metrics need a confounder check"*
    — applies here as an *absence* note: there is no guard to define
    because there is no plausible causal path from `LICENSE` presence to
    any other measured field. If any other field moves in the post-audit
    row, the change is attributable to concurrent work, not this PR.
- **Sampling cadence:** every weekly audit run. The dispatcher's existing
  `make audit` cron (`infra/hermes/`) picks this up automatically; no
  one-off audit invocation is required.
- **Success threshold:** after the chunk's execution PR merges, the next
  audit row must have `docs.license_present: true` *and* must not include
  a gap with `gap_id: compliance-f6003ab812` in its `gaps:` array. Both
  conditions, not one — the second guards against an auditor bug where the
  flag flips but the gap de-duplication breaks.
- **When to call it:** the dispatcher runs an audit immediately after the
  execution PR merges and appends the Outcome section. No multi-cycle
  observation window is needed; this is a presence check, not a trend.
- **What would falsify it:**
  - `docs.license_present` stays `false` — the auditor isn't detecting the
    file. Check: is it at repo root, named exactly `LICENSE`, committed
    (not staged)? If all three, file an auditor bug (`audit.py:272`'s
    check should match).
  - `docs.license_present` flips to `true` but the gap re-appears with the
    same `gap_id` — `derive_gaps()` is not reading `docs["license_present"]`
    correctly. File a bug against `audit.py:440`.
  - A follow-up proposal in `compliance` area (e.g. SECURITY.md) stays
    gated by this one because the LICENSE wording is contradictory with
    something downstream — treat as scope creep on this PR, file as its
    own proposal.

## Research / prior art

The research step considered the three options the auditor's `proposed_action`
hint lists plus a "do nothing" baseline, and consulted the SPDX and
choosealicense.com directories for each.

- **Considered:** [**MIT License**](https://opensource.org/license/mit)
  (SPDX: `MIT`) — maximally permissive, ~20 lines, ubiquitous. Right for
  a public library whose adoption is the point; wrong for a private
  internal IaC repo whose adoption is explicitly *not* the point. Also
  carries no patent grant, which matters less for infra-as-code but
  matters some.
- **Considered:** [**Apache License 2.0**](https://opensource.org/license/apache-2-0)
  (SPDX: `Apache-2.0`) — explicit patent grant, contributor-safety clauses
  (DCO-adjacent §9), de-facto standard for cloud-native tooling. Right if
  the repo ever goes OSS; the patent grant is the differentiating reason
  to pick it over MIT. **Wrong for the current state** — declaring OSS
  terms on an internal repo creates ambiguity about what the LLC is
  actually doing (rather than resolving it, which is the gap's point).
- **Considered:** [**Business Source License 1.1**](https://mariadb.com/bsl11/)
  (SPDX: `BUSL-1.1`) — commercial "source-available with delayed OSS
  conversion" model. Overkill for a non-distributed internal IaC repo;
  BSL's value proposition is "commercial product you also want to show to
  the world," not an LLC's internal infra.
- **Considered:** **Do nothing** (leave the repo unlicensed). Under US
  copyright default, this already means "all rights reserved" — but the
  NIST SSDF PO.1 requirement is that the terms be *documented*, not merely
  defaulted-to. The gap exists precisely because implicit ≠ documented.
- **Picked:** **Proprietary / all-rights-reserved** with an explicit
  internal-use carve-out for Dolas LLC employees and automated agents.
  Rationale: the repo's actual state — private GitHub remote
  (`DolasDev/dolios`), LLC-owned commercial-product backing (Pegasus),
  operator email under the LLC, no public distribution — is already
  proprietary; a `LICENSE` that says so is the honest documentation that
  PO.1 asks for. The internal-use carve-out is non-cosmetic: without it,
  the autonomous-coder's own commits arguably lack a written permission
  to modify the Software, which is the very "ambiguous reuse posture" the
  gap flags.

  SPDX identifier: for all-rights-reserved proprietary notices there is no
  standard SPDX short-form; `LicenseRef-DolasLLC-Proprietary` would be the
  SPDX-conformant custom id if any dependency consumer needs one later.
  Out of scope for this PR; file as a follow-up if/when `pyproject.toml`
  grows a `license` field.

## Effort & risk

- **Effort:** **1 PR, ~15 minutes of dispatcher time.** One new file, ~15
  lines, no tests to write (the auditor's existing filesystem check is
  the test), no runtime surface touched, no CI matrix to adjust.
- **Risk — wrong license choice.** Proprietary might not match Dolas LLC's
  actual intent; a later decision to open-source the fleet-management
  pieces would then require a second PR to swap the LICENSE. **Mitigation:**
  the chunk's description explicitly flags this as a reviewer decision
  point. Swapping to Apache-2.0 or MIT at merge time is a 1-line change
  (replace the file contents); the metric flips regardless. Writing
  the proposal with a default pick rather than leaving the choice to
  "the reviewer in the PR" avoids an empty-shell PR that would need its
  own decision-making round-trip.
- **Risk — the internal-use carve-out is legally awkward or
  over/under-broad.** The suggested wording is not legal advice; a real
  Dolas LLC counsel review may rewrite it. **Mitigation:** the metric
  flips on *presence*, not content, so counsel can revise the file in a
  follow-up PR without undoing this gap's resolution. The specific
  wording in this proposal is a reasonable starting point, not a final
  legal text.
- **Risk — downstream dependency consumers miss the SPDX id.** No current
  consumers; `pyproject.toml` has no `license` field yet; `pip install`
  of this repo isn't a thing. **Mitigation:** none needed at this time;
  file a follow-up if that changes.
- **Risk — the auditor's detection check is case-sensitive and a reviewer
  renames the file to `License.md`.** `audit.py:272` checks exactly
  `LICENSE`, `LICENSE.md`, `LICENSE.txt` — case-sensitive on Linux.
  **Mitigation:** the chunk explicitly specifies `LICENSE` (bare) as the
  filename; reviewer-side rename to a case-variant is caught by the
  Measurement plan's "did the metric actually flip?" check and fixed in
  a follow-up.
- **Risk — the auditor regresses between this proposal and the post-merge
  audit.** Low; `audit_docs()` is stable and `test_audit.py:271` covers
  `license_present: True`. **Mitigation:** the post-merge audit is the
  oracle; if the metric doesn't flip, debug the auditor, not the LICENSE.

## Outcome

> *TBD — appended after the re-measure step.*

| Metric | Baseline | Post-execution | Δ | Target | Verdict |
|---|---|---|---|---|---|
| `docs.license_present` | `false` | *(tbd)* | *(tbd)* | `true` | *(tbd)* |

- **Did the hypothesis hold?** *(tbd)*
- **Unexpected movement** in other metrics (intended or otherwise). *(tbd)*
- **What we learned**, for the next proposal of this kind. *(tbd)*
