# Chunk-mode claude prompts must explicitly forbid touching the proposal markdown

## Context

First autonomous run on dolios (chunk 1 of dolios/2026-05-28-adopt-github-actions-ci)
on 2026-05-31: claude received `chunk.title + chunk.description` as its
prompt, read the proposal markdown for context, and helpfully flipped chunk
1's own `[ ]` → `[x]` itself. Then the dispatcher's atomic flip step
collided with the already-`[x]` state and aborted before commit. The work
was lost; we paid for the dispatch with nothing to show.

## Lesson

In chunk mode the dispatcher MUST wrap the chunk content with a preamble
that names the proposal path as off-limits and explicitly says the
dispatcher handles state. The preamble is now baked into
`services/coder/dispatch.py`:

  - "Do NOT modify `<proposal_path>`" — not frontmatter, checkboxes, Outcome.
  - "Stay strictly inside chunk N's scope. Do not implement future chunks."
  - "Do not run git or commit. The dispatcher handles version control."

Regression test: `test_chunk_mode_prompt_warns_claude_off_the_proposal_file`.

## Apply to

Any new dispatch path that introduces atomic state changes alongside claude's
output. Examples that will need the same defensive preamble:

- A future `--proposal-mode` dispatcher that writes a *new* proposal — claude
  must be told the dispatcher will commit + open the PR, so claude shouldn't
  run git itself.
- A future `--remeasure-mode` dispatcher that flips `status: approved → done`
  + adds the `done:` date — claude must be told the dispatcher handles the
  frontmatter edits.
- More broadly: any time the dispatcher and claude both want to edit the same
  file in the same commit, the preamble has to disambiguate ownership.
