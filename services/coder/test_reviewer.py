#!/usr/bin/env python3
"""Tests for the auto-PR reviewer.

The reviewer's job is to issue a structured decision per PR; tests inject a
fake `runner` so we can verify the decision-extraction logic and the right
gh / claude commands are issued for each path (approve → enable_auto_merge,
reject → close_pr, abstain → no-op).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import reviewer as r


# --------------------------------------------------------------------------- #
# Fake runner: maps a matcher → (rc, stdout, stderr)
# --------------------------------------------------------------------------- #
class FakeRunner:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, cmd, cwd):
        self.calls.append(cmd)
        joined = " ".join(cmd)
        for matcher, resp in self.responses.items():
            if matcher in joined:
                return resp
        return 0, "", ""


PR_URL = "https://github.com/DolasDev/dolios/pull/42"


def _claude_response(decision: str, reasoning: str = "looks good", cost: float = 1.0,
                     wrap: bool = True) -> str:
    """Wrap a JSON decision in claude's --output-format json shape."""
    inner_text = (
        "Here's my analysis.\n\n"
        "The diff looks clean and well-scoped.\n\n"
        f'{{"decision": "{decision}", "reasoning": "{reasoning}"}}'
    )
    if not wrap:
        return inner_text
    return json.dumps({"result": inner_text, "total_cost_usd": cost})


# --------------------------------------------------------------------------- #
# review_pr — happy paths
# --------------------------------------------------------------------------- #
def test_review_returns_approve_with_cost_and_reasoning():
    runner = FakeRunner({
        "pr diff":  (0, "--- a/x\n+++ b/x\n+ok\n", ""),
        "pr view":  (0, json.dumps({"title": "auto-coder: chunk-1",
                                    "body": "implements chunk 1",
                                    "headRefName": "auto/coder/x",
                                    "additions": 1, "deletions": 0}), ""),
        "claude":   (0, _claude_response("approve", "scope ok", cost=0.7), ""),
    })
    out = r.review_pr(PR_URL, Path("/tmp"), runner=runner)
    assert out["decision"] == "approve"
    assert out["reasoning"] == "scope ok"
    assert out["cost_usd"] == 0.7
    assert out["pr_number"] == "42"


def test_review_returns_reject_with_reasoning():
    runner = FakeRunner({
        "pr diff":  (0, "diff body", ""),
        "pr view":  (0, "{}", ""),
        "claude":   (0, _claude_response("reject", "destructive operation", cost=0.5), ""),
    })
    out = r.review_pr(PR_URL, Path("/tmp"), runner=runner)
    assert out["decision"] == "reject"
    assert out["reasoning"] == "destructive operation"


# --------------------------------------------------------------------------- #
# review_pr — failure modes that must abstain (not crash, not erroneously approve)
# --------------------------------------------------------------------------- #
def test_review_abstains_when_pr_url_has_no_number():
    out = r.review_pr("https://example.com/no-pr-here", Path("/tmp"),
                       runner=FakeRunner({}))
    assert out["decision"] == "abstain"
    assert "parse PR number" in out["reasoning"]


def test_review_abstains_when_gh_diff_fails():
    runner = FakeRunner({
        "pr diff":  (1, "", "gh: API rate limit"),
    })
    out = r.review_pr(PR_URL, Path("/tmp"), runner=runner)
    assert out["decision"] == "abstain"
    assert "gh pr diff" in out["reasoning"]


def test_review_abstains_when_claude_returns_non_json():
    runner = FakeRunner({
        "pr diff":  (0, "diff", ""),
        "pr view":  (0, "{}", ""),
        "claude":   (0, "not json at all", ""),
    })
    out = r.review_pr(PR_URL, Path("/tmp"), runner=runner)
    assert out["decision"] == "abstain"
    assert "not JSON" in out["reasoning"]


def test_review_abstains_when_decision_json_missing_from_claude_text():
    """claude returned valid JSON envelope but no decision-shaped line inside."""
    runner = FakeRunner({
        "pr diff":  (0, "diff", ""),
        "pr view":  (0, "{}", ""),
        "claude":   (0, json.dumps({"result": "I think it's fine, but I'll stop here.",
                                    "total_cost_usd": 0.3}), ""),
    })
    out = r.review_pr(PR_URL, Path("/tmp"), runner=runner)
    assert out["decision"] == "abstain"
    assert out["cost_usd"] == 0.3   # cost still recorded even on abstain


# --------------------------------------------------------------------------- #
# Decision extraction edge cases
# --------------------------------------------------------------------------- #
def test_decision_extraction_picks_last_json_block():
    """claude often emits sample/example JSON earlier in its reasoning; the
    extractor must pick the FINAL decision block, not a prior example."""
    text = """\
Maybe the right shape is {"decision": "approve", "reasoning": "EXAMPLE"} — but the actual review:

The diff looks good.

{"decision": "request_changes", "reasoning": "real one"}
"""
    out = r._extract_decision_json(text)
    assert out["decision"] == "request_changes"
    assert out["reasoning"] == "real one"


def test_decision_extraction_returns_none_when_no_match():
    assert r._extract_decision_json("no decision json here") is None


# --------------------------------------------------------------------------- #
# enable_auto_merge / close_pr — gh wrappers
# --------------------------------------------------------------------------- #
def test_enable_auto_merge_invokes_gh_with_auto_squash():
    runner = FakeRunner({"pr merge": (0, "✓ Pull request will be automatically merged", "")})
    out = r.enable_auto_merge(PR_URL, Path("/tmp"), runner=runner)
    assert out["ok"] is True and out["queued"] is True
    cmd = runner.calls[-1]
    assert cmd[:4] == ["gh", "pr", "merge", "42"]
    assert "--auto" in cmd and "--squash" in cmd


def test_enable_auto_merge_returns_error_on_gh_failure():
    runner = FakeRunner({"pr merge": (1, "", "auto-merge is not enabled for this repo")})
    out = r.enable_auto_merge(PR_URL, Path("/tmp"), runner=runner)
    assert out["ok"] is False
    assert "auto-merge is not enabled" in out["error"]


def test_close_pr_posts_comment_and_closes():
    runner = FakeRunner({"pr close": (0, "✓ Closed pull request", "")})
    out = r.close_pr(PR_URL, Path("/tmp"), "rejected: destructive op",
                     runner=runner)
    assert out["ok"] is True and out["closed"] is True
    cmd = runner.calls[-1]
    assert cmd[:4] == ["gh", "pr", "close", "42"]
    assert "--comment" in cmd
    assert "rejected: destructive op" in cmd


# --------------------------------------------------------------------------- #
# pr_number_from_url
# --------------------------------------------------------------------------- #
def test_pr_number_from_url():
    assert r._pr_number_from_url("https://github.com/x/y/pull/7") == "7"
    assert r._pr_number_from_url(None) is None
    assert r._pr_number_from_url("https://no-pr") is None


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
