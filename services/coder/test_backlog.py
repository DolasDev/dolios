#!/usr/bin/env python3
"""Tests for the deterministic priority picker.

Each test builds a temp dolios-root with a synthetic `.dolios/metrics/<repo>/
history.jsonl` and `proposals/<repo>/*.md` set, then runs `pick()` against it.
Real yaml + real json — no mocks of those — so the frontmatter contract and
the JSONL history contract are both exercised end-to-end.

Runs under pytest, or standalone:  `python3 test_backlog.py`.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import backlog as b


# --------------------------------------------------------------------------- #
# Fixtures: build a dolios-shaped tree, write audit rows + proposals
# --------------------------------------------------------------------------- #
def _write_audit_row(root, repo, *, audited_at, gaps):
    """gaps is a list of (severity, area, gap_id, summary) tuples."""
    p = root / ".dolios" / "metrics" / repo / "history.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "schema_version": 1,
        "audited_at": audited_at,
        "repo": repo,
        "gaps": [
            {"severity": sev, "area": area, "gap_id": gid, "summary": summary,
             "frameworks": ["DORA: Test"], "detail": "...", "proposed_action": "..."}
            for sev, area, gid, summary in gaps
        ],
        "not_measured": [],
    }
    with p.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def _write_proposal(root, repo, slug, *, status="proposed", gap_ids=None):
    p = root / "proposals" / repo / f"{slug}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    fm_lines = [
        "---",
        f"id:     {repo}/{slug}",
        f"status: {status}",
        f"repo:   {repo}",
        "audit:  .dolios/metrics/" + repo + "/history.jsonl#L1@2026-05-28T00:00:00Z",
    ]
    if gap_ids:
        fm_lines.append("gap_ids:")
        for g in gap_ids:
            fm_lines.append(f"  - {g}")
    fm_lines += [
        "frameworks: [\"DORA: Test\"]",
        "opened:    2026-05-28",
        "approved:  null",
        "done:      null",
        "---",
        "",
        "# Title",
        "",
        "body.",
    ]
    p.write_text("\n".join(fm_lines))


def _iso_minus_days(days):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400))


# --------------------------------------------------------------------------- #
# 1. Audit-due (no history yet OR stale)
# --------------------------------------------------------------------------- #
def test_no_history_is_first_audit():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl])
        assert d["kind"] == "audit"
        assert "first audit" in d["rationale"]
        assert d["repo"] == "dolios"


def test_stale_audit_picks_audit():
    """An audit > STALE_AUDIT_DAYS old triggers a re-audit before any propose work."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios",
                         audited_at=_iso_minus_days(b.STALE_AUDIT_DAYS + 1),
                         gaps=[("high", "ci", "ci-aaa", "No CI")])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl])
        assert d["kind"] == "audit"
        assert "old" in d["rationale"]


def test_fresh_audit_does_not_pick_audit():
    """Today's audit means we skip past the audit kind into propose / empty."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios",
                         audited_at=_iso_minus_days(0),
                         gaps=[])  # no gaps → empty, not audit
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl])
        assert d["kind"] == "empty"


# --------------------------------------------------------------------------- #
# 2. Propose
# --------------------------------------------------------------------------- #
def test_uncovered_high_severity_gap_is_proposed():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1),
                         gaps=[
                             ("low",    "review",     "review-l1",   "No CODEOWNERS"),
                             ("high",   "ci",         "ci-aaa",      "No CI"),
                             ("medium", "compliance", "compl-bbb",   "No LICENSE"),
                         ])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl])
        assert d["kind"] == "propose"
        assert d["gap_id"] == "ci-aaa"
        assert d["gap_severity"] == "high"


def test_active_proposal_covers_gap():
    """A proposal in `proposed`/`approved`/`implementing` covers its gap_ids."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1),
                         gaps=[
                             ("high",   "ci",         "ci-aaa",    "No CI"),
                             ("medium", "compliance", "compl-bbb", "No LICENSE"),
                         ])
        _write_proposal(root, "dolios", "2026-05-28-adopt-ci",
                        status="proposed", gap_ids=["ci-aaa"])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl])
        # high-severity gap is covered → fall through to medium.
        assert d["kind"] == "propose"
        assert d["gap_id"] == "compl-bbb"


def test_done_proposal_does_NOT_cover_gap():
    """A proposal in `done` lets the gap be re-proposed (e.g. regression)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1),
                         gaps=[("high", "ci", "ci-aaa", "No CI")])
        _write_proposal(root, "dolios", "old-done",
                        status="done", gap_ids=["ci-aaa"])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl])
        assert d["kind"] == "propose"
        assert d["gap_id"] == "ci-aaa"


def test_three_implementing_caps_proposing_on_that_repo():
    """At the per-repo cap on `implementing`, no more propose for that repo."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1),
                         gaps=[("high", "ci", "ci-aaa", "No CI")])
        for i, gid in enumerate(("g1", "g2", "g3")):
            _write_proposal(root, "dolios", f"impl-{i}",
                            status="implementing", gap_ids=[gid])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl])
        assert d["kind"] == "empty"


def test_highest_severity_wins_across_repos():
    """A high gap in repo B beats a medium gap in repo A."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "alpha", audited_at=_iso_minus_days(1),
                         gaps=[("medium", "x", "x-1", "x")])
        _write_audit_row(root, "beta", audited_at=_iso_minus_days(1),
                         gaps=[("high", "y", "y-1", "y")])
        bls = [
            b.build_repo_backlog("alpha", root / "alpha", dolios_root=root),
            b.build_repo_backlog("beta",  root / "beta",  dolios_root=root),
        ]
        d = b.pick(bls)
        assert d["kind"] == "propose"
        assert d["repo"] == "beta"
        assert d["gap_id"] == "y-1"


# --------------------------------------------------------------------------- #
# 3. End-to-end via main(): writes structured stdout, exits 0
# --------------------------------------------------------------------------- #
def test_main_emits_valid_json_and_exits_zero(capsys=None):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Set up a dolios-root with an allowlist of one fresh-audited repo
        # whose only gap is already covered → expect kind=empty.
        cfg = root / "coder.yaml"
        repo_path = root / "checkouts" / "dolios"
        repo_path.mkdir(parents=True)
        cfg.write_text(f"allowlist:\n  dolios: {repo_path}\n")
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1),
                         gaps=[("high", "ci", "ci-aaa", "No CI")])
        _write_proposal(root, "dolios", "active",
                        status="approved", gap_ids=["ci-aaa"])

        # Redirect stdout in a portable way (no capsys to keep standalone runnable)
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = b.main(["--next", "--config", str(cfg), "--root", str(root)])
        assert rc == 0
        out = json.loads(buf.getvalue())
        assert out["kind"] == "empty"


def test_main_errors_on_missing_config():
    with tempfile.TemporaryDirectory() as tmp:
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = b.main(["--next", "--config", str(Path(tmp) / "nope.yaml")])
        assert rc == 2
        out = json.loads(buf.getvalue())
        assert out["kind"] == "error"


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
