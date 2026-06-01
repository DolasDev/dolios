#!/usr/bin/env python3
"""Tests for the prompt composition module.

prompts.py is the deterministic side of the agent-driven dispatches — pure
file IO and string assembly. These tests pin the contracts the propose /
remeasure / reflect handlers depend on.

Runs under pytest or standalone:  `python3 test_prompts.py`.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import prompts as p


def _seed(root: Path, files: dict[str, str]) -> None:
    """Bulk-create files. Key is path relative to root, value is content."""
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


# --------------------------------------------------------------------------- #
# read_memories
# --------------------------------------------------------------------------- #
def test_read_memories_concatenates_all_md_except_readme():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed(root, {
            "infra/hermes/memories/README.md": "# Convention notes — should NOT appear",
            "infra/hermes/memories/0001-first.md": "first memory body",
            "infra/hermes/memories/0002-second.md": "second memory body",
        })
        out = p.read_memories(root)
        assert "first memory body" in out
        assert "second memory body" in out
        assert "Convention notes" not in out
        # Ordering is deterministic (sorted by filename → 0001 before 0002).
        assert out.index("first memory body") < out.index("second memory body")


def test_read_memories_returns_empty_when_dir_missing():
    with tempfile.TemporaryDirectory() as tmp:
        assert p.read_memories(Path(tmp)) == ""


# --------------------------------------------------------------------------- #
# read_skills
# --------------------------------------------------------------------------- #
def test_read_skills_inlines_only_named_skills_silently_skips_missing():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed(root, {
            "infra/hermes/skills/skill-a/SKILL.md": "alpha body",
            "infra/hermes/skills/skill-b/SKILL.md": "beta body",
        })
        out = p.read_skills(root, ["skill-a", "missing-skill", "skill-b"])
        assert "alpha body" in out and "beta body" in out
        # Missing skill must not error or insert a placeholder.
        assert "missing-skill" not in out


# --------------------------------------------------------------------------- #
# read_recent_outcomes
# --------------------------------------------------------------------------- #
DONE_PROPOSAL = """\
---
id: dolios/2026-05-28-x
status: done
done:   2026-06-01
---

# Title

## Hypothesis

xxx

## Outcome

| Metric | Baseline | Post | Verdict |
|---|---|---|---|
| ci.workflow_count | 0 | 1 | met |

Hypothesis held. CI workflow is in place.
"""

OPEN_PROPOSAL = """\
---
id: dolios/2026-05-30-y
status: approved
---

# Title

## Outcome

TBD — appended after the re-measure step.
"""


def test_read_recent_outcomes_only_includes_done_proposals_newest_first():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed(root, {
            "proposals/dolios/2026-05-28-x.md": DONE_PROPOSAL,
            "proposals/dolios/2026-05-30-y.md": OPEN_PROPOSAL,
            "proposals/dolios/_template.md":     "should be skipped",
        })
        out = p.read_recent_outcomes(root, "dolios")
        assert "Hypothesis held" in out
        # Open proposal's Outcome is just "TBD" — should be filtered out by
        # the status check before we even look at the section.
        assert "TBD — appended" not in out
        # Template skipped.
        assert "should be skipped" not in out


def test_read_recent_outcomes_respects_limit():
    """Newer-first ordering + limit clip."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for date in ("2026-04-01", "2026-04-15", "2026-05-01"):
            _seed(root, {f"proposals/dolios/{date}-x.md": DONE_PROPOSAL.replace(
                "2026-05-28-x", f"{date}-x")})
        out = p.read_recent_outcomes(root, "dolios", limit=2)
        # 3 done proposals on disk, limit=2 → newest two only.
        # Verify by counting how many "Closed proposal:" headers landed.
        assert out.count("Closed proposal:") == 2
        # Newest ("2026-05-01") must be in; oldest ("2026-04-01") must not.
        assert "2026-05-01" in out
        assert "2026-04-01" not in out


# --------------------------------------------------------------------------- #
# find_gap
# --------------------------------------------------------------------------- #
def test_find_gap_matches_by_gap_id():
    audit = {"gaps": [
        {"gap_id": "a-1", "summary": "first"},
        {"gap_id": "b-2", "summary": "second"},
    ]}
    assert p.find_gap(audit, "b-2")["summary"] == "second"
    assert p.find_gap(audit, "missing") is None


# --------------------------------------------------------------------------- #
# compose_propose_instructions — the surface that tick.py depends on
# --------------------------------------------------------------------------- #
def test_compose_propose_includes_gap_details_audit_ref_today_and_memories():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed(root, {
            "infra/hermes/memories/0001-x.md": "Lesson: read this every time.",
        })
        gap = {
            "gap_id": "ci-foo",
            "area": "ci",
            "severity": "high",
            "summary": "No CI workflows detected",
            "frameworks": ["DORA: Continuous Integration"],
            "proposed_action": "Adopt GitHub Actions",
        }
        out = p.compose_propose_instructions(
            root=root, repo="dolios", gap=gap,
            audit_ref=".dolios/metrics/dolios/history.jsonl#L2@2026-06-01T00:00:00Z",
            today="2026-06-01",
        )
        # All the key elements show up in the rendered prompt.
        for needle in (
            "ci-foo", "No CI workflows detected", "Adopt GitHub Actions",
            "DORA: Continuous Integration",
            "L2@2026-06-01T00:00:00Z",
            "2026-06-01",
            "Lesson: read this every time.",
        ):
            assert needle in out, f"missing in propose prompt: {needle!r}"


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
