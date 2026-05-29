#!/usr/bin/env python3
"""Deterministic priority picker for the autonomous-coder.

Reads coder.yaml's allowlist + the audit history + the proposals/ directory,
emits the next dispatch task as JSON. The supervisor's cron prompt switches on
`kind` and acts mechanically — keeping the picking logic in code rather than
in the 35B's prompt is what makes the loop reliable.

V1 priority order (highest first — finish what you started before opening new fronts):
  1. **audit**     — repo has no audit yet, or last audit > 7d old.
  2. **remeasure** — approved proposal where every Intervention chunk is checked
     off but no Outcome / `done:` date has been appended yet. Re-audit, write
     Outcome, flip status to done. Highest priority because closing a proposal
     unblocks the implementing-cap slot.
  3. **execute**   — approved proposal with at least one unchecked Intervention
     chunk. Picks the FIFO-oldest such proposal (by frontmatter `opened:`).
     Continuing a chunk on an already-implementing proposal is always allowed;
     starting a brand-new approved one is gated on `effective_implementing
     < 3` per repo (the proposals/README.md cap).
  4. **propose**   — repo has an uncovered open gap (`gap_id` not referenced by
     any active proposal). Highest-severity uncovered gap across all repos
     wins; ties broken by repo name → gap area for determinism.
  5. **empty**     — nothing to do this tick.

Chunk state lives in the proposal markdown itself (`- [ ]` / `- [x]` checkboxes
in the `## Intervention` section, parsed by chunks.py). The dispatcher flips
boxes as part of each execution PR's commit, so human review sees the
implementation + box flip in one diff. No sidecar required for V1.

"Effective implementing" — a proposal counts toward the 3-active cap if its
file status is `implementing` (legacy / explicit) OR (status is `approved` AND
at least one chunk is `[x]` but not all). Strict `approved`-with-no-progress
doesn't count; starting work on it is what tips it into implementing.

Usage:
    python3 backlog.py --next                       # JSON to stdout
    python3 backlog.py --next --config <path>       # explicit coder.yaml

Exit codes: 0 on success (even for `kind: empty`); 2 on bad config / missing
deps so the supervisor can shell-branch on `$?`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import chunks as ch

HERE = Path(__file__).resolve().parent
DOLIOS_ROOT = HERE.parent.parent  # services/coder/ → dolios/

# An audit row's `audited_at` older than this is "stale" — the picker schedules
# a fresh audit before reaching for any proposal work on that repo.
STALE_AUDIT_DAYS = 7

# Per-repo cap on proposals in `implementing` state. Matches the rule in
# proposals/README.md ("Hard cap: 3 active per repo").
MAX_IMPLEMENTING_PER_REPO = 3

# Statuses that "cover" a gap — anything still in the work-in-progress arc.
# `done` and `abandoned` do NOT cover; the picker may re-propose if the gap
# resurfaces (e.g. CI added then removed, abandoned → re-propose under new
# rationale).
ACTIVE_PROPOSAL_STATUSES = {"proposed", "approved", "implementing"}

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _now_ts() -> float:
    return time.time()


def _parse_iso(ts: str | None) -> float | None:
    """ISO-8601 (with `Z` suffix) → epoch seconds; None on parse failure."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Frontmatter / history loaders — all take an explicit dolios_root so tests
# can drive them against a temp directory with no real on-disk state.
# --------------------------------------------------------------------------- #
def _parse_frontmatter(path: Path) -> dict | None:
    """Return the YAML frontmatter dict from a markdown file, or None if the
    file has no `---` block at the top."""
    try:
        import yaml
    except ImportError:
        raise RuntimeError("pyyaml is required to parse proposal frontmatter")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    try:
        return yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        return None


def _load_latest_audit_row(repo_name: str, dolios_root: Path) -> dict | None:
    """Latest line of `.dolios/metrics/<repo>/history.jsonl`, or None if no
    history file exists yet (first-audit case)."""
    history = dolios_root / ".dolios" / "metrics" / repo_name / "history.jsonl"
    if not history.exists():
        return None
    last = None
    with history.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                last = json.loads(line)
            except json.JSONDecodeError:
                continue
    return last


def _load_proposals_for_repo(repo_name: str, dolios_root: Path) -> list[dict]:
    """All proposals under `proposals/<repo>/`. Returns the frontmatter dicts,
    each annotated with `_path` (relative to dolios_root) and `_abs_path`
    (absolute, used to load chunk state via chunks.proposal_chunks).
    `_template.md` and any leading-underscore files are skipped."""
    pdir = dolios_root / "proposals" / repo_name
    if not pdir.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(pdir.glob("*.md")):
        if p.name.startswith("_"):
            continue
        fm = _parse_frontmatter(p)
        if fm:
            fm["_path"] = str(p.relative_to(dolios_root))
            fm["_abs_path"] = str(p)
            out.append(fm)
    return out


