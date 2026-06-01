#!/usr/bin/env python3
"""Prompt composition for the agent-driven dispatch kinds.

`tick.py`'s propose / remeasure / reflect paths each need to compose a rich
instructions string that gets passed to `dispatch.py` in free-form mode.
Centralizing the prompt engineering here keeps the picker's prompt design
out of the orchestration code, and out of model judgment — the prompts are
just deterministic string assembly over versioned context files in
`infra/hermes/memories/`, `infra/hermes/skills/`, and `proposals/<repo>/*.md`.

No model is invoked from this module. It returns strings.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

MEMORIES_DIR = "infra/hermes/memories"
SKILLS_DIR = "infra/hermes/skills"


# --------------------------------------------------------------------------- #
# Context loaders — read versioned learning artifacts off disk
# --------------------------------------------------------------------------- #
def read_memories(root: Path) -> str:
    """Concatenate every `.md` in `<root>/infra/hermes/memories/` (except
    README) into a single labelled block. Returns "" if no memories.

    The propose / remeasure / reflect prompts always include this — every
    dispatch sees every memory. Sized to stay small enough not to dominate
    the prompt; if memories ever get noisy, the right move is to consolidate
    or prune them via a follow-up reflect dispatch, not filter here."""
    mem_dir = root / MEMORIES_DIR
    if not mem_dir.is_dir():
        return ""
    pieces = []
    for path in sorted(mem_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        body = path.read_text(encoding="utf-8")
        pieces.append(f"### From `{path.relative_to(root)}`\n\n{body.strip()}")
    if not pieces:
        return ""
    return "\n\n---\n\n".join(pieces)


def read_skills(root: Path, slugs: Iterable[str]) -> str:
    """Inline the `SKILL.md` content of the named skills. Skills that don't
    exist are silently skipped (no skill > wrong skill). Returns "" if none
    found — keeps the prompt clean during the early period when no custom
    skills have been authored yet."""
    skill_dir = root / SKILLS_DIR
    pieces = []
    for slug in slugs:
        path = skill_dir / slug / "SKILL.md"
        if path.is_file():
            body = path.read_text(encoding="utf-8")
            pieces.append(f"### Skill `{slug}`\n\n{body.strip()}")
    return "\n\n---\n\n".join(pieces) if pieces else ""


def read_recent_outcomes(root: Path, repo: str, limit: int = 5) -> str:
    """For each of the most recent up-to-`limit` proposals in
    `proposals/<repo>/` with `status: done` in frontmatter, extract their
    `## Outcome` section. These are the explicit "we tried X, it moved
    metric M from A to B" learnings — the single richest source of feedback
    the loop produces, and the natural prior for new proposals on the same
    repo."""
    repo_proposals = root / "proposals" / repo
    if not repo_proposals.is_dir():
        return ""
    pieces: list[str] = []
    # Filenames begin with YYYY-MM-DD; sorting descending gives newest first.
    for path in sorted(repo_proposals.glob("*.md"), reverse=True):
        if path.name.startswith("_"):
            continue
        if len(pieces) >= limit:
            break
        text = path.read_text(encoding="utf-8")
        if not _has_done_status(text):
            continue
        outcome = _extract_section(text, "Outcome")
        if outcome and outcome.strip():
            pieces.append(
                f"### Closed proposal: `{path.relative_to(root)}`\n\n"
                f"{outcome.strip()}"
            )
    return "\n\n---\n\n".join(pieces) if pieces else ""


def _has_done_status(markdown_text: str) -> bool:
    """True if YAML frontmatter has `status: done`."""
    if not markdown_text.startswith("---\n"):
        return False
    end = markdown_text.find("\n---\n", 4)
    if end == -1:
        return False
    frontmatter = markdown_text[4:end]
    return bool(re.search(r"^status:\s*done\s*$", frontmatter, re.MULTILINE))


def _extract_section(markdown_text: str, heading: str) -> str | None:
    """Body of `## <heading>` up to the next `## ` heading or EOF.
    Mirrors `chunks._extract_section` deliberately — same semantics."""
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    m = pattern.search(markdown_text)
    if not m:
        return None
    start = m.end()
    next_h = re.search(r"^##\s+", markdown_text[start:], re.MULTILINE)
    end = start + next_h.start() if next_h else len(markdown_text)
    return markdown_text[start:end]


def find_gap(audit_row: dict, gap_id: str) -> dict | None:
    """Look up a gap by `gap_id` in the audit row's `gaps` list."""
    for g in audit_row.get("gaps", []) or []:
        if g.get("gap_id") == gap_id:
            return g
    return None


