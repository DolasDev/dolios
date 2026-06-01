#!/usr/bin/env python3
"""Tests for the deterministic priority picker.

Each test builds a temp dolios-root with a synthetic `.dolios/metrics/<repo>/
history.jsonl` and `proposals/<repo>/*.md` set, then runs `pick()` against it.
Real yaml + real json — no mocks of those — so the frontmatter contract and
the JSONL history contract are both exercised end-to-end.

Runs under pytest, or standalone:  `python3 test_backlog.py`.
"""

import json
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


def _write_proposal(root, repo, slug, *, status="proposed", gap_ids=None,
                    opened="2026-05-28", done=None, chunks=None):
    """chunks: list of (title, done_bool) tuples → checkbox Intervention.
    If None, no Intervention section (parser returns [])."""
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
        f"opened:    {opened}",
        "approved:  null",
        f"done:      {done if done else 'null'}",
        "---",
        "",
        "# Title",
        "",
    ]
    if chunks is not None:
        fm_lines += ["## Intervention", ""]
        for title, is_done in chunks:
            box = "x" if is_done else " "
            fm_lines.append(f"- [{box}] **{title}**")
        fm_lines += ["", "## Measurement plan", "", "stuff."]
    else:
        fm_lines.append("body.")
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
# 3. Execute path — approved proposal with unchecked chunks
# --------------------------------------------------------------------------- #
def test_approved_proposal_with_unchecked_chunks_picks_execute():
    """The very first execute on an approved proposal."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1),
                         gaps=[("high", "ci", "ci-aaa", "No CI")])
        _write_proposal(root, "dolios", "2026-05-28-adopt-ci",
                        status="approved", gap_ids=["ci-aaa"],
                        chunks=[("chunk 1 title", False),
                                ("chunk 2 title", False),
                                ("chunk 3 title", False)])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl])
        assert d["kind"] == "execute"
        assert d["proposal_id"] == "dolios/2026-05-28-adopt-ci"
        assert d["chunk_index"] == 1
        assert "chunk 1 title" in d["chunk_title"]
        # task_id is dispatcher-safe (no '/')
        assert "/" not in d["task_id"]
        assert d["task_id"].endswith("-chunk-1")


def test_execute_picks_next_unchecked_chunk():
    """Chunk 1 done, chunk 2 unchecked → execute chunk 2."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1), gaps=[])
        _write_proposal(root, "dolios", "p1", status="approved",
                        chunks=[("first", True), ("second", False), ("third", False)])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl])
        assert d["kind"] == "execute"
        assert d["chunk_index"] == 2


def test_continuing_a_proposal_skips_cap_check():
    """A proposal already-implementing (some chunks done) can continue even
    when implementing_count would otherwise gate a fresh start."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1), gaps=[])
        # 3 proposals already mid-flight (one done, one not) → effective_implementing
        # for each is True, implementing_count = 3 (the cap).
        for i in range(3):
            _write_proposal(root, "dolios", f"impl-{i}", status="approved",
                            chunks=[("a", True), ("b", False)])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl])
        # Should still execute on one of them (continuing, not starting).
        assert d["kind"] == "execute"
        assert d["chunk_index"] == 2


def test_starting_fresh_approved_blocked_by_cap():
    """3 implementing + 1 approved-with-no-progress → cap blocks starting #4."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1), gaps=[])
        # 3 already-mid-flight (all-done would be remeasure; here partially done)
        for i in range(3):
            _write_proposal(root, "dolios", f"impl-{i}", status="approved",
                            opened=f"2026-05-2{i}",
                            chunks=[("a", True), ("b", False)])
        # 4th: approved, no progress, MORE RECENT opened so FIFO won't pick it first
        _write_proposal(root, "dolios", "fresh", status="approved",
                        opened="2026-05-29",
                        chunks=[("a", False), ("b", False)])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        # The picker walks FIFO — three implementing proposals come first and
        # one of them gets executed (continuing). The fresh one is never reached.
        d = b.pick([bl])
        assert d["kind"] == "execute"
        assert "impl-" in d["task_id"]


def test_fifo_executes_oldest_opened_first():
    """Two approved proposals, both with unchecked chunks → oldest opened wins."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1), gaps=[])
        _write_proposal(root, "dolios", "newer", status="approved",
                        opened="2026-05-28",
                        chunks=[("c1", False)])
        _write_proposal(root, "dolios", "older", status="approved",
                        opened="2026-05-20",
                        chunks=[("c1", False)])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl])
        assert d["kind"] == "execute"
        assert "older" in d["proposal_id"]


# --------------------------------------------------------------------------- #
# 4. Remeasure path — every chunk done but no `done:` date
# --------------------------------------------------------------------------- #
def test_all_chunks_done_with_no_done_date_picks_remeasure():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1), gaps=[])
        _write_proposal(root, "dolios", "complete", status="approved",
                        chunks=[("a", True), ("b", True), ("c", True)])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl])
        assert d["kind"] == "remeasure"
        assert d["proposal_id"] == "dolios/complete"
        assert "command_audit" in d


def test_all_done_with_done_date_is_skipped():
    """A proposal that's already had its Outcome appended (done date set) is
    inert — picker ignores it and moves on."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1),
                         gaps=[("high", "ci", "ci-fresh", "Still a gap")])
        _write_proposal(root, "dolios", "closed", status="approved",
                        done="2026-05-29",
                        chunks=[("a", True), ("b", True)],
                        gap_ids=["ci-old"])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl])
        # Not remeasure or execute — propose the still-open new gap.
        assert d["kind"] == "propose"
        assert d["gap_id"] == "ci-fresh"


