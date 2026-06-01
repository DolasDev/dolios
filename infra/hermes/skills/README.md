# skills

Versioned custom skills the autonomous-coder uses. **Plain markdown files,
diffable, reviewable as PRs** — the same as memories, for the same reasons.

Each subdirectory is one skill. Inside, the canonical entry point is
`SKILL.md`: a markdown document teaching claude (or any LLM) how to approach
a particular kind of task, in this repo's idiom.

```
skills/
  README.md                ← this file
  <slug>/
    SKILL.md               ← the skill, in markdown
    examples/              ← optional, referenced from SKILL.md
```

## How skills get used

When `services/coder/tick.py` composes a dispatch prompt (for propose,
remeasure, or reflect), it can reference specific skills by slug — their
`SKILL.md` contents get inlined into claude's prompt as context.

A skill that's "always relevant" (e.g. `dolios-proposal-conventions`) is
read into every propose dispatch. A skill that's "conditionally relevant"
(e.g. `dolios-ruff-pitfalls`) is read when the dispatch's gap area matches
its trigger.

Triggering rules live as YAML frontmatter on each `SKILL.md`:

```yaml
---
trigger:
  always: false
  on_gap_areas: [ci, testing]        # any of these in the gap → load
  on_proposal_kind: [propose]        # which dispatch kinds → load
---

# How to think about ruff config in this repo

...
```

## How skills get *authored*

Same way as everything else in this loop: a proposal recommends a new skill
as an Intervention chunk. The execution PR for that chunk writes the new
`skills/<slug>/SKILL.md` file. Humans review the PR; the skill is live in
the next dispatch after merge. **The agent improving itself goes through
the same review boundary as the agent improving anything else.**

This is the place where hermes-agent's `hermes-agent-skill-authoring`
bundled skill is most relevant — when the autonomous-coder writes a new
skill, it should be told to read that meta-skill for guidance on structure.

## What's NOT here

Hermes-agent ships **90 bundled skills** (`writing-plans`,
`subagent-driven-development`, `github-pr-workflow`, `test-driven-development`,
`codebase-inspection`, `systematic-debugging`, …). Those live in the agent
install at `~/.hermes/skills/` and are loaded automatically by hermes-agent
when its model is invoked. They're not duplicated here.

This directory holds **only the dolios-specific skills** the agent has
authored or that we've written to capture project-specific patterns
(idioms, gotchas, conventions). Empty until the first such skill is needed.
