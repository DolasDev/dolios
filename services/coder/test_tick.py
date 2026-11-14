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
        joined = " ".join(str(c) for c in cmd)
        for needle, resp in self.responses.items():
            # Match either as a substring of the joined command (works for
            # multi-word fragments like "pr diff") or as a substring of any
            # individual arg.
            if needle in joined or any(needle in arg for arg in cmd):
                return resp
        return 0, "", ""


def _make(responses: dict, tmp, *, sync_defaults: bool = True) -> t.TickRunner:
    # Keep existing tests oblivious to the sync-before-picker step: provide
    # a clean-ff default (on main, clean tree, fetch + merge succeed). A test
    # that wants to drive a sync failure passes its own overrides — matched
    # first because `responses` is merged ahead of these defaults.
    if sync_defaults:
        # Defaults first so tests can override by reusing the same key;
        # iteration order still finds the shared-key entry at its default
        # slot, but `{**a, **b}` merging lets `responses` win on value.
        responses = {
            "abbrev-ref": (0, "main\n", ""),
            "status --porcelain": (0, "", ""),
            "git fetch": (0, "", ""),
            "ff-only": (0, "", ""),
            "rev-parse HEAD": (0, "deadbeef\n", ""),
            **responses,
        }
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
        # preflight + 5 sync subcommands + picker. No worker call after.
        assert len(tr._runner.calls) == 7


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
    audit_command = (
        "python3 services/auditor/audit.py --repo /repos/dolios --name dolios "
        "--history .dolios/metrics/dolios/history.jsonl"
    )
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
        # (Find the dispatch call by --proposal-path; the reviewer's gh/claude
        # calls also run after the dispatch but don't carry that flag.)
        disp_call = next(c for c in tr._runner.calls if "--proposal-path" in c)
        assert "proposals/dolios/p1.md" in disp_call
        assert "--chunk-index" in disp_call
        assert "2" in disp_call
        # Multi-line instructions pass through Python argv (no shell escaping).
        assert "multi-line\ninstructions\nhere" in disp_call


def test_review_approves_and_queues_auto_merge_after_successful_execute():
    """After execute opens a PR successfully, the reviewer fires; on
    approve, gh pr merge --auto --squash is queued. Tick record carries
    decision + reasoning + review_cost."""
    job = {
        "kind": "execute",
        "repo": "dolios",
        "proposal_id": "dolios/p1",
        "proposal_path": "proposals/dolios/p1.md",
        "chunk_index": 1,
        "task_id": "dolios-p1-chunk-1",
        "instructions": "do it",
        "rationale": "",
    }
    dispatch_response = json.dumps({
        "ok": True,
        "record": {"pr_url": "https://github.com/x/y/pull/42",
                   "cost_usd": 0.6, "chunk_flipped": True,
                   "branch": "auto/coder/dolios-p1-chunk-1"},
    })
    with tempfile.TemporaryDirectory() as tmp:
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "backlog.py":       (0, json.dumps(job), ""),
            "--chunk-index":    (0, dispatch_response, ""),
            # Reviewer responses:
            "pr diff":          (0, "--- a\n+++ b\n+line\n", ""),
            "pr view":          (0, json.dumps({"title": "x"}), ""),
            # claude's review verdict:
            "claude":           (0, json.dumps({
                "result": ('Looks scoped to chunk 1.\n\n'
                           '{"decision": "approve", "reasoning": "scope ok"}'),
                "total_cost_usd": 0.25,
            }), ""),
            "pr merge":         (0, "✓ queued", ""),
        }, tmp)
        record = tr.run_tick()
        assert record["kind"] == "execute"
        assert record["pr_url"] == "https://github.com/x/y/pull/42"
        assert record["review_decision"] == "approve"
        assert record["review_reasoning"] == "scope ok"
        assert record["review_cost_usd"] == 0.25
        assert record["merge_queued"] is True
        # Order matters: the merge call must come AFTER the dispatch
        # AND the review. Match on "pr merge" specifically so the sync's
        # `git merge --ff-only` doesn't shadow this lookup.
        cmds = tr._runner.calls
        merge_idx = next(i for i, c in enumerate(cmds) if "pr merge" in " ".join(c))
        diff_idx  = next(i for i, c in enumerate(cmds) if "pr diff" in " ".join(c))
        assert diff_idx < merge_idx


