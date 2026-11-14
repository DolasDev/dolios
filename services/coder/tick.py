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
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOLIOS_ROOT = HERE.parent.parent  # services/coder/ → dolios/

DEFAULT_LOG = DOLIOS_ROOT / ".dolios" / "tick-log.jsonl"


def _review_and_act(pr_url: str | None, repo_path: Path, record: dict,
                    *, runner=None) -> None:
    """After a PR-opening dispatch succeeds, run the auto-reviewer and act:
    approve → enable gh auto-merge; reject → close with reasoning; abstain/
    request_changes → leave open. Records every step into the tick record
    so behavior is reviewable in tick-log over time.

    `runner` is the same subprocess-runner injected into the TickRunner —
    threading it down to the reviewer keeps the side-effect surface unified
    and lets tick tests mock the reviewer's gh/claude calls without setting
    up a separate fake."""
    if not pr_url:
        return
    sys.path.insert(0, str(repo_path / "services" / "coder"))
    try:
        import reviewer as _rv
    except ImportError as exc:
        record["review_error"] = f"cannot import reviewer module: {exc}"
        return

    rev = _rv.review_pr(pr_url, repo_path, runner=runner)
    record["review_decision"]  = rev.get("decision")
    record["review_reasoning"] = rev.get("reasoning")
    record["review_cost_usd"]  = rev.get("cost_usd")

    decision = rev.get("decision")
    if decision == "approve":
        # Protected paths (the loop's own guardrails) need a human merge.
        # Unknown file list → fail closed.
        files = _rv.pr_changed_files(pr_url, repo_path, runner=runner)
        held = ["<could not list PR files>"] if files is None \
            else _rv.protected_files(files)
        if held:
            record["merge_held"] = held
            _rv.comment_pr(pr_url, repo_path, (
                "Auto-reviewer **approved**, but this PR touches protected "
                "paths, so auto-merge was NOT queued — needs a human merge.\n\n"
                + "\n".join(f"- `{p}`" for p in held)
                + f"\n\nReviewer: {rev.get('reasoning', '')}"
            ), runner=runner)
            _notify(f"[dolios-coder] needs your merge: {pr_url} touches "
                    f"protected paths ({', '.join(held[:5])}). Reviewer "
                    f"approved: {rev.get('reasoning', '')[:300]}")
            return
        merge_res = _rv.enable_auto_merge(pr_url, repo_path, runner=runner)
        record["merge_queued"] = bool(merge_res.get("queued"))
        if not merge_res.get("ok"):
            record["merge_error"] = merge_res.get("error", "")
    elif decision == "reject":
        comment = (
            f"Auto-reviewer rejected this PR:\n\n"
            f"{rev.get('reasoning', '(no reasoning)')}\n\n"
            f"_Closed automatically — the picker may re-attempt this task on a "
            f"future tick._"
        )
        close_res = _rv.close_pr(pr_url, repo_path, comment, runner=runner)
        record["pr_closed"] = bool(close_res.get("closed"))
        if not close_res.get("ok"):
            record["close_error"] = close_res.get("error", "")
    # For abstain / request_changes: leave the PR open. Humans can review,
    # or a future tick may re-review after rebase / CI signal.


def _notify(text: str) -> None:
    """Best-effort one-shot Matrix message (same channel as the watchdog).
    Silently a no-op when Matrix isn't configured (tests, host runs)."""
    try:
        sys.path.insert(0, str(HERE))
        import watchdog as _wd
        send = _wd.matrix_sender_from_env()
        if send:
            send(text)
    except Exception:  # noqa: BLE001 — never break the tick over a ping
        pass


