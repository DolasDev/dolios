#!/usr/bin/env python3
"""Guardrail tests for the coder dispatcher — all side effects mocked.

These lock in the safety properties: the dispatcher must refuse to act when the
gate holds, when a repo isn't allowlisted, on a dirty tree, or over budget; it
must always move off the base branch before running Claude Code; and it must
open a PR, never merge. Runs under pytest or standalone:
`python3 test_dispatch.py`.
"""

import json
import os
import tempfile

import dispatch as d


class FakeRepo:
    """Stateful fake backing the git/claude/gh runners."""

    def __init__(self, *, initial_dirty=False, claude_changes=True,
                 cost=0.5, checkout_works=True):
        self.branch = "main"
        self.initial_dirty = initial_dirty
        self.claude_changes = claude_changes
        self.cost = cost
        self.checkout_works = checkout_works
        self.claude_ran = False
        self.git_calls = []
        self.gh_calls = []
        self.pushed = False
        self.committed = False

    def git(self, args, cwd):
        self.git_calls.append(args)
        if args[:2] == ["status", "--porcelain"]:
            if not self.claude_ran:
                return "M file\n" if self.initial_dirty else ""
            return " M changed.py\n" if self.claude_changes else ""
        if args and args[0] == "checkout" and "-b" in args:
            if self.checkout_works:
                self.branch = args[2]
            return ""
        if args[:1] == ["rev-parse"]:
            return self.branch + "\n"
        if args and args[0] == "commit":
            self.committed = True
            return ""
        if args and args[0] == "push":
            self.pushed = True
            return ""
        return ""

    def claude(self, instructions, cwd):
        self.claude_ran = True
        return {"total_cost_usd": self.cost, "is_error": False}

    def gh(self, args, cwd):
        self.gh_calls.append(args)
        return "https://github.com/dolas/dolios/pull/1"


def make(tmp, repo, *, gate="dispatch", ledger_seed=None,
         per_run=2.0, per_5h=10.0, allow=True, now=1_000_000.0):
    """Build a (Config, Runners, Dispatcher) wired to a fake repo."""
    repo_path = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo_path, ".git"), exist_ok=True)
    ledger = os.path.join(tmp, "ledger.jsonl")
    if ledger_seed is not None:
        with open(ledger, "w") as fh:
            for ts, cost in ledger_seed:
                fh.write(json.dumps({"ts": ts, "cost_usd": cost}) + "\n")
    cfg = d.Config(
        allowlist={"dolios": repo_path} if allow else {},
        base_branch="main", branch_prefix="auto/coder",
        budget=d.Budget(max_cost_usd_per_run=per_run,
                        max_cost_usd_per_5h=per_5h, ledger_path=ledger),
    )
    runners = d.Runners(
        gate_decide=lambda: {"decision": gate, "reason": "test"},
        git=repo.git, claude=repo.claude, gh=repo.gh, now=lambda: now,
    )
    return cfg, runners, d.Dispatcher(cfg, runners)


def _expect_guardrail(fn):
    try:
        fn()
    except d.GuardrailError as exc:
        return str(exc)
    raise AssertionError("expected GuardrailError, none raised")


def test_hold_aborts_before_any_work():
    with tempfile.TemporaryDirectory() as tmp:
        repo = FakeRepo()
        _, _, disp = make(tmp, repo, gate="hold")
        msg = _expect_guardrail(lambda: disp.dispatch("dolios", "T1", "do thing"))
        assert "gate holds" in msg
        assert not repo.claude_ran and not repo.gh_calls


def test_non_allowlisted_repo_refused():
    with tempfile.TemporaryDirectory() as tmp:
        repo = FakeRepo()
        _, _, disp = make(tmp, repo)
        msg = _expect_guardrail(lambda: disp.dispatch("not-allowed", "T1", "x"))
        assert "allowlist" in msg
        assert not repo.claude_ran


def test_dirty_tree_refused():
    with tempfile.TemporaryDirectory() as tmp:
        repo = FakeRepo(initial_dirty=True)
        _, _, disp = make(tmp, repo)
        msg = _expect_guardrail(lambda: disp.dispatch("dolios", "T1", "x"))
        assert "not clean" in msg
        assert not repo.claude_ran