def _approve_tick(tmp, extra: dict):
    job = {"kind": "execute", "repo": "dolios", "proposal_id": "dolios/p1",
           "proposal_path": "proposals/dolios/p1.md", "chunk_index": 1,
           "task_id": "dolios-p1-chunk-1", "instructions": "do it",
           "rationale": ""}
    dispatch_response = json.dumps({"ok": True, "record": {
        "pr_url": "https://github.com/x/y/pull/42", "cost_usd": 0.6,
        "chunk_flipped": True, "branch": "auto/coder/dolios-p1-chunk-1"}})
    responses = {
        "--preflight-only": _preflight_ok(),
        "backlog.py":       (0, json.dumps(job), ""),
        "--chunk-index":    (0, dispatch_response, ""),
        **extra,  # earlier keys win in FakeRunner, so overrides go first below
        "pr diff":          (0, "--- a\n+++ b\n+line\n", ""),
        "pr view":          (0, json.dumps({"title": "x"}), ""),
        "claude":           (0, json.dumps({
            "result": '{"decision": "approve", "reasoning": "scope ok"}',
            "total_cost_usd": 0.25}), ""),
        "pr merge":         (0, "queued", ""),
        "pr comment":       (0, "", ""),
    }
    tr = _make(responses, tmp)
    return tr, tr.run_tick()


def test_approved_pr_touching_protected_paths_is_held_for_a_human():
    with tempfile.TemporaryDirectory() as tmp:
        tr, record = _approve_tick(tmp, {
            "--name-only": (0, "services/coder/tick.py\ndocs/x.md\n", ""),
        })
        assert record["review_decision"] == "approve"
        assert record["merge_held"] == ["services/coder/tick.py"]
        assert "merge_queued" not in record
        cmds = [" ".join(c) for c in tr._runner.calls]
        assert not any("pr merge" in c for c in cmds)
        comment = next(c for c in cmds if "pr comment" in c)
        assert "services/coder/tick.py" in comment and "human merge" in comment


def test_unlistable_pr_files_fail_closed():
    with tempfile.TemporaryDirectory() as tmp:
        tr, record = _approve_tick(tmp, {"--name-only": (1, "", "gh: boom")})
        assert record["merge_held"] == ["<could not list PR files>"]
        assert not any("pr merge" in " ".join(c) for c in tr._runner.calls)


def test_approved_pr_outside_protected_paths_still_auto_merges():
    with tempfile.TemporaryDirectory() as tmp:
        tr, record = _approve_tick(tmp, {
            "--name-only": (0, "services/auditor/ci_api.py\n"
                               "infra/hermes/memories/0005-x.md\n", ""),
        })
        assert record.get("merge_queued") is True
        assert "merge_held" not in record


