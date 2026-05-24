#!/usr/bin/env python3
"""Spare-capacity gate for the Dolios orchestrator.

Before the orchestrator dispatches a Claude Code task, it must know whether the
Anthropic subscription has headroom. This module answers that — and, critically,
it hands the model an *explicit, unit-labelled* contract so the model never has
to interpret a raw, ambiguously-scaled `utilization` number again.

  Why this exists (the bug it fixes)
  -----------------------------------
  The undocumented `GET /api/oauth/usage` endpoint returns utilization on a
  PERCENT scale (0-100): `five_hour: 1.0` means 1% used. The orchestrator model,
  pattern-matching on the far more common 0-1 header convention, read `1.0` as
  "100% used" and wrongly refused to dispatch. Two sources, two scales, no units
  attached — a data-presentation trap. So the gate normalizes everything to one
  contract with named units (`percent_used`, `percent_remaining`) and, better
  still, leans on Anthropic's own authoritative `...-status: allowed|rejected`
  signal rather than asking the model to threshold a number at all.

  Sources (in order of authority)
  -------------------------------
  PRIMARY  — rate-limit headers off a 1-token `/v1/messages` ping. These are the
             same numbers Claude Code's own `/usage` shows. Scale is 0-1.
             Includes per-window `-status` (allowed/rejected) and `-reset`.
  ENRICH   — `GET /api/oauth/usage` (undocumented). Adds per-model breakdowns the
             headers don't carry. Scale is 0-100. Best-effort; never required.

Usage:
    python3 usage_gate.py                 # emit the normalized snapshot as JSON
    python3 usage_gate.py --decide        # emit a dispatch/hold decision
    python3 usage_gate.py --decide --max-utilization 85
    python3 usage_gate.py --no-enrich     # skip the endpoint call (headers only)

Exit codes: 0 = ran (see JSON); 2 = could not determine usage (auth/network).
In --decide mode the process also exits 1 when the decision is "hold", so a
shell orchestrator can branch on `$?` without parsing JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

CREDENTIALS_PATH = os.path.expanduser("~/.claude/.credentials.json")
API_BASE = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
OAUTH_BETA = "oauth-2025-04-20"
# OAuth token refresh. The console.anthropic.com token endpoint sits behind a
# Cloudflare challenge that blocks programmatic clients; api.anthropic.com hosts
# the same grant without it. client_id is Claude Code's public OAuth client.
OAUTH_TOKEN_URL = f"{API_BASE}/v1/oauth/token"
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
# OAuth subscription tokens only resolve models Claude Code itself uses, and the
# request must look like a Claude Code request (system-prompt preamble below).
PING_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_CODE_PREAMBLE = "You are Claude Code, Anthropic's official CLI for Claude."

# Refresh the token this long before it actually expires, so a long task started
# right at the gate check doesn't run into a mid-flight expiry.
EXPIRY_BUFFER_S = 300


class UsageError(RuntimeError):
    """Raised when usage cannot be determined (auth, network, malformed)."""


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #
def load_oauth() -> dict:
    try:
        with open(CREDENTIALS_PATH) as fh:
            return json.load(fh)["claudeAiOauth"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise UsageError(f"cannot read OAuth credentials at {CREDENTIALS_PATH}: {exc}")


def token_expired(oauth: dict, buffer_s: int = EXPIRY_BUFFER_S) -> bool:
    # expiresAt is epoch milliseconds.
    return (oauth.get("expiresAt", 0) / 1000) - buffer_s < time.time()


def _post_oauth_token(body: dict, *, timeout: int = 30) -> dict:
    """POST the refresh grant to the api.anthropic.com token endpoint."""
    req = urllib.request.Request(
        OAUTH_TOKEN_URL, data=json.dumps(body).encode(), method="POST"
    )
    req.add_header("content-type", "application/json")
    req.add_header("user-agent", "anthropic")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise UsageError(f"token refresh HTTP {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        raise UsageError(f"network error during token refresh: {exc}")


def refresh_access_token(
    *,
    credentials_path: str = CREDENTIALS_PATH,
    poster=_post_oauth_token,
    now=None,
    dry_run: bool = False,
) -> dict:
    """Exchange the stored refresh token for a fresh access token.

    DESTRUCTIVE: on success this rewrites `credentials_path` with rotated tokens
    (the old file is copied to `<path>.bak` first, and the new file is written
    atomically with 0600 perms). The refresh token itself rotates, so a failed
    or partial write must not lose it — hence backup + atomic replace.

    `poster` is injectable for testing; `dry_run=True` builds and returns the
    request (token redacted) WITHOUT sending it or touching any file.
    """
    now = now if now is not None else time.time()
    with open(credentials_path) as fh:
        doc = json.load(fh)
    oauth = doc.get("claudeAiOauth", {})
    refresh = oauth.get("refreshToken")
    if not refresh:
        raise UsageError(f"no refreshToken in {credentials_path}; cannot refresh")

    body = {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": OAUTH_CLIENT_ID,
    }
    if dry_run:
        redacted = {**body, "refresh_token": "<redacted>"}
        return {"dry_run": True, "url": OAUTH_TOKEN_URL, "body": redacted}

    resp = poster(body)
    access = resp.get("access_token")
    if not access:
        raise UsageError(f"token refresh response missing access_token: {resp}")

    # expires_in is seconds; the credentials file stores expiresAt in ms.
    expires_in = resp.get("expires_in")
    if expires_in is not None:
        expires_at_ms = int((now + float(expires_in)) * 1000)
    else:  # fall back to a returned expires_at (seconds) if that's what we got
        expires_at_ms = int(float(resp.get("expires_at", now)) * 1000)

    oauth["accessToken"] = access
    oauth["refreshToken"] = resp.get("refresh_token", refresh)  # rotation
    oauth["expiresAt"] = expires_at_ms
    doc["claudeAiOauth"] = oauth

    # Back up, then write atomically with the original perms (default 0600).
    if os.path.exists(credentials_path):
        shutil.copy2(credentials_path, credentials_path + ".bak")
    try:
        mode = os.stat(credentials_path).st_mode & 0o777
    except OSError:
        mode = 0o600
    tmp = credentials_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(doc, fh, indent=2)
    os.chmod(tmp, mode)
    os.replace(tmp, credentials_path)

    return {
        "refreshed": True,
        "expires_at": _iso(expires_at_ms / 1000),
        "seconds_until_expiry": int(expires_at_ms / 1000 - now),
        "backup": credentials_path + ".bak",
    }


# --------------------------------------------------------------------------- #
# Source 1 (PRIMARY): rate-limit headers from a minimal /v1/messages ping
# --------------------------------------------------------------------------- #
def _auth_headers(token: str) -> dict:
    return {
        "authorization": f"Bearer {token}",
        "anthropic-version": ANTHROPIC_VERSION,
        "anthropic-beta": OAUTH_BETA,
        "content-type": "application/json",
    }


def fetch_ping_headers(token: str, *, model: str = PING_MODEL, timeout: int = 30) -> dict:
    """One-token generation purely to read the unified rate-limit headers.

    Returns the relevant `anthropic-ratelimit-unified-*` headers (lowercased,
    prefix stripped) plus `retry-after` if present. Raises UsageError on auth
    failure so the gate fails closed rather than guessing.
    """
    body = json.dumps(
        {
            "model": model,
            "max_tokens": 1,
            "system": CLAUDE_CODE_PREAMBLE,
            "messages": [{"role": "user", "content": "ping"}],
        }
    ).encode()
    req = urllib.request.Request(f"{API_BASE}/v1/messages", data=body, method="POST")
    for k, v in _auth_headers(token).items():
        req.add_header(k, v)

    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw = dict(resp.headers)
    except urllib.error.HTTPError as exc:
        raw = dict(exc.headers or {})
        # A 429 still carries the headers we want — that's a valid "rejected"
        # reading, not an error. Anything else without usable headers is fatal.
        if exc.code in (401, 403):
            raise UsageError(f"OAuth token rejected by /v1/messages (HTTP {exc.code})")
        if not any("ratelimit-unified" in k.lower() for k in raw):
            detail = exc.read().decode(errors="replace")[:300]
            raise UsageError(f"/v1/messages HTTP {exc.code}, no rate-limit headers: {detail}")
    except urllib.error.URLError as exc:
        raise UsageError(f"network error reaching /v1/messages: {exc}")

    prefix = "anthropic-ratelimit-unified-"
    out: dict[str, str] = {}
    for key, val in raw.items():
        lk = key.lower()
        if lk.startswith(prefix):
            out[lk[len(prefix):]] = val
        elif lk == "retry-after":
            out["retry-after"] = val
    if not out:
        raise UsageError("no unified rate-limit headers present on /v1/messages response")
    return out


# --------------------------------------------------------------------------- #
# Source 2 (ENRICH): undocumented usage endpoint
# --------------------------------------------------------------------------- #
def fetch_usage_endpoint(token: str, *, timeout: int = 30) -> dict | None:
    """Best-effort. Returns parsed JSON or None — never raises into the gate."""
    req = urllib.request.Request(f"{API_BASE}/api/oauth/usage", method="GET")
    for k, v in _auth_headers(token).items():
        if k != "content-type":
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


# --------------------------------------------------------------------------- #
# Normalization — one explicit contract, no raw utilization leaks to the model
# --------------------------------------------------------------------------- #
def _iso(epoch_s: float | None) -> str | None:
    if not epoch_s:
        return None
    return datetime.fromtimestamp(int(epoch_s), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _window(headers: dict, name: str) -> dict:
    """Build one window's view from headers. `utilization` here is the 0-1 scale."""
    util = headers.get(f"{name}-utilization")
    pct_used = round(float(util) * 100, 2) if util is not None else None
    reset = headers.get(f"{name}-reset")
    reset_epoch = int(reset) if reset and reset.isdigit() else None
    return {
        "status": headers.get(f"{name}-status"),  # allowed | rejected — authoritative
        "percent_used": pct_used,
        "percent_remaining": round(100 - pct_used, 2) if pct_used is not None else None,
        "resets_at": _iso(reset_epoch),
        "resets_in_seconds": max(0, reset_epoch - int(time.time())) if reset_epoch else None,
    }


