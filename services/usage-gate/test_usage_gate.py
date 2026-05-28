#!/usr/bin/env python3
"""Tests for the spare-capacity gate.

These exercise normalize() and decide() against synthetic header/endpoint data
— no network — so the scale-normalization fix is locked in as a regression.
Runs under pytest, or standalone: `python3 test_usage_gate.py`.

The headline test is `test_low_utilization_does_not_hold`: it reproduces the
exact reading that originally caused a wrong "capacity exhausted" refusal and
asserts the gate now dispatches.
"""

import json
import os
import tempfile

import usage_gate as ug


# Real header shape, lowercased + prefix-stripped, as fetch_ping_headers returns.
def _headers(*, util_5h="0.09", util_7d="0.19", status_5h="allowed",
             status_7d="allowed", overall="allowed", binding="five_hour",
             reset_5h="9999999999", reset_7d="9999999999", retry_after=None):
    h = {
        "5h-utilization": util_5h, "5h-status": status_5h, "5h-reset": reset_5h,
        "7d-utilization": util_7d, "7d-status": status_7d, "7d-reset": reset_7d,
        "status": overall, "representative-claim": binding,
        "overage-status": "rejected", "overage-disabled-reason": "org_level_disabled",
    }
    if retry_after is not None:
        h["retry-after"] = retry_after
    return h


def test_header_fraction_becomes_explicit_percent():
    """0-1 header scale must surface as an explicit 0-100 percent_used."""
    snap = ug.normalize(_headers(util_5h="0.09"), None)
    win = snap["windows"]["five_hour"]
    assert win["percent_used"] == 9.0
    assert win["percent_remaining"] == 91.0


def test_low_utilization_does_not_hold():
    """Regression for the original capacity-refusal bug.

    A 5h reading of 0.01 means 1% USED (99% free). The old code read the raw
    value as a 0-1 fraction of "exhaustion" and held. The gate must dispatch.
    """
    snap = ug.normalize(_headers(util_5h="0.01", util_7d="0.02"), None)
    assert snap["windows"]["five_hour"]["percent_used"] == 1.0
    result = ug.decide(snap, max_utilization=85.0)
    assert result["decision"] == "dispatch", result


def test_rejected_status_holds_with_retry():
    snap = ug.normalize(
        _headers(status_5h="rejected", overall="rejected", retry_after="600"), None
    )
    result = ug.decide(snap, max_utilization=85.0)
    assert result["decision"] == "hold"
    assert "rejected" in result["reason"]
    assert result["retry_after_seconds"] == 600


def test_threshold_fallback_when_no_status():
    """When a -status header is absent, fall back to the percent threshold."""
    h = _headers(util_5h="0.90")
    del h["5h-status"]
    del h["status"]
    snap = ug.normalize(h, None)
    result = ug.decide(snap, max_utilization=85.0)
    assert result["decision"] == "hold"
    assert "90.0%" in result["reason"]


def test_high_status_allowed_overrides_high_number_is_not_assumed():
    """A high utilization still holds even if status says allowed, via threshold."""
    snap = ug.normalize(_headers(util_5h="0.95", status_5h="allowed"), None)
    result = ug.decide(snap, max_utilization=85.0)
    assert result["decision"] == "hold"


# --------------------------------------------------------------------------- #
# Pacing (per-window) decision path — the nightly catch-up model
# --------------------------------------------------------------------------- #
import time as _time

# Aggressive default: weekly linear 0→100, 5h flat 95.
PACING = {
    "seven_day": {"floor": 0, "ceiling": 100, "k": 1},
    "five_hour": {"floor": 95, "ceiling": 95, "k": 1},
}


def _reset_at(window_length_s, t):
    """`-reset` header (epoch s) for a window of that length at elapsed-fraction t."""
    return str(int(_time.time() + (1 - t) * window_length_s))


def test_pacing_holds_when_at_or_ahead_of_weekly_pace():
    """Mon AM (t≈0.05, target≈5%) with W_used=20% → ahead of pace, hold."""
    snap = ug.normalize(_headers(
        util_7d="0.20", util_5h="0.10",
        reset_7d=_reset_at(7 * 86400, 0.05),
        reset_5h=_reset_at(5 * 3600, 0.5),
    ), None)
    res = ug.decide(snap, windows=PACING)
    assert res["decision"] == "hold", res
    assert "pace target" in res["reason"]
    assert res["headroom_by_window"]["seven_day"] < 0


def test_pacing_dispatches_when_behind_pace_with_headroom():
    """Sat (t≈0.85, target≈85%) with W_used=30% → 55% behind pace → dispatch."""
    snap = ug.normalize(_headers(
        util_7d="0.30", util_5h="0.10",
        reset_7d=_reset_at(7 * 86400, 0.85),
        reset_5h=_reset_at(5 * 3600, 0.5),
    ), None)
    res = ug.decide(snap, windows=PACING)
    assert res["decision"] == "dispatch", res
    # Binding headroom = min(seven_day, five_hour). 5h is 95-10=85; 7d ≈ 85-30=55.
    assert 50 <= res["binding_headroom_pct"] <= 60
    assert res["headroom_by_window"]["seven_day"] > 50
    assert res["headroom_by_window"]["five_hour"] > 80


def test_pacing_five_hour_flat_holds_at_ceiling():
    """5h is floor==ceiling==95, so 96% used → hold regardless of weekly slack."""
    snap = ug.normalize(_headers(
        util_5h="0.96", util_7d="0.40",
        reset_7d=_reset_at(7 * 86400, 0.7),
        reset_5h=_reset_at(5 * 3600, 0.5),
    ), None)
    res = ug.decide(snap, windows=PACING)
    assert res["decision"] == "hold", res
    assert "five_hour" in res["reason"]


