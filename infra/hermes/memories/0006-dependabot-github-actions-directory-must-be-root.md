---
name: dependabot-github-actions-directory-must-be-root
description: Dependabot's github-actions ecosystem requires `directory: "/"`; pointing it at `.github/workflows/` silently opens zero PRs
metadata:
  type: feedback
---

# Dependabot `github-actions` directory MUST be `/`, not `.github/workflows/`

## The rule

In every `.github/dependabot.yml` for any repo in this fleet, the
`github-actions` ecosystem stanza MUST pin `directory: "/"`. Not
`directory: ".github/workflows/"`, not `directory: ".github/"`, not
`directory: "/.github/workflows"` — the literal string `"/"`. The
`docker`, `pip`, `npm` etc. ecosystems can and should point at the
directory holding the manifest; `github-actions` is special-cased.

## Why

Dependabot treats `directory:` as the **root** at which the ecosystem's
auto-discovery runs, not as the location of the manifest files. For the
`github-actions` ecosystem, auto-discovery walks `${directory}/.github/
workflows/` — so with `directory: "/"` it inspects
`/.github/workflows/`, which is where the workflows actually live.
Point `directory:` at `.github/workflows/` and it inspects
`.github/workflows/.github/workflows/`, which does not exist. Dependabot
does NOT error — it emits zero PRs and logs the empty scan in the
Dependabot UI under *Insights → Dependency updates*, which nobody checks
unless they already suspect a problem.

So the failure mode is **silent**: the metric
`dependencies.dependabot_config` flips to `true` (the file exists),
Scorecard's `Dependency-Update-Tool` check scores 10/10 (the file
exists), the Measurement plan's primary check passes — and Dependabot
still never opens a PR, forever. The GitHub Dependabot community
discussions over the last 18 months show "my Dependabot config
isn't producing PRs" as the #1 misconfiguration, and `directory:
.github/workflows/` is the #1 cause within that.

Caught while drafting
`proposals/dolios/2026-11-15-adopt-dependabot.md`. The fleet's
"shift-left security" posture rests on the dependency gate actually
opening PRs, not on the metric merely registering as green; a
copy-pasted stanza that looks intuitive would have silently made the
whole mechanism a no-op.

## How to apply

- When drafting any proposal that adds a Dependabot config: pin
  `github-actions` with `directory: "/"`. Pin other ecosystems
  (`docker`, `pip`, `npm`, `cargo`, `gomod`, …) at the directory
  holding their manifest.
- When reviewing someone else's Dependabot YAML (ours or a third
  party's): if the `github-actions` stanza has anything other than
  `directory: "/"`, flag it as silently broken.
- When auditing an existing Dependabot setup on a repo being onboarded
  to the fleet: open the GitHub Dependabot UI
  (`Insights → Dependency updates`) on the repo and check that
  `github-actions` lists non-zero discovered manifests. If it shows
  zero, the `directory:` pin is the first thing to check even if the
  file validates cleanly.
- Add a 7-day post-merge sanity check whenever a Dependabot proposal
  lands: did at least one Dependabot PR open against an actions pin
  that is *known* to have been bumped upstream? (`actions/checkout`,
  `actions/setup-python`, etc., release regularly enough that a 7-day
  silence is almost always a config bug, not upstream calm.)

Important: do NOT extend the fleet-level definition of "configured" to
include "PRs are actually opening." The auditor's presence-check is the
right abstraction — it's cheap, stable, and doesn't require GitHub API
credentials. This memory is about what reviewers and proposal authors
should *additionally* verify at merge time; it is not a call to rebuild
the auditor.

## Apply to

- Any new fleet repo adopting Dependabot — same `directory: "/"` rule
  applies universally for `github-actions`.
- Any proposal that migrates a Renovate-configured repo onto Dependabot
  (or vice versa). Renovate has no analogous trap — it scans
  everything recursively — so a Dependabot config translated from
  Renovate by hand is especially at risk of landing with a wrong
  `directory:`.
- Reviewers of the follow-on `security-e8dffa5d30` (OpenSSF Scorecard
  workflow) proposal, when that lands: Scorecard's
  `Dependency-Update-Tool` check is a presence test, so a
  mis-configured Dependabot will still score 10/10 on that check.
  Don't treat Scorecard's green as "Dependabot is working" — the
  7-day PR sanity check above is the real validator.

The same class of trap lives in Dependabot's `docker` ecosystem but is
less common: pointing at `/` for `docker` scans the repo root for a
Dockerfile (works if the Dockerfile IS at the root, fails silently if
it isn't). The rule is less uniform than the `github-actions` case,
but the failure mode is the same shape — silent zero PRs.

Related: [[0005-gitleaks-action-v2-dead-use-v3]] — same family of "CI
or supply-chain gate landed fine, flipped the metric, didn't actually
do the thing." Both failure modes passed the proposal's Measurement
plan and would only surface via an out-of-band sanity check in the
days after merge.
