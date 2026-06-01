#!/usr/bin/env python3
"""Tests for the chunk parser. Pure-string fixtures, no filesystem mocking."""

import sys

import chunks as c

# --------------------------------------------------------------------------- #
# Fixture markdown
# --------------------------------------------------------------------------- #
CHECKBOX_PROPOSAL = """\
# Title

## Hypothesis

Stuff.

## Intervention

Some intro text — not a chunk.

- [ ] **Chunk 1** — add `.github/workflows/ci.yml`.
  - Path: `.github/workflows/ci.yml`.
  - Triggers: pull_request.
- [x] **Chunk 2** — add `pyproject.toml` for ruff.
- [ ] **Chunk 3** — extend the auditor to read GH Actions API.

## Measurement plan

More stuff.
"""

NUMBERED_PROPOSAL = """\
# Title

## Intervention

Intro.

1. **First chunk** — body.
2. **Second chunk** — body.

## Outcome

TBD.
"""

NO_INTERVENTION = """\
# Title

## Hypothesis

Yes.

## Measurement plan

OK.
"""

ALL_DONE = """\
## Intervention

- [x] one
- [x] two
"""


# --------------------------------------------------------------------------- #
# Checkbox parsing
# --------------------------------------------------------------------------- #
def test_checkbox_format_extracts_three_chunks_with_correct_done_state():
    cs = c.parse_chunks(CHECKBOX_PROPOSAL)
    assert len(cs) == 3
    assert [x.index for x in cs] == [1, 2, 3]
    assert [x.done for x in cs] == [False, True, False]
    assert cs[0].title.startswith("**Chunk 1**")
    # Description captures the sub-bullets that belong to chunk 1, not chunk 2.
    assert "Path: `.github/workflows/ci.yml`" in cs[0].description
    assert "pyproject.toml" not in cs[0].description


def test_next_pending_chunk_skips_done_ones():
    cs = c.parse_chunks(CHECKBOX_PROPOSAL)
    pending = c.next_pending_chunk(cs)
    assert pending is not None
    assert pending.index == 1
    assert pending.done is False


def test_next_pending_after_first_done_returns_chunk_3():
    """If chunk 1 also gets checked, picker moves to chunk 3 (which is still open)."""
    md = CHECKBOX_PROPOSAL.replace("- [ ] **Chunk 1**", "- [x] **Chunk 1**")
    cs = c.parse_chunks(md)
    pending = c.next_pending_chunk(cs)
    assert pending is not None and pending.index == 3


def test_all_chunks_done_only_true_when_every_box_checked():
    cs = c.parse_chunks(CHECKBOX_PROPOSAL)
    assert c.all_chunks_done(cs) is False
    cs_done = c.parse_chunks(ALL_DONE)
    assert c.all_chunks_done(cs_done) is True


# --------------------------------------------------------------------------- #
# Numbered-list fallback (legacy proposals predating the checkbox convention)
# --------------------------------------------------------------------------- #
def test_numbered_format_falls_back_with_done_false():
    cs = c.parse_chunks(NUMBERED_PROPOSAL)
    assert len(cs) == 2
    assert all(not x.done for x in cs)
    # The picker would see "first chunk" as pending.
    assert c.next_pending_chunk(cs).index == 1


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #
def test_no_intervention_section_returns_empty_list():
    assert c.parse_chunks(NO_INTERVENTION) == []
    assert c.next_pending_chunk([]) is None
    assert c.all_chunks_done([]) is False


def test_section_boundary_does_not_leak_into_chunk_descriptions():
    """A chunk's description must end at the next chunk OR the next section."""
    cs = c.parse_chunks(CHECKBOX_PROPOSAL)
    # Last chunk's description shouldn't include the "## Measurement plan" line.
    assert "Measurement plan" not in cs[-1].description


def test_capital_X_also_counts_as_done():
    """Editors sometimes upper-case the X — we accept both."""
    md = "## Intervention\n\n- [X] big-X\n- [x] small-x\n- [ ] open\n"
    cs = c.parse_chunks(md)
    assert [x.done for x in cs] == [True, True, False]


# --------------------------------------------------------------------------- #
# flip_chunk — what the dispatcher calls when it lands a chunk's execution PR
# --------------------------------------------------------------------------- #
def test_flip_chunk_marks_a_pending_chunk_as_done():
    out = c.flip_chunk(CHECKBOX_PROPOSAL, 1)
    assert "- [x] **Chunk 1**" in out
    assert "- [x] **Chunk 2**" in out   # was already done, untouched
    assert "- [ ] **Chunk 3**" in out   # still pending


def test_flip_chunk_idempotency_already_checked_raises():
    """Flipping a chunk that's already `[x]` is a guardrail violation —
    means the dispatcher is about to re-run merged work. Loud failure."""
    try:
        c.flip_chunk(CHECKBOX_PROPOSAL, 2)
    except ValueError as exc:
        assert "already checked" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")


def test_flip_chunk_out_of_range_raises():
    try:
        c.flip_chunk(CHECKBOX_PROPOSAL, 99)
    except ValueError as exc:
        assert "out of range" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_flip_chunk_no_intervention_raises():
    try:
        c.flip_chunk(NO_INTERVENTION, 1)
    except ValueError as exc:
        assert "Intervention" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_flip_chunk_doesnt_touch_checkboxes_in_other_sections():
    """A `- [ ]` in some other section (e.g. a Risks bullet list quoted as a
    todo) must not be misread as a chunk."""
    md = """\
## Intervention

- [ ] **the only chunk**

## Risks

- [ ] unrelated checkbox that must NOT flip
"""
    out = c.flip_chunk(md, 1)
    assert "- [x] **the only chunk**" in out
    assert "- [ ] unrelated checkbox that must NOT flip" in out


# --------------------------------------------------------------------------- #
# Standalone runner
# --------------------------------------------------------------------------- #
def _run_standalone():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_standalone())
