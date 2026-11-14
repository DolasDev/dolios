#!/usr/bin/env python3
"""Loop watchdog for the autonomous-coder — detect a stuck or misbehaving
loop from its own tick log and alert a human over Matrix.

Why this exists: from 2026-06-10 to 2026-11-14 every tick held on an expired
OAuth token — 2,821 identical failures, nobody told. Failures in the path the
coder uses to ship (token, cron env, push creds, timeouts) can't be repaired
by the coder itself, because the fix would have to travel through the broken
path. The realistic goal for that class is: notice within a tick or two and
page a human. Deterministic, no LLM.

Checks (each yields a stable `key` so alerts dedupe across runs):

- **repeat**      — the last REPEAT_N ticks all failed with the same signature.
- **duplicate**   — the same task produced >1 PR (not counting PRs the
                    reviewer rejected/closed) within DUP_WINDOW_S. Symptom of
                    the loop acting on stale state.
- **stale**       — no tick logged for STALE_S (cron dead, gateway down, or
                    the tick killed before it could log). Only meaningful when
                    run independently of the tick (the hourly watchdog cron).
- **no-progress** — ticks are running but none made progress (successful
                    audit / PR) in NO_PROGRESS_S.

Alerting: a new finding alerts once; a still-active finding re-alerts every
REALERT_S; a finding that clears sends a "resolved" note. State lives in
`.dolios/watchdog-state.json` (gitignored, per-host).

Matrix delivery uses MATRIX_HOMESERVER + MATRIX_ACCESS_TOKEN (already in the
profile .env for hermes) + MATRIX_ALERT_ROOM. If any are missing the alert is
printed only — the watchdog never raises into its caller.

Usage:
    python3 watchdog.py               # evaluate, alert, update state
    python3 watchdog.py --dry-run     # evaluate + print, no send, no state write
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOLIOS_ROOT = HERE.parent.parent
DEFAULT_LOG = DOLIOS_ROOT / ".dolios" / "tick-log.jsonl"
DEFAULT_STATE = DOLIOS_ROOT / ".dolios" / "watchdog-state.json"

REPEAT_N = 3
DUP_WINDOW_S = 48 * 3600
# Ticks run 03:00-11:30 UTC, so the normal overnight gap is 15.5h.
STALE_S = 18 * 3600
NO_PROGRESS_S = 7 * 24 * 3600
REALERT_S = 24 * 3600
TAIL_ROWS = 500

# Holds that are the gate doing its job (pacing / budget), not a fault.
_NEUTRAL_HOLD_MARKERS = ("pace target", "budget exhausted", "at cap", "used >=")


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def _norm(text: str, limit: int = 160) -> str:
    """Collapse volatile bits (timestamps, long numbers, whitespace) so the
    same fault yields the same signature tick after tick."""
    text = re.sub(r"\d{4,}", "N", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _last_line(text: str) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def failure_signature(row: dict) -> str | None:
    """Stable failure signature for a tick row, or None if the tick was
    healthy or a deliberate hold."""
    kind = row.get("kind")
    if kind == "hold":
        reason = row.get("gate_reason") or ""
        if any(m in reason for m in _NEUTRAL_HOLD_MARKERS):
            return None
        return "hold: " + _norm(reason)
    if kind in ("preflight_error", "picker_error", "error"):
        return f"{kind}: " + _norm(row.get("error") or "")
    if row.get("audit_rc") not in (None, 0):
        return "audit: " + _norm(_last_line(row.get("error") or ""))
    if row.get("dispatch_rc") not in (None, 0):
        return f"{kind}: " + _norm(_last_line(row.get("dispatch_error") or "")
                                    or f"dispatch rc={row.get('dispatch_rc')}")
    if kind in ("propose", "remeasure", "reflect") and row.get("error"):
        return f"{kind}: " + _norm(row["error"])
    for key in ("review_error", "merge_error", "close_error"):
        if row.get(key):
            return f"{key}: " + _norm(row[key])
    return None


def made_progress(row: dict) -> bool:
    if row.get("kind") == "audit" and row.get("audit_rc") == 0:
        return True
    return bool(row.get("pr_url")) and row.get("dispatch_rc") == 0


def _task_identity(row: dict) -> str | None:
    """Branch minus the free-form timestamp suffix = the logical task."""
    branch = row.get("branch")
    if not branch:
        return None
    return re.sub(r"-\d{8}-\d{6}$", "", branch)


def _key(prefix: str, text: str) -> str:
    return f"{prefix}:{hashlib.sha256(text.encode()).hexdigest()[:10]}"


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
def evaluate(rows: list[dict], now: float, *, check_stale: bool = True) -> list[dict]:
    """Return findings: [{key, message}] for the current tick-log tail."""
    findings: list[dict] = []
    if not rows:
        return findings

    # repeat
    tail = rows[-REPEAT_N:]
    sigs = [failure_signature(r) for r in tail]
    if len(tail) == REPEAT_N and sigs[0] and all(s == sigs[0] for s in sigs):
        streak = 0
        for r in reversed(rows):
            if failure_signature(r) != sigs[0]:
                break
            streak += 1
        findings.append({
            "key": _key("repeat", sigs[0]),
            "message": (f"last {streak} ticks failed the same way "
                        f"(since {rows[-streak].get('iso')}): {sigs[0]}"),
        })

    # duplicate
    by_task: dict[str, list[dict]] = {}
    for r in rows:
        if now - float(r.get("ts", 0)) > DUP_WINDOW_S:
            continue
        ident = _task_identity(r)
        if ident and r.get("pr_url") and not r.get("pr_closed"):
            by_task.setdefault(ident, []).append(r)
    for ident, rs in sorted(by_task.items()):
        urls = sorted({r["pr_url"] for r in rs})
        if len(urls) > 1:
            findings.append({
                "key": _key("duplicate", ident),
                "message": (f"task `{ident}` opened {len(urls)} PRs "
                            f"({', '.join(urls)}) — loop is acting on stale state"),
            })

    # stale
    last_ts = float(rows[-1].get("ts", 0))
    if check_stale and now - last_ts > STALE_S:
        findings.append({
            "key": "stale",
            "message": (f"no tick logged for {(now - last_ts) / 3600:.1f}h "
                        f"(last {rows[-1].get('iso')}) — cron/gateway down or "
                        f"tick killed before logging"),
        })

    # no-progress
    window = [r for r in rows if now - float(r.get("ts", 0)) <= NO_PROGRESS_S]
    first_ts = float(rows[0].get("ts", 0))
    if (window and now - first_ts >= NO_PROGRESS_S
            and not any(made_progress(r) for r in window)):
        findings.append({
            "key": "no-progress",
            "message": (f"{len(window)} ticks in the last "
                        f"{NO_PROGRESS_S // 86400}d, none made progress "
                        f"(no successful audit or PR)"),
        })
    return findings


# --------------------------------------------------------------------------- #
# Alerting
# --------------------------------------------------------------------------- #
def matrix_sender_from_env(env=os.environ) -> Callable[[str], bool] | None:
    hs = env.get("MATRIX_HOMESERVER")
    token = env.get("MATRIX_ACCESS_TOKEN")
    room = env.get("MATRIX_ALERT_ROOM")
    if not (hs and token and room):
        return None

    def send(text: str) -> bool:
        txn = f"dolios-watchdog-{time.time_ns()}"
        url = (f"{hs.rstrip('/')}/_matrix/client/v3/rooms/"
               f"{urllib.parse.quote(room, safe='')}/send/m.room.message/{txn}")
        body = json.dumps({"msgtype": "m.text", "body": text}).encode()
        req = urllib.request.Request(url, data=body, method="PUT", headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return 200 <= resp.status < 300
        except Exception as exc:  # never raise into the tick
            print(f"watchdog: matrix send failed: {exc}", file=sys.stderr)
            return False

    return send


def reconcile(findings: list[dict], state: dict, now: float,
              send: Callable[[str], bool] | None) -> tuple[dict, list[str]]:
    """Diff findings against state; send new/re-alert/resolved messages.
    Returns (new_state, messages_attempted)."""
    active: dict = dict(state.get("active", {}))
    out: list[str] = []

    def deliver(text: str) -> bool:
        out.append(text)
        return send(text) if send else False

    current = {f["key"]: f for f in findings}
    for key, f in current.items():
        prev = active.get(key)
        if prev is None or not prev.get("alerted"):
            msg = f"[dolios-coder] ALERT: {f['message']}"
        elif now - prev.get("last_alert", 0) >= REALERT_S:
            msg = f"[dolios-coder] STILL FAILING: {f['message']}"
        else:
            continue
        entry = dict(prev or {"first": now})
        entry["message"] = f["message"]
        if deliver(msg) or send is None:
            entry["alerted"] = True
            entry["last_alert"] = now
        else:
            entry.setdefault("alerted", False)  # retry next run
        active[key] = entry

    for key in list(active):
        if key not in current:
            prev = active.pop(key)
            if prev.get("alerted"):
                deliver(f"[dolios-coder] resolved: {prev.get('message', key)}")

    return {"active": active, "updated": now}, out


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #
def _read_tail(log_path: Path, n: int = TAIL_ROWS) -> list[dict]:
    if not log_path.exists():
        return []
    rows = []
    with log_path.open() as fh:
        for line in fh.readlines()[-n:]:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def run(*, log_path: Path = DEFAULT_LOG, state_path: Path = DEFAULT_STATE,
        now: float | None = None, send: Callable[[str], bool] | None = None,
        use_env_sender: bool = True, dry_run: bool = False,
        check_stale: bool = True) -> dict:
    now = time.time() if now is None else now
    rows = _read_tail(log_path)
    findings = evaluate(rows, now, check_stale=check_stale)
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        state = {}
    # `stale` can only be judged by the independent cron run; the in-tick run
    # must not resolve it (the tick having just logged already clears it).
    if not check_stale and "stale" in state.get("active", {}):
        findings.append({"key": "stale",
                         "message": state["active"]["stale"].get("message", "stale")})
    if send is None and use_env_sender and not dry_run:
        send = matrix_sender_from_env()
    if dry_run:
        _, msgs = reconcile(findings, state, now, None)
        return {"findings": findings, "messages": msgs, "dry_run": True}
    new_state, msgs = reconcile(findings, state, now, send)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(new_state, indent=2))
    tmp.replace(state_path)
    return {"findings": findings, "messages": msgs,
            "channel": "matrix" if send else "none"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="autonomous-coder loop watchdog")
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    ap.add_argument("--state", default=str(DEFAULT_STATE))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    res = run(log_path=Path(args.log), state_path=Path(args.state),
              dry_run=args.dry_run)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