def _extract_frontmatter_field(markdown_text: str, key: str) -> str | None:
    """Quick-and-dirty YAML frontmatter field extractor — no pyyaml needed.
    Returns the value of `key:` in the first `---`-delimited block at the top
    of the file, or None. Single-line values only; this is enough for the
    `audit:`, `status:`, `id:` fields we read from proposals."""
    if not markdown_text.startswith("---\n"):
        return None
    end = markdown_text.find("\n---\n", 4)
    if end == -1:
        return None
    fm = markdown_text[4:end]
    import re as _re
    m = _re.search(rf"^{_re.escape(key)}:\s*(.+)$", fm, _re.MULTILINE)
    if not m:
        return None
    return m.group(1).strip()

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
    def _real_runner(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
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

        # 1b. Sync the checkout to origin/main before reading state. If the
        # fast-forward can't happen cleanly, we refuse to pick work — a stale
        # checkout is how the loop opened duplicate PRs
        # (proposals/dolios/2026-11-14-sync-base-before-picking-work.md).
        if not self._sync_to_base(record):
            return record

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
                    _review_and_act(record.get("pr_url"), self.root, record,
                            runner=self._runner)
                else:
                    record["dispatch_error"] = disp.get("error")

        elif kind == "propose":
            self._handle_propose(job, record)

        elif kind == "remeasure":
            self._handle_remeasure(job, record)

        elif kind == "reflect":
            self._handle_reflect(job, record)

        elif kind == "error":
            record["error"] = job.get("error", "picker reported error")
            self._log(record)
            return record

        record["duration_seconds"] = round(self._now() - start, 2)
        self._log(record)
        return record

    # -- origin/<base> sync -------------------------------------------- #
    def _sync_to_base(self, record: dict, base: str = "main") -> bool:
        """Fast-forward `self.root` to `origin/<base>` before picking work.

        Returns True on success (record gets `synced_to` = new HEAD sha);
        False on any failure (record gets `kind: "sync_error"` + an
        `error` field, is logged, and the tick is over).

        Preconditions: HEAD is `<base>` and the working tree has no dirty
        paths outside `.dolios/metrics/` (the fleet's runtime-state
        exemption from `dispatch.EXEMPT_DIRTY_PREFIXES`). Pending local
        audit rows in dirty metrics files would block the ff-merge, so we
        snapshot each such file, `git checkout --` it, ff-merge, then
        re-append rows whose `audited_at` is not already present in the
        updated file. Order of local rows is preserved.
        """
        sys.path.insert(0, str(HERE))
        try:
            import dispatch as _dispatch
        except ImportError as exc:
            return self._sync_fail(record, f"cannot import dispatch: {exc}")

        # HEAD must be on base.
        rc, out, err = self._runner(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], self.root)
        if rc != 0:
            return self._sync_fail(
                record, f"git rev-parse HEAD failed: {(err or out)[:300]}")
        head_branch = out.strip()
        if head_branch != base:
            return self._sync_fail(
                record, f"HEAD is '{head_branch}', not '{base}'")

        # Working tree must have no non-exempt dirt.
        rc, out, err = self._runner(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            self.root)
        if rc != 0:
            return self._sync_fail(
                record, f"git status failed: {(err or out)[:300]}")
        dirty_paths = _dispatch._porcelain_paths(out)
        blocking = [p for p in dirty_paths if not _dispatch._is_exempt(p)]
        if blocking:
            return self._sync_fail(
                record, f"foreign dirt blocks sync: {blocking[:10]}")

        # Snapshot + reset pending metrics files so the ff-merge isn't
        # blocked. Keep a copy of their local rows for re-append after.
        pending: dict[str, list[dict]] = {}
        for p in dirty_paths:
            if not _dispatch._is_exempt(p):
                continue
            full = self.root / p
            try:
                text = full.read_text(encoding="utf-8")
            except OSError:
                continue
            rows = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            pending[p] = rows
            rc, co_out, co_err = self._runner(
                ["git", "checkout", "--", p], self.root)
            if rc != 0:
                self._restore_pending_rows(pending)
                return self._sync_fail(
                    record,
                    f"git checkout -- {p} failed: {(co_err or co_out)[:300]}")

        # Fetch + ff-merge.
        rc, out, err = self._runner(
            ["git", "fetch", "origin", base], self.root)
        if rc != 0:
            self._restore_pending_rows(pending)
            return self._sync_fail(
                record, f"git fetch origin {base} failed: {(err or out)[:300]}")
        rc, out, err = self._runner(
            ["git", "merge", "--ff-only", f"origin/{base}"], self.root)
        if rc != 0:
            self._restore_pending_rows(pending)
            return self._sync_fail(
                record,
                f"git merge --ff-only origin/{base} failed: {(err or out)[:300]}")

        # Re-append local audit rows that aren't already in the merged file.
        self._restore_pending_rows(pending)

        rc, out, _ = self._runner(["git", "rev-parse", "HEAD"], self.root)
        if rc == 0 and out.strip():
            record["synced_to"] = out.strip()
        return True

    def _sync_fail(self, record: dict, error: str) -> bool:
        record.update({"kind": "sync_error", "error": error})
        self._log(record)
        return False

    def _restore_pending_rows(self, pending: dict[str, list[dict]]) -> None:
        """Re-append rows whose `audited_at` isn't already in the file on
        disk, preserving the local order."""
        for rel, rows in pending.items():
            if not rows:
                continue
            full = self.root / rel
            existing: set[str] = set()
            if full.exists():
                try:
                    for line in full.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            at = json.loads(line).get("audited_at", "")
                        except json.JSONDecodeError:
                            continue
                        if at:
                            existing.add(at)
                except OSError:
                    pass
            full.parent.mkdir(parents=True, exist_ok=True)
            with full.open("a") as fh:
                for row in rows:
                    at = row.get("audited_at", "")
                    if at and at in existing:
                        continue
                    fh.write(json.dumps(row) + "\n")
                    if at:
                        existing.add(at)

    # -- kind=reflect handler ------------------------------------------- #
    def _handle_reflect(self, job: dict, record: dict) -> None:
        """Periodic meta-loop: dispatch claude to read the loop's own
        behavior over the lookback window (tick-log + ledger + closed
        proposals + audit history) and distill ONE new memory summarizing
        the most important cross-cutting pattern. Lands as a PR like
        everything else; humans review the lesson before it sticks."""
        sys.path.insert(0, str(self.root / "services" / "coder"))
        try:
            import prompts as _prompts
        except ImportError as exc:
            record["error"] = f"cannot import prompts module: {exc}"
            return

        today = time.strftime("%Y-%m-%d", time.gmtime(self._now()))
        instructions = _prompts.compose_reflect_instructions(
            root=self.root, days=7, today=today,
        )
        # Reflect dispatches against the dolios repo (where the loop's own
        # infrastructure — memories/, skills/, hooks/ — lives). task_id is
        # date-stamped so each week's reflect gets a distinct branch +
        # idempotent re-runs within the same day.
        task_id = f"reflect-{today}"
        ex_rc, ex_out, ex_err = self._runner(
            [
                "python3", "services/coder/dispatch.py",
                "--repo",         "dolios",
                "--task",         task_id,
                "--instructions", instructions,
            ],
            self.root,
        )
        record["dispatch_rc"] = ex_rc
        record["task_id"] = task_id
        try:
            disp = json.loads(ex_out)
        except (json.JSONDecodeError, ValueError):
            record["dispatch_error"] = (ex_out or ex_err)[-400:]
            return
        if disp.get("ok"):
            inner = disp.get("record", {})
            record["pr_url"]   = inner.get("pr_url")
            record["cost_usd"] = inner.get("cost_usd")
            record["branch"]   = inner.get("branch")
            _review_and_act(record.get("pr_url"), self.root, record,
                            runner=self._runner)
        else:
            record["dispatch_error"] = disp.get("error", "")

    # -- kind=remeasure handler ----------------------------------------- #
    def _handle_remeasure(self, job: dict, record: dict) -> None:
        """Close out an approved-and-fully-implemented proposal: run a fresh
        audit + write the Outcome + flip status: done — all in one
        free-form dispatch. Claude's prompt instructs it to run the audit
        command itself (appending the post-row) before reading and writing,
        so the new audit row + the Outcome edits land in a single commit /
        PR rather than racing through two separate ones."""
        sys.path.insert(0, str(self.root / "services" / "coder"))
        try:
            import prompts as _prompts
        except ImportError as exc:
            record["error"] = f"cannot import prompts module: {exc}"
            return

        repo = job.get("repo")
        proposal_path = job.get("proposal_path")
        proposal_id = job.get("proposal_id", "")
        if not (repo and proposal_path):
            record["error"] = f"remeasure job missing repo or proposal_path: {job}"
            return

        # Read the proposal's frontmatter to recover the pre-audit citation.
        full_path = self.root / proposal_path
        if not full_path.is_file():
            record["error"] = f"proposal not found at {full_path}"
            return
        text = full_path.read_text(encoding="utf-8")
        pre_audit_ref = _extract_frontmatter_field(text, "audit") or "(not found)"

        today = time.strftime("%Y-%m-%d", time.gmtime(self._now()))
        instructions = _prompts.compose_remeasure_instructions(
            root=self.root, repo=repo, proposal_path=proposal_path,
            pre_audit_ref=pre_audit_ref, today=today,
        )

        # Deterministic task_id from the proposal id. Idempotency precheck
        # refuses if a remeasure-PR for the same proposal is already open.
        task_id = "remeasure-" + proposal_id.replace("/", "-")
        ex_rc, ex_out, ex_err = self._runner(
            [
                "python3", "services/coder/dispatch.py",
                "--repo",         repo,
                "--task",         task_id,
                "--instructions", instructions,
            ],
            self.root,
        )
        record["dispatch_rc"] = ex_rc
        record["task_id"] = task_id
        try:
            disp = json.loads(ex_out)
        except (json.JSONDecodeError, ValueError):
            record["dispatch_error"] = (ex_out or ex_err)[-400:]
            return
        if disp.get("ok"):
            inner = disp.get("record", {})
            record["pr_url"]   = inner.get("pr_url")
            record["cost_usd"] = inner.get("cost_usd")
            record["branch"]   = inner.get("branch")
            _review_and_act(record.get("pr_url"), self.root, record,
                            runner=self._runner)
        else:
            record["dispatch_error"] = disp.get("error", "")

    # -- kind=propose handler ------------------------------------------- #
    def _handle_propose(self, job: dict, record: dict) -> None:
        """Compose a rich proposal-generation prompt from versioned learning
        artifacts (memories, recent outcomes, skills) and free-form-dispatch
        it. The dispatcher handles branch / commit / push / PR; claude writes
        the proposal markdown into the work branch."""
        # Lazy import — keeps the picker/empty/audit/execute paths free of
        # this dependency until they actually need it.
        sys.path.insert(0, str(self.root / "services" / "coder"))
        try:
            import prompts as _prompts
        except ImportError as exc:
            record["error"] = f"cannot import prompts module: {exc}"
            return

        repo = job.get("repo")
        gap_id = job.get("gap_id")
        if not (repo and gap_id):
            record["error"] = f"propose job missing repo or gap_id: {job}"
            return

        # Load the latest audit row for the repo + the specific gap by id.
        history_path = (self.root / ".dolios" / "metrics" / repo /
                        "history.jsonl")
        if not history_path.exists():
            record["error"] = f"no audit history at {history_path}"
            return
        rows = [json.loads(line) for line in history_path.read_text().splitlines()
                if line.strip()]
        if not rows:
            record["error"] = "audit history file is empty"
            return
        audit_row = rows[-1]
        gap = _prompts.find_gap(audit_row, gap_id)
        if not gap:
            record["error"] = f"gap_id {gap_id} not found in latest audit row"
            return

        audit_ref = (
            f".dolios/metrics/{repo}/history.jsonl"
            f"#L{len(rows)}@{audit_row['audited_at']}"
        )
        today = time.strftime("%Y-%m-%d", time.gmtime(self._now()))

        instructions = _prompts.compose_propose_instructions(
            root=self.root, repo=repo, gap=gap,
            audit_ref=audit_ref, today=today,
        )

        # task_id forms a deterministic branch name auto/coder/propose-<gap_id>;
        # the dispatcher's gh idempotency precheck will refuse if a PR for the
        # same gap is already open.
        task_id = f"propose-{gap_id}"
        ex_rc, ex_out, ex_err = self._runner(
            [
                "python3", "services/coder/dispatch.py",
                "--repo",         repo,
                "--task",         task_id,
                "--instructions", instructions,
            ],
            self.root,
        )
        record["dispatch_rc"] = ex_rc
        record["task_id"] = task_id
        try:
            disp = json.loads(ex_out)
        except (json.JSONDecodeError, ValueError):
            record["dispatch_error"] = (ex_out or ex_err)[-400:]
            return
        if disp.get("ok"):
            inner = disp.get("record", {})
            record["pr_url"]   = inner.get("pr_url")
            record["cost_usd"] = inner.get("cost_usd")
            record["branch"]   = inner.get("branch")
            _review_and_act(record.get("pr_url"), self.root, record,
                            runner=self._runner)
        else:
            record["dispatch_error"] = disp.get("error", "")


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

    # Loop watchdog: page a human if the loop is stuck or misbehaving. The
    # stale check is left to the independent hourly watchdog cron — this tick
    # just logged, so it can't judge staleness. Never let it break the tick.
    try:
        sys.path.insert(0, str(HERE))
        import watchdog as _wd
        wd = _wd.run(log_path=runner.log_path, check_stale=False)
        if wd.get("messages"):
            print(json.dumps({"watchdog": wd}, indent=2), file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"watchdog failed: {exc}", file=sys.stderr)

    if record["kind"] in ("preflight_error", "picker_error", "sync_error", "error"):
        return 2
    if record.get("dispatch_rc", 0) != 0 or record.get("audit_rc", 0) != 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
