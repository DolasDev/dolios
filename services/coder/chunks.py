#!/usr/bin/env python3
"""Chunk parser for proposal markdown.

A proposal's `## Intervention` section is a checkbox list — each top-level item
is one execution-PR-sized chunk. The dispatcher flips `- [ ]` → `- [x]` as part
of the execution PR's commit (so the human reviewer sees implementation + the
box flip together in one diff), and the picker reads the checkboxes to decide
what's next.

  - [ ] **Chunk 1 title** — description...
  - [x] **Chunk 2 title** — description (this one is done)

This module is pure-string / pure-file; no gh, no model, no network. The
dispatcher will write checkbox flips through its own runners; the picker
(backlog.py) consumes the parsed state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# A top-level `- [ ]` / `- [x]` list item — only at column 0 (no indentation),
# so we don't mistake a sub-bullet inside a chunk description for another chunk.
CHECKBOX_RE = re.compile(r"^-\s+\[([ xX])\]\s+(.+)$", re.MULTILINE)

# Numbered-list fallback for proposals predating the checkbox convention.
# Same column-0 constraint.
NUMBERED_RE = re.compile(r"^(\d+)\.\s+(.+)$", re.MULTILINE)


@dataclass
class Chunk:
    index: int          # 1-based, in source order
    title: str          # the first line after the marker (may carry markdown)
    description: str    # any continuation lines up to the next chunk (stripped)
    done: bool          # True iff `[x]` (or `[X]`); numbered lists default False


def parse_chunks(markdown_text: str) -> list[Chunk]:
    """Parse the Intervention section's chunks from a proposal's markdown body.

    Returns chunks in source order. Prefers the checkbox format; falls back to
    a numbered list if no checkboxes are found (legacy proposals). Returns []
    if there's no `## Intervention` section.
    """
    body = _extract_section(markdown_text, "Intervention")
    if body is None:
        return []
    return _parse_checkboxes(body) or _parse_numbered(body)


def proposal_chunks(proposal_path: Path) -> list[Chunk]:
    """Convenience: read a proposal file and return its chunks."""
    return parse_chunks(proposal_path.read_text(encoding="utf-8"))


def next_pending_chunk(chunks: list[Chunk]) -> Chunk | None:
    """First chunk that isn't `done`. None if all done or no chunks at all."""
    return next((c for c in chunks if not c.done), None)


def all_chunks_done(chunks: list[Chunk]) -> bool:
    """True iff there is at least one chunk and every chunk is done.
    Used by the picker to detect "ready for remeasure"."""
    return bool(chunks) and all(c.done for c in chunks)


def flip_chunk(markdown_text: str, chunk_index: int) -> str:
    """Return `markdown_text` with chunk `chunk_index`'s `[ ]` flipped to `[x]`.

    This is what the dispatcher calls as part of each execution PR's commit —
    so the box flip and the implementation are one diff. Raises ValueError if
    the chunk is out of range, already checked, or if there's no Intervention
    section. The proposal's source-order chunk list (per `parse_chunks`) is the
    authority for what "Nth chunk" means.
    """
    h = re.search(r"^##\s+Intervention\s*$", markdown_text, re.MULTILINE)
    if not h:
        raise ValueError("no '## Intervention' section in proposal")
    section_start = h.end()
    next_h = re.search(r"^##\s+", markdown_text[section_start:], re.MULTILINE)
    section_end = (section_start + next_h.start()) if next_h else len(markdown_text)

    # Match within the section bounds only (so we can't accidentally flip a
    # checkbox in an unrelated section).
    matches = [m for m in CHECKBOX_RE.finditer(markdown_text)
               if section_start <= m.start() < section_end]
    if not matches:
        raise ValueError("no checkbox chunks in Intervention section")
    if not 1 <= chunk_index <= len(matches):
        raise ValueError(
            f"chunk_index {chunk_index} out of range (1..{len(matches)})"
        )
    target = matches[chunk_index - 1]
    if target.group(1).lower() == "x":
        raise ValueError(f"chunk {chunk_index} is already checked off")

    # Replace the single space inside `[ ]` with `x`.
    state_start = target.start(1)
    state_end = target.end(1)
    return markdown_text[:state_start] + "x" + markdown_text[state_end:]


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #
def _extract_section(text: str, heading: str) -> str | None:
    """Return the body of `## <heading>` up to the next `##` heading or EOF."""
    pat = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    m = pat.search(text)
    if not m:
        return None
    start = m.end()
    next_h = re.search(r"^##\s+", text[start:], re.MULTILINE)
    end = start + next_h.start() if next_h else len(text)
    return text[start:end]


def _build_chunks(body: str, matches: list[re.Match], *, done_from_match) -> list[Chunk]:
    """Shared chunk-builder: each match's title + description (the text between
    this match's end and the next match's start, stripped)."""
    chunks: list[Chunk] = []
    for i, m in enumerate(matches):
        title = m.group(2).strip()
        desc_start = m.end()
        desc_end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunks.append(Chunk(
            index=i + 1,
            title=title,
            description=body[desc_start:desc_end].strip(),
            done=done_from_match(m),
        ))
    return chunks


def _parse_checkboxes(body: str) -> list[Chunk]:
    matches = list(CHECKBOX_RE.finditer(body))
    return _build_chunks(body, matches,
                         done_from_match=lambda m: m.group(1).lower() == "x")


def _parse_numbered(body: str) -> list[Chunk]:
    matches = list(NUMBERED_RE.finditer(body))
    # Numbered lists have no done marker → False; the picker treats these as
    # "all pending" so a legacy proposal stays addressable.
    return _build_chunks(body, matches, done_from_match=lambda m: False)
