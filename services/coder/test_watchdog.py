#!/usr/bin/env python3
"""Tests for the loop watchdog. Pure functions + an injected sender — no
network. Runs under pytest or standalone: `python3 test_watchdog.py`."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import watchdog as w

# Belt-and-braces: no test may reach a real Matrix room (the container's
# profile .env sets these). Every test injects its own sender anyway.
for _k in ("MATRIX_HOMESERVER", "MATRIX_ACCESS_TOKEN", "MATRIX_ALERT_ROOM"):
    os.environ.pop(_k, None)

H = 3600.0
T0 = 1_800_000_000.0

TOKEN_HOLD = ("capacity gate holds: gate check failed: OAuth access token "
              "expired or expiring within 300s")
PACE_HOLD = "capacity gate holds: seven_day at 14.0% used >= pace target 6.0%"


def hold(ts, reason):
    return {"ts": ts, "iso": f"t{ts}", "kind": "hold", "gate_decision": None,
            "gate_reason": reason}


def pr_row(ts, branch, url, **kw):
    return {"ts": ts, "iso": f"t{ts}", "kind": kw.pop("kind", "propose"),
            "dispatch_rc": 0, "branch": branch, "pr_url": url, **kw}


def audit_ok(ts):
    return {"ts": ts, "iso": f"t{ts}", "kind": "audit", "audit_rc": 0}


# -- classification -------------------------------------------------------- #
def test_pacing_hold_is_not_a_failure():
    assert w.failure_signature(hold(T0, PACE_HOLD)) is None


def test_token_hold_is_a_failure():
    assert "gate check failed" in w.failure_signature(hold(T0, TOKEN_HOLD))


def test_dispatch_error_signature_uses_last_line_and_drops_timestamps():
    a = {"kind": "execute", "dispatch_rc": 1,
         "dispatch_error": "Traceback\n  ...\nCalledProcessError: git push x-20261114-090055"}
    b = dict(a, dispatch_error="other\nCalledProcessError: git push x-20261115-100001")
    assert w.failure_signature(a) == w.failure_signature(b)
    assert w.failure_signature(a).startswith("execute: CalledProcessError")


def test_successful_pr_tick_is_healthy():
    assert w.failure_signature(pr_row(T0, "b", "u")) is None


def test_open_chunk_pr_awaiting_human_is_waiting_not_failing():
    row = {"kind": "execute", "dispatch_rc": 1, "dispatch_error":
           "chunk already has a OPEN PR #31 on branch 'auto/coder/x': u"}
    assert w.failure_signature(row) is None
    merged = dict(row, dispatch_error=row["dispatch_error"].replace("OPEN", "MERGED"))
    assert w.failure_signature(merged) is not None


# -- checks ---------------------------------------------------------------- #
def test_repeat_fires_after_three_identical_failures():
    rows = [audit_ok(T0)] + [hold(T0 + i * H, TOKEN_HOLD) for i in range(1, 4)]
    keys = [f["key"] for f in w.evaluate(rows, T0 + 4 * H)]
    assert any(k.startswith("repeat:") for k in keys)


def test_foreign_dirt_repeat_says_how_to_unblock():
    dirt = "foreign dirt blocks sync: ['services/coder/approvals.py']"
    rows = [audit_ok(T0)] + [{"ts": T0 + i * H, "iso": f"t{i}", "kind": "sync_error",
                              "error": dirt} for i in range(1, 4)]
    msgs = [f["message"] for f in w.evaluate(rows, T0 + 4 * H)
            if f["key"].startswith("repeat:")]
    assert msgs and "BLOCKED" in msgs[0] and "git checkout --" in msgs[0], msgs


def test_repeat_needs_the_same_signature():
    rows = [hold(T0, TOKEN_HOLD), hold(T0 + H, TOKEN_HOLD),
            {"ts": T0 + 2 * H, "kind": "execute", "dispatch_rc": 1,
             "dispatch_error": "working tree is not clean"}]
    assert not [f for f in w.evaluate(rows, T0 + 3 * H)
                if f["key"].startswith("repeat:")]


def test_pacing_holds_never_trigger_repeat():
    rows = [audit_ok(T0)] + [hold(T0 + i * H, PACE_HOLD) for i in range(1, 6)]
    assert not w.evaluate(rows, T0 + 6 * H)


def test_duplicate_prs_for_one_task_are_flagged():
    rows = [pr_row(T0, "auto/coder/propose-gap1-20261114-103050", "u/21"),
            pr_row(T0 + H, "auto/coder/propose-gap1-20261114-110029", "u/22")]
    f = w.evaluate(rows, T0 + 2 * H)
    assert len(f) == 1 and f[0]["key"].startswith("duplicate:")
    assert "u/21" in f[0]["message"] and "u/22" in f[0]["message"]


def test_rejected_and_closed_pr_is_not_a_duplicate():
    rows = [pr_row(T0, "auto/coder/propose-gap1-20261114-103050", "u/21",
                   pr_closed=True),
            pr_row(T0 + H, "auto/coder/propose-gap1-20261114-110029", "u/22")]
    assert not w.evaluate(rows, T0 + 2 * H)


def test_duplicates_age_out_of_the_window():
    rows = [pr_row(T0, "auto/coder/x-20261114-103050", "u/1"),
            pr_row(T0 + H, "auto/coder/x-20261114-110029", "u/2")]
    assert not [f for f in w.evaluate(rows, T0 + w.DUP_WINDOW_S + 2 * H,
                                      check_stale=False)
                if f["key"].startswith("duplicate:")]


def test_stale_fires_only_when_checked():
    rows = [audit_ok(T0)]
    later = T0 + w.STALE_S + H
    assert [f for f in w.evaluate(rows, later) if f["key"] == "stale"]
    assert not [f for f in w.evaluate(rows, later, check_stale=False)
                if f["key"] == "stale"]


def test_no_progress_over_a_week_of_ticks():
    rows = [hold(T0 + i * 12 * H, PACE_HOLD) for i in range(16)]
    keys = [f["key"] for f in w.evaluate(rows, rows[-1]["ts"], check_stale=False)]
    assert "no-progress" in keys


# -- alert lifecycle ------------------------------------------------------- #
class Sender:
    def __init__(self, ok=True):
        self.sent, self.ok = [], ok

    def __call__(self, text):
        self.sent.append(text)
        return self.ok


def test_alert_once_then_realert_then_resolve():
    f = [{"key": "repeat:abc", "message": "boom"}]
    s = Sender()
    state, _ = w.reconcile(f, {}, T0, s)
    assert s.sent == ["[dolios-coder] ALERT: boom"]
    state, _ = w.reconcile(f, state, T0 + H, s)          # within re-alert window
    assert len(s.sent) == 1
    state, _ = w.reconcile(f, state, T0 + w.REALERT_S + 1, s)
    assert s.sent[-1].startswith("[dolios-coder] STILL FAILING")
    state, _ = w.reconcile([], state, T0 + w.REALERT_S + 2, s)
    assert s.sent[-1] == "[dolios-coder] resolved: boom"
    assert state["active"] == {}


def test_failed_send_retries_next_run():
    f = [{"key": "k", "message": "m"}]
    bad = Sender(ok=False)
    state, _ = w.reconcile(f, {}, T0, bad)
    good = Sender()
    w.reconcile(f, state, T0 + 60, good)
    assert good.sent == ["[dolios-coder] ALERT: m"]


def test_run_end_to_end_with_files_and_no_env_sender():
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "tick-log.jsonl"
        state = Path(tmp) / "state.json"
        rows = [hold(T0 + i * H, TOKEN_HOLD) for i in range(3)]
        log.write_text("".join(json.dumps(r) + "\n" for r in rows))
        s = Sender()
        res = w.run(log_path=log, state_path=state, now=T0 + 3 * H, send=s)
        assert len(s.sent) == 1 and "gate check failed" in s.sent[0]
        assert json.loads(state.read_text())["active"]
        # second run: deduped
        w.run(log_path=log, state_path=state, now=T0 + 3.5 * H, send=s)
        assert len(s.sent) == 1
        assert res["findings"]


def test_in_tick_run_does_not_resolve_stale():
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "tick-log.jsonl"
        state = Path(tmp) / "state.json"
        log.write_text(json.dumps(audit_ok(T0)) + "\n")
        s = Sender()
        w.run(log_path=log, state_path=state, now=T0 + w.STALE_S + H, send=s)
        assert any("no tick logged" in m for m in s.sent)
        # a tick lands and runs the watchdog in-tick: stale must stay active
        log.write_text(log.read_text() + json.dumps(audit_ok(T0 + w.STALE_S + 2 * H)) + "\n")
        w.run(log_path=log, state_path=state, now=T0 + w.STALE_S + 2 * H,
              send=s, check_stale=False)
        assert not any(m.startswith("[dolios-coder] resolved") for m in s.sent)
        # the independent cron run then resolves it
        w.run(log_path=log, state_path=state, now=T0 + w.STALE_S + 3 * H, send=s)
        assert s.sent[-1].startswith("[dolios-coder] resolved")


def test_matrix_sender_absent_without_full_env():
    assert w.matrix_sender_from_env({"MATRIX_HOMESERVER": "x"}) is None
    assert w.matrix_sender_from_env({"MATRIX_HOMESERVER": "x",
                                     "MATRIX_ACCESS_TOKEN": "t",
                                     "MATRIX_ALERT_ROOM": "!r"}) is not None


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
