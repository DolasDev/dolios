#!/usr/bin/env python3
"""Tests for Matrix proposal approvals. No network: Matrix and gh are faked.
Runs under pytest or standalone: `python3 test_approvals.py`."""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import approvals as a

for _k in ("MATRIX_HOMESERVER", "MATRIX_ACCESS_TOKEN", "MATRIX_ALERT_ROOM",
           "MATRIX_ALLOWED_USERS"):
    os.environ.pop(_k, None)

STEVE = "@steve:hs"
BOT = "@bot:hs"
NOW_MS = 1_800_000_000_000


def proposal(slug, status="proposed", pitch=None, chunks=1, day="2026-11-15"):
    fm = [f"id:     dolios/{day}-{slug}", f"status: {status}", "repo:   dolios",
          "gap_ids:", f"  - gap-{slug}"]
    if pitch:
        fm += ["pitch: >-", f"  {pitch}"]
    fm += [f"opened:    {day}", "approved:  null", "done:      null"]
    boxes = "\n".join(f"- [ ] **Chunk {i}** do thing {i}" for i in range(1, chunks + 1))
    text = ("---\n" + "\n".join(fm) + "\n---\n\n"
            f"# Do the {slug} thing\n\n## Hypothesis\n\n"
            f"> Adopting **{slug}** should move `x.y_z` up. Second sentence here. "
            f"Third sentence dropped.\n\n## Intervention\n\n{boxes}\n")
    return f"proposals/dolios/{day}-{slug}.md", text


def files(*ps):
    return dict(ps)


PROPS = a.load_proposals(files(
    proposal("add-security-md", pitch="Adds a SECURITY.md. Low risk."),
    proposal("adopt-gitleaks-secrets-scanner", chunks=3),
    proposal("add-codeowners"),
    proposal("enable-dependabot", status="approved"),
    proposal("add-license-file", status="done", day="2026-11-14"),
))


def by(slug):
    return next(p for p in PROPS if p["slug"] == slug)


def msg(sender, body, age_s=60, eid=None):
    return {"sender": sender, "event_id": eid or f"$e{abs(hash((sender, body, age_s)))}",
            "origin_server_ts": NOW_MS - age_s * 1000,
            "content": {"msgtype": "m.text", "body": body}}


# --------------------------------------------------------------------------- #
def test_load_and_pitch():
    p = by("add-security-md")
    assert p["pitch"] == "Adds a SECURITY.md. Low risk."
    g = by("adopt-gitleaks-secrets-scanner")
    # Fallback: first two Hypothesis sentences, markdown stripped, ids intact.
    assert g["pitch"] == ("Adopting adopt-gitleaks-secrets-scanner should move "
                          "x.y_z up. Second sentence here."), g["pitch"]
    assert g["chunks"] == 3
    assert g["title"] == "Do the adopt-gitleaks-secrets-scanner thing"


def test_resolve():
    assert a.resolve("gitleaks", PROPS)[0]["slug"] == "adopt-gitleaks-secrets-scanner"
    assert a.resolve("`security`.", PROPS)[0]["slug"] == "add-security-md"
    p, err = a.resolve("add", PROPS)
    assert p is None and "ambiguous" in err
    p, err = a.resolve("nope", PROPS)
    assert p is None and "no proposal" in err
    # `license` only matches a done proposal — still resolvable (decide refuses later)
    assert a.resolve("license", PROPS)[0]["status"] == "done"


def test_digest_lists_pending_only_and_marks_new():
    with tempfile.TemporaryDirectory() as d:
        state = {"digested": [by("add-codeowners")["path"]],
                 "parked": [by("add-security-md")["path"]]}
        plain, rich, paths = a.compose_digest(PROPS, state, root=Path(d),
                                              web_base="https://x/blob/main")
    assert "waiting on you: 2 (1 parked)" in plain
    assert "add-security-md" not in plain.split("Approved")[0]
    assert "`adopt-gitleaks-secrets-scanner` (NEW, 3 chunks)" in plain
    assert "`add-codeowners` (1 chunk)" in plain
    assert "Approved / in progress: enable-dependabot" in plain
    assert "approve <name>" in plain and "<ol>" in rich
    assert "https://x/blob/main/proposals/dolios/" in plain
    assert len(paths) == 2


def test_digest_none_when_nothing_pending():
    only = a.load_proposals(files(proposal("x", status="approved")))
    assert a.compose_digest(only, {}, root=Path("."), web_base=None) is None


def test_apply_decision_approve_and_abandon():
    _, text = proposal("add-codeowners")
    out = a.apply_decision(text, "approve", "2026-11-16", "fine")
    assert "status: approved" in out and "approved:  2026-11-16" in out
    assert "# Do the add-codeowners thing\n\n> **Decision (human, 2026-11-16, " \
           "via Matrix): approved.** fine\n" in out
    out = a.apply_decision(text, "abandon", "2026-11-16", None)
    assert "status: abandoned" in out and "approved:  null" in out
    try:
        a.apply_decision(out, "approve", "2026-11-16", None)
    except ValueError:
        pass
    else:
        raise AssertionError("re-deciding a non-proposed file must fail")


# --------------------------------------------------------------------------- #
# Authorization — the guard that keeps the chat model from acting alone.
# --------------------------------------------------------------------------- #
def auth(events, verb="approve", slug="adopt-gitleaks-secrets-scanner",
         consumed=()):
    return a.find_authorization(events, verb, by(slug), PROPS, {STEVE},
                                NOW_MS, set(consumed))


