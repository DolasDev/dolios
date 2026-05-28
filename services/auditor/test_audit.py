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
from pathlib import Path

import audit as a


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
