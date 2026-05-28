#!/usr/bin/env python3
"""Deterministic priority picker for the autonomous-coder.

Reads coder.yaml's allowlist + the audit history + the proposals/ directory,
emits the next dispatch task as JSON. The supervisor's cron prompt switches on
`kind` and acts mechanically — keeping the picking logic in code rather than
in the 35B's prompt is what makes the loop reliable.

V0 priority order (highest first):
  1. **audit**   — repo has no audit yet, or last audit > 7d old.
  2. **propose** — repo has an uncovered open gap (`gap_id` not referenced by
     any active proposal) AND fewer than 3 proposals in `implementing` state.
     Pick the highest-severity uncovered gap across all repos; ties broken by
     repo name → gap area for determinism.
  3. **empty**   — nothing to do this tick.

Deferred to V1:
  - **execute**   — next chunk of an approved proposal. Needs chunk-completion
    state tracking (sidecar JSONL or open-PR scan).
  - **remeasure** — re-audit after last execution PR merges, append Outcome.
    Same dependency.

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
    each annotated with `_path` (relative to dolios_root) for debugging.
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
            out.append(fm)
    return out


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
        if status == "implementing":
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
        # Convenience so the supervisor's prompt is a literal shell command.
        "command": (
            f"python3 services/auditor/audit.py --repo {b.path} "
            f"--name {b.name} "
            f".dolios/metrics/{b.name}/history.jsonl".replace(
                ".dolios/metrics", "--history .dolios/metrics")
        ),
    }


def pick(backlogs: list[RepoBacklog]) -> dict:
    """V0 priority logic. Returns a dict suitable for `json.dumps`."""

    # 1. Audit-due. Deterministic order by repo name so multiple stale repos
    # don't shuffle between ticks.
    for b in sorted(backlogs, key=lambda x: x.name):
        if b.audit_stale:
            return _audit_task(b)

    # 2. Propose for the highest-severity uncovered gap with room under the cap.
    candidates: list[tuple] = []  # (sev_rank, repo_name, gap_area, gap_id, gap)
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
            # No command — the supervisor's prompt constructs the claude
            # dispatch from the structured context above (gap_id, summary,
            # frameworks, the latest audit row).
        }

    # 3. Quiet tick.
    return {
        "kind": "empty",
        "rationale": "no stale audits; every open gap is covered by an active proposal (or every repo is at the 3-implementing cap)",
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