def test_budget_precheck_blocks():
    with tempfile.TemporaryDirectory() as tmp:
        repo = FakeRepo()
        # Already at/over the cap in-window → a new run is blocked at preflight.
        _, _, disp = make(tmp, repo, per_5h=10.0,
                          ledger_seed=[(1_000_000.0 - 60, 10.5)])
        msg = _expect_guardrail(lambda: disp.dispatch("dolios", "T1", "x"))
        assert "budget exhausted" in msg
        assert not repo.claude_ran


def test_old_ledger_entries_fall_out_of_window():
    with tempfile.TemporaryDirectory() as tmp:
        repo = FakeRepo()
        # 9.5 spent but 6h ago — outside the 5h window, so it does NOT block.
        _, _, disp = make(tmp, repo, per_5h=10.0,
                          ledger_seed=[(1_000_000.0 - 6 * 3600, 9.5)])
        rec = disp.dispatch("dolios", "T1", "x")
        assert repo.claude_ran and rec["pr_url"]


def test_happy_path_branches_runs_and_opens_pr():
    with tempfile.TemporaryDirectory() as tmp:
        repo = FakeRepo(cost=0.5)
        _, _, disp = make(tmp, repo)
        rec = disp.dispatch("dolios", "TASK-1", "fix the thing")
        # branched off base and moved HEAD onto the work branch
        assert repo.branch == rec["branch"] and rec["branch"].startswith("auto/coder/TASK-1")
        assert repo.claude_ran and repo.committed and repo.pushed
        # opened a PR, never merged
        assert any(c[:2] == ["pr", "create"] for c in repo.gh_calls)
        assert all("merge" not in c for c in repo.gh_calls)
        assert rec["pr_url"] and not rec["over_run_budget"]
        # ledger recorded the spend
        with open(disp.cfg.budget.ledger_path) as fh:
            assert json.loads(fh.readline())["cost_usd"] == 0.5


def test_never_moves_off_base_guardrail():
    with tempfile.TemporaryDirectory() as tmp:
        repo = FakeRepo(checkout_works=False)  # simulate checkout not moving HEAD
        _, _, disp = make(tmp, repo)
        msg = _expect_guardrail(lambda: disp.dispatch("dolios", "T1", "x"))
        assert "HEAD is 'main'" in msg
        assert not repo.claude_ran  # never ran Claude on base


def test_per_run_over_budget_flagged_but_completes():
    with tempfile.TemporaryDirectory() as tmp:
        repo = FakeRepo(cost=5.0)  # > per_run cap 2.0
        _, _, disp = make(tmp, repo, per_run=2.0)
        rec = disp.dispatch("dolios", "T1", "x")
        assert rec["over_run_budget"] is True
        assert rec["pr_url"]  # work exists; surfaced for human review


# --------------------------------------------------------------------------- #
# Chunk-mode (V1): deterministic branch, gh idempotency, atomic box flip
# --------------------------------------------------------------------------- #
PROPOSAL_BODY = """\
---
id: dolios/p1
status: approved
---

# Title

## Intervention

- [ ] **Chunk 1** — first
- [ ] **Chunk 2** — second
"""


def _write_proposal(tmp_root, repo_relpath, body=PROPOSAL_BODY):
    """Drop a proposal at <repo>/<relpath>. Returns (full_repo_path, full_md_path).
    Matches how the real allowlist + proposals/ layout looks."""
    repo = os.path.join(tmp_root, "repo")
    os.makedirs(os.path.join(repo, ".git"), exist_ok=True)
    md = os.path.join(repo, repo_relpath)
    os.makedirs(os.path.dirname(md), exist_ok=True)
    with open(md, "w") as fh:
        fh.write(body)
    return repo, md


