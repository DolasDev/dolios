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
from unittest import mock

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
    # Pin dates for determinism, but relative to now: the auditor only counts
    # commits inside its LOOKBACK_DAYS window, so a fixed calendar date rots.
    when = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for i, (name, content) in enumerate(commits or []):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(content)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", f"c{i}"], cwd=repo, check=True,
                       env={**os.environ, "GIT_AUTHOR_DATE": when,
                            "GIT_COMMITTER_DATE": when})


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
# GH Actions API half (chunk 3) — mocked so tests stay offline
# --------------------------------------------------------------------------- #
def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fake_runs_payload():
    """Six runs: four recent + successful, one recent + failed, one PR-triggered.
    Shapes the fields gh_ci_metrics computes so we can check all three at once."""
    now = datetime.now(UTC)
    def run(minutes_ago, duration_s, event, conclusion, status="completed"):
        created = now - timedelta(minutes=minutes_ago)
        started = created
        updated = created + timedelta(seconds=duration_s)
        return {
            "status": status,
            "conclusion": conclusion,
            "event": event,
            "created_at": _iso(created),
            "run_started_at": _iso(started),
            "updated_at": _iso(updated),
        }
    return {
        "workflow_runs": [
            run(60,   120, "push",         "success"),
            run(120,  180, "push",         "success"),
            run(180,  240, "pull_request", "success"),
            run(240,  150, "push",         "success"),
            run(300,  200, "push",         "failure"),
            # Older than 30d but inside 90d lookback: feeds median, not success rate.
            run(60 * 24 * 45, 300, "push", "success"),
        ]
    }


def test_gh_ci_metrics_null_shape_when_no_token():
    out = ci_api.gh_ci_metrics("acme", "r", token=None)
    # Status quo for unauthenticated runs: no behaviour change.
    assert out["test_runs_on_pr"] is None
    assert out["median_runtime_seconds"] is None
    assert out["success_rate_30d"] is None
    assert "_note" in out


def test_gh_ci_metrics_computes_fields_from_mocked_api():
    with mock.patch.object(ci_api, "_fetch_runs", return_value=_fake_runs_payload()):
        out = ci_api.gh_ci_metrics("acme", "r", token="t")
    assert out["test_runs_on_pr"] is True
    assert isinstance(out["median_runtime_seconds"], int)
    assert out["median_runtime_seconds"] > 0
    # 4 success / 5 completed inside the 30d window = 0.80.
    assert out["success_rate_30d"] == 0.8
    # Measured shape drops the `_note` placeholder.
    assert "_note" not in out