def _proposal_chunks(fm: dict) -> list[ch.Chunk]:
    """Convenience: load chunks from a proposal frontmatter dict."""
    abs_path = fm.get("_abs_path")
    if not abs_path:
        return []
    return ch.proposal_chunks(Path(abs_path))


def effective_implementing(fm: dict, chunks: list[ch.Chunk]) -> bool:
    """Does this proposal count toward the per-repo 3-active cap?

    Legacy: file `status: implementing` always counts. New convention: status
    `approved` + at least one `[x]` chunk but not all → effectively implementing.
    Approved-with-no-progress does NOT count yet; the first execute tips it in.
    """
    file_status = fm.get("status")
    if file_status == "implementing":
        return True
    if file_status == "approved" and chunks:
        any_done = any(c.done for c in chunks)
        if any_done and not ch.all_chunks_done(chunks):
            return True
    return False


# --------------------------------------------------------------------------- #
# Per-repo backlog assembly
# --------------------------------------------------------------------------- #
@dataclass
class RepoBacklog:
    name: str
    path: Path
    latest_audit_row: dict | None
    last_audit_ts: float | None
    proposals: list[dict] = field(default_factory=list)
    covered_gap_ids: set[str] = field(default_factory=set)
    implementing_count: int = 0

    @property
    def audit_stale(self) -> bool:
        if self.last_audit_ts is None:
            return True
        return _now_ts() - self.last_audit_ts > STALE_AUDIT_DAYS * 86400


def build_repo_backlog(
    repo_name: str, repo_path: Path, *, dolios_root: Path = DOLIOS_ROOT
) -> RepoBacklog:
    row = _load_latest_audit_row(repo_name, dolios_root)
    proposals = _load_proposals_for_repo(repo_name, dolios_root)

    covered: set[str] = set()
    implementing = 0
    for fm in proposals:
        status = fm.get("status")
        if status in ACTIVE_PROPOSAL_STATUSES:
            for gid in fm.get("gap_ids", []) or []:
                covered.add(gid)
        # Effective implementing — file status OR computed-from-chunks.
        if effective_implementing(fm, _proposal_chunks(fm)):
            implementing += 1

    return RepoBacklog(
        name=repo_name,
        path=repo_path,
        latest_audit_row=row,
        last_audit_ts=_parse_iso(row["audited_at"]) if row else None,
        proposals=proposals,
        covered_gap_ids=covered,
        implementing_count=implementing,
    )


# --------------------------------------------------------------------------- #
# The picker
# --------------------------------------------------------------------------- #
def _audit_task(b: RepoBacklog) -> dict:
    return {
        "kind": "audit",
        "repo": b.name,
        "repo_path": str(b.path),
        "rationale": ("first audit for repo" if b.last_audit_ts is None
                      else f"audit > {STALE_AUDIT_DAYS}d old (last {datetime.fromtimestamp(b.last_audit_ts, tz=timezone.utc).isoformat()}Z)"),
        "command": (
            f"python3 services/auditor/audit.py --repo {b.path} "
            f"--name {b.name} "
            f"--history .dolios/metrics/{b.name}/history.jsonl"
        ),
    }


def _remeasure_task(b: RepoBacklog, fm: dict, chunks: list[ch.Chunk]) -> dict:
    proposal_id = fm.get("id", "")
    return {
        "kind": "remeasure",
        "repo": b.name,
        "repo_path": str(b.path),
        "proposal_id": proposal_id,
        "proposal_path": fm.get("_path"),
        "rationale": (f"approved proposal '{proposal_id}' has all "
                      f"{len(chunks)} chunks checked; ready to re-audit and "
                      f"append Outcome"),
        # The supervisor first runs this audit, then dispatches claude to read
        # the new audit row + the original baseline row, populate the proposal's
        # Outcome section, and flip status: approved → done with today's date.
        "command_audit": (
            f"python3 services/auditor/audit.py --repo {b.path} "
            f"--name {b.name} "
            f"--history .dolios/metrics/{b.name}/history.jsonl"
        ),
    }


def _execute_task(b: RepoBacklog, fm: dict, chunk: ch.Chunk,
                  *, is_first_chunk: bool) -> dict:
    proposal_id = fm.get("id", "")
    # task_id stays inside the dispatcher's branch-name char set (safe slug);
    # proposal_id already uses `/` so we replace it with `-`.
    task_id = f"{proposal_id.replace('/', '-')}-chunk-{chunk.index}"
    instructions = f"{chunk.title}\n\n{chunk.description}".strip()
    return {
        "kind": "execute",
        "repo": b.name,
        "repo_path": str(b.path),
        "proposal_id": proposal_id,
        "proposal_path": fm.get("_path"),
        "chunk_index": chunk.index,
        "chunk_title": chunk.title,
        "task_id": task_id,
        # Pass-through fields the supervisor / dispatcher consume directly.
        # Multi-line instructions: the supervisor reads from this field, not
        # the shell-pasted command.
        "instructions": instructions,
        "rationale": (f"approved proposal '{proposal_id}' chunk "
                      f"{chunk.index}/{len(_proposal_chunks(fm))} "
                      f"({'starting' if is_first_chunk else 'continuing'})"),
    }