def test_review_rejects_and_closes_pr_with_reasoning_comment():
    """Reject path: the PR gets closed via gh, with the reviewer's
    reasoning posted as a comment. No auto-merge call."""
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
        "ok": True,
        "record": {"pr_url": "https://github.com/x/y/pull/9",
                   "cost_usd": 0.4, "chunk_flipped": True,
                   "branch": "auto/coder/dolios-p1-chunk-1"},
    })
    with tempfile.TemporaryDirectory() as tmp:
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "backlog.py":       (0, json.dumps(job), ""),
            "--chunk-index":    (0, dispatch_response, ""),
            "pr diff":          (0, "diff", ""),
            "pr view":          (0, "{}", ""),
            "claude":           (0, json.dumps({
                "result": ('{"decision": "reject", "reasoning": '
                           '"touches main.py outside chunk scope"}'),
                "total_cost_usd": 0.2,
            }), ""),
            "pr close":         (0, "✓ closed", ""),
        }, tmp)
        record = tr.run_tick()
        assert record["review_decision"] == "reject"
        assert record["pr_closed"] is True
        close_cmd = next(c for c in tr._runner.calls if "pr close" in " ".join(c))
        # The reasoning is included in the close comment.
        assert any("touches main.py" in arg for arg in close_cmd)
        # No `gh pr merge` call (the reviewer's prompt text mentions "merge",
        # so substring-matching is too loose — check the gh command shape).
        assert not any(c[:3] == ["gh", "pr", "merge"]
                       for c in tr._runner.calls)


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
def test_propose_kind_dispatches_with_context_loaded():
    """Propose path: load gap from audit history, compose rich instructions
    with memories + outcomes context, dispatch via dispatch.py free-form
    mode. The instructions string passed to dispatch must carry the gap_id,
    the audit ref, and any memories on disk."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Seed a minimal audit history with the gap the picker will reference.
        (root / ".dolios" / "metrics" / "dolios").mkdir(parents=True)
        (root / ".dolios" / "metrics" / "dolios" / "history.jsonl").write_text(
            json.dumps({
                "schema_version": 1,
                "audited_at": "2026-06-01T12:00:00Z",
                "repo": "dolios",
                "gaps": [{
                    "area": "supply_chain", "severity": "medium",
                    "gap_id": "supply_chain-abc123",
                    "summary": "No dependency-update tool configured",
                    "frameworks": ["DORA: Shift-left security"],
                    "proposed_action": "Enable Dependabot",
                }],
            }) + "\n"
        )
        # Seed a memory so we can assert it gets injected into the prompt.
        (root / "infra" / "hermes" / "memories").mkdir(parents=True)
        (root / "infra" / "hermes" / "memories" / "0001-test-lesson.md").write_text(
            "# Test lesson\n\nDispatcher must always flip the box itself.\n"
        )

        # Required for the dispatch.py invocation; we just match on the flag.
        dispatch_response = json.dumps({
            "ok": True,
            "record": {
                "pr_url": "https://example/pr/42",
                "cost_usd": 2.5,
                "branch": "auto/coder/propose-supply_chain-abc123",
            },
        })
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "backlog.py":       (0, json.dumps({
                "kind": "propose",
                "repo": "dolios",
                "gap_id": "supply_chain-abc123",
                "gap_summary": "No dependency-update tool configured",
                "gap_severity": "medium",
                "frameworks": ["DORA: Shift-left security"],
                "rationale": "open gap",
            }), ""),
            "propose-supply_chain-abc123": (0, dispatch_response, ""),
        }, tmp)
        record = tr.run_tick()
        assert record["kind"] == "propose"
        assert record["dispatch_rc"] == 0
        assert record["pr_url"] == "https://example/pr/42"
        assert record["task_id"] == "propose-supply_chain-abc123"
        # Inspect the dispatch invocation — assert the propose prompt
        # got the gap details + memory body + audit-line citation.
        disp_call = tr._runner.calls[-1]
        assert "--task" in disp_call
        # The instructions arg is right after --instructions.
        inst_arg = disp_call[disp_call.index("--instructions") + 1]
        assert "supply_chain-abc123" in inst_arg
        assert "No dependency-update tool configured" in inst_arg
        assert "Enable Dependabot" in inst_arg          # auditor's proposed_action
        assert "Dispatcher must always flip the box itself." in inst_arg   # memory
        assert "history.jsonl#L1@2026-06-01T12:00:00Z" in inst_arg          # audit ref


def test_propose_with_missing_audit_history_records_error_cleanly():
    """If a repo has never been audited, the propose path can't form a
    citation. It must NOT crash — record an error and exit."""
    with tempfile.TemporaryDirectory() as tmp:
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "backlog.py":       (0, json.dumps({
                "kind": "propose",
                "repo": "freshrepo",
                "gap_id": "ci-xyz",
                "rationale": "open gap",
            }), ""),
        }, tmp)
        record = tr.run_tick()
        assert record["kind"] == "propose"
        assert "no audit history" in record["error"].lower()
        # No dispatch call should have happened.
        assert not any("--task" in c for c in tr._runner.calls)


def test_remeasure_kind_dispatches_with_pre_audit_ref_from_proposal_frontmatter():
    """The remeasure handler reads the proposal's `audit:` frontmatter field
    to recover the pre-measurement citation, composes the remeasure prompt
    around it, and dispatches in free-form mode with a deterministic
    `remeasure-<proposal-id>` task_id."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Seed an approved proposal with all chunks `[x]` and a baseline
        # audit citation.
        (root / "proposals" / "dolios").mkdir(parents=True)
        (root / "proposals" / "dolios" / "p1.md").write_text(
            "---\n"
            "id:     dolios/p1\n"
            "status: approved\n"
            "repo:   dolios\n"
            "audit:  .dolios/metrics/dolios/history.jsonl#L2@2026-05-28T21:17:28Z\n"
            "---\n\n"
            "## Intervention\n\n"
            "- [x] **Chunk 1**\n"
            "- [x] **Chunk 2**\n"
        )
        dispatch_response = json.dumps({
            "ok": True,
            "record": {
                "pr_url": "https://example/pr/9",
                "cost_usd": 1.5,
                "branch": "auto/coder/remeasure-dolios-p1",
            },
        })
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "backlog.py":       (0, json.dumps({
                "kind": "remeasure",
                "repo": "dolios",
                "proposal_id": "dolios/p1",
                "proposal_path": "proposals/dolios/p1.md",
                "rationale": "all chunks done",
            }), ""),
            "remeasure-dolios-p1": (0, dispatch_response, ""),
        }, tmp)
        record = tr.run_tick()
        assert record["kind"] == "remeasure"
        assert record["dispatch_rc"] == 0
        assert record["pr_url"] == "https://example/pr/9"
        assert record["task_id"] == "remeasure-dolios-p1"
        # Inspect the dispatched instructions — must carry pre-audit ref +
        # the audit-command claude will run for the post measurement.
        disp_call = tr._runner.calls[-1]
        inst_arg = disp_call[disp_call.index("--instructions") + 1]
        assert "L2@2026-05-28T21:17:28Z" in inst_arg   # pre-audit ref
        assert "services/auditor/audit.py" in inst_arg # post-audit command
        assert "proposals/dolios/p1.md" in inst_arg
        assert "approved" in inst_arg                  # status flip mentioned