# --------------------------------------------------------------------------- #
# Prompt composers — one per dispatch kind
# --------------------------------------------------------------------------- #
def compose_propose_instructions(
    *,
    root: Path,
    repo: str,
    gap: dict,
    audit_ref: str,
    today: str,
) -> str:
    """Instructions for a `kind=propose` dispatch. Free-form mode (no chunk
    args). Claude reads this, the template, the audit row, the memories,
    and writes a single new proposal file."""
    memories = read_memories(root) or "(no prior learnings on file yet)"
    outcomes = read_recent_outcomes(root, repo) or "(no closed proposals on this repo yet)"
    # Pull in any dolios-specific authoring skills if they exist; first one
    # is intentionally aspirational (will exist after the agent's first
    # self-improvement pass).
    skills = read_skills(root, ["dolios-proposal-conventions"]) or "(no custom dolios skills yet — read proposals/_template.md as the source of truth)"

    return _PROPOSE_TEMPLATE.format(
        repo=repo,
        gap_id=gap.get("gap_id", "?"),
        gap_area=gap.get("area", "?"),
        gap_summary=gap.get("summary", "?"),
        gap_severity=gap.get("severity", "?"),
        gap_frameworks=", ".join(gap.get("frameworks") or []),
        gap_proposed_action=gap.get("proposed_action", ""),
        audit_ref=audit_ref,
        today=today,
        memories_block=memories,
        outcomes_block=outcomes,
        skills_block=skills,
    )


def compose_remeasure_instructions(
    *,
    root: Path,
    repo: str,
    proposal_path: str,
    pre_audit_ref: str,
    post_audit_ref: str,
    today: str,
) -> str:
    """Instructions for a `kind=remeasure` dispatch. Free-form mode. Claude
    reads the proposal, reads the pre/post audit rows, writes the Outcome
    section, and flips `status: approved → done` + sets the `done:` date in
    frontmatter. The dispatcher commits + pushes + opens the closing PR."""
    memories = read_memories(root) or "(no prior learnings on file yet)"
    return _REMEASURE_TEMPLATE.format(
        repo=repo,
        proposal_path=proposal_path,
        pre_audit_ref=pre_audit_ref,
        post_audit_ref=post_audit_ref,
        today=today,
        memories_block=memories,
    )


def compose_reflect_instructions(
    *,
    root: Path,
    days: int,
    today: str,
) -> str:
    """Instructions for a `kind=reflect` dispatch. Free-form mode. Claude
    reads the tick-log + ledger + closed proposals over the lookback window,
    distills cross-cutting patterns, and writes one new memory file
    summarizing the most important learning. The dispatcher commits + opens
    the PR."""
    memories = read_memories(root) or "(no prior learnings yet — this may be the first reflect)"
    return _REFLECT_TEMPLATE.format(
        days=days, today=today, memories_block=memories,
    )


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #
_PROPOSE_TEMPLATE = """\
You are the autonomous-coder for the Dolios fleet, executing a kind=propose
dispatch on repo `{repo}`. The picker identified an uncovered gap and asked
you to draft a proposal for it.

# Hard rules — read carefully

- Write EXACTLY ONE proposal file at `proposals/{repo}/{today}-<slug>.md`.
  Slug is short, kebab-case, descriptive (e.g. "adopt-osv-scanner").
- Follow `proposals/_template.md` EXACTLY: same sections in the same order,
  YAML frontmatter at the top.
- Cite the exact `gap_id` `{gap_id}` in the proposal's `gap_ids:` frontmatter
  list.
- Do NOT modify any existing file. You MAY write at most ONE new memory at
  `infra/hermes/memories/NNNN-<slug>.md` (next unused NNNN), but only if
  writing this proposal surfaced a distilled lesson worth keeping — a
  tooling pitfall, a recurring pattern, an estimation correction. If nothing
  rises to that level, do not write a memory.
- Do NOT commit, push, or run git. The dispatcher handles version control.
- Do NOT run any other commands; just read + write the files described.

# The gap you are addressing

- gap_id:     `{gap_id}`
- area:       `{gap_area}`
- summary:    {gap_summary}
- severity:   {gap_severity}
- frameworks: {gap_frameworks}
- proposed_action (auditor's hint): {gap_proposed_action}

# Audit citation

Cite this in the proposal's `audit:` frontmatter and in the Audit citation
section: `{audit_ref}`

# Prior learnings — read these, they shape what kind of proposal lands cleanly

{memories_block}

# Recent closed-proposal outcomes for this repo — read these, they're the
# explicit "what worked, what didn't" record

{outcomes_block}

# Custom skills

{skills_block}

# Research

Use WebSearch / WebFetch to verify current best-practice tooling. Cite
specific tools, versions, and links in the proposal's Research / prior art
section.

# Required frontmatter shape

```yaml
id:     {repo}/{today}-<your-slug>
status: proposed
repo:   {repo}
audit:  {audit_ref}
gap_ids:
  - {gap_id}
metrics: [...]
frameworks: [...]
opened:    {today}
approved:  null
done:      null
```

# Output

After writing, print one line: `Proposal written: proposals/{repo}/{today}-<your-slug>.md`
(and if you wrote a memory: `Memory written: infra/hermes/memories/NNNN-<slug>.md`).
"""


