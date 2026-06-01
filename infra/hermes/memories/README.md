# memories

Versioned, human-readable lessons the autonomous-coder accumulates over time —
the substrate of its long-term learning. Each file is a single distilled
learning, written in plain markdown so a human or any LLM can read it.

## Why this lives in `infra/hermes/` and not in `~/.hermes/`

hermes-agent stores in-session memory at `~/.hermes/profiles/<role>/memories/`,
but that's:

- **Opaque** — model-bound, not directly auditable.
- **Per-host** — doesn't propagate when the fleet expands.
- **Mutable without review** — the agent can write whatever it wants there.

We put memories in this repo instead so they're:

- **Plain markdown** — diffable, greppable, reviewable as PRs.
- **Versioned in git** — every change has provenance + can be reverted.
- **Mounted into the container** at `/opt/data/repos/dolios/infra/hermes/memories/`
  so the dispatcher can read them when composing prompts for propose,
  remeasure, and reflect runs.

The `~/.hermes/profiles/<role>/memories/` directory still exists (the agent
*could* write there during a `chat`/`--tui` session), but for any structured
learning we want the loop to actually use, it lives here.

## How memories get used

When the autonomous-coder dispatches a **propose** or **remeasure** run,
`services/coder/tick.py` reads every `.md` file in this directory and injects
the bodies into claude's prompt as a "Prior learnings" section. So if the
agent learned six weeks ago that `ruff line-length=100` produces 150 lines of
forced reformatting on freshly-linted code, that learning shows up in the
next ruff-related proposal — claude reads it and can either anticipate the
volume or pick a different value.

Each propose dispatch can also **author a new memory** as part of its work,
by writing a new file in this directory. That edit lands in the same PR as
the proposal, so humans review the learning at the same time as the work.

## File naming

```
NNNN-short-slug.md          where NNNN is a zero-padded sequence number
```

Sequence number for ordering / dedup; slug for human readability. Examples:

```
0001-cont-init-shebang-needs-with-contenv.md
0002-ruff-line-length-100-bulk-reformat.md
```

## File format

Plain markdown. At minimum:

- An H1 title naming the lesson.
- A "Context" paragraph: where this came from (PR url, audit row, date).
- A "Lesson" paragraph: what to remember.
- An "Apply to" paragraph: under what future conditions this matters.

No frontmatter required (humans can write these too), but the propose/
remeasure paths will accept either.
