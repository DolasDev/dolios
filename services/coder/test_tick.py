#!/usr/bin/env python3
"""Tests for the single-tick orchestrator.

Tick is shell-out only — backlog.py and dispatch.py are subprocess'd. Tests
inject a fake runner that returns canned (rc, stdout, stderr) per command, so
the dispatch graph is exercised end-to-end without touching real claude/git/gh.
Runs under pytest or standalone:  `python3 test_tick.py`.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import tick as t


# --------------------------------------------------------------------------- #
# Fake runner: maps command-substring → (rc, stdout, stderr)
# --------------------------------------------------------------------------- #
class FakeRunner:
    def __init__(self, responses: dict[str, tuple[int, str, str]]):
        self.responses = responses
        self.calls: list[list[str]] = []

    def __call__(self, cmd, cwd):
        self.calls.append(cmd)
        for needle, resp in self.responses.items():
            if any(needle in arg for arg in cmd):
                return resp
        return 0, "", ""


def _make(responses: dict, tmp) -> t.TickRunner:
    return t.TickRunner(
        root=Path(tmp),
        runner=FakeRunner(responses),
        log_path=Path(tmp) / "tick-log.jsonl",
        now=lambda: 1_700_000_000.0,
    )


def _preflight_ok():
    return 0, json.dumps({
        "ok": True,
        "gate": {"decision": "dispatch", "binding_window": "five_hour",
                 "binding_headroom_pct": 42.0},
    }), ""


def _preflight_hold(reason="binding window at cap"):
    return 1, json.dumps({
        "ok": False,
        "error": "capacity gate holds: " + reason,
        "gate": {"decision": "hold", "reason": reason,
                 "binding_window": "seven_day"},
    }), ""


# --------------------------------------------------------------------------- #
# Gate paths
# --------------------------------------------------------------------------- #
def test_held_gate_logs_a_hold_tick_and_exits_clean():
    with tempfile.TemporaryDirectory() as tmp:
        tr = _make({"--preflight-only": _preflight_hold("7d at 91%")}, tmp)
        record = tr.run_tick()
        assert record["kind"] == "hold"
        assert record["gate_decision"] == "hold"
        assert "7d at 91%" in record["gate_reason"]
        # Picker was NOT called — we exit before reaching it.
        assert len(tr._runner.calls) == 1


def test_preflight_non_json_logged_as_error():
    """A broken preflight (e.g., python import error) shouldn't crash the loop."""
    with tempfile.TemporaryDirectory() as tmp:
        tr = _make({"--preflight-only": (1, "Traceback (most recent call last)...", "")}, tmp)
        record = tr.run_tick()
        assert record["kind"] == "preflight_error"
        assert "Traceback" in record["error"]


# --------------------------------------------------------------------------- #
# Picker paths
# --------------------------------------------------------------------------- #
def test_empty_picker_exits_clean():
    with tempfile.TemporaryDirectory() as tmp:
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "backlog.py":       (0, json.dumps({
                "kind": "empty",
                "rationale": "no work this tick",
            }), ""),
        }, tmp)
        record = tr.run_tick()
        assert record["kind"] == "empty"
        assert record["rationale"] == "no work this tick"
        # 2 calls: preflight + picker. No third call to a worker.
        assert len(tr._runner.calls) == 2


def test_picker_rc_non_zero_logs_picker_error():
    with tempfile.TemporaryDirectory() as tmp:
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "backlog.py":       (2, "", "no config at services/coder/coder.yaml"),
        }, tmp)
        record = tr.run_tick()
        assert record["kind"] == "picker_error"
        assert "no config" in record["error"]


# --------------------------------------------------------------------------- #
# Audit kind
# --------------------------------------------------------------------------- #
def test_audit_kind_runs_the_command_field():
    audit_command = "python3 services/auditor/audit.py --repo /repos/dolios --name dolios --history .dolios/metrics/dolios/history.jsonl"
    with tempfile.TemporaryDirectory() as tmp:
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "backlog.py":       (0, json.dumps({
                "kind": "audit",
                "repo": "dolios",
                "repo_path": "/repos/dolios",
                "rationale": "audit > 7d old",
                "command": audit_command,
            }), ""),
            "audit.py":         (0, '{"audited_at": "..."}', ""),
        }, tmp)
        record = tr.run_tick()
        assert record["kind"] == "audit"
        assert record["audit_rc"] == 0
        # The third call must be the audit subprocess with the picker's command.
        assert tr._runner.calls[-1] == audit_command.split()