_REMEASURE_TEMPLATE = """\
You are the autonomous-coder for the Dolios fleet, executing a kind=remeasure
dispatch. All chunks of an approved proposal have landed; this dispatch
closes the loop by populating its Outcome section and flipping its status.

# Hard rules

- Edit EXACTLY this one file: `{proposal_path}`.
  - Populate the `## Outcome` section per the template's spec (one row per
    `metrics:` frontmatter entry, in the same order, plus any guard metrics).
  - Set `done: {today}` in the YAML frontmatter.
  - Flip `status: approved` to `status: done` in the YAML frontmatter.
- You MAY write at most ONE new memory at `infra/hermes/memories/NNNN-<slug>.md`
  if the comparison surfaced a distilled lesson worth keeping. Otherwise
  don't.
- Do NOT modify any other file. Do NOT commit, push, or run git. The
  dispatcher handles version control.

# The audit rows you must compare

- pre  (the proposal's cited baseline): `{pre_audit_ref}`
- post (the fresh row just appended):   `{post_audit_ref}`

Read both rows. For each metric in the proposal's `metrics:` list, find the
matching value pre and post, compute the delta, fill the Outcome table.

# Prior learnings

{memories_block}

# Output

After writing, print one line: `Outcome populated: {proposal_path}`
(and if you wrote a memory: `Memory written: infra/hermes/memories/NNNN-<slug>.md`).
"""


_REFLECT_TEMPLATE = """\
You are the autonomous-coder for the Dolios fleet, executing a kind=reflect
dispatch. This is the periodic meta-loop: read the loop's own behavior over
the last {days} days and distill ONE new lesson worth keeping.

# Hard rules

- Read these and reason over them:
  - `.dolios/tick-log.jsonl`   — every tick's outcome
  - `services/coder/.ledger.jsonl`  — every dispatch's cost + result
  - `proposals/*/` `*.md`      — closed proposals with their Outcomes
  - `.dolios/metrics/*/history.jsonl` — audit history (trend signal)
- Write EXACTLY ONE new memory at `infra/hermes/memories/NNNN-<slug>.md`
  (next unused NNNN) summarizing the single most useful cross-cutting pattern
  you observed. If nothing rises above noise, write a memory that says exactly
  that — "no novel pattern surfaced this week" with one paragraph of evidence.
  Either way, write exactly one file.
- Format the memory per the README: H1 title, Context paragraph (what data
  it came from), Lesson paragraph (what to remember), Apply-to paragraph
  (under what future conditions this matters).
- Do NOT modify any other file. Do NOT commit, push, or run git. The
  dispatcher handles version control.

# Existing memories — don't duplicate these

{memories_block}

# Output

After writing, print one line: `Memory written: infra/hermes/memories/NNNN-<slug>.md`.
"""