class FakeRepoWithProposal(FakeRepo):
    """FakeRepo + a real on-disk proposal at proposals/dolios/p1.md so
    flip_chunk has something to edit."""

    def __init__(self, repo_path, *, gh_pr_list_response="[]", **kw):
        super().__init__(**kw)
        self.repo_path = repo_path
        self.gh_pr_list_response = gh_pr_list_response

    def gh(self, args, cwd):
        self.gh_calls.append(args)
        # Idempotency check uses `pr list --head <branch> ...`
        if args[:2] == ["pr", "list"]:
            return self.gh_pr_list_response
        return "https://github.com/dolas/dolios/pull/1"


def test_chunk_mode_uses_deterministic_branch_and_flips_the_box():
    with tempfile.TemporaryDirectory() as tmp:
        repo_path, md = _write_proposal(tmp, "proposals/dolios/p1.md")
        repo = FakeRepoWithProposal(repo_path)
        # Build a config whose allowlist points at this fake repo
        ledger = os.path.join(tmp, "ledger.jsonl")
        cfg = d.Config(allowlist={"dolios": repo_path}, base_branch="main",
                       branch_prefix="auto/coder",
                       budget=d.Budget(ledger_path=ledger))
        runners = d.Runners(gate_decide=lambda: {"decision": "dispatch", "reason": "ok"},
                            git=repo.git, claude=repo.claude, gh=repo.gh,
                            now=lambda: 1_700_000_000.0)
        disp = d.Dispatcher(cfg, runners)

        rec = disp.dispatch(
            "dolios", "dolios-p1-chunk-1", "do chunk 1",
            proposal_path="proposals/dolios/p1.md", chunk_index=1,
        )
        # Deterministic branch — no timestamp suffix
        assert rec["branch"] == "auto/coder/dolios-p1-chunk-1"
        assert rec["chunk_flipped"] is True
        # Box flipped in the proposal markdown on disk
        with open(md) as fh:
            body = fh.read()
        assert "- [x] **Chunk 1**" in body
        assert "- [ ] **Chunk 2**" in body
        # PR was opened
        assert any(c[:2] == ["pr", "create"] for c in repo.gh_calls)


def test_chunk_mode_refuses_when_open_pr_already_exists():
    """If gh reports an OPEN PR on this chunk's branch, abort — chunk in flight."""
    with tempfile.TemporaryDirectory() as tmp:
        repo_path, _ = _write_proposal(tmp, "proposals/dolios/p1.md")
        repo = FakeRepoWithProposal(
            repo_path,
            gh_pr_list_response=json.dumps([{
                "number": 42, "state": "OPEN", "url": "https://x/42",
            }]),
        )
        cfg = d.Config(allowlist={"dolios": repo_path}, base_branch="main",
                       branch_prefix="auto/coder",
                       budget=d.Budget(ledger_path=os.path.join(tmp, "l.jsonl")))
        runners = d.Runners(gate_decide=lambda: {"decision": "dispatch", "reason": "ok"},
                            git=repo.git, claude=repo.claude, gh=repo.gh,
                            now=lambda: 1.0)
        disp = d.Dispatcher(cfg, runners)
        msg = _expect_guardrail(lambda: disp.dispatch(
            "dolios", "dolios-p1-chunk-1", "do chunk 1",
            proposal_path="proposals/dolios/p1.md", chunk_index=1,
        ))
        assert "OPEN PR" in msg and "42" in msg
        assert not repo.claude_ran   # never ran a duplicate


def test_chunk_mode_refuses_when_merged_pr_already_exists():
    """A MERGED PR for this chunk's branch means the chunk is already done —
    the picker should have skipped it; refuse loudly."""
    with tempfile.TemporaryDirectory() as tmp:
        repo_path, _ = _write_proposal(tmp, "proposals/dolios/p1.md")
        repo = FakeRepoWithProposal(
            repo_path,
            gh_pr_list_response=json.dumps([{
                "number": 7, "state": "MERGED", "url": "https://x/7",
            }]),
        )
        cfg = d.Config(allowlist={"dolios": repo_path}, base_branch="main",
                       branch_prefix="auto/coder",
                       budget=d.Budget(ledger_path=os.path.join(tmp, "l.jsonl")))
        runners = d.Runners(gate_decide=lambda: {"decision": "dispatch", "reason": "ok"},
                            git=repo.git, claude=repo.claude, gh=repo.gh,
                            now=lambda: 1.0)
        disp = d.Dispatcher(cfg, runners)
        msg = _expect_guardrail(lambda: disp.dispatch(
            "dolios", "dolios-p1-chunk-1", "x",
            proposal_path="proposals/dolios/p1.md", chunk_index=1,
        ))
        assert "MERGED" in msg
        assert not repo.claude_ran


