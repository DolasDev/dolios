#!/usr/bin/env python3
"""GitHub Actions API client for the auditor.

Augments the filesystem-based CI audit with API-derived metrics: median
runtime, 30-day success rate, and whether PR-triggered runs exist. When
``GH_TOKEN`` is unavailable, returns the same null-with-``_note`` shape that
``audit_ci()`` emitted in V0 — so the offline / local-checkout case is
unchanged.

Stdlib only (``urllib``) to keep the auditor install footprint at zero. The
HTTP call is factored out as ``_http_get_json`` so tests can monkey-patch a
fake response without touching the network.
"""

from __future__ import annotations

import json
import statistics
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

_NOT_MEASURED_NOTE = (
    "runtime + flake rate need CI log access (GH Actions API); "
    "planned as a proposal output"
)


def _not_measured_shape() -> dict:
    """Identical to what ``audit_ci()`` returned in V0 for these fields, plus
    the new ``success_rate_30d`` slot — so callers without a token see exactly
    the prior behaviour, with one extra ``None``."""
    return {
        "test_runs_on_pr": None,
        "median_runtime_seconds": None,
        "success_rate_30d": None,
        "_note": _NOT_MEASURED_NOTE,
    }


def _http_get_json(url: str, headers: dict) -> dict:
    """Stdlib JSON GET. Factored out so tests can monkey-patch the network."""
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def gh_ci_metrics(
    owner: str | None,
    repo: str | None,
    *,
    token: str | None,
    lookback_days: int = 90,
) -> dict:
    """Return CI runtime/reliability metrics from the GH Actions API.

    Falls back to the V0 null-with-``_note`` shape when ``token`` is ``None``
    or when ``owner``/``repo`` could not be derived — the audit stays runnable
    offline / without auth.

    When the call succeeds, returns three measured fields:
      - ``test_runs_on_pr``: ``True`` iff any ``pull_request``-triggered run
        exists in the lookback window.
      - ``median_runtime_seconds``: integer median of
        ``(updated_at − run_started_at)`` across completed runs in the window.
        ``None`` if no completed runs.
      - ``success_rate_30d``: ``success`` / ``completed`` over the last 30
        days, rounded to 3 decimals. ``None`` if no completed runs in that
        window.
    """
    if token is None or not owner or not repo:
        return _not_measured_shape()

    url = (
        f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
        f"?branch=main&per_page=100"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "dolios-auditor",
    }
    try:
        data = _http_get_json(url, headers)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        # Network/auth failure — degrade to not_measured so a transient blip
        # never crashes the audit. The _note already explains the absence.
        return _not_measured_shape()

    runs = data.get("workflow_runs") or []
    now = datetime.now(UTC)
    window_start = now - timedelta(days=lookback_days)
    thirty_start = now - timedelta(days=30)

    durations: list[float] = []
    pr_run_seen = False
    completed_30d = 0
    success_30d = 0
    for run in runs:
        started = _parse_iso(run.get("run_started_at"))
        if not started or started < window_start:
            continue
        if run.get("event") == "pull_request":
            pr_run_seen = True
        if run.get("status") == "completed":
            updated = _parse_iso(run.get("updated_at"))
            if updated and updated >= started:
                durations.append((updated - started).total_seconds())
            if started >= thirty_start:
                completed_30d += 1
                if run.get("conclusion") == "success":
                    success_30d += 1

    median_runtime = (
        int(round(statistics.median(durations))) if durations else None
    )
    success_rate = (
        round(success_30d / completed_30d, 3) if completed_30d else None
    )
    return {
        "test_runs_on_pr": pr_run_seen,
        "median_runtime_seconds": median_runtime,
        "success_rate_30d": success_rate,
    }