def test_reflect_kind_dispatches_with_lookback_prompt():
    """Reflect handler dispatches via dispatch.py free-form mode against
    dolios with a date-stamped task_id; instructions reference reading
    tick-log, ledger, and closed proposals."""
    with tempfile.TemporaryDirectory() as tmp:
        dispatch_response = json.dumps({
            "ok": True,
            "record": {
                "pr_url": "https://example/pr/77",
                "cost_usd": 1.8,
                "branch": "auto/coder/reflect-2026-06-01",
            },
        })
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "backlog.py":       (0, json.dumps({
                "kind": "reflect",
                "rationale": "no kind=reflect tick in the last 7 days; "
                             "distill one memory",
            }), ""),
            "reflect-": (0, dispatch_response, ""),
        }, tmp)
        record = tr.run_tick()
        assert record["kind"] == "reflect"
        assert record["dispatch_rc"] == 0
        assert record["pr_url"] == "https://example/pr/77"
        # task_id is date-stamped — won't match the hardcoded fixture date
        # exactly since _make uses fixed `now`, but it has the prefix.
        assert record["task_id"].startswith("reflect-")
        disp_call = tr._runner.calls[-1]
        inst_arg = disp_call[disp_call.index("--instructions") + 1]
        # Reflect prompt references all four reading sources.
        for needle in (".dolios/tick-log.jsonl", "services/coder/.ledger.jsonl",
                       "proposals/", ".dolios/metrics/"):
            assert needle in inst_arg, f"reflect prompt missing: {needle!r}"


def test_remeasure_with_missing_proposal_records_error_cleanly():
    with tempfile.TemporaryDirectory() as tmp:
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "backlog.py":       (0, json.dumps({
                "kind": "remeasure",
                "repo": "dolios",
                "proposal_id": "dolios/missing",
                "proposal_path": "proposals/dolios/missing.md",
                "rationale": "all chunks done",
            }), ""),
        }, tmp)
        record = tr.run_tick()
        assert record["kind"] == "remeasure"
        assert "proposal not found" in record["error"]
        # No dispatch call should have happened.
        assert not any("remeasure-" in str(c) for c in tr._runner.calls)


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
# Sync-to-base — runs between preflight and picker
# --------------------------------------------------------------------------- #
def test_sync_clean_ff_records_synced_to_and_proceeds_to_picker():
    """Happy path: HEAD is main, tree is clean, fetch + ff-merge succeed.
    The tick records `synced_to`, moves on to the picker, and ends clean."""
    with tempfile.TemporaryDirectory() as tmp:
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "rev-parse HEAD":   (0, "cafef00d\n", ""),
            "backlog.py":       (0, json.dumps({
                "kind": "empty", "rationale": "nothing to do",
            }), ""),
        }, tmp)
        record = tr.run_tick()
        assert record["kind"] == "empty"
        assert record["synced_to"] == "cafef00d"
        # Sync must happen BEFORE the picker.
        cmds = [" ".join(str(x) for x in c) for c in tr._runner.calls]
        merge_idx = next(i for i, c in enumerate(cmds) if "merge --ff-only" in c)
        picker_idx = next(i for i, c in enumerate(cmds) if "backlog.py" in c)
        assert merge_idx < picker_idx


def test_sync_not_on_main_short_circuits_with_sync_error():
    """HEAD on a stray branch → sync_error, picker never runs."""
    with tempfile.TemporaryDirectory() as tmp:
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "abbrev-ref":       (0, "auto/coder/stray-branch\n", ""),
            "backlog.py":       (0, json.dumps({"kind": "empty"}), ""),
        }, tmp)
        record = tr.run_tick()
        assert record["kind"] == "sync_error"
        assert "auto/coder/stray-branch" in record["error"]
        assert "main" in record["error"]
        assert not any("backlog.py" in " ".join(c) for c in tr._runner.calls)
        assert not any("merge --ff-only" in " ".join(c) for c in tr._runner.calls)


