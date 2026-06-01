#!/usr/bin/env python3
"""Tests for the V0 auditor — fixture-based, no network, no external tools.

Each test builds a minimal temp repo with the specific surface it cares about,
runs the relevant audit function, and asserts on the structured output. The
gap-derivation tests pin the framework anchors so the proposal step always has
something specific to cite.

Runs under pytest, or standalone:  `python3 test_audit.py`.
"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import audit as a
import ci_api


# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #
def _init_git(repo: Path, *, author="dev <dev@x>", commits=None):
    """Stand up a real git repo with `commits` = list of (filename, content)
    pairs, so commit/git-log metrics get real data."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "dev@x"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "dev"], cwd=repo, check=True)
    for i, (name, content) in enumerate(commits or []):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(content)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", f"c{i}"], cwd=repo, check=True,
                       env={**os.environ, "GIT_AUTHOR_DATE": "2026-05-01T00:00:00Z",
                            "GIT_COMMITTER_DATE": "2026-05-01T00:00:00Z"})


def _run(repo, *, name="testrepo"):
    return a.run(Path(repo), name)


# --------------------------------------------------------------------------- #
# Per-section: a bare repo surfaces the expected gaps
# --------------------------------------------------------------------------- #
def test_empty_repo_surfaces_ci_license_security_secrets_gaps():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_git(repo, commits=[("README.md", "minimal\n")])
        snap = _run(repo)
        areas = {g["area"] for g in snap["gaps"]}
        # Foundational hygiene that's just absent in a bare repo:
        for expected in ("ci", "security", "compliance", "supply_chain", "testing"):
            assert expected in areas, f"expected {expected} gap, got {areas}"
        # Highest severity comes first.
        severities = [g["severity"] for g in snap["gaps"]]
        rank = {"high": 0, "medium": 1, "low": 2}
        assert severities == sorted(severities, key=rank.get), severities


def test_gap_messages_cite_framework_anchors():
    """Every gap must name at least one DORA / OpenSSF / NIST capability —
    so a Claude-Code-generated proposal can cite *why* it's worth doing."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_git(repo, commits=[("a.py", "x = 1\n")])
        snap = _run(repo)
        for gap in snap["gaps"]:
            assert gap.get("frameworks"), gap
            assert any(any(tag in fw for tag in ("DORA", "OpenSSF", "NIST", "SPACE"))
                       for fw in gap["frameworks"]), gap


def test_every_gap_has_a_stable_id():
    """gap_id must be present, area-prefixed, and identical across runs for the
    same (area, summary) — that's what makes proposals reference-stable."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_git(repo, commits=[("a.py", "x = 1\n")])
        snap_a, snap_b = _run(repo), _run(repo)
        for g in snap_a["gaps"]:
            assert g.get("gap_id"), g
            assert g["gap_id"].startswith(g["area"] + "-"), g
        # Same audit → same gap_ids, position-independent.
        ids_a = {g["gap_id"] for g in snap_a["gaps"]}
        ids_b = {g["gap_id"] for g in snap_b["gaps"]}
        assert ids_a == ids_b