def test_chunk_mode_no_changes_from_claude_aborts_before_flipping_the_box():
    """If claude makes zero changes (denied permissions, refused, errored),
    the dispatcher must NOT flip the chunk checkbox — would otherwise advance
    state on `main` without an implementation. Loud, no commit, no PR."""
    with tempfile.TemporaryDirectory() as tmp:
        repo_path, md = _write_proposal(tmp, "proposals/dolios/p1.md")
        repo = FakeRepoWithProposal(repo_path, claude_changes=False)
        cfg = d.Config(allowlist={"dolios": repo_path}, base_branch="main",
                       branch_prefix="auto/coder",
                       budget=d.Budget(ledger_path=os.path.join(tmp, "l.jsonl")))
        runners = d.Runners(gate_decide=lambda: {"decision": "dispatch", "reason": "ok"},
                            git=repo.git, claude=repo.claude, gh=repo.gh,
                            now=lambda: 1.0)
        disp = d.Dispatcher(cfg, runners)
        msg = _expect_guardrail(lambda: disp.dispatch(
            "dolios", "dolios-p1-chunk-1", "x",
            proposal_path="proposals/dolios/p1.md", chunk_index=1,
        ))
        assert "no changes" in msg.lower()
        # claude WAS run (we discovered the no-changes case after, not before)
        assert repo.claude_ran
        # Box must NOT be flipped; commit must NOT exist.
        with open(md) as fh:
            body = fh.read()
        assert "- [ ] **Chunk 1**" in body
        assert not repo.committed and not repo.pushed


def test_chunk_mode_flip_failure_aborts_after_claude():
    """If the box can't be flipped (e.g. already checked), surface a guardrail
    error AFTER claude — we have no clean "undo" but at least we don't commit
    a half-done state."""
    body = PROPOSAL_BODY.replace("- [ ] **Chunk 1**", "- [x] **Chunk 1**")
    with tempfile.TemporaryDirectory() as tmp:
        repo_path, _ = _write_proposal(tmp, "proposals/dolios/p1.md", body=body)
        repo = FakeRepoWithProposal(repo_path)
        cfg = d.Config(allowlist={"dolios": repo_path}, base_branch="main",
                       branch_prefix="auto/coder",
                       budget=d.Budget(ledger_path=os.path.join(tmp, "l.jsonl")))
        runners = d.Runners(gate_decide=lambda: {"decision": "dispatch", "reason": "ok"},
                            git=repo.git, claude=repo.claude, gh=repo.gh,
                            now=lambda: 1.0)
        disp = d.Dispatcher(cfg, runners)
        msg = _expect_guardrail(lambda: disp.dispatch(
            "dolios", "dolios-p1-chunk-1", "x",
            proposal_path="proposals/dolios/p1.md", chunk_index=1,
        ))
        assert "already checked" in msg
        # claude DID run (flip happens after) — that's the documented behavior;
        # the loud failure prevents the implementation commit from landing
        # without the state-change diff.
        assert repo.claude_ran


# --------------------------------------------------------------------------- #
# Backwards compat: free-form (non-chunk) dispatches still work
# --------------------------------------------------------------------------- #
def test_no_changes_means_no_pr():
    with tempfile.TemporaryDirectory() as tmp:
        repo = FakeRepo(claude_changes=False)
        _, _, disp = make(tmp, repo)
        rec = disp.dispatch("dolios", "T1", "x")
        assert repo.claude_ran and not repo.committed and not repo.pushed
        assert rec["pr_url"] == "" and not repo.gh_calls


def _run_standalone():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1; print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run_standalone())
