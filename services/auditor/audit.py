#!/usr/bin/env python3
"""Repo health auditor for the Dolios fleet.

The deterministic half of the discovery loop: produces a structured snapshot of
code/architecture quality metrics for a repo, anchored in DORA / SPACE /
OpenSSF, and ranks the gaps. The output feeds the proposal-generation step
(where Claude Code reads this JSON + the repo + the web to propose
interventions) — see proposals/README.md for the full lifecycle.

MVP scope: this V0 uses **git + filesystem only** — no external tools required,
so it runs anywhere and the first audit can land in a clean PR without bringing
new install footprint to the host or container. Metrics whose proper measurement
requires external tooling (radon, interrogate, gitleaks, osv-scanner, OpenSSF
Scorecard, pytest --cov, CI logs) are deliberately reported as "not_measured"
with a pointer — adopting each tool will be its own proposal generated *from*
this audit, which is exactly the recursive bootstrap we want.

Usage:
  python3 audit.py --repo /path/to/repo --name dolios          # JSON to stdout
  python3 audit.py --repo /path/to/repo --name dolios --history .dolios/metrics/dolios/history.jsonl
  python3 audit.py --repo /path/to/repo --name dolios --gaps   # only the ranked gaps

Exit codes: 0 on success; 2 on a bad repo path.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

# How many days of history to scan for git-based metrics (commit cadence, sizes).
LOOKBACK_DAYS = 90

# Languages we recognize by extension; first-cut, expand as needed.
SOURCE_EXTS = {
    "python": (".py",),
    "javascript": (".js", ".mjs", ".cjs"),
    "typescript": (".ts", ".tsx"),
    "go": (".go",),
    "rust": (".rs",),
    "java": (".java",),
    "shell": (".sh",),
    "yaml": (".yml", ".yaml"),
    "dockerfile": ("Dockerfile",),  # filename match, not extension
}

# Cheap secret patterns — meant to flag obvious leakage in the tree, NOT to
# replace a real scanner (gitleaks/trufflehog). False positives are expected;
# real adoption is a proposal output.
SECRET_PATTERNS = [
    ("aws_access_key_id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github_pat", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openrouter_key", re.compile(r"sk-or-[A-Za-z0-9-]{20,}")),
    ("generic_pem", re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----")),
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _iso(ts: float | None = None) -> str:
    ts = ts if ts is not None else datetime.now(timezone.utc).timestamp()
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _git(repo: Path, *args: str) -> str:
    """Run a git command in the repo and return stdout. Empty on failure."""
    try:
        return subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True, text=True
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _walk_source(repo: Path):
    """Yield repo-relative Paths for files under the repo, skipping VCS, vendor,
    and build dirs. Cheap heuristic — sufficient for ratio/extension counts."""
    skip_dirs = {".git", "node_modules", "venv", ".venv", "__pycache__",
                 ".pytest_cache", "dist", "build", ".tox", ".mypy_cache",
                 ".ruff_cache", ".idea", ".vscode"}
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        rel_root = Path(root).relative_to(repo)
        for f in files:
            yield rel_root / f


def _ext_lang(path: Path) -> str | None:
    name = path.name
    for lang, exts in SOURCE_EXTS.items():
        if any(name.endswith(e) or name == e for e in exts):
            return lang
    return None


def _word_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="replace").split())
    except OSError:
        return 0


# --------------------------------------------------------------------------- #
# Audit sections — each returns a dict for one area
# --------------------------------------------------------------------------- #
def audit_commits(repo: Path) -> dict:
    """Commit cadence + size distribution over the lookback window.

    A proxy for the DORA 'working in small batches' capability — until we can
    read merged-PR sizes (needs gh + auth), commit shortstats are the cheap
    stand-in. Median commit lines-changed correlates with PR size in practice.
    """
    since = f"--since={LOOKBACK_DAYS}.days.ago"
    log = _git(repo, "log", since, "--pretty=tformat:===%H %ct", "--shortstat")
    if not log.strip():
        return {"count": 0, "lookback_days": LOOKBACK_DAYS, "note": "no commits in lookback window or not a git repo"}
    commits, sizes, authors = 0, [], set()
    cur = None
    for line in log.splitlines():
        if line.startswith("==="):
            if cur is not None:
                sizes.append(cur)
            commits += 1
            cur = 0
        elif "changed" in line and ("insertion" in line or "deletion" in line):
            ins = sum(int(m) for m in re.findall(r"(\d+) insertion", line))
            dels = sum(int(m) for m in re.findall(r"(\d+) deletion", line))
            cur = (cur or 0) + ins + dels
    if cur is not None:
        sizes.append(cur)
    # distinct authors
    authors_out = _git(repo, "log", since, "--pretty=format:%ae")
    authors = {a.strip() for a in authors_out.splitlines() if a.strip()}
    return {
        "count": commits,
        "lookback_days": LOOKBACK_DAYS,
        "median_lines_changed": int(statistics.median(sizes)) if sizes else 0,
        "p95_lines_changed": int(statistics.quantiles(sizes, n=20)[-1]) if len(sizes) >= 20 else (max(sizes) if sizes else 0),
        "max_lines_changed": max(sizes) if sizes else 0,
        "distinct_authors": len(authors),
    }


def audit_ci(repo: Path) -> dict:
    """Presence of automated CI — DORA's 'continuous integration' capability."""
    workflows = sorted((repo / ".github" / "workflows").glob("*.y*ml")) if (repo / ".github" / "workflows").exists() else []
    return {
        "github_actions_present": bool(workflows),
        "workflow_count": len(workflows),
        "workflow_files": [str(p.relative_to(repo)) for p in workflows],
        "other_ci_detected": any((repo / f).exists() for f in (".circleci/config.yml", ".gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile")),
        "test_runs_on_pr": None,  # not measurable from filesystem alone
        "median_runtime_seconds": None,
        "_note": "runtime + flake rate need CI log access (GH Actions API); planned as a proposal output",
    }