# --------------------------------------------------------------------------- #
# Execute kind — the main path
# --------------------------------------------------------------------------- #
def test_execute_kind_invokes_dispatch_with_chunk_args():
    job = {
        "kind": "execute",
        "repo": "dolios",
        "repo_path": "/repos/dolios",
        "proposal_id": "dolios/p1",
        "proposal_path": "proposals/dolios/p1.md",
        "chunk_index": 2,
        "chunk_title": "**Chunk 2**",
        "task_id": "dolios-p1-chunk-2",
        "instructions": "multi-line\ninstructions\nhere",
        "rationale": "approved proposal chunk 2/3",
    }
    dispatch_response = json.dumps({
        "ok": True,
        "record": {
            "pr_url": "https://github.com/x/x/pull/42",
            "cost_usd": 1.23,
            "chunk_flipped": True,
            "branch": "auto/coder/dolios-p1-chunk-2",
        },
    })
    with tempfile.TemporaryDirectory() as tmp:
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "backlog.py":       (0, json.dumps(job), ""),
            # Match on a flag that only appears in the chunk-mode invocation:
            "--chunk-index":    (0, dispatch_response, ""),
        }, tmp)
        record = tr.run_tick()
        assert record["kind"] == "execute"
        assert record["pr_url"] == "https://github.com/x/x/pull/42"
        assert record["cost_usd"] == 1.23
        assert record["chunk_flipped"] is True
        # Verify the dispatch call actually carried the chunk args through.
        disp_call = tr._runner.calls[-1]
        assert "--proposal-path" in disp_call
        assert "proposals/dolios/p1.md" in disp_call
        assert "--chunk-index" in disp_call
        assert "2" in disp_call
        # Multi-line instructions pass through Python argv (no shell escaping).
        assert "multi-line\ninstructions\nhere" in disp_call


def test_execute_dispatch_error_lands_in_the_log_not_a_crash():
    """When the dispatcher refuses (idempotency, dirty tree, etc.), the tick
    still ends cleanly with the error captured."""
    job = {
        "kind": "execute",
        "repo": "dolios",
        "proposal_id": "dolios/p1",
        "proposal_path": "proposals/dolios/p1.md",
        "chunk_index": 1,
        "task_id": "dolios-p1-chunk-1",
        "instructions": "x",
        "rationale": "",
    }
    dispatch_response = json.dumps({
        "ok": False,
        "error": "chunk already has an OPEN PR #1 on branch 'auto/coder/...'",
    })
    with tempfile.TemporaryDirectory() as tmp:
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "backlog.py":       (0, json.dumps(job), ""),
            "--chunk-index":    (1, dispatch_response, ""),
        }, tmp)
        record = tr.run_tick()
        assert record["kind"] == "execute"
        assert record["dispatch_rc"] == 1
        assert "OPEN PR" in record["dispatch_error"]


# --------------------------------------------------------------------------- #
# Deferred kinds (propose / remeasure) — V1 logs + exits clean
# --------------------------------------------------------------------------- #
def test_propose_kind_is_logged_and_exits_clean_pending_implementation():
    with tempfile.TemporaryDirectory() as tmp:
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "backlog.py":       (0, json.dumps({
                "kind": "propose",
                "repo": "dolios",
                "gap_id": "ci-aaa",
                "gap_summary": "No CI",
                "rationale": "open gap",
            }), ""),
        }, tmp)
        record = tr.run_tick()
        assert record["kind"] == "propose"
        assert "needs_implementation" in record["deferred"] or "not yet auto-implemented" in record["deferred"]


def test_remeasure_kind_same_deferred_path():
    with tempfile.TemporaryDirectory() as tmp:
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "backlog.py":       (0, json.dumps({
                "kind": "remeasure",
                "repo": "dolios",
                "proposal_id": "dolios/p1",
                "rationale": "all chunks done",
                "command_audit": "...",
            }), ""),
        }, tmp)
        record = tr.run_tick()
        assert record["kind"] == "remeasure"
        assert record.get("deferred")


# --------------------------------------------------------------------------- #
# Tick log — one line per tick, append-only
# --------------------------------------------------------------------------- #
def test_tick_log_appends_one_jsonl_row_per_tick():
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "tick-log.jsonl"
        for _ in range(3):
            tr = t.TickRunner(
                root=Path(tmp),
                runner=FakeRunner({"--preflight-only": _preflight_hold("test")}),
                log_path=log,
                now=lambda: 1_700_000_000.0,
            )
            tr.run_tick()
        rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
        assert len(rows) == 3
        assert all(r["kind"] == "hold" for r in rows)


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