def normalize(headers: dict, endpoint: dict | None) -> dict:
    snapshot = {
        "ok": True,
        "checked_at": _iso(time.time()),
        "source": "headers",
        # Authoritative overall allow/deny from Anthropic — gate on THIS, not a
        # number, when it's present.
        "overall_status": headers.get("status"),
        # Which window is currently the binding constraint.
        "binding_window": headers.get("representative-claim"),
        "windows": {
            "five_hour": _window(headers, "5h"),
            "seven_day": _window(headers, "7d"),
        },
        "overage": {
            "status": headers.get("overage-status"),
            "disabled_reason": headers.get("overage-disabled-reason"),
        },
        "retry_after_seconds": int(headers["retry-after"]) if "retry-after" in headers else None,
    }
    if endpoint is not None:
        # Endpoint utilization is PERCENT (0-100) — kept under a clearly-named key
        # so its different scale can never be confused with the windows above.
        snapshot["source"] = "headers+endpoint"
        snapshot["endpoint_raw"] = endpoint
    return snapshot


# --------------------------------------------------------------------------- #
# Decision
# --------------------------------------------------------------------------- #
def decide(snapshot: dict, max_utilization: float) -> dict:
    """Translate a snapshot into dispatch/hold.

    Prefers Anthropic's authoritative status fields; falls back to the
    percent-used threshold only when a status field is missing.
    """
    windows = snapshot["windows"]
    reasons: list[str] = []
    hold = False

    if snapshot.get("overall_status") == "rejected":
        hold = True
        reasons.append("overall unified status is 'rejected'")

    for name, win in windows.items():
        status, used = win.get("status"), win.get("percent_used")
        if status == "rejected":
            hold = True
            reasons.append(f"{name} status is 'rejected'")
        elif used is not None and used >= max_utilization:
            hold = True
            reasons.append(f"{name} at {used}% used (>= {max_utilization}% cap)")

    binding = windows.get(snapshot.get("binding_window") or "", {})
    retry = snapshot.get("retry_after_seconds") or binding.get("resets_in_seconds")

    return {
        "decision": "hold" if hold else "dispatch",
        "reason": "; ".join(reasons) if reasons else "capacity available",
        "binding_window": snapshot.get("binding_window"),
        "retry_after_seconds": retry if hold else None,
        "snapshot": snapshot,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def gather(*, enrich: bool = True, auto_refresh: bool = False) -> dict:
    oauth = load_oauth()
    if token_expired(oauth):
        if auto_refresh:
            refresh_access_token()       # rotates + rewrites the credentials file
            oauth = load_oauth()
        else:
            # Fail closed rather than send a dead token. Pass auto_refresh=True
            # (CLI: --auto-refresh) for unattended use, or run any `claude`
            # command to refresh ~/.claude/.credentials.json, then retry.
            raise UsageError(
                "OAuth access token expired or expiring within "
                f"{EXPIRY_BUFFER_S}s; pass --auto-refresh or run any `claude` "
                "command to refresh ~/.claude/.credentials.json, then retry."
            )
    token = oauth["accessToken"]
    headers = fetch_ping_headers(token)
    endpoint = fetch_usage_endpoint(token) if enrich else None
    return normalize(headers, endpoint)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dolios spare-capacity gate.")
    ap.add_argument("--decide", action="store_true", help="emit a dispatch/hold decision")
    ap.add_argument("--max-utilization", type=float, default=85.0,
                    help="percent-used cap used only when a status field is absent (default 85)")
    ap.add_argument("--no-enrich", action="store_true", help="skip the /api/oauth/usage call")
    ap.add_argument("--auto-refresh", action="store_true",
                    help="if the token is expired, refresh it (rewrites the credentials file)")
    ap.add_argument("--refresh", action="store_true",
                    help="refresh the OAuth token now and exit (DESTRUCTIVE: rotates + rewrites creds)")
    ap.add_argument("--refresh-dry-run", action="store_true",
                    help="show the refresh request without sending it or touching any file")
    args = ap.parse_args(argv)

    if args.refresh or args.refresh_dry_run:
        try:
            result = refresh_access_token(dry_run=args.refresh_dry_run)
        except UsageError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
            return 2
        print(json.dumps({"ok": True, **result}, indent=2))
        return 0

    try:
        snapshot = gather(enrich=not args.no_enrich, auto_refresh=args.auto_refresh)
    except UsageError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    if args.decide:
        result = decide(snapshot, args.max_utilization)
        print(json.dumps(result, indent=2))
        return 1 if result["decision"] == "hold" else 0

    print(json.dumps(snapshot, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
