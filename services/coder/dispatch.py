#!/usr/bin/env python3
"""Guardrailed dispatcher for the autonomous-coder employee.

The local model (the supervisor) decides *which* task and repo to work on. This
module decides *how* — and enforces every safety rule in code, never trusting
the model to honor them:

  1. Capacity gate — refuse to start unless the spare-capacity gate says
     "dispatch" (see ../usage-gate).
  2. Allowlist — refuse any repo not explicitly permitted in the config.
  3. Never touch the base branch — all work happens on a fresh work branch;
     the dispatcher asserts HEAD has actually moved off base before running.
  4. Budget — refuse to start if the rolling-window spend cap is already hit;
     flag a run whose cost exceeds the per-run cap.
  5. PR, never merge — work lands as a pull request for human review. This
     module has no code path that merges.

All external effects go through injectable `Runners` so the guardrail logic is
unit-tested with fakes (no real git/claude/gh/network). See test_dispatch.py.

CLI:
    python3 dispatch.py --repo dolios --task TASK-1 --instructions "…"
    python3 dispatch.py --config services/coder/coder.yaml --repo … --task … --instructions …
    python3 dispatch.py --preflight-only      # just run the gate + budget checks
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))


class GuardrailError(RuntimeError):
    """A safety rule was violated, or a precondition failed. Dispatch aborts."""


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
@dataclass
class Budget:
    max_cost_usd_per_run: float = 2.0
    max_cost_usd_per_5h: float = 10.0
    ledger_path: str = os.path.join(HERE, ".ledger.jsonl")


@dataclass
class Config:
    allowlist: dict[str, str]
    base_branch: str = "main"
    branch_prefix: str = "auto/coder"
    budget: Budget = field(default_factory=Budget)
    gate_max_utilization: float = 85.0
    # Per-window pacing config (see services/usage-gate/usage_gate.decide).
    # When set, the dispatcher uses pacing — that's the nightly catch-up model.
    # `None` falls back to the flat `gate_max_utilization` threshold.
    gate_windows: dict | None = None

    @classmethod
    def load(cls, path: str) -> Config:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover
            raise GuardrailError("pyyaml is required to load coder config") from exc
        with open(path) as fh:
            raw = yaml.safe_load(fh) or {}
        b = raw.get("budget", {})
        # ledger path is relative to the config file's repo root when relative
        ledger = b.get("ledger_path", Budget.ledger_path)
        if not os.path.isabs(ledger):
            ledger = os.path.abspath(ledger)
        gate_raw = raw.get("gate", {}) or {}
        return cls(
            allowlist=raw.get("allowlist", {}) or {},
            base_branch=raw.get("base_branch", "main"),
            branch_prefix=raw.get("branch_prefix", "auto/coder"),
            budget=Budget(
                max_cost_usd_per_run=float(b.get("max_cost_usd_per_run", 2.0)),
                max_cost_usd_per_5h=float(b.get("max_cost_usd_per_5h", 10.0)),
                ledger_path=ledger,
            ),
            gate_max_utilization=float(gate_raw.get("max_utilization", 85.0)),
            gate_windows=gate_raw.get("windows"),
        )


# --------------------------------------------------------------------------- #
# Runners — every side effect, injectable for tests
# --------------------------------------------------------------------------- #
@dataclass
class Runners:
    gate_decide: Callable[[], dict]
    git: Callable[[list, str], str]
    claude: Callable[[str, str], dict]
    gh: Callable[[list, str], str]
    now: Callable[[], float] = time.time


def _real_git(args: list, cwd: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _real_claude(instructions: str, cwd: str) -> dict:
    """Headless Claude Code with write/edit permissions granted.

    `--dangerously-skip-permissions` is appropriate here because the dispatcher
    bounds the work in code: branch off main (never base), allowlisted repo,
    PR-not-merge. Without this flag, claude in headless `-p` mode refuses to
    write files — the dispatcher would silently produce a no-op commit, and
    in chunk mode that's catastrophic (would flip the checkbox without doing
    the work). See _check_claude_made_changes guardrail too.
    """
    out = subprocess.run(
        ["claude", "-p", instructions, "--output-format", "json",
         "--dangerously-skip-permissions"],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def _real_gh(args: list, cwd: str) -> str:
    """gh CLI runner. Converts FileNotFoundError (gh not installed) into a
    GuardrailError so callers see a clean message instead of a Python
    traceback. The dispatcher's try/finally then still appends the ledger row
    and resets HEAD on the way out."""
    try:
        return subprocess.run(
            ["gh", *args], cwd=cwd, check=True, capture_output=True, text=True
        ).stdout.strip()
    except FileNotFoundError as exc:
        raise GuardrailError(
            "gh CLI not on PATH — install it (https://cli.github.com) and "
            "set GH_TOKEN before retrying."
        ) from exc


def _real_gate_decide(max_utilization: float, windows: dict | None) -> dict:
    """Call the spare-capacity gate. Any failure is treated as 'hold' (fail closed).

    Prefers per-window pacing when `windows` is configured (the nightly
    catch-up model); falls back to the flat `max_utilization` threshold.
    """
    sys.path.insert(0, os.path.join(HERE, "..", "usage-gate"))
    try:
        import usage_gate
        snapshot = usage_gate.gather(enrich=False)
        return usage_gate.decide(snapshot, max_utilization=max_utilization,
                                 windows=windows)
    except Exception as exc:  # gate unreachable / token expired → do not dispatch
        return {"decision": "hold", "reason": f"gate check failed: {exc}"}


def default_runners(config: Config) -> Runners:
    return Runners(
        gate_decide=lambda: _real_gate_decide(
            config.gate_max_utilization, config.gate_windows
        ),
        git=_real_git,
        claude=_real_claude,
        gh=_real_gh,
    )


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #
class Dispatcher:
    def __init__(self, config: Config, runners: Runners):
        self.cfg = config
        self.r = runners

    # -- guardrail helpers ------------------------------------------------- #
    def _git(self, repo_path: str):
        return lambda *args: self.r.git(list(args), repo_path)

    def _window_cost(self, window_s: float) -> float:
        path = self.cfg.budget.ledger_path
        if not os.path.exists(path):
            return 0.0
        cutoff = self.r.now() - window_s
        total = 0.0
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("ts", 0) >= cutoff:
                    total += float(rec.get("cost_usd", 0.0))
        return total

    def _append_ledger(self, record: dict) -> None:
        path = self.cfg.budget.ledger_path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a") as fh:
            fh.write(json.dumps(record) + "\n")

    def preflight(self) -> dict:
        """Gate + budget checks only. Raises GuardrailError to abort."""
        decision = self.r.gate_decide()
        if decision.get("decision") != "dispatch":
            raise GuardrailError(f"capacity gate holds: {decision.get('reason')}")
        spent = self._window_cost(5 * 3600)
        cap = self.cfg.budget.max_cost_usd_per_5h
        if spent >= cap:
            raise GuardrailError(f"5h budget exhausted: ${spent:.2f} >= ${cap:.2f}")
        return {"gate": decision, "spent_5h": spent, "budget_5h": cap}

    def _resolve_repo(self, name: str) -> str:
        path = self.cfg.allowlist.get(name)
        if not path:
            raise GuardrailError(
                f"repo '{name}' is not in the allowlist {sorted(self.cfg.allowlist)}"
            )
        if not os.path.isdir(os.path.join(path, ".git")):
            raise GuardrailError(f"repo '{name}' path is not a git checkout: {path}")
        return path

    # -- the dispatch ------------------------------------------------------ #
    def dispatch(
        self,
        repo_name: str,
        task_id: str,
        instructions: str,
        *,
        proposal_path: str | None = None,
        chunk_index: int | None = None,
    ) -> dict:
        """Run one chunk of work.

        Two modes:

        - **Free-form** (`proposal_path=None`): the historical mode. Branch
          name carries a timestamp suffix so re-runs don't collide; no
          checkbox is flipped; no idempotency check against gh.

        - **Chunk mode** (`proposal_path` + `chunk_index` both set): the V1
          autonomous mode. Branch name is **deterministic** —
          `<branch_prefix>/<task_id>` with no timestamp — so an attempt to
          re-dispatch the same chunk while one is in-flight collides loudly.
          Before claude runs, we also query `gh pr list --head <branch>` and
          refuse if any open/merged PR already exists. **Before commit**, the
          proposal markdown's chunk `[ ]` is flipped to `[x]` so the execution
          PR diff carries both the implementation and the chunk-done state
          change atomically.
        """
        self.preflight()
        repo_path = self._resolve_repo(repo_name)
        git = self._git(repo_path)

        # Precondition: clean tree, so we never entangle the coder's work with
        # pre-existing uncommitted changes.
        if git("status", "--porcelain").strip():
            raise GuardrailError("working tree is not clean; refusing to start")

        base = self.cfg.base_branch
        chunk_mode = proposal_path is not None and chunk_index is not None
        if chunk_mode:
            # Deterministic name = idempotency on collision.
            branch = f"{self.cfg.branch_prefix}/{task_id}"
            self._check_chunk_idempotent(branch, repo_path)
        else:
            ts = datetime.datetime.fromtimestamp(self.r.now()).strftime("%Y%m%d-%H%M%S")
            branch = f"{self.cfg.branch_prefix}/{task_id}-{ts}"

        # Branch OFF base; we never commit onto base itself.
        git("checkout", "-b", branch, base)

        # GUARDRAIL: confirm we actually moved off the base branch.
        head = git("rev-parse", "--abbrev-ref", "HEAD").strip()
        if head == base or head != branch:
            raise GuardrailError(
                f"refusing to run: HEAD is '{head}', expected work branch '{branch}'"
            )

        # --- begin work block -------------------------------------------- #
        # Everything below is in try/finally so that:
        #   (1) the ledger row is appended even if the work raises mid-flight
        #       (cost from claude must be recorded even when push or gh fails);
        #   (2) HEAD is best-effort returned to `base` so the next tick's
        #       working-tree-clean precondition is met without manual cleanup.
        result: dict | None = None
        cost = 0.0
        over_run_budget = False
        chunk_flipped = False
        committed = False
        pr_url = ""
        try:
            # In chunk mode, wrap the chunk instructions with a preamble so
            # claude knows the dispatcher rules — without it, claude often
            # flips the chunk's own checkbox proactively (helpful but breaks
            # the atomic "implementation + flip in one diff" invariant) and
            # the dispatcher's flip_chunk then aborts with "already checked".
            if chunk_mode:
                claude_prompt = (
                    f"You are executing chunk {chunk_index} of an autonomous-coder "
                    f"proposal at `{proposal_path}`.\n\n"
                    f"Hard rules for chunk mode (the dispatcher will refuse "
                    f"the work if you violate any of these):\n"
                    f"- Do NOT modify `{proposal_path}` — not the frontmatter, "
                    f"not the Intervention checkboxes, not the Outcome. The "
                    f"dispatcher flips the chunk-{chunk_index} checkbox itself "
                    f"in the same commit; if you flip it too, that collision "
                    f"is detected and the run aborts.\n"
                    f"- Stay strictly inside chunk {chunk_index}'s scope. Do "
                    f"not implement future chunks.\n"
                    f"- Do not run git or commit. The dispatcher handles "
                    f"version control.\n\n"
                    f"{instructions}"
                )
            else:
                claude_prompt = instructions
            # Hand the actual engineering to Claude Code, inside the work branch.
            result = self.r.claude(claude_prompt, repo_path)
            cost = float(result.get("total_cost_usd", 0.0))
            over_run_budget = cost > self.cfg.budget.max_cost_usd_per_run

            # Chunk mode: flip the proposal's checkbox so the same commit
            # carries both the work AND the chunk-done state change.
            # GUARDRAIL: refuse to flip if claude made no changes — would
            # otherwise land a commit that marks the chunk "done" without any
            # implementation. The flip itself counts as a tree change, so we
            # have to check BEFORE.
            if chunk_mode:
                if not git("status", "--porcelain").strip():
                    raise GuardrailError(
                        "claude made no changes in chunk mode — refusing to "
                        f"flip the chunk-{chunk_index} checkbox (claude "
                        f"is_error={result.get('is_error')}, cost_usd={cost}). "
                        "Did claude lack write permissions, or refuse the work?"
                    )
                self._flip_proposal_chunk(repo_path, proposal_path, chunk_index)
                chunk_flipped = True

            # Commit whatever Claude Code changed (on the work branch only).
            git("add", "-A")
            committed = bool(git("status", "--porcelain").strip())
            if committed:
                commit_msg = f"auto-coder: {task_id}"
                if chunk_mode:
                    commit_msg += (f"\n\nChunk {chunk_index} of {proposal_path}; "
                                   "box flipped in this commit.")
                git("commit", "-m", commit_msg)
                git("push", "-u", "origin", branch)
                pr_url = self.r.gh(
                    ["pr", "create", "--base", base, "--head", branch,
                     "--title", f"auto-coder: {task_id}",
                     "--body", (instructions[:1000] or task_id)],
                    repo_path,
                )
        finally:
            record = {
                "ts": self.r.now(),
                "iso": datetime.datetime.fromtimestamp(self.r.now()).isoformat(),
                "repo": repo_name,
                "task_id": task_id,
                "branch": branch,
                "cost_usd": cost,
                "over_run_budget": over_run_budget,
                "committed": committed,
                "pr_url": pr_url,
                "is_error": bool(result.get("is_error")) if result else None,
                "proposal_path": proposal_path,
                "chunk_index": chunk_index,
                "chunk_flipped": chunk_flipped,
            }
            self._append_ledger(record)
            # Best-effort HEAD reset. Skip the checkout when the tree isn't
            # clean (would fail noisily) — uncommitted state is rare, and the
            # operator can review/discard it manually.
            try:
                if not self.r.git(["status", "--porcelain"], repo_path).strip():
                    self.r.git(["checkout", base], repo_path)
            except Exception:
                pass  # don't double-fault during cleanup
        return record

    # -- chunk-mode helpers ----------------------------------------------- #
    def _check_chunk_idempotent(self, branch: str, repo_path: str) -> None:
        """Refuse if a PR already exists for this chunk's deterministic branch.

        For V1 the canonical "is this chunk in flight or already merged?"
        signal is `gh pr list --head <branch> --state all`. A gh failure is
        non-fatal — the subsequent `git checkout -b <branch>` will fail on
        local-branch collision regardless, which is the secondary guard.
        """
        try:
            raw = self.r.gh(
                ["pr", "list", "--head", branch, "--state", "all",
                 "--json", "number,state,url"],
                repo_path,
            )
        except Exception:
            return  # gh unreachable / not auth'd — fall through to local guard
        try:
            prs = json.loads(raw) if raw else []
        except (TypeError, json.JSONDecodeError):
            return
        for pr in prs or []:
            if pr.get("state") in ("OPEN", "MERGED"):
                raise GuardrailError(
                    f"chunk already has a {pr['state']} PR #{pr['number']} "
                    f"on branch '{branch}': {pr.get('url')}"
                )

    def _flip_proposal_chunk(self, repo_path: str, proposal_path: str,
                              chunk_index: int) -> None:
        """Apply `chunks.flip_chunk` to the proposal markdown on the work
        branch's tree. Raises GuardrailError on any failure; we'd rather abort
        a chunk than land an implementation without the state-change diff."""
        # The chunks module lives next to dispatch.py; import lazily so the
        # picker-free mode doesn't depend on it.
        sys.path.insert(0, HERE)
        try:
            import chunks as ch
        except ImportError as exc:
            raise GuardrailError(f"cannot import chunks module: {exc}") from exc

        full = os.path.join(repo_path, proposal_path)
        if not os.path.isfile(full):
            raise GuardrailError(f"proposal not found: {full}")
        text = open(full).read()
        try:
            new_text = ch.flip_chunk(text, chunk_index)
        except ValueError as exc:
            raise GuardrailError(f"checkbox flip failed: {exc}") from exc
        with open(full, "w") as fh:
            fh.write(new_text)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Guardrailed autonomous-coder dispatcher.")
    ap.add_argument("--config", default=os.path.join(HERE, "coder.yaml"))
    ap.add_argument("--repo")
    ap.add_argument("--task")
    ap.add_argument("--instructions")
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--proposal-path",
                    help="enable chunk-mode: relative path to the proposal markdown")
    ap.add_argument("--chunk-index", type=int,
                    help="enable chunk-mode: 1-based index of the chunk this run lands")
    args = ap.parse_args(argv)

    if not os.path.exists(args.config):
        print(json.dumps({"ok": False, "error": f"no config at {args.config} "
                          "(copy coder.example.yaml → coder.yaml)"}, indent=2))
        return 2

    config = Config.load(args.config)
    disp = Dispatcher(config, default_runners(config))

    try:
        if args.preflight_only:
            print(json.dumps({"ok": True, **disp.preflight()}, indent=2, default=str))
            return 0
        if not (args.repo and args.task and args.instructions):
            raise GuardrailError("--repo, --task and --instructions are required")
        # Chunk mode requires both flags or neither.
        if (args.proposal_path is None) ^ (args.chunk_index is None):
            raise GuardrailError(
                "chunk mode requires both --proposal-path and --chunk-index"
            )
        record = disp.dispatch(
            args.repo, args.task, args.instructions,
            proposal_path=args.proposal_path,
            chunk_index=args.chunk_index,
        )
        print(json.dumps({"ok": True, "record": record}, indent=2, default=str))
        return 0
    except GuardrailError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
