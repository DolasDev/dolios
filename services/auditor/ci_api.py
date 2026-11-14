"""GitHub Actions API glue for the auditor.

`audit_ci()` in `audit.py` can tell from the filesystem whether CI exists, but
not how it's performing. The three fields the proposal chunk-3 flip targets —
`test_runs_on_pr`, `median_runtime_seconds`, `success_rate_30d` — require
reading `GET /repos/{owner}/{repo}/actions/runs`, which needs a token.

This module stays import-safe without `GH_TOKEN`: when `token is None`, it
returns the same `null`-with-`_note` shape the filesystem-only path has always
emitted, so the weekly offline audit is unchanged.
"""

from __future__ import annotations

import json
import re
import statistics
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

GH_API = "https://api.github.com"

_NOTE_UNMEASURED = (
    "runtime + flake rate need CI log access (GH Actions API); "
    "planned as a proposal output"
)


def _not_measured() -> dict:
    return {
        "test_runs_on_pr": None,
        "median_runtime_seconds": None,
        "success_rate_30d": None,
        "_note": _NOTE_UNMEASURED,
    }


def parse_origin(url: str) -> tuple[str, str] | None:
    """Pull `(owner, repo)` out of a GitHub remote URL. Supports both the HTTPS
    form (`https://github.com/owner/repo.git`) and the SSH form
    (`git@github.com:owner/repo.git`). Returns None if the URL isn't a GitHub
    origin we can recognize — the caller falls back to `--gh-repo`.
    """
    s = url.strip()
    if not s:
        return None
    m = re.match(
        r"^(?:https?://github\.com/|git@github\.com:)([^/]+)/([^/]+?)(?:\.git)?/?$",
        s,
    )
    if not m:
        return None
    return m.group(1), m.group(2)


def _fetch_runs(owner: str, repo: str, *, token: str, per_page: int = 100) -> dict:
    """GET one page of actions/runs filtered to the main branch."""
    url = (
        f"{GH_API}/repos/{owner}/{repo}/actions/runs"
        f"?branch=main&per_page={per_page}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "dolios-auditor",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (hardcoded https)
        return json.loads(resp.read().decode("utf-8"))


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _compute(runs: list[dict], lookback_days: int) -> dict:
    """Reduce raw workflow_runs to the three audited fields.

    - `median_runtime_seconds`: median of `updated_at − run_started_at` across
      runs whose `status == completed`, over the full lookback window.
    - `success_rate_30d`: fraction of `completed` runs whose
      `conclusion == success`, over the last 30 days.
    - `test_runs_on_pr`: True iff any `pull_request`-triggered run exists in
      the lookback window.
    """
    now = datetime.now(UTC)
    cutoff_lookback = now - timedelta(days=lookback_days)
    cutoff_30d = now - timedelta(days=30)

    runtimes: list[float] = []
    completed_30d_total = 0
    completed_30d_success = 0
    test_runs_on_pr = False

    for r in runs:
        created = _parse_iso(r.get("created_at"))
        if created is None or created < cutoff_lookback:
            continue
        if r.get("event") == "pull_request":
            test_runs_on_pr = True
        if r.get("status") != "completed":
            continue
        started = _parse_iso(r.get("run_started_at"))
        updated = _parse_iso(r.get("updated_at"))
        if started and updated and updated > started:
            runtimes.append((updated - started).total_seconds())
        if created >= cutoff_30d:
            completed_30d_total += 1
            if r.get("conclusion") == "success":
                completed_30d_success += 1

    median_runtime = int(statistics.median(runtimes)) if runtimes else None
    success_rate = (
        round(completed_30d_success / completed_30d_total, 3)
        if completed_30d_total
        else None
    )
    return {
        "test_runs_on_pr": test_runs_on_pr,
        "median_runtime_seconds": median_runtime,
        "success_rate_30d": success_rate,
    }


def gh_ci_metrics(
    owner: str,
    repo: str,
    *,
    token: str | None,
    lookback_days: int = 90,
) -> dict:
    """Return the three measured CI fields, or the null-with-`_note` shape.

    When `token` is None (offline / local-only audit), returns the same shape
    `audit_ci()` emitted before chunk 3 — unauthenticated runs don't change.
    When the API call fails (network, auth, repo not found), the null shape is
    returned with a specific `_note` so the failure surfaces in the snapshot
    without aborting the whole audit.
    """
    if not token:
        return _not_measured()
    try:
        payload = _fetch_runs(owner, repo, token=token)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        out = _not_measured()
        out["_note"] = f"GH Actions API fetch failed ({type(exc).__name__}); fields remain null"
        return out
    return _compute(payload.get("workflow_runs", []), lookback_days)
