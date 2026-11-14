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

# Add an explicit LICENSE at the repo root

## Hypothesis

> Adding a single `LICENSE` file at the repo root should move
> **`docs.license_present`** from baseline **`false`** to **`true`** within
> **1 audit cycle** because the auditor
> (`services/auditor/audit.py:272`) checks for `LICENSE` / `LICENSE.md` /
> `LICENSE.txt` at the repo root and nothing else — NIST SSDF **PO.1**
> requires that the project's security & compliance posture (including
> reuse rights) be explicitly defined rather than left ambiguous.

The falsifiable claim: a single, correctly-named file flips exactly one
boolean. The interesting decision is **which** license, not whether the
auditor's check will clear.

## Audit citation

- **Audit row:** `.dolios/metrics/dolios/history.jsonl` line 5
  (`audited_at: 2026-11-14T09:00:59Z`).
- **Gap targeted:** `compliance` / "No LICENSE file" (severity: `medium`,
  gap_id `compliance-f6003ab812`). Auditor detail: "Repo has no
  `LICENSE`/`LICENSE.md`/`LICENSE.txt` — legally ambiguous reuse
  posture."
- **Frameworks:** NIST SSDF **PO.1** — "Define Security Requirements for
  Software Development … including applicable legal/compliance
  requirements." Absent a declared license, U.S. copyright law's default
  is that *all* rights are reserved to the author, but third parties
  cannot rely on that without a written statement, which is exactly the
  ambiguity PO.1 asks projects to eliminate.

## Baseline

| Metric | Current | Source |
|---|---|---|
| `docs.license_present` | `false` | audit row above |

## Intervention

One chunk. The file is small and self-contained; splitting would be
ceremony.

- [ ] **Add `LICENSE` at repo root** — write the chosen license text
  (see "Recommended text" below) to `/LICENSE` (no extension, matches
  the first path the auditor probes). Optionally append a one-line
  "License" section to `README.md` pointing at `LICENSE`. **No** source
  file SPDX-header sweep — that is a separate, much larger proposal if
  we ever need per-file provenance and is out of scope for closing this
  gap. **No** `pyproject.toml` `license = "…"` field change — that
  touches packaging and is not what the auditor measures.

### Recommended text