def test_sync_foreign_dirt_short_circuits_with_sync_error():
    """Any dirty path outside `.dolios/metrics/` blocks the sync."""
    with tempfile.TemporaryDirectory() as tmp:
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "status --porcelain": (0, " M services/coder/tick.py\n", ""),
            "backlog.py":       (0, json.dumps({"kind": "empty"}), ""),
        }, tmp)
        record = tr.run_tick()
        assert record["kind"] == "sync_error"
        assert "services/coder/tick.py" in record["error"]
        assert not any("backlog.py" in " ".join(c) for c in tr._runner.calls)
        assert not any("merge --ff-only" in " ".join(c) for c in tr._runner.calls)


def test_sync_fetch_failure_short_circuits_with_sync_error():
    """A failed `git fetch` is a fail-stop: the picker never runs."""
    with tempfile.TemporaryDirectory() as tmp:
        tr = _make({
            "--preflight-only": _preflight_ok(),
            "git fetch":        (1, "", "fatal: unable to access 'origin'"),
            "backlog.py":       (0, json.dumps({"kind": "empty"}), ""),
        }, tmp)
        record = tr.run_tick()
        assert record["kind"] == "sync_error"
        assert "fetch" in record["error"]
        assert "fatal: unable to access" in record["error"]
        assert not any("backlog.py" in " ".join(c) for c in tr._runner.calls)
        assert not any("merge --ff-only" in " ".join(c) for c in tr._runner.calls)


def test_sync_preserves_pending_audit_rows_across_ff():
    """Dirty `.dolios/metrics/<repo>/history.jsonl` rows survive the sync:
    the file is reset, ff-merged, and the local rows (by `audited_at`) that
    aren't in the merged file are re-appended in order."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        metrics_dir = root / ".dolios" / "metrics" / "dolios"
        metrics_dir.mkdir(parents=True)
        history = metrics_dir / "history.jsonl"
        # Pending local state: one row already shared with origin, two new.
        shared = {"audited_at": "2026-06-01T00:00:00Z", "repo": "dolios", "n": 1}
        new_a  = {"audited_at": "2026-06-02T00:00:00Z", "repo": "dolios", "n": 2}
        new_b  = {"audited_at": "2026-06-03T00:00:00Z", "repo": "dolios", "n": 3}
        history.write_text(
            json.dumps(shared) + "\n"
            + json.dumps(new_a) + "\n"
            + json.dumps(new_b) + "\n"
        )

        # Fake a `git checkout --` that resets the file to the version in
        # the merged tree: just `shared` is present. Our runner can't shell
        # out, so simulate the checkout by writing the "HEAD" version.
        class _CheckoutRunner(FakeRunner):
            def __call__(self, cmd, cwd):
                self.calls.append(cmd)
                joined = " ".join(str(c) for c in cmd)
                if "checkout" in cmd and "--" in cmd:
                    # Any `git checkout -- <rel>` within the dolios root resets
                    # the file to its HEAD version (here: just the shared row).
                    rel = cmd[cmd.index("--") + 1]
                    (Path(cwd) / rel).write_text(json.dumps(shared) + "\n")
                    return 0, "", ""
                for needle, resp in self.responses.items():
                    if needle in joined or any(needle in arg for arg in cmd):
                        return resp
                return 0, "", ""

        responses = {
            "--preflight-only": _preflight_ok(),
            "abbrev-ref":       (0, "main\n", ""),
            "status --porcelain": (0, " M .dolios/metrics/dolios/history.jsonl\n", ""),
            "git fetch":        (0, "", ""),
            "ff-only":          (0, "", ""),
            "rev-parse HEAD":   (0, "newhead\n", ""),
            "backlog.py":       (0, json.dumps({"kind": "empty"}), ""),
        }
        tr = t.TickRunner(
            root=root,
            runner=_CheckoutRunner(responses),
            log_path=root / "tick-log.jsonl",
            now=lambda: 1_700_000_000.0,
        )
        record = tr.run_tick()
        assert record["kind"] == "empty"
        assert record["synced_to"] == "newhead"

        # All three rows are back, in local order; `shared` appears exactly
        # once (we skipped it on re-append because the merged file already had
        # it).
        rows = [json.loads(line) for line in history.read_text().splitlines()
                if line.strip()]
        assert rows == [shared, new_a, new_b]


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
