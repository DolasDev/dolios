#!/usr/bin/env python3
"""Single-tick orchestrator for the autonomous-coder.

What the supervisor cron's prose was meant to do, in deterministic Python —
removes the 35B model's judgment from the orchestration layer entirely. The
supervisor still does the heavy lifting INSIDE the dispatched claude calls
(where its judgment matters); here we just shell out mechanically.

  1. `dispatch.py --preflight-only`  → capacity gate + budget check
     If gate holds, log the tick as `kind: hold` and exit 0 cleanly.
  2. `backlog.py --next`              → next task as structured JSON
  3. Switch on `kind`:
       - "audit":     run the picker's `command` field verbatim.
       - "execute":   run `dispatch.py` in chunk mode (proposal_path +
                      chunk_index pass through).
       - "empty":     log + exit 0.
       - "propose"    } V1 deferred — log as "needs_implementation" and exit 0
       - "remeasure"  } so the loop stays alive while waiting on those paths.
       - "error":     log + exit 2.

Every tick lands as one JSON line in `.dolios/tick-log.jsonl` so the loop's
behavior over time is reviewable without parsing model output.

Exit codes:
  0 — tick completed cleanly (work done, quiet, hold, or known-deferred kind)
  1 — picker dispatched but the work itself failed (claude / gh / git / etc.)
  2 — preflight or picker exited badly (config/auth/network)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
DOLIOS_ROOT = HERE.parent.parent  # services/coder/ → dolios/

DEFAULT_LOG = DOLIOS_ROOT / ".dolios" / "tick-log.jsonl"

# Subprocess return shape.
Runner = Callable[[list[str], Path], "tuple[int, str, str]"]


# --------------------------------------------------------------------------- #
# TickRunner — encapsulates side effects so tests can swap them out
# --------------------------------------------------------------------------- #
class TickRunner:
    def __init__(
        self,
        *,
        root: Path = DOLIOS_ROOT,
        runner: Runner | None = None,
        log_path: Path | None = None,
        now: Callable[[], float] = time.time,
    ):
        self.root = root
        self._runner = runner or self._real_runner
        self.log_path = log_path or DEFAULT_LOG
        self._now = now

    @staticmethod
    def _real_runner(cmd: list[str], cwd: Path) -> "tuple[int, str, str]":
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    def _log(self, record: dict) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")

    # -- the tick ---------------------------------------------------------- #
    def run_tick(self) -> dict:
        start = self._now()
        record: dict = {
            "ts": start,
            "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start)),
        }

        # 1. Preflight (gate + budget check). dispatch.py --preflight-only
        # always emits JSON; rc==0 on dispatch, rc==1 on a held gate or other
        # GuardrailError, rc==2 on bad config.
        pf_rc, pf_out, pf_err = self._runner(
            ["python3", "services/coder/dispatch.py", "--preflight-only"],
            self.root,
        )
        try:
            preflight = json.loads(pf_out)
        except (json.JSONDecodeError, ValueError):
            record.update({
                "kind": "preflight_error",
                "error": f"non-JSON preflight (rc={pf_rc}): {(pf_out or pf_err)[:300]}",
            })
            self._log(record)
            return record

        if pf_rc != 0 or not preflight.get("ok", True):
            gate = preflight.get("gate") or {}
            record.update({
                "kind": "hold",
                "gate_decision": gate.get("decision"),
                "gate_reason": gate.get("reason") or preflight.get("error"),
                "binding_window": gate.get("binding_window"),
                "binding_headroom_pct": gate.get("binding_headroom_pct"),
            })
            self._log(record)
            return record

        record["gate_headroom_pct"] = (
            preflight.get("gate", {}).get("binding_headroom_pct")
        )

        # 2. Picker.
        pk_rc, pk_out, pk_err = self._runner(
            ["python3", "services/coder/backlog.py", "--next"],
            self.root,
        )
        if pk_rc != 0:
            record.update({
                "kind": "picker_error",
                "error": f"picker rc={pk_rc}: {(pk_err or pk_out)[:300]}",
            })
            self._log(record)
            return record
        try:
            job = json.loads(pk_out)
        except (json.JSONDecodeError, ValueError):
            record.update({
                "kind": "picker_error",
                "error": f"picker returned non-JSON: {pk_out[:300]}",
            })
            self._log(record)
            return record

        kind = job.get("kind", "unknown")
        record["kind"] = kind
        record["rationale"] = job.get("rationale", "")

        # 3. Dispatch by kind.
        if kind == "empty":
            pass

        elif kind == "audit":
            cmd = job["command"].split()
            au_rc, au_out, au_err = self._runner(cmd, self.root)
            record["audit_rc"] = au_rc
            record["audit_stdout_tail"] = (au_out or "")[-400:]
            if au_rc != 0:
                record["error"] = (au_err or au_out)[-300:]

        elif kind == "execute":
            ex_rc, ex_out, ex_err = self._runner(
                [
                    "python3", "services/coder/dispatch.py",
                    "--repo",            job["repo"],
                    "--task",            job["task_id"],
                    "--instructions",    job["instructions"],
                    "--proposal-path",   job["proposal_path"],
                    "--chunk-index",     str(job["chunk_index"]),
                ],
                self.root,
            )
            record["dispatch_rc"] = ex_rc
            # The dispatcher's stdout is structured JSON either way.
            try:
                disp = json.loads(ex_out)
            except (json.JSONDecodeError, ValueError):
                record["dispatch_error"] = (ex_out or ex_err)[-300:]
            else:
                if disp.get("ok"):
                    inner = disp.get("record", {})
                    record["pr_url"]        = inner.get("pr_url")
                    record["cost_usd"]      = inner.get("cost_usd")
                    record["chunk_flipped"] = inner.get("chunk_flipped")
                    record["branch"]        = inner.get("branch")
                else:
                    record["dispatch_error"] = disp.get("error")

        elif kind in ("propose", "remeasure"):
            # V1 hasn't built the agent-driven path for these. The tick still
            # exits clean so the cron stays alive; next tick will hit the same
            # case until the picker advances or the supervisor handles it
            # manually.
            record["deferred"] = (
                f"kind={kind} not yet auto-implemented; see services/coder/README.md"
            )

        elif kind == "error":
            record["error"] = job.get("error", "picker reported error")
            self._log(record)
            return record

        record["duration_seconds"] = round(self._now() - start, 2)
        self._log(record)
        return record


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Single-tick orchestrator.")
    ap.add_argument("--root", default=str(DOLIOS_ROOT),
                    help="dolios repo root (default: derived from this file)")
    ap.add_argument("--log", default=None, help="tick log path (default: .dolios/tick-log.jsonl)")
    args = ap.parse_args(argv)

    runner = TickRunner(
        root=Path(args.root).resolve(),
        log_path=Path(args.log).resolve() if args.log else None,
    )
    record = runner.run_tick()
    print(json.dumps(record, indent=2))

    if record["kind"] in ("preflight_error", "picker_error", "error"):
        return 2
    if record.get("dispatch_rc", 0) != 0 or record.get("audit_rc", 0) != 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
