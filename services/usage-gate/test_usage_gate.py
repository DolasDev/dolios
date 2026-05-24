#!/usr/bin/env python3
"""Tests for the spare-capacity gate.

These exercise normalize() and decide() against synthetic header/endpoint data
— no network — so the scale-normalization fix is locked in as a regression.
Runs under pytest, or standalone: `python3 test_usage_gate.py`.

The headline test is `test_low_utilization_does_not_hold`: it reproduces the
exact reading that originally caused a wrong "capacity exhausted" refusal and
asserts the gate now dispatches.
"""

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


def test_endpoint_scale_isolated_from_windows():
    """Endpoint utilization is 0-100; it must not contaminate the 0-100 windows
    (which we derived from 0-1 headers). Both end up percent, and the raw
    endpoint stays under its own key."""
    endpoint = {"five_hour": {"utilization": 10.0, "resets_at": "..."}}
    snap = ug.normalize(_headers(util_5h="0.09"), endpoint)
    assert snap["source"] == "headers+endpoint"
    assert snap["windows"]["five_hour"]["percent_used"] == 9.0  # from header, 0-1
    assert snap["endpoint_raw"]["five_hour"]["utilization"] == 10.0  # raw, 0-100


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
