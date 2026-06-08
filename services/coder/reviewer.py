#!/usr/bin/env python3
"""Auto-PR reviewer for the autonomous-coder.

Dispatches claude headless to review each PR the loop opens and returns a
structured decision. tick.py then either:
  - enables gh's auto-merge (CI-green-gated) on approve
  - closes the PR with reasoning on reject

The reviewer is a *separate* claude dispatch from the one that wrote the PR.
Different prompt, different model session, no shared context — so it's
genuinely an independent check, not the same model rubber-stamping itself.

Costs: ~$0.50–1.50 notional per PR (subscription = $0 real spend). Worth
flagging in the tick record so cost accumulation over a week is visible.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

# Subprocess runner shape; injectable for tests.
Runner = Callable[[list[str], Path], "tuple[int, str, str]"]


def _real_runner(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def review_pr(pr_url: str, repo_path: Path,
              runner: Runner | None = None) -> dict:
    """Fetch a PR's diff + metadata, ask claude for a structured review.

    Returns:
        {
          "decision": "approve" | "request_changes" | "reject" | "abstain",
          "reasoning": str,
          "cost_usd": float,
          "pr_number": str | None,
        }

    `abstain` is for tooling failures (no PR number, gh unreachable, claude
    returned junk) — tick.py treats it as "do nothing, leave the PR open
    for the next reviewer pass / a human".
    """
    runner = runner or _real_runner
    pr_number = _pr_number_from_url(pr_url)
    base = {"decision": "abstain", "reasoning": "", "cost_usd": 0.0,
            "pr_number": pr_number}

    if not pr_number:
        base["reasoning"] = f"could not parse PR number from URL: {pr_url}"
        return base

    # Diff first — that's the actual change to evaluate.
    rc, diff, err = runner(["gh", "pr", "diff", pr_number], repo_path)
    if rc != 0 or not diff.strip():
        base["reasoning"] = f"gh pr diff #{pr_number} failed: {(err or diff)[:200]}"
        return base

    # Metadata for the review prompt — title/body tell claude what the PR
    # purports to do, so it can spot scope drift.
    rc, meta_raw, _ = runner(
        ["gh", "pr", "view", pr_number, "--json",
         "title,body,headRefName,additions,deletions"],
        repo_path,
    )
    try:
        meta = json.loads(meta_raw) if rc == 0 else {}
    except (json.JSONDecodeError, ValueError):
        meta = {}

    prompt = _compose_review_prompt(meta, diff)

    rc, raw, err = runner(
        ["claude", "-p", prompt, "--output-format", "json",
         "--dangerously-skip-permissions"],
        repo_path,
    )
    if rc != 0:
        base["reasoning"] = f"claude reviewer failed (rc={rc}): {(err or raw)[:200]}"
        return base

    try:
        claude_response = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        base["reasoning"] = f"claude response was not JSON: {raw[:200]}"
        return base

    base["cost_usd"] = float(claude_response.get("total_cost_usd", 0.0))
    text = claude_response.get("result", "") or ""

    # The prompt asks claude to end its response with one line of JSON like
    # {"decision": "approve", "reasoning": "..."}. Pull it out leniently.
    decision_json = _extract_decision_json(text)
    if not decision_json:
        base["reasoning"] = (
            f"could not extract decision JSON from claude's response. "
            f"Tail: {text[-300:]}"
        )
        return base

    base["decision"] = decision_json.get("decision", "abstain")
    base["reasoning"] = decision_json.get("reasoning", "")[:1000]
    return base


def enable_auto_merge(pr_url: str, repo_path: Path,
                     runner: Runner | None = None) -> dict:
    """Queue the PR for auto-merge once CI passes. Uses gh's --auto flag,
    which requires branch protection to be configured at the repo level
    (the rule that gates auto-merge on green checks). If branch protection
    isn't set up, this returns an error and tick.py logs it — the PR stays
    open for manual handling."""
    runner = runner or _real_runner
    pr_number = _pr_number_from_url(pr_url)
    if not pr_number:
        return {"ok": False, "error": f"no pr number in {pr_url}"}
    rc, out, err = runner(
        ["gh", "pr", "merge", pr_number, "--auto", "--squash"], repo_path,
    )
    if rc != 0:
        return {"ok": False, "error": (err or out).strip()[:300]}
    return {"ok": True, "queued": True}


def close_pr(pr_url: str, repo_path: Path, comment: str,
             runner: Runner | None = None) -> dict:
    """Close a rejected PR with the reviewer's reasoning posted as a
    comment, so the reject is auditable in the PR thread."""
    runner = runner or _real_runner
    pr_number = _pr_number_from_url(pr_url)
    if not pr_number:
        return {"ok": False, "error": f"no pr number in {pr_url}"}
    rc, out, err = runner(
        ["gh", "pr", "close", pr_number, "--comment", comment], repo_path,
    )
    if rc != 0:
        return {"ok": False, "error": (err or out).strip()[:300]}
    return {"ok": True, "closed": True}


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #
def _pr_number_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"/pull/(\d+)", url)
    return m.group(1) if m else None


def _extract_decision_json(text: str) -> dict | None:
    """Find the last `{...}` block in `text` that parses as JSON with a
    `decision` field. Robust to claude's tendency to include explanation
    text around the JSON."""
    # Walk from the end to find balanced braces.
    candidates = []
    depth = 0
    end = -1
    for i in range(len(text) - 1, -1, -1):
        c = text[i]
        if c == "}":
            if depth == 0:
                end = i + 1
            depth += 1
        elif c == "{":
            depth -= 1
            if depth == 0 and end > i:
                candidates.append(text[i:end])
                end = -1
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict) and "decision" in obj:
            return obj
    return None


def _compose_review_prompt(meta: dict, diff: str) -> str:
    """Render the review prompt. Diff is truncated to keep prompt budget
    sane — most chunks are small (<200 lines) and the truncation message
    nudges claude to flag the situation if it does occur."""
    MAX_DIFF_CHARS = 24000
    truncated = ""
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS]
        truncated = (
            "\n\n[diff truncated above this line — original was "
            f"{len(diff)} chars]"
        )
    title = (meta.get("title") or "(no title)")[:200]
    body  = (meta.get("body") or "(no body)")[:2000]
    head  = meta.get("headRefName") or "?"
    return _REVIEW_PROMPT_TEMPLATE.format(
        title=title, body=body, head=head, diff=diff + truncated,
    )


_REVIEW_PROMPT_TEMPLATE = """You are an independent reviewer for a pull request opened autonomously by the Dolios autonomous-coder. Your decision either approves it for auto-merge (gated on CI green) or rejects it (the PR will be closed).