def pick(backlogs: list[RepoBacklog]) -> dict:
    """V1 priority logic. Returns a dict suitable for `json.dumps`."""

    # 1. Audit-due. Deterministic order by repo name.
    for b in sorted(backlogs, key=lambda x: x.name):
        if b.audit_stale:
            return _audit_task(b)

    # Gather approved proposals once (with their parsed chunks) — needed for
    # both remeasure and execute. Sort FIFO by `opened:` so the oldest in-flight
    # work is finished first.
    approved: list[tuple[RepoBacklog, dict, list[ch.Chunk]]] = []
    for b in sorted(backlogs, key=lambda x: x.name):
        for fm in b.proposals:
            if fm.get("status") != "approved":
                continue
            if fm.get("done"):
                continue  # done date set → already closed
            approved.append((b, fm, _proposal_chunks(fm)))
    approved.sort(key=lambda t: (t[1].get("opened") or "9999-12-31",
                                 t[1].get("id") or ""))

    # 2. Remeasure — approved proposal with all chunks done. Closing one frees
    # an implementing-cap slot, so this comes before execute and propose.
    for b, fm, chunks in approved:
        if ch.all_chunks_done(chunks):
            return _remeasure_task(b, fm, chunks)

    # 3. Execute — next unchecked chunk in the oldest-opened approved proposal,
    # respecting the per-repo cap. A proposal that's already in progress
    # (`effective_implementing` True) can continue regardless of cap; a fresh
    # approved-with-no-progress proposal can only START if the repo is under cap.
    for b, fm, chunks in approved:
        pending = ch.next_pending_chunk(chunks)
        if pending is None:
            continue
        already_implementing = effective_implementing(fm, chunks)
        if already_implementing:
            return _execute_task(b, fm, pending, is_first_chunk=False)
        # Starting fresh → cap check.
        if b.implementing_count < MAX_IMPLEMENTING_PER_REPO:
            return _execute_task(b, fm, pending, is_first_chunk=True)
        # Else: this proposal can't start this tick; try the next one.

    # 4. Propose — highest-severity uncovered gap with room under the cap.
    candidates: list[tuple] = []
    for b in sorted(backlogs, key=lambda x: x.name):
        if b.implementing_count >= MAX_IMPLEMENTING_PER_REPO:
            continue
        row = b.latest_audit_row
        if not row:
            continue
        for g in row.get("gaps", []):
            gid = g.get("gap_id")
            if not gid or gid in b.covered_gap_ids:
                continue
            candidates.append(
                (SEVERITY_RANK.get(g.get("severity"), 9), b.name,
                 g.get("area", ""), gid, g)
            )
    if candidates:
        candidates.sort(key=lambda t: (t[0], t[1], t[2]))
        sev_rank, repo, area, gid, gap = candidates[0]
        sev = ("high", "medium", "low")[sev_rank] if sev_rank < 3 else "unknown"
        return {
            "kind": "propose",
            "repo": repo,
            "gap_id": gid,
            "gap_area": area,
            "gap_summary": gap.get("summary"),
            "gap_severity": gap.get("severity"),
            "frameworks": gap.get("frameworks", []),
            "rationale": (f"open {sev}-severity gap '{gid}' has no active "
                          f"covering proposal; under the 3-active cap"),
        }

    # 5. Quiet tick.
    return {
        "kind": "empty",
        "rationale": ("no stale audits; no approved proposals with pending "
                      "chunks; every open gap is covered or every repo is at "
                      "the 3-implementing cap"),
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _load_allowlist(config_path: Path) -> dict[str, Path]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("pyyaml is required to load coder.yaml") from exc
    raw = yaml.safe_load(config_path.read_text()) or {}
    return {name: Path(p) for name, p in (raw.get("allowlist") or {}).items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Autonomous-coder priority picker.")
    ap.add_argument("--config", default=str(HERE / "coder.yaml"),
                    help="path to coder.yaml (defines the allowlist)")
    ap.add_argument("--next", action="store_true",
                    help="emit the next dispatch task as JSON")
    ap.add_argument("--root", default=str(DOLIOS_ROOT),
                    help="dolios repo root (default: derived from this file)")
    args = ap.parse_args(argv)

    cfg = Path(args.config)
    if not cfg.exists():
        print(json.dumps({"kind": "error",
                          "error": f"no config at {cfg} (copy coder.example.yaml → coder.yaml)"}, indent=2))
        return 2

    try:
        allow = _load_allowlist(cfg)
    except RuntimeError as exc:
        print(json.dumps({"kind": "error", "error": str(exc)}, indent=2))
        return 2

    if not allow:
        print(json.dumps({"kind": "empty", "rationale": "empty allowlist"}, indent=2))
        return 0

    dolios_root = Path(args.root).resolve()
    backlogs = [build_repo_backlog(name, path, dolios_root=dolios_root)
                for name, path in allow.items()]
    print(json.dumps(pick(backlogs), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
