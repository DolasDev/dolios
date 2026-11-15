# V0 presence-metric audits can't catch a syntactically valid but functionally broken file

## Context

Drafting `proposals/dolios/2026-11-15-add-codeowners.md` (gap
`review-e401f3007f`). The auditor's check for CODEOWNERS is a stat() on
`CODEOWNERS` or `.github/CODEOWNERS` — no parse, no handle resolution, no
"does this actually route a review" probe (see
`services/auditor/audit.py:audit_docs` around line 278). So the metric
`docs.codeowners_present` flips to `true` **the moment the file exists in
the right path**, independent of whether its contents do anything.

GitHub's CODEOWNERS parser then silently skips any line it can't make
sense of — invalid login, nonexistent `@org/team`, malformed glob,
trailing cruft. Both ends of the pipeline fail quietly: the metric says
"we have CODEOWNERS", the GitHub UI shows no auto-requested reviewers,
and nothing surfaces the mismatch. The proposal is now shipping a
pre-merge handle-verification step to catch this at review time.

## Lesson

The V0 auditor's **presence-only** fields are a class — not an
exception. `docs.license_present`, `docs.security_md_present`,
`docs.codeowners_present`, `docs.contributing_present`,
`docs.code_of_conduct_present`, `dependencies.dependabot_config`,
`dependencies.renovate_config`, `security.gitleaks_config_present`,
`security.openssf_scorecard_present`, `ci.github_actions_present` all
answer "is there a file at a known path", not "does the file do what
its name promises". For files whose downstream consumer parses them
silently (GitHub's CODEOWNERS parser, Dependabot's YAML schema loader,
Scorecard's workflow interpreter, OSV-Scanner's manifest reader), a
proposal that *only* trips the presence bit can land a non-functional
artefact with a green audit row.

A LICENSE proposal is unusually safe here because its downstream
consumer (humans reading it, badge services counting it) treats *any*
bytes as acceptable. CODEOWNERS, SECURITY.md (contact needs to exist),
`.github/dependabot.yml` (schema-validated — but validation errors
only appear in the GitHub UI, not in the auditor), `.gitleaks.toml`
(silently falls back to defaults on parse error), and
`.github/workflows/scorecard.yml` (YAML parse errors fail the first
*run* but not the presence check) are the risky members of the class.

## Apply to

- **Any proposal with `metrics:` containing a `*_present` boolean
  only.** Add an explicit pre-merge content check into the chunk
  definition — not into the Measurement plan, because the metric by
  construction cannot verify content. Examples:
  - CODEOWNERS: `curl -sf https://github.com/<handle>` or `gh api
    users/<handle>` returns 200 for every listed owner before merging.
  - `.github/dependabot.yml`: `gh api
    /repos/<owner>/<repo>/dependabot/alerts` returns something after
    one scan cycle (not 404 / "no config detected").
  - `.github/workflows/scorecard.yml`: the first run on `main` goes
    green, not red on an `actionlint`-class error.
  - `SECURITY.md`: reporting channel named in the body actually
    resolves (email domain has an MX record, URL returns 200).
- **When extending the auditor to catch this family of failures**,
  prefer a second non-boolean field rather than overloading the
  `_present` boolean — e.g. keep `docs.codeowners_present` and add
  `docs.codeowners_valid` (all listed logins resolve). That preserves
  the cheap presence probe and lets proposals target the richer
  signal explicitly.
- **Reviewers of presence-metric remeasure outcomes** should treat a
  green verdict as "the file exists" and separately ask "does the
  file do its job?" — the latter is almost never answered by the
  audit row.

Related: [[0003-gh-actions-api-branch-filter-hides-pr-runs]] — same
family of "the metric looked fine, the real behaviour wasn't
happening." Both failures pass their local probe and only surface on
an end-to-end check against a live integration. Both argue the same
general discipline: *for every metric you declare "met", have one
concrete artefact of the downstream system actually behaving
differently.*