# PR metadata

- Title: {title}
- Branch: {head}

# PR body (what the autonomous-coder claims the PR does)

{body}

# Diff

```
{diff}
```

# Your job

Decide ONE of:

- **approve**: the change is scoped correctly, implements what the title/body claim, has no obvious bugs / security holes / destructive operations, and is safe to merge once CI passes.
- **request_changes**: the change has fixable issues — wrong scope, missing piece, lint problems claude can fix in a follow-up.
- **reject**: the change is wrong, harmful, or fundamentally off-scope. The PR should be closed and re-opened from scratch.

Check carefully for:

1. **Scope discipline** — every changed file maps to something the PR title/body claims to do. If a chunk-mode PR touches files outside its chunk's stated paths, flag it.
2. **Implementation correctness** — does the diff actually do what's described, or does it stub / no-op key bits?
3. **No secrets in the diff** — no API keys, no `GH_TOKEN=…` lines, no `.env` files, no production credentials.
4. **No destructive operations** — `rm -rf`, force-push commands, `DROP TABLE`, etc. Reject decisively.
5. **Atomic state changes** — if this is a chunk-mode execution PR, exactly ONE checkbox in a `## Intervention` section should have flipped `[ ]` → `[x]`, and the rest of that proposal file should be unchanged.

If unsure between approve and request_changes, lean approve only if the worst case is "human will see this and adjust later." Lean request_changes if the worst case is "this breaks main."

# Output

End your response with EXACTLY one line of JSON, on its own line, like this:

{{"decision": "approve", "reasoning": "two-sentence summary"}}

Or:

{{"decision": "reject", "reasoning": "what's wrong and why it can't be salvaged"}}

The JSON line MUST be the last line of your output."""