def test_auth_accepts_exact_human_command():
    eid, _ = auth([msg(STEVE, "approve gitleaks", eid="$ok")])
    assert eid == "$ok"


def test_auth_ignores_reply_fallback_and_case():
    body = "> <@bot:hs> Dolios proposals waiting on you\n> approve codeowners\n\nApprove `gitleaks`"
    assert auth([msg(STEVE, body, eid="$r")])[0] == "$r"


def test_auth_rejects_bot_paraphrase_old_consumed_wrong_target():
    assert auth([msg(BOT, "approve gitleaks")])[0] is None          # not a human
    assert auth([msg(STEVE, "yes go ahead with gitleaks")])[0] is None
    assert auth([msg(STEVE, "approve gitleaks", age_s=3600)])[0] is None
    assert auth([msg(STEVE, "approve gitleaks", eid="$x")], consumed={"$x"})[0] is None
    assert auth([msg(STEVE, "approve codeowners")])[0] is None       # other proposal
    assert auth([msg(STEVE, "park gitleaks")])[0] is None            # other verb
    assert auth([msg(STEVE, "approve add")])[0] is None              # ambiguous ref


def test_auth_refuses_without_allowlist():
    eid, why = a.find_authorization([msg(STEVE, "approve gitleaks")], "approve",
                                    by("adopt-gitleaks-secrets-scanner"), PROPS,
                                    set(), NOW_MS, set())
    assert eid is None and "MATRIX_ALLOWED_USERS" in why


# --------------------------------------------------------------------------- #
# decide end-to-end with fakes
# --------------------------------------------------------------------------- #
class FakeMatrix:
    def __init__(self, events):
        self.events, self.allowed, self.sent = events, {STEVE}, []

    def recent_messages(self, limit=50):
        return self.events

    def send(self, text, html_body=None):
        self.sent.append(text)
        return True


class FakeRunner:
    """Serves proposal files via `git show` and records gh calls."""

    def __init__(self, fs):
        self.fs, self.calls, self.put = fs, [], None

    def __call__(self, cmd, cwd, stdin=None):
        self.calls.append(cmd)
        if cmd[:2] == ["git", "fetch"]:
            return 0, "", ""
        if cmd[:2] == ["git", "ls-tree"]:
            return 0, "\n".join(self.fs), ""
        if cmd[:2] == ["git", "show"]:
            return 0, self.fs[cmd[2].split(":", 1)[1]], ""
        if cmd[:3] == ["gh", "repo", "view"]:
            return 0, "Org/repo\n", ""
        if cmd[:2] == ["gh", "api"]:
            path = cmd[2]
            if "/contents/" in path and "--input" not in cmd:
                rel = path.split("/contents/")[1].split("?")[0]
                return 0, json.dumps({"sha": "blob1", "content":
                                      base64.b64encode(self.fs[rel].encode()).decode()}), ""
            if path.endswith("git/ref/heads/main"):
                return 0, json.dumps({"object": {"sha": "abc"}}), ""
            if path.endswith("git/refs"):
                return 0, "{}", ""
            if "--input" in cmd:
                self.put = json.loads(stdin)
                return 0, "{}", ""
        if cmd[:3] == ["gh", "pr", "create"]:
            return 0, "https://github.com/Org/repo/pull/99\n", ""
        if cmd[:3] == ["gh", "pr", "merge"]:
            return 0, "", ""
        return 1, "", f"unexpected {cmd}"


def run_decide(argv, events, fs=None):
    fs = fs or files(proposal("add-security-md"),
                     proposal("adopt-gitleaks-secrets-scanner", chunks=3))
    runner = FakeRunner(fs)
    mx = FakeMatrix(events)
    with tempfile.TemporaryDirectory() as d:
        sp = Path(d) / "state.json"
        args = SimpleNamespace(ref=argv[0], verb=argv[1], note=None)
        rc = a.cmd_decide(args, root=Path(d), state_path=sp, runner=runner,
                          matrix=mx, now_ms=NOW_MS)
        state = a.load_state(sp)
    return rc, runner, state


def test_decide_approve_opens_pr_and_consumes_event():
    rc, r, state = run_decide(["gitleaks", "approve"],
                              [msg(STEVE, "approve gitleaks", eid="$go")])
    assert rc == 0
    new = base64.b64decode(r.put["content"]).decode()
    assert "status: approved" in new and r.put["branch"].startswith(
        "proposal/approve-adopt-gitleaks-secrets-scanner-")
    assert any(c[:3] == ["gh", "pr", "merge"] and "--auto" in c for c in r.calls)
    assert state["consumed_events"] == ["$go"]


def test_decide_refuses_without_human_command():
    rc, r, state = run_decide(["gitleaks", "approve"],
                              [msg(STEVE, "sure, sounds good")])
    assert rc == 3 and r.put is None and not state
    assert not any(c[:2] == ["gh", "api"] for c in r.calls)


def test_decide_park_is_local_only():
    rc, r, state = run_decide(["security", "park"], [msg(STEVE, "park security")])
    assert rc == 0 and r.put is None
    assert state["parked"] == ["proposals/dolios/2026-11-15-add-security-md.md"]


def test_decide_refuses_non_proposed():
    fs = files(proposal("enable-dependabot", status="approved"))
    rc, r, _ = run_decide(["dependabot", "approve"],
                          [msg(STEVE, "approve dependabot")], fs=fs)
    assert rc == 2 and r.put is None


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {exc!r}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