def test_pacing_user_example_hour_150_of_168():
    """User's example: at hour 150/168 (t=0.8929) target is 89.28%; W_used=88%
    means the agent has ~1.28% headroom on the weekly window — dispatches."""
    snap = ug.normalize(_headers(
        util_7d="0.88", util_5h="0.20",
        reset_7d=_reset_at(7 * 86400, 150 / 168),
        reset_5h=_reset_at(5 * 3600, 0.5),
    ), None)
    res = ug.decide(snap, windows=PACING)
    assert res["decision"] == "dispatch", res
    # Weekly headroom: allow(0.8929) - 88 ≈ 89.28 - 88 = 1.28 (binding).
    assert 1.0 <= res["headroom_by_window"]["seven_day"] <= 1.6


def test_pacing_authoritative_rejected_overrides_headroom():
    """Even with plenty of pacing slack, a 'rejected' status holds the gate."""
    snap = ug.normalize(_headers(
        util_5h="0.10", status_5h="rejected", overall="rejected", retry_after="900",
    ), None)
    res = ug.decide(snap, windows=PACING)
    assert res["decision"] == "hold"
    assert res["retry_after_seconds"] == 900


def test_pacing_overage_status_surfaced():
    """The overage status is exposed so callers can warn under the $0 policy."""
    snap = ug.normalize(_headers(util_5h="0.10", util_7d="0.10"), None)
    res = ug.decide(snap, windows=PACING)
    assert res["overage_status"] in ("allowed", "rejected", None)


def test_endpoint_scale_isolated_from_windows():
    """Endpoint utilization is 0-100; it must not contaminate the 0-100 windows
    (which we derived from 0-1 headers). Both end up percent, and the raw
    endpoint stays under its own key."""
    endpoint = {"five_hour": {"utilization": 10.0, "resets_at": "..."}}
    snap = ug.normalize(_headers(util_5h="0.09"), endpoint)
    assert snap["source"] == "headers+endpoint"
    assert snap["windows"]["five_hour"]["percent_used"] == 9.0  # from header, 0-1
    assert snap["endpoint_raw"]["five_hour"]["utilization"] == 10.0  # raw, 0-100


# --------------------------------------------------------------------------- #
# Token refresh — mocked HTTP + temp credentials file (no real network/creds)
# --------------------------------------------------------------------------- #
def _creds_file(tmp, *, refresh="rt-old", access="at-old", extra=None):
    path = os.path.join(tmp, "creds.json")
    oauth = {"accessToken": access, "refreshToken": refresh,
             "expiresAt": 1, "subscriptionType": "max", "scopes": ["a"]}
    if extra:
        oauth.update(extra)
    with open(path, "w") as fh:
        json.dump({"claudeAiOauth": oauth}, fh)
    os.chmod(path, 0o600)
    return path


def test_refresh_updates_credentials_atomically():
    with tempfile.TemporaryDirectory() as tmp:
        path = _creds_file(tmp)
        poster = lambda body: {"access_token": "at-new", "refresh_token": "rt-new",
                               "expires_in": 3600}
        res = ug.refresh_access_token(credentials_path=path, poster=poster, now=1_000_000.0)
        assert res["refreshed"]
        doc = json.load(open(path))["claudeAiOauth"]
        assert doc["accessToken"] == "at-new"
        assert doc["refreshToken"] == "rt-new"                 # rotated
        assert doc["expiresAt"] == int((1_000_000.0 + 3600) * 1000)  # ms
        assert doc["subscriptionType"] == "max"                # preserved
        assert os.path.exists(path + ".bak")                   # backup made
        assert oct(os.stat(path).st_mode & 0o777) == "0o600"   # perms kept


def test_refresh_request_body_shape():
    captured = {}
    with tempfile.TemporaryDirectory() as tmp:
        path = _creds_file(tmp, refresh="rt-xyz")
        def poster(body):
            captured.update(body)
            return {"access_token": "a", "expires_in": 1}
        ug.refresh_access_token(credentials_path=path, poster=poster, now=0)
    assert captured["grant_type"] == "refresh_token"
    assert captured["refresh_token"] == "rt-xyz"
    assert captured["client_id"] == ug.OAUTH_CLIENT_ID


def test_refresh_dry_run_sends_nothing_and_redacts():
    sent = []
    with tempfile.TemporaryDirectory() as tmp:
        path = _creds_file(tmp)
        before = open(path).read()
        out = ug.refresh_access_token(
            credentials_path=path, poster=lambda b: sent.append(b), dry_run=True)
        assert out["dry_run"] and out["body"]["refresh_token"] == "<redacted>"
        assert sent == []                       # never called the endpoint
        assert open(path).read() == before      # file untouched


def test_refresh_missing_refresh_token_errors():
    with tempfile.TemporaryDirectory() as tmp:
        path = _creds_file(tmp, refresh=None)
        try:
            ug.refresh_access_token(credentials_path=path, poster=lambda b: {})
        except ug.UsageError as exc:
            assert "refreshToken" in str(exc)
        else:
            raise AssertionError("expected UsageError")


def test_refresh_bad_response_leaves_file_intact():
    with tempfile.TemporaryDirectory() as tmp:
        path = _creds_file(tmp)
        before = open(path).read()
        try:
            ug.refresh_access_token(credentials_path=path,
                                    poster=lambda b: {"error": "nope"})
        except ug.UsageError:
            pass
        else:
            raise AssertionError("expected UsageError")
        assert open(path).read() == before      # no partial write before access check


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
    import sys
    sys.exit(_run_standalone())
