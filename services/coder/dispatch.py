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
import dataclasses
import datetime
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

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

    @classmethod
    def load(cls, path: str) -> "Config":
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
        return cls(
            allowlist=raw.get("allowlist", {}) or {},
            base_branch=raw.get("base_branch", "main"),
            branch_prefix=raw.get("branch_prefix", "auto/coder"),
            budget=Budget(
                max_cost_usd_per_run=float(b.get("max_cost_usd_per_run", 2.0)),
                max_cost_usd_per_5h=float(b.get("max_cost_usd_per_5h", 10.0)),
                ledger_path=ledger,
            ),
            gate_max_utilization=float(raw.get("gate", {}).get("max_utilization", 85.0)),
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
    out = subprocess.run(
        ["claude", "-p", instructions, "--output-format", "json"],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def _real_gh(args: list, cwd: str) -> str:
    return subprocess.run(
        ["gh", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _real_gate_decide(max_utilization: float) -> dict:
    """Call the spare-capacity gate. Any failure is treated as 'hold' (fail closed)."""
    sys.path.insert(0, os.path.join(HERE, "..", "usage-gate"))
    try:
        import usage_gate
        snapshot = usage_gate.gather(enrich=False)
        return usage_gate.decide(snapshot, max_utilization)
    except Exception as exc:  # gate unreachable / token expired → do not dispatch
        return {"decision": "hold", "reason": f"gate check failed: {exc}"}


def default_runners(config: Config) -> Runners:
    return Runners(
        gate_decide=lambda: _real_gate_decide(config.gate_max_utilization),
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
    def dispatch(self, repo_name: str, task_id: str, instructions: str) -> dict:
        self.preflight()
        repo_path = self._resolve_repo(repo_name)
        git = self._git(repo_path)

        # Precondition: clean tree, so we never entangle the coder's work with
        # pre-existing uncommitted changes.
        if git("status", "--porcelain").strip():
            raise GuardrailError("working tree is not clean; refusing to start")

        base = self.cfg.base_branch
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

        # Hand the actual engineering to Claude Code, inside the work branch.
        result = self.r.claude(instructions, repo_path)
        cost = float(result.get("total_cost_usd", 0.0))
        over_run_budget = cost > self.cfg.budget.max_cost_usd_per_run

        # Commit whatever Claude Code changed (on the work branch only).
        git("add", "-A")
        committed = bool(git("status", "--porcelain").strip())
        if committed:
            git("commit", "-m", f"auto-coder: {task_id}")

        pr_url = ""
        if committed:
            git("push", "-u", "origin", branch)
            pr_url = self.r.gh(
                ["pr", "create", "--base", base, "--head", branch,
                 "--title", f"auto-coder: {task_id}",
                 "--body", (instructions[:1000] or task_id)],
                repo_path,
            )

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
            "is_error": bool(result.get("is_error")),
        }
        self._append_ledger(record)
        return record


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
        record = disp.dispatch(args.repo, args.task, args.instructions)
        print(json.dumps({"ok": True, "record": record}, indent=2, default=str))
        return 0
    except GuardrailError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