def audit_testing(repo: Path) -> dict:
    """Test infrastructure presence + coarse coverage proxy (file ratio).

    Real coverage % needs running the tests with a coverage tool; that's a
    deliberate gap to surface (the audit's first proposal usually adopts one).
    """
    test_files, source_files = [], []
    test_re = re.compile(r"(^|/)(test_[^/]+\.py|.*_test\.py|.*\.test\.[jt]sx?)$")
    for rel in _walk_source(repo):
        lang = _ext_lang(rel)
        if not lang or lang in ("yaml", "dockerfile"):
            continue
        s = str(rel).replace("\\", "/")
        (test_files if test_re.search(s) else source_files).append(s)
    has_pytest_config = any((repo / p).exists() for p in ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"))
    return {
        "test_files": len(test_files),
        "source_files": len(source_files),
        "test_to_source_ratio": round(len(test_files) / len(source_files), 3) if source_files else None,
        "pytest_config_present": has_pytest_config,
        "coverage_measured": False,
        "coverage_percent": None,
        "_note": "coverage % + flake rate not measured in V0 (need test-run integration); planned as a proposal output",
    }


def audit_docs(repo: Path) -> dict:
    """Doc presence and a coarse depth signal (word count)."""
    readme = repo / "README.md"
    return {
        "readme_present": readme.exists(),
        "readme_word_count": _word_count(readme) if readme.exists() else 0,
        "contributing_present": (repo / "CONTRIBUTING.md").exists(),
        "code_of_conduct_present": (repo / "CODE_OF_CONDUCT.md").exists(),
        "license_present": (repo / "LICENSE").exists() or (repo / "LICENSE.md").exists() or (repo / "LICENSE.txt").exists(),
        "security_md_present": (repo / "SECURITY.md").exists(),
        "codeowners_present": (repo / "CODEOWNERS").exists() or (repo / ".github" / "CODEOWNERS").exists(),
        "doc_coverage_measured": False,
        "_note": "public-API docstring coverage (interrogate / similar) not measured in V0; planned as a proposal output",
    }


def audit_security(repo: Path) -> dict:
    """Cheap, regex-only secret sweep + presence checks for serious tools."""
    gitleaks_cfg = any((repo / p).exists() for p in (".gitleaks.toml", ".gitleaksignore"))
    findings: list[dict] = []
    for rel in _walk_source(repo):
        if str(rel).endswith((".bak",)) or rel.name == "audit.py":  # don't self-match
            continue
        try:
            text = (repo / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for label, pat in SECRET_PATTERNS:
            if pat.search(text):
                findings.append({"file": str(rel), "pattern": label})
    return {
        "gitleaks_config_present": gitleaks_cfg,
        "regex_secret_findings": findings,
        "regex_secret_finding_count": len(findings),
        "osv_scanner_present": (repo / ".osv-scanner.toml").exists(),
        "openssf_scorecard_present": (repo / ".github" / "workflows" / "scorecard.yml").exists(),
        "_note": "regex sweep is a placeholder for gitleaks (high FP rate by design); proper scanners are a proposal output",
    }


def audit_dependencies(repo: Path) -> dict:
    """Dependency-manifest presence — feeds the supply-chain / vuln-tracking story."""
    return {
        "python_pyproject_toml": (repo / "pyproject.toml").exists(),
        "python_requirements_txt": (repo / "requirements.txt").exists(),
        "python_setup_py": (repo / "setup.py").exists(),
        "node_package_json": (repo / "package.json").exists(),
        "dependabot_config": (repo / ".github" / "dependabot.yml").exists() or (repo / ".github" / "dependabot.yaml").exists(),
        "renovate_config": any((repo / p).exists() for p in ("renovate.json", "renovate.json5", ".renovaterc")),
        "_note": "actual vulnerability count needs osv-scanner / Dependabot alerts; planned as a proposal output",
    }


def audit_iac(repo: Path) -> dict:
    """Infrastructure-as-Code surface — DORA 'deployment automation' / 'version control of all production artifacts'."""
    has_dockerfile = any(p.name == "Dockerfile" for p in _walk_source(repo))
    has_compose = any(p.name.startswith("docker-compose") or p.name.startswith("compose.") for p in _walk_source(repo))
    has_terraform = any(p.suffix == ".tf" for p in _walk_source(repo))
    has_helm = (repo / "Chart.yaml").exists() or any(p.parent.name == "templates" and p.suffix in (".yml", ".yaml") for p in _walk_source(repo))
    has_ansible = (repo / "ansible").exists() or any(p.name in ("playbook.yml", "playbook.yaml") for p in _walk_source(repo))
    has_makefile = (repo / "Makefile").exists() or (repo / "makefile").exists()
    return {
        "dockerfile_present": has_dockerfile,
        "compose_present": has_compose,
        "terraform_present": has_terraform,
        "helm_present": has_helm,
        "ansible_present": has_ansible,
        "makefile_present": has_makefile,
    }


def audit_repo_shape(repo: Path) -> dict:
    """Language mix + scale, for context on every other metric."""
    by_lang: dict[str, int] = {}
    total_files = 0
    for rel in _walk_source(repo):
        total_files += 1
        lang = _ext_lang(rel)
        if lang:
            by_lang[lang] = by_lang.get(lang, 0) + 1
    return {
        "total_tracked_files": total_files,
        "files_by_language": dict(sorted(by_lang.items(), key=lambda kv: -kv[1])),
    }


# --------------------------------------------------------------------------- #
# Gap derivation — frames every finding against a named capability/framework
# --------------------------------------------------------------------------- #
def derive_gaps(metrics: dict) -> list[dict]:
    """Each gap names the framework capability it falls under, so proposals can
    cite the leading-indicator evidence (DORA Accelerate, OpenSSF Scorecard,
    NIST SSDF) instead of feeling arbitrary."""
    gaps: list[dict] = []

    ci, sec, docs, tests, deps = (
        metrics["ci"], metrics["security"], metrics["docs"],
        metrics["testing"], metrics["dependencies"],
    )

    if not ci["github_actions_present"] and not ci["other_ci_detected"]:
        gaps.append({
            "area": "ci",
            "severity": "high",
            "frameworks": ["DORA: Continuous Integration", "DORA: Deployment Automation"],
            "summary": "No CI workflows detected",
            "detail": "No .github/workflows/*.yml and no other CI config — there is no automated test/lint/security signal on PRs.",
            "proposed_action": "Adopt GitHub Actions; minimal first workflow runs the existing make test targets and a lint pass on PRs.",
        })

    if not docs["license_present"]:
        gaps.append({
            "area": "compliance",
            "severity": "medium",
            "frameworks": ["NIST SSDF: PO.1 — define the security & compliance requirements"],
            "summary": "No LICENSE file",
            "detail": "Repo has no LICENSE/LICENSE.md/LICENSE.txt — legally ambiguous reuse posture.",
            "proposed_action": "Add an explicit LICENSE (Apache-2.0 / MIT / proprietary, per the project's intent).",
        })

    if not docs["security_md_present"]:
        gaps.append({
            "area": "security",
            "severity": "medium",
            "frameworks": ["OpenSSF Scorecard: Security-Policy", "NIST SSDF: PO.1"],
            "summary": "No SECURITY.md",
            "detail": "No vulnerability-disclosure policy — researchers have nowhere documented to report findings.",
            "proposed_action": "Add SECURITY.md naming a reporting channel and a response SLA.",
        })

    if not docs["codeowners_present"]:
        gaps.append({
            "area": "review",
            "severity": "low",
            "frameworks": ["DORA: Streamlining change approval"],
            "summary": "No CODEOWNERS",
            "detail": "Review-routing relies on humans remembering who to ask.",
            "proposed_action": "Add CODEOWNERS once CI is in place and required-reviews can enforce it.",
        })

    if not sec["gitleaks_config_present"]:
        gaps.append({
            "area": "security",
            "severity": "medium",
            "frameworks": ["DORA: Shift-left security", "OpenSSF Scorecard: Token-Permissions / Pinned-Dependencies"],
            "summary": "No secrets scanner configured",
            "detail": "V0 audit's regex sweep is a placeholder; a real scanner (gitleaks/trufflehog) must run pre-commit and in CI.",
            "proposed_action": "Adopt gitleaks; add a pre-commit hook and a CI job. Tune .gitleaks.toml for this repo's patterns.",
        })

    if sec["regex_secret_finding_count"] > 0:
        gaps.append({
            "area": "security",
            "severity": "high",
            "frameworks": ["DORA: Shift-left security"],
            "summary": f"V0 regex sweep found {sec['regex_secret_finding_count']} possible secret(s)",
            "detail": "These are likely false positives (the V0 patterns are conservative) but must be triaged.",
            "proposed_action": "Triage the regex hits; adopt gitleaks for proper detection (see secrets-scanner gap).",
        })

    if not sec["openssf_scorecard_present"]:
        gaps.append({
            "area": "security",
            "severity": "low",
            "frameworks": ["OpenSSF Scorecard"],
            "summary": "No OpenSSF Scorecard workflow",
            "detail": "Without Scorecard there's no continuous, comparable security-posture score.",
            "proposed_action": "Add the official scorecard-action workflow once basic CI exists.",
        })

    if not deps["dependabot_config"] and not deps["renovate_config"]:
        gaps.append({
            "area": "supply_chain",
            "severity": "medium",
            "frameworks": ["DORA: Shift-left security", "OpenSSF Scorecard: Dependency-Update-Tool"],
            "summary": "No dependency-update tool configured",
            "detail": "No Dependabot or Renovate config — vulnerable transitive updates won't be flagged automatically.",
            "proposed_action": "Enable Dependabot (free for GitHub repos); grouping rules to avoid noise.",
        })

    if not tests["coverage_measured"]:
        gaps.append({
            "area": "testing",
            "severity": "medium",
            "frameworks": ["DORA: Test automation"],
            "summary": "No test-coverage measurement",
            "detail": "V0 audit only counts test files; no coverage % is produced, so we can't see drift.",
            "proposed_action": "Add coverage.py to the pytest runs in CI; publish a per-PR summary; track median over time.",
        })

    # Stable order by severity then area, so audit diffs in PRs are readable.
    rank = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: (rank.get(g["severity"], 9), g["area"]))
    return gaps


# --------------------------------------------------------------------------- #
# Top-level
# --------------------------------------------------------------------------- #
def run(repo: Path, name: str) -> dict:
    metrics = {
        "commits": audit_commits(repo),
        "ci": audit_ci(repo),
        "testing": audit_testing(repo),
        "docs": audit_docs(repo),
        "security": audit_security(repo),
        "dependencies": audit_dependencies(repo),
        "iac": audit_iac(repo),
        "shape": audit_repo_shape(repo),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "audited_at": _iso(),
        "repo": name,
        "repo_path": str(repo),
        "git_head": _git(repo, "rev-parse", "HEAD").strip() or None,
        "git_branch": _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() or None,
        "metrics": metrics,
        "gaps": derive_gaps(metrics),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Repo health auditor (DORA/SPACE/OpenSSF-anchored).")
    ap.add_argument("--repo", required=True, help="path to the repo to audit")
    ap.add_argument("--name", required=True, help="short logical name (used in history path + JSON)")
    ap.add_argument("--history", help="append the snapshot to this JSONL history file")
    ap.add_argument("--gaps", action="store_true", help="emit only the ranked gaps")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(json.dumps({"ok": False, "error": f"no such directory: {repo}"}), file=sys.stderr)
        return 2

    snapshot = run(repo, args.name)
    out = snapshot["gaps"] if args.gaps else snapshot
    print(json.dumps(out, indent=2))

    if args.history:
        hp = Path(args.history)
        hp.parent.mkdir(parents=True, exist_ok=True)
        with hp.open("a") as fh:
            fh.write(json.dumps(snapshot) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
