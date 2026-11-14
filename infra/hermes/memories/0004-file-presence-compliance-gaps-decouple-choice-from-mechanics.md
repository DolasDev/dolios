# "File-presence" compliance gaps: let the reviewer swap the body at approval, don't hardwire the choice

## Context

Writing the LICENSE proposal (`proposals/dolios/2026-11-14-add-license-file.md`,
gap `compliance-f6003ab812`) surfaced a structural difference between
this class of gap and the ones we'd done before (adopt-GHA-CI, etc.):

- For CI adoption, "which tool" is a real engineering trade-off (hosted
  runners vs. self-hosted, YAML dialect, matrix shape) and the proposal
  committing to one answer is what lets the chunks be small.
- For "no LICENSE file" / "no SECURITY.md" / "no CODEOWNERS" the
  *mechanical* work is almost nothing (add a text file at a known path);
  the only real decision is **what the file says** — and that's a
  product/legal/policy call the autonomous coder is not the right one
  to make unilaterally.

The auditor at `services/auditor/audit.py:272` only checks for file
presence by name — it does not parse the content. So any text at
`LICENSE` / `LICENSE.md` / `LICENSE.txt` flips the bit, and the
proposal's hypothesis does not depend on *which* license.

## Lesson

For presence-only compliance gaps, structure the proposal so:

1. The chunk commits to the **path and filename** (that's what the
   auditor measures).
2. The Research/prior-art section lays out named alternatives for the
   **content**, with explicit rationale for a recommended default *and*
   the trade-offs of the other named options.
3. State clearly that the human reviewer can swap the chunk body at
   approval time without reshaping the proposal — the hypothesis is
   content-agnostic.
4. Prefer the **reversible** default. Proprietary → permissive is a
   file edit when the holder is a single entity; permissive → more-
   restrictive is impossible for already-shipped versions. The same
   asymmetry applies elsewhere (e.g. SECURITY.md disclosure SLA: start
   conservative, loosen later).

The anti-pattern this guards against: dispatching an autonomous chunk
that silently picks MIT because it was in the first Google result,
then having to re-license under contributor assent later. For a
single-entity repo that hasn't accepted outside contributions yet,
relicensing is still cheap; after the first external PR it isn't.

## Apply to

- The **SECURITY.md** proposal for gap `security-629ad05d83` ("No
  SECURITY.md"). Same shape: auditor checks presence only; the real
  decision is the reporting channel + SLA wording. Lay out
  `security@` vs. GitHub Security Advisories vs. a private
  issue-tracker channel; recommend one; let the reviewer finalize.
- The **CODEOWNERS** proposal for gap `review-e401f3007f`. Same shape:
  auditor checks for `CODEOWNERS` / `.github/CODEOWNERS` presence; the
  hard part is *who* goes in the file, not the syntax.
- A future **CONTRIBUTING.md / CODE_OF_CONDUCT.md** proposal if those
  gaps open.

Does NOT apply to: proposals where the chunk's primary value is wiring
a *tool* (gitleaks, dependabot, coverage.py). There, committing to the
tool at proposal time is the whole point — the content decoupling here
would just be ceremony. Keep that class of proposal single-choice.

Related: [[0002-chunk-mode-claude-must-not-touch-proposal]] — same
family of "give claude a narrow lane, let human own the irreversible
bits" instinct. Related in the opposite direction:
[[0003-gh-actions-api-branch-filter-hides-pr-runs]] — a case where the
proposal *correctly* committed to a tool and the miss was in
implementation, not in the decision-structure.