def test_audit_ci_merges_api_fields_and_graduates_not_measured():
    """With token set, audit_ci() merges the API-derived fields into its
    existing filesystem-only output, and run() drops the ci.* rows from
    `not_measured`."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / ".github" / "workflows").mkdir(parents=True)
        (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\non: [push]\njobs: {}\n")
        _init_git(repo, commits=[("a.py", "x = 1\n")])
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:acme/r.git"],
            cwd=repo, check=True,
        )
        with mock.patch.object(ci_api, "_fetch_runs", return_value=_fake_runs_payload()):
            snap = a.run(repo, "t", gh_token="fake")
        ci = snap["metrics"]["ci"]
        # Filesystem half still measured.
        assert ci["github_actions_present"] is True
        assert ci["workflow_count"] == 1
        # API half now measured.
        assert ci["test_runs_on_pr"] is True
        assert isinstance(ci["median_runtime_seconds"], int)
        assert ci["success_rate_30d"] == 0.8
        # And graduated out of the deferred-metrics list.
        nm_paths = {e["path"] for e in snap["not_measured"]}
        assert not any(p.startswith("ci.") for p in nm_paths)


def test_derive_gaps_adds_test_reliability_gap_below_threshold():
    """A measured success_rate_30d under 0.80 adds a high-severity
    DORA: Test reliability gap."""
    # Build the minimal metrics shape derive_gaps consumes.
    metrics = {
        "ci": {
            "github_actions_present": True,
            "other_ci_detected": False,
            "success_rate_30d": 0.5,
        },
        "security": {
            "gitleaks_config_present": True,
            "regex_secret_finding_count": 0,
            "openssf_scorecard_present": True,
        },
        "docs": {
            "license_present": True,
            "security_md_present": True,
            "codeowners_present": True,
        },
        "testing": {"coverage_measured": True},
        "dependencies": {"dependabot_config": True, "renovate_config": False},
    }
    gaps = a.derive_gaps(metrics)
    reliability = [g for g in gaps if "Test reliability" in " ".join(g.get("frameworks", []))]
    assert len(reliability) == 1
    assert reliability[0]["severity"] == "high"
    assert reliability[0]["area"] == "ci"

    # And the inverse: at/above threshold → no reliability gap.
    metrics["ci"]["success_rate_30d"] = 0.95
    gaps = a.derive_gaps(metrics)
    assert not any("Test reliability" in " ".join(g.get("frameworks", [])) for g in gaps)


# --------------------------------------------------------------------------- #
# Loop-health ("ops") metrics + gaps
# --------------------------------------------------------------------------- #
def _clean_metrics(**over):
    m = {
        "ci": {"github_actions_present": True, "other_ci_detected": False},
        "security": {"gitleaks_config_present": True,
                     "regex_secret_finding_count": 0,
                     "openssf_scorecard_present": True},
        "docs": {"license_present": True, "security_md_present": True,
                 "codeowners_present": True},
        "testing": {"coverage_measured": True},
        "dependencies": {"dependabot_config": True, "renovate_config": False},
    }
    m.update(over)
    return m


def _ops_repo(tmp, rows):
    repo = Path(tmp)
    _init_git(repo, commits=[("services/coder/tick.py", "x\n")])  # 1 day ago
    (repo / ".dolios").mkdir()
    (repo / ".dolios" / "tick-log.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows))
    return repo


def _now():
    return datetime.now(UTC).timestamp()


def test_ops_absent_without_a_tick_log():
    with tempfile.TemporaryDirectory() as tmp:
        _init_git(Path(tmp), commits=[("a.py", "x\n")])
        assert a.audit_ops(Path(tmp)) == {"present": False}


def test_ops_counts_only_failures_after_the_latest_loop_code_commit():
    now = _now()
    fail = {"kind": "execute", "dispatch_rc": 1,
            "dispatch_error": "CalledProcessError: git push"}
    rows = ([dict(fail, ts=now - 3 * 86400) for _ in range(5)]      # before fix
            + [dict(fail, ts=now - 3600 * i) for i in (3, 2, 1)])    # after
    with tempfile.TemporaryDirectory() as tmp:
        ops = a.audit_ops(_ops_repo(tmp, rows), now=now)
    assert ops["present"] and ops["ticks"] == 3
    assert ops["repeated_failures"] == [
        {"signature": "execute: CalledProcessError: git push", "count": 3}]


def test_ops_flags_duplicate_prs_after_cutoff():
    now = _now()
    rows = [{"ts": now - 7200, "kind": "propose", "dispatch_rc": 0,
             "branch": "auto/coder/propose-g1-20261114-103050", "pr_url": "u/21"},
            {"ts": now - 3600, "kind": "propose", "dispatch_rc": 0,
             "branch": "auto/coder/propose-g1-20261114-110029", "pr_url": "u/22"}]
    with tempfile.TemporaryDirectory() as tmp:
        ops = a.audit_ops(_ops_repo(tmp, rows), now=now)
    assert ops["duplicate_pr_tasks"] == [
        {"task": "auto/coder/propose-g1", "prs": ["u/21", "u/22"]}]


def test_ops_gaps_are_high_and_have_stable_ids():
    ops = {"present": True, "code_cutoff": "t",
           "repeated_failures": [{"signature": "s", "count": 4}],
           "duplicate_pr_tasks": [{"task": "t", "prs": ["a", "b"]}]}
    g1 = [g for g in a.derive_gaps(_clean_metrics(ops=ops)) if g["area"] == "ops"]
    ops2 = dict(ops, repeated_failures=[{"signature": "other", "count": 9}])
    g2 = [g for g in a.derive_gaps(_clean_metrics(ops=ops2)) if g["area"] == "ops"]
    assert len(g1) == 2 and all(g["severity"] == "high" for g in g1)
    # counts/signatures live in `detail`, so the id survives changing numbers
    assert {g["gap_id"] for g in g1} == {g["gap_id"] for g in g2}


def test_healthy_ops_and_old_rows_without_ops_add_no_gap():
    assert not [g for g in a.derive_gaps(_clean_metrics()) if g["area"] == "ops"]
    ok = {"present": True, "repeated_failures": [], "duplicate_pr_tasks": []}
    assert not [g for g in a.derive_gaps(_clean_metrics(ops=ok)) if g["area"] == "ops"]


def test_ci_not_observed_on_prs_is_a_gap_only_when_measured_false():
    def ci_gaps(v):
        ci = {"github_actions_present": True, "other_ci_detected": False,
              "test_runs_on_pr": v}
        return [g for g in a.derive_gaps(_clean_metrics(ci=ci))
                if g["summary"] == "CI runs not observed on pull requests"]
    assert len(ci_gaps(False)) == 1
    assert not ci_gaps(True) and not ci_gaps(None)


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
