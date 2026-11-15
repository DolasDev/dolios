---
name: gitleaks-action-v2-dead-use-v3
description: gitleaks/gitleaks-action@v2 stopped working on GitHub-hosted runners on 2026-09-16 when Node 20 was removed; always pin v3+ by SHA
metadata:
  type: feedback
---

# `gitleaks/gitleaks-action@v2` is dead on GitHub-hosted runners — use v3+

## The rule

Any new or copied GitHub Actions workflow that runs gitleaks must use
`gitleaks/gitleaks-action@v3` (or later), pinned by commit SHA in the same
`actions/checkout@<sha> # <tag>` style the rest of this fleet uses. Never
paste `@v2` from an older guide and ship it.

## Why

**v2 of `gitleaks-action` runs on Node 20. GitHub-hosted runners removed
Node 20 from the runner image on 2026-09-16.** Any workflow pinning `@v2`
fails at job-start on GitHub-hosted runners with a "node 20 not found"
style error — not at `gitleaks detect` time, but before gitleaks ever
runs, so the usual "flag found / no flag found" output is absent and the
failure reads as if the action itself is broken. v3 (Node 22) is the only
live line today.

Caught while drafting
`proposals/dolios/2026-11-15-adopt-gitleaks-secrets-scanner.md`. The
fleet's "shift-left security" posture rests on the CI job actually
running; a copy-pasted `@v2` pin would have silently failed the scanner
job on the chunk's own merge PR, which is the worst possible moment to
discover a broken security gate.

## How to apply

- When drafting any proposal that adds a gitleaks CI workflow: pin
  `gitleaks/gitleaks-action@v3` by SHA.
- When reviewing someone else's gitleaks workflow (ours or a third
  party's): if the pin reads `@v2`, `@v2.1.x`, or any `v2.x` SHA on a
  workflow slated to run on `ubuntu-latest` / any GitHub-hosted runner,
  flag it as broken-on-merge.
- When migrating a real project onto this fleet that already has
  gitleaks wired up: check the pin first; a repo that merged a gitleaks
  workflow before Sept 2026 and hasn't touched it since is running a
  gate that no longer actually scans anything.
- Self-hosted runners may still carry Node 20 for a while — the rule
  above is specifically about GitHub-hosted runners, which is what
  every workflow in this fleet uses today.

The same shape of trap applies to any GitHub Action whose `runs:` block
names a Node version the runner no longer ships. Current risk is low
(GitHub gives months of deprecation warning, Dependabot would normally
flag it) but worth remembering as a *class* of failure: an action pin
that compiled, scanned, and merged a year ago can silently stop running
when the runner image rolls forward.

## Apply to

- The follow-up `proposals/dolios/2026-11-15-adopt-gitleaks-secrets-scanner.md`
  (chunk 2 — the gitleaks CI job). The proposal already names this; the
  memory is the durable copy for the *next* repo in the fleet that
  adopts gitleaks.
- Any future Scorecard-workflow proposal (gap `security-e8dffa5d30`):
  `ossf/scorecard-action` has analogous version pinning and the same
  Node-runtime vulnerability.
- Reviewers of any copy-pasted GitHub Actions snippet: the `uses: …@v2`
  pattern is a code smell on a Node-based action in late 2026.

Related: [[0003-gh-actions-api-branch-filter-hides-pr-runs]] — same
family of "CI gate looked fine, wasn't actually doing the thing we
thought." Both failure modes passed their local tests and only
surfaced on a real GitHub run.