Default recommendation: **proprietary / "All Rights Reserved"** (short
notice, see below). Rationale for the default vs. the two permissive
alternatives is in [Research / prior art](#research--prior-art); the
human reviewer picks the actual license at approval time by editing the
chunk's LICENSE content before dispatch. The proposal is written so
either of the three named choices satisfies the metric — the chunk only
has to produce *a* file named `LICENSE` with coherent content.

Suggested proprietary notice (concise, modeled on the FSF's "no license
granted" template):

```
Copyright (c) 2026 Dolas LLC. All rights reserved.

This source code and the accompanying configuration is proprietary and
confidential. No license, express or implied, is granted to use, copy,
modify, merge, publish, distribute, sublicense, or sell copies of the
code, in whole or in part, except with prior written permission from
Dolas LLC.
```

If the reviewer instead picks **MIT** or **Apache-2.0** at approval, the
canonical texts from <https://spdx.org/licenses/MIT.html> or
<https://spdx.org/licenses/Apache-2.0.html> are dropped in verbatim with
the year (`2026`) and copyright holder (`Dolas LLC`) filled in.

## Measurement plan

- **Metric(s) to watch:** `docs.license_present` (primary).
- **Guard metrics:** none that this change can plausibly move — the
  intervention adds a static text file, touches no code paths, no CI,
  no deps. The nominal `commits.count` / `commits.median_lines_changed`
  guards from the CI proposal apply but are not expected to shift from
  a single ~1-line addition. *Explicit confounder check* (per the
  learning from the CI proposal's `commits.count` miss): if either
  commit guard moves, it is overwhelmingly likely to be unrelated
  regime effects (continued autonomous-coder cadence), not caused by
  this proposal.
- **Sampling cadence:** every audit run (weekly).
- **Success threshold:** `docs.license_present == true` on the first
  audit after merge. Pre-merge sanity is trivial: `test -f LICENSE`.
- **When to call it:** after the chunk's PR merges, trigger a
  remeasure; one cycle is enough — the signal is binary and won't
  flicker.
- **What would falsify it:** the only ways this fails are (a) the file
  is named something other than `LICENSE` / `LICENSE.md` /
  `LICENSE.txt` (operator error — guarded by the chunk description
  being explicit about the path), or (b) the auditor is changed to
  demand more than presence (e.g. SPDX-identifier parsing or GitHub's
  Licensee-style detection). Neither is a reason to abandon — it's a
  reason to iterate on the auditor, which is out of this proposal's
  scope.

## Research / prior art

The decision isn't "will a LICENSE file satisfy the check" (it will);
it is "which license best matches the project's intent." I weighed
three realistic options and one non-option.

- **Considered: MIT** (<https://spdx.org/licenses/MIT.html>) — shortest
  permissive license, minimal notice-retention requirements, no patent
  grant. Good default for small reusable utilities. Not picked as the
  default here because the repo is explicitly scoped as
  *company-internal* infrastructure (hermes-agent profile specs for
  the Dolas fleet, references to private APIs under `dolas.dev`,
  `dolo-llm` / `dolo-docker` machine names). Granting the world a
  perpetual permissive license to internal ops tooling is a decision
  the owner should make deliberately, not as a side-effect of closing
  a compliance gap.
- **Considered: Apache-2.0** (<https://spdx.org/licenses/Apache-2.0.html>)
  — same permissive spirit as MIT but adds a patent grant and requires
  a `NOTICE` file for modifications. Preferred over MIT for anything
  that might eventually see broad contribution (the patent clause
  matters), but has the same "this is actually internal tooling, do we
  want to open-source it right now?" question as MIT.
- **Picked as default: proprietary / "All rights reserved"** (notice
  text in [Intervention](#intervention); modeled on FSF's guidance at
  <https://www.gnu.org/licenses/no-license.en.html> and the
  `choosealicense.com` "No license" entry at
  <https://choosealicense.com/no-permission/> — note: a *stated*
  no-license is strictly better than silent no-license, because it
  resolves the ambiguity the auditor and PO.1 both flag, without
  granting unintended rights). This matches the current posture of
  the repo (private infra for a specific LLC) and leaves the door
  fully open to relicense later under MIT/Apache if the posture
  changes. Relicensing *from* proprietary to permissive is a simple
  file edit when the holder is a single entity; relicensing *away
  from* MIT/Apache-granted code is not reversible for any already-shipped
  version.
- **Rejected: GPL / AGPL.** Copyleft is a strong policy choice with
  downstream distribution implications; it's a different conversation
  than "close a PO.1 gap" and not implied by the audit's hint.
- **Rejected: `LICENSE` absent + a note in `README.md`.** Does not
  flip the auditor bit (it reads the filename), and does not resolve
  the PO.1 ambiguity in the way reviewers / tooling (GitHub Licensee,
  OpenSSF Scorecard's License check) expect.

**Prior-art precedent in this repo:** the first large proposal
(`proposals/dolios/2026-05-28-adopt-github-actions-ci.md`) landed by
decomposing a measurable gap into small chunks with a two-arm
hypothesis ("thing exists" / "thing is measured correctly"). This
proposal is deliberately smaller — one chunk, one arm — because the
intervention is a text file, not a tool integration. The remeasure
learning from that proposal (unit tests ≠ end-to-end audit, see
`infra/hermes/memories/0003-gh-actions-api-branch-filter-hides-pr-runs.md`)
is still honored here: the Measurement plan's "call it" step is an
actual audit run against the repo, not a mocked check of
`_fetch_runs`-equivalent logic.

## Effort & risk

- **Effort:** one dispatcher run, one small PR (~1 file added, ~5
  lines added to `README.md` optional). Dispatcher wall-clock well
  under 15 min; human review a few minutes.
- **Risk:**
  1. **Picking the "wrong" license.** Mitigated by making the choice
     explicit in the proposal with named alternatives — the human
     reviewer can swap the LICENSE body at chunk-execution time
     without reshaping the proposal. Reversible for proprietary;
     essentially irreversible once a permissive license ships against
     a public commit (so if in doubt, start proprietary).
  2. **Interaction with future SPDX / scorecard work.** None blocking.
     A future proposal that adds per-file SPDX headers or wires
     OpenSSF Scorecard's License check can assume a LICENSE file
     exists after this merges — in fact, Scorecard's License check
     specifically requires it (<https://github.com/ossf/scorecard/blob/main/docs/checks.md#license>).
  3. **`pyproject.toml` desync.** `pyproject.toml` currently has no
     `license =` field; leaving it that way is fine for an application
     (not-published-to-PyPI) repo. If someone later adds packaging,
     that PR should add the matching SPDX expression. Not in scope.
- **Mitigations:** all three risks are either bounded by the single
  file's scope or deferred cleanly to a separate proposal.

## Outcome

> *TBD — appended after the re-measure step.*

| Metric | Baseline | Post-execution | Δ | Target | Verdict |
|---|---|---|---|---|---|
| `docs.license_present` | `false` | <p> | <±> | `true` | met / missed / partial |