def test_not_measured_is_a_structured_list_at_snapshot_root():
    """V0's deferred metrics live at snap['not_measured'] with path/tool/needs
    fields, so the picker doesn't have to grep free-text `_note`s."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_git(repo, commits=[("a.py", "x = 1\n")])
        snap = _run(repo)
        nm = snap.get("not_measured")
        assert isinstance(nm, list) and nm
        for entry in nm:
            assert set(entry.keys()) >= {"path", "tool", "needs"}, entry
        # Spot-check: the CI metrics the first proposal calls out are present.
        paths = {e["path"] for e in nm}
        assert "ci.test_runs_on_pr" in paths
        assert "testing.coverage_percent" in paths


# --------------------------------------------------------------------------- #
# CI presence flips the gap
# --------------------------------------------------------------------------- #
def test_ci_workflow_presence_clears_ci_gap():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / ".github" / "workflows").mkdir(parents=True)
        (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\non: [push]\njobs: {}\n")
        _init_git(repo, commits=[("a.py", "x = 1\n")])
        snap = _run(repo)
        assert snap["metrics"]["ci"]["github_actions_present"] is True
        assert snap["metrics"]["ci"]["workflow_count"] == 1
        assert "ci" not in {g["area"] for g in snap["gaps"]}


# --------------------------------------------------------------------------- #
# GH Actions API: mocked response flips ci.* from not_measured to measured.
# --------------------------------------------------------------------------- #
def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def test_ci_api_mocked_response_flips_not_measured_to_measured():
    """With a fake GH Actions API payload, audit_ci's API-derived fields move
    from None to real values and the new ci.success_rate_30d slot is set."""
    now = datetime.now(UTC)
    workflow_runs = [
        # 120s, success, push — counts toward median + success rate.
        {
            "status": "completed", "conclusion": "success", "event": "push",
            "run_started_at": _iso(now - timedelta(days=2)),
            "updated_at": _iso(now - timedelta(days=2) + timedelta(seconds=120)),
        },
        # 180s, success, pull_request — flips test_runs_on_pr.
        {
            "status": "completed", "conclusion": "success", "event": "pull_request",
            "run_started_at": _iso(now - timedelta(days=5)),
            "updated_at": _iso(now - timedelta(days=5) + timedelta(seconds=180)),
        },
        # 240s, failure — drags success rate down.
        {
            "status": "completed", "conclusion": "failure", "event": "push",
            "run_started_at": _iso(now - timedelta(days=7)),
            "updated_at": _iso(now - timedelta(days=7) + timedelta(seconds=240)),
        },
        # in-progress run — must be ignored.
        {
            "status": "in_progress", "conclusion": None, "event": "push",
            "run_started_at": _iso(now - timedelta(hours=1)),
            "updated_at": _iso(now - timedelta(hours=1)),
        },
    ]

    original = ci_api._http_get_json
    ci_api._http_get_json = lambda url, headers: {"workflow_runs": workflow_runs}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_git(repo, commits=[("a.py", "x = 1\n")])
            snap = a.run(repo, "t", gh_repo="DolasDev/dolios", gh_token="fake-token")
    finally:
        ci_api._http_get_json = original

    ci = snap["metrics"]["ci"]
    # All three API-derived fields are now measured.
    assert ci["test_runs_on_pr"] is True
    assert isinstance(ci["median_runtime_seconds"], int)
    assert ci["median_runtime_seconds"] == 180  # median of [120, 180, 240]
    assert ci["success_rate_30d"] == round(2 / 3, 3)
    # _note is only present in the not-measured shape — measured runs drop it.
    assert "_note" not in ci


def test_ci_api_low_success_rate_adds_dora_test_reliability_gap():
    """When the mocked API response shows < 80% success over 30d, derive_gaps
    must add a ci/high gap framed against DORA: Test reliability."""
    now = datetime.now(UTC)
    # 1 success + 4 failures = 20% — well below the 80% floor.
    workflow_runs = [
        {
            "status": "completed", "conclusion": "success", "event": "push",
            "run_started_at": _iso(now - timedelta(days=1)),
            "updated_at": _iso(now - timedelta(days=1) + timedelta(seconds=60)),
        },
    ] + [
        {
            "status": "completed", "conclusion": "failure", "event": "push",
            "run_started_at": _iso(now - timedelta(days=i + 2)),
            "updated_at": _iso(now - timedelta(days=i + 2) + timedelta(seconds=60)),
        }
        for i in range(4)
    ]

    original = ci_api._http_get_json
    ci_api._http_get_json = lambda url, headers: {"workflow_runs": workflow_runs}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            # CI workflow present so the "no CI" gap doesn't dominate.
            (repo / ".github" / "workflows").mkdir(parents=True)
            (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\non: [push]\n")
            _init_git(repo, commits=[("a.py", "x = 1\n")])
            snap = a.run(repo, "t", gh_repo="DolasDev/dolios", gh_token="fake-token")
    finally:
        ci_api._http_get_json = original

    ci_gaps = [g for g in snap["gaps"] if g["area"] == "ci"]
    assert any(
        g["severity"] == "high" and "DORA: Test reliability" in g["frameworks"]
        for g in ci_gaps
    ), ci_gaps


# --------------------------------------------------------------------------- #
# Testing
# --------------------------------------------------------------------------- #
def test_testing_counts_python_test_files_and_ratio():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        for name, body in [
            ("src/foo.py", "def f(): pass\n"),
            ("src/bar.py", "def g(): pass\n"),
            ("tests/test_foo.py", "def test_f(): pass\n"),
        ]:
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(body)
        _init_git(repo, commits=[("a.py", "x = 1\n")])
        snap = _run(repo)
        t = snap["metrics"]["testing"]
        assert t["test_files"] == 1
        # 3 .py files (a.py, src/foo.py, src/bar.py) - 1 test file = 2 source files
        # Actually let's be precise about what the auditor counts. The test file
        # is identified by name; source files are non-test code files.
        assert t["source_files"] >= 2
        assert 0 < t["test_to_source_ratio"] < 1


# --------------------------------------------------------------------------- #
# Secrets — V0 regex sweep catches an obvious leak; never matches its own self
# --------------------------------------------------------------------------- #
def test_regex_secret_sweep_flags_an_aws_key():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "leak.py").write_text("AWS_ACCESS_KEY_ID = 'AKIA" + "X" * 16 + "'\n")
        _init_git(repo, commits=[("placeholder.md", "x\n")])
        snap = _run(repo)
        s = snap["metrics"]["security"]
        assert s["regex_secret_finding_count"] >= 1
        assert any(f["pattern"] == "aws_access_key_id" for f in s["regex_secret_findings"])
        # And there's a high-sev gap for it.
        assert any(g["area"] == "security" and g["severity"] == "high"
                   and "regex sweep" in g["summary"] for g in snap["gaps"])


# --------------------------------------------------------------------------- #
# History append round-trips
# --------------------------------------------------------------------------- #
def test_history_append_writes_a_jsonl_row():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_git(repo, commits=[("a.py", "x = 1\n")])
        hp = Path(tmp) / "metrics" / "history.jsonl"
        # Drive through main() to exercise the CLI path.
        rc = a.main(["--repo", str(repo), "--name", "t", "--history", str(hp)])
        assert rc == 0
        rc = a.main(["--repo", str(repo), "--name", "t", "--history", str(hp)])
        assert rc == 0
        rows = [json.loads(line) for line in hp.read_text().splitlines() if line]
        assert len(rows) == 2
        assert all(r["schema_version"] == a.SCHEMA_VERSION for r in rows)
        assert all(r["repo"] == "t" for r in rows)


# --------------------------------------------------------------------------- #
# Commit size proxy
# --------------------------------------------------------------------------- #
def test_commit_size_metrics_reflect_real_commits():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_git(repo, commits=[
            ("a.py", "x = 1\n"),                                # 1 line
            ("b.py", "\n".join(f"l{i}" for i in range(20)) + "\n"),  # 20 lines
            ("c.py", "\n".join(f"l{i}" for i in range(5)) + "\n"),   # 5 lines
        ])
        snap = _run(repo)
        c = snap["metrics"]["commits"]
        assert c["count"] == 3
        assert c["distinct_authors"] >= 1
        assert c["max_lines_changed"] >= 20
        assert c["median_lines_changed"] >= 1


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