def test_remeasure_beats_execute_and_propose():
    """Closing a proposal frees a cap slot, so it's higher priority than
    starting new work."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1),
                         gaps=[("high", "ci", "ci-uncov", "Uncovered gap")])
        # One ready to close, one with pending chunks.
        _write_proposal(root, "dolios", "ready-to-close", status="approved",
                        opened="2026-05-20",
                        chunks=[("a", True)])
        _write_proposal(root, "dolios", "still-going", status="approved",
                        opened="2026-05-22",
                        chunks=[("a", False)])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl])
        assert d["kind"] == "remeasure"
        assert "ready-to-close" in d["proposal_id"]


# --------------------------------------------------------------------------- #
# 5. Reflect — fires when no successful reflect tick in the lookback window
# --------------------------------------------------------------------------- #
def _seed_tick_log(root, rows):
    p = root / ".dolios" / "tick-log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_reflect_fires_when_no_prior_reflect_and_nothing_else_to_do():
    """All-clean state: fresh audit, only gap is covered by a *closed*
    proposal (so neither propose nor remeasure can fire). No reflect in
    the log. Picker emits kind=reflect."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1),
                         gaps=[("high", "ci", "ci-aaa", "No CI")])
        # Closed proposal: done status with done date → doesn't cover gaps for
        # propose, doesn't trigger remeasure, doesn't trigger execute.
        _write_proposal(root, "dolios", "closed", status="done",
                        gap_ids=["ci-aaa"], done="2026-05-30",
                        chunks=[("c1", True)])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl], dolios_root=root)
        # Above-reflect kinds: status:done doesn't cover, so propose fires
        # for ci-aaa first. To actually test reflect, the gap needs to be
        # covered by an ACTIVE proposal, but that proposal can't have
        # pending chunks (or execute fires) or all-done-no-done-date (or
        # remeasure fires). So: cover with proposed status (covers via
        # ACTIVE_PROPOSAL_STATUSES, blocks propose; no chunks → execute
        # skips; status not approved → remeasure skips).
        # Adjust by adding a second proposal that covers it actively.
        _write_proposal(root, "dolios", "covering", status="proposed",
                        gap_ids=["ci-aaa"])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl], dolios_root=root)
        assert d["kind"] == "reflect", d
        assert "no kind=reflect tick in the last" in d["rationale"]


def test_reflect_does_not_fire_when_recent_reflect_in_log():
    """A reflect tick within the lookback window suppresses the next one."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1), gaps=[])
        _seed_tick_log(root, [{
            "ts": time.time() - 86400,    # 1 day ago
            "kind": "reflect",
        }])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl], dolios_root=root)
        assert d["kind"] == "empty"   # reflect suppressed; nothing else to do


def test_reflect_fires_when_last_reflect_is_older_than_lookback():
    """An old reflect entry shouldn't suppress a fresh one."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1), gaps=[])
        _seed_tick_log(root, [{
            "ts": time.time() - (b.REFLECT_INTERVAL_DAYS + 1) * 86400,
            "kind": "reflect",
        }])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl], dolios_root=root)
        assert d["kind"] == "reflect"


def test_reflect_loses_to_work_creating_kinds():
    """Even if reflect is due, an actual work item wins."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1),
                         gaps=[("medium", "x", "x-1", "uncovered gap")])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl], dolios_root=root)
        assert d["kind"] == "propose"
        assert d["gap_id"] == "x-1"


def test_reflect_check_skipped_when_no_dolios_root_passed():
    """The legacy `pick([backlogs])` call shape still works — reflect is
    just unreachable without dolios_root."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_audit_row(root, "dolios", audited_at=_iso_minus_days(1), gaps=[])
        bl = b.build_repo_backlog("dolios", root / "repo", dolios_root=root)
        d = b.pick([bl])  # no dolios_root kwarg → reflect unreachable
        assert d["kind"] == "empty"


# --------------------------------------------------------------------------- #
# 6. End-to-end via main(): writes structured stdout, exits 0
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
        # Seed a recent reflect so the empty path wins over reflect.
        _seed_tick_log(root, [{"ts": time.time() - 86400, "kind": "reflect"}])

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
