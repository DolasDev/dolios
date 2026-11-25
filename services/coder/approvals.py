#!/usr/bin/env python3
"""Human approval of proposals over Matrix (Element).

The loop drafts proposals overnight and merges them as `status: proposed`.
Only a human may flip a proposal to `approved`. This module lets that human
do it from their phone:

  digest              Morning Matrix message listing every pending proposal
                      with a plain-English pitch and the reply commands.
                      Runs from the `dolios-approvals-digest` cron job.
  list                Print the pending proposals (for the chat agent).
  decide <ref> <verb> Apply a human decision: `approve` / `abandon` open a
                      PR that edits the proposal on main (via the GitHub API,
                      never the shared working tree) and queue auto-merge.
                      `park` hides it from future digests (local state only;
                      the proposal stays `proposed`, so its gap stays covered).

The chat agent (hermes, local model) runs `decide` when the human asks it to.
`decide` does not trust the model: before acting it re-reads the Matrix room
and requires a recent message FROM AN ALLOWED HUMAN (MATRIX_ALLOWED_USERS)
that literally says `<verb> <ref>` and resolves to the same proposal. Each
such message authorizes exactly one decision (replay-protected by event id).

<ref> is a unique substring of the proposal slug (filename minus the date),
e.g. `gitleaks` for `2026-11-15-adopt-gitleaks-secrets-scanner.md`.

Env: MATRIX_HOMESERVER, MATRIX_ACCESS_TOKEN, MATRIX_ALERT_ROOM,
MATRIX_ALLOWED_USERS (all in the hermes profile .env); GH_TOKEN for gh.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOLIOS_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

import chunks as ch  # noqa: E402

DEFAULT_STATE = DOLIOS_ROOT / ".dolios" / "approvals-state.json"

# A human command older than this does not authorize a decision.
COMMAND_MAX_AGE_S = 30 * 60
VERBS = ("approve", "abandon", "park")
PITCH_MAX = 420

Runner = Callable[[list[str], Path], "tuple[int, str, str]"]


def _real_runner(cmd: list[str], cwd: Path, stdin: str | None = None
                 ) -> tuple[int, str, str]:
    p = subprocess.run(cmd, cwd=cwd, input=stdin, capture_output=True,
                       text=True, timeout=120)
    return p.returncode, p.stdout, p.stderr


# --------------------------------------------------------------------------- #
# Proposal loading
# --------------------------------------------------------------------------- #
def split_frontmatter(text: str) -> tuple[dict, str]:
    try:
        import yaml
    except ImportError:
        sys.exit("ERROR: pyyaml missing — run this via "
                 "/opt/data/profiles/autonomous-coder/scripts/dolios-approvals.sh")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    try:
        fm = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, text[end + 5:]


def slug_of(path: str) -> str:
    """`proposals/dolios/2026-11-15-add-security-md.md` → `add-security-md`."""
    stem = Path(path).stem
    return re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem)


def _strip_md(s: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)   # links → text
    s = re.sub(r"[*`]+|^\s*>\s?", "", s, flags=re.M)
    return re.sub(r"\s+", " ", s).strip()


def pitch_of(fm: dict, body: str) -> str:
    """The proposal's `pitch:` frontmatter, else the first two sentences of
    its Hypothesis section (older proposals predate the field)."""
    pitch = fm.get("pitch")
    if isinstance(pitch, str) and pitch.strip():
        return re.sub(r"\s+", " ", pitch).strip()
    m = re.search(r"^## Hypothesis\s*\n(.*?)(?=^## |\Z)", body, re.S | re.M)
    text = _strip_md(m.group(1)) if m else ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = " ".join(sentences[:2]).strip()
    if len(out) > PITCH_MAX:
        out = out[:PITCH_MAX - 1].rstrip() + "…"
    return out or "(no summary — read the file)"


def title_of(body: str, fallback: str) -> str:
    m = re.search(r"^# (.+)$", body, re.M)
    return _strip_md(m.group(1)) if m else fallback


def load_proposals(files: dict[str, str]) -> list[dict]:
    """`files` maps repo-relative path → text. Returns one dict per
    proposal with frontmatter + derived fields."""
    out = []
    for path, text in sorted(files.items()):
        if Path(path).name.startswith("_") or not path.endswith(".md"):
            continue
        fm, body = split_frontmatter(text)
        if not fm.get("status"):
            continue
        out.append({
            "path": path,
            "slug": slug_of(path),
            "status": str(fm.get("status")).strip(),
            "repo": fm.get("repo") or Path(path).parent.name,
            "gap_ids": fm.get("gap_ids") or [],
            "title": title_of(body, slug_of(path)),
            "pitch": pitch_of(fm, body),
            "chunks": len(ch.parse_chunks(text)),
            "text": text,
        })
    return out


def read_proposal_files(root: Path, ref: str | None, runner: Runner = None
                        ) -> dict[str, str]:
    """Proposal markdown at `ref` (e.g. `origin/main`, after a fetch) without
    touching the working tree — the checkout is shared with the tick. Falls
    back to the working tree when ref is None or git fails."""
    runner = runner or _real_runner
    if ref:
        rc, out, _ = runner(["git", "fetch", "-q", "origin", "main"], root)
        rc2, names, _ = runner(["git", "ls-tree", "-r", "--name-only", ref,
                                "proposals/"], root)
        if rc == 0 and rc2 == 0:
            files = {}
            for name in names.split():
                if name.endswith(".md") and name.count("/") >= 2:
                    rc3, text, _ = runner(["git", "show", f"{ref}:{name}"], root)
                    if rc3 == 0:
                        files[name] = text
            return files
    files = {}
    for p in sorted((root / "proposals").glob("*/*.md")):
        files[str(p.relative_to(root))] = p.read_text(encoding="utf-8")
    return files


def resolve(ref: str, proposals: list[dict]) -> tuple[dict | None, str]:
    """Unique-substring match of `ref` against proposal slugs (pending ones
    preferred). Returns (proposal, error)."""
    ref = ref.strip().lower().strip("`'\".,!")
    if not ref:
        return None, "empty reference"
    exact = [p for p in proposals if p["slug"] == ref]
    if len(exact) == 1:
        return exact[0], ""
    hits = [p for p in proposals if ref in p["slug"]]
    pending = [p for p in hits if p["status"] == "proposed"]
    if len(pending) == 1:
        return pending[0], ""
    if len(hits) == 1:
        return hits[0], ""
    if not hits:
        return None, f"no proposal matches `{ref}`"
    return None, (f"`{ref}` is ambiguous: "
                  + ", ".join(p["slug"] for p in hits))


# --------------------------------------------------------------------------- #
# State (.dolios/approvals-state.json, gitignored, per host)
# --------------------------------------------------------------------------- #
def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(path)


# --------------------------------------------------------------------------- #
# Matrix
# --------------------------------------------------------------------------- #
class Matrix:
    def __init__(self, hs: str, token: str, room: str, allowed: set[str]):
        self.hs, self.token, self.room = hs.rstrip("/"), token, room
        self.allowed = allowed

    @classmethod
    def from_env(cls, env=os.environ) -> Matrix | None:
        hs, token = env.get("MATRIX_HOMESERVER"), env.get("MATRIX_ACCESS_TOKEN")
        room = env.get("MATRIX_ALERT_ROOM")
        if not (hs and token and room):
            return None
        allowed = {u.strip() for u in env.get("MATRIX_ALLOWED_USERS", "").split(",")
                   if u.strip()}
        return cls(hs, token, room, allowed)

    def _req(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self.hs}/_matrix/client/v3/rooms/{urllib.parse.quote(self.room, safe='')}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read() or b"{}")

    def send(self, text: str, html_body: str | None = None) -> bool:
        content = {"msgtype": "m.text", "body": text}
        if html_body:
            content |= {"format": "org.matrix.custom.html",
                        "formatted_body": html_body}
        try:
            self._req("PUT", f"/send/m.room.message/dolios-approvals-{time.time_ns()}",
                      content)
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"approvals: matrix send failed: {exc}", file=sys.stderr)
            return False

    def recent_messages(self, limit: int = 50) -> list[dict]:
        q = urllib.parse.urlencode({
            "dir": "b", "limit": limit,
            "filter": json.dumps({"types": ["m.room.message"]}),
        })
        return self._req("GET", f"/messages?{q}").get("chunk", [])


def _command_text(body: str) -> str:
    """Drop Matrix reply fallback (`> quoted` lines) from a message body."""
    lines = [ln for ln in body.splitlines() if not ln.startswith(">")]
    return "\n".join(lines).strip()


CMD_RE = re.compile(r"^\s*(approve|abandon|park)\s+`?([\w.-]+)`?", re.I | re.M)


def find_authorization(events: list[dict], verb: str, target: dict,
                       proposals: list[dict], allowed: set[str], now_ms: int,
                       consumed: set[str]) -> tuple[str | None, str]:
    """Return (event_id, "") of an unconsumed, recent message from an allowed
    human that says `<verb> <ref>` where <ref> resolves to `target`."""
    if not allowed:
        return None, "MATRIX_ALLOWED_USERS is empty — refusing to act"
    for ev in events:  # newest first
        if ev.get("sender") not in allowed:
            continue
        if now_ms - int(ev.get("origin_server_ts", 0)) > COMMAND_MAX_AGE_S * 1000:
            break
        eid = ev.get("event_id")
        if not eid or eid in consumed:
            continue
        body = _command_text((ev.get("content") or {}).get("body", ""))
        for m in CMD_RE.finditer(body):
            if m.group(1).lower() != verb:
                continue
            hit, _ = resolve(m.group(2), proposals)
            if hit and hit["path"] == target["path"]:
                return eid, ""
    return None, (f"no recent message from you saying `{verb} {target['slug']}` "
                  f"(within {COMMAND_MAX_AGE_S // 60} min) — send it in the "
                  f"alerts room and I'll apply it")


# --------------------------------------------------------------------------- #
# Digest
# --------------------------------------------------------------------------- #
def _gap_severity(root: Path, p: dict) -> str | None:
    hist = root / ".dolios" / "metrics" / str(p["repo"]) / "history.jsonl"
    try:
        last = [ln for ln in hist.read_text().splitlines() if ln.strip()][-1]
        gaps = json.loads(last).get("gaps") or []
    except (OSError, IndexError, ValueError):
        return None
    for g in gaps:
        if g.get("gap_id") in p["gap_ids"]:
            return g.get("severity")
    return None


def compose_digest(proposals: list[dict], state: dict, *, root: Path,
                   web_base: str | None) -> tuple[str, str, list[str]] | None:
    """(plain, html, pending_slugs) or None if nothing is pending."""
    parked = set(state.get("parked", []))
    seen = set(state.get("digested", []))
    pending = [p for p in proposals if p["status"] == "proposed"
               and p["path"] not in parked]
    if not pending:
        return None
    active = [p for p in proposals if p["status"] in ("approved", "implementing")]
    n_parked = sum(1 for p in proposals
                   if p["status"] == "proposed" and p["path"] in parked)

    head = (f"Dolios proposals waiting on you: {len(pending)}"
            + (f" ({n_parked} parked)" if n_parked else ""))
    plain, rich = [head, ""], [f"<p><b>{html.escape(head)}</b></p><ol>"]
    for p in pending:
        sev = _gap_severity(root, p)
        meta = ", ".join(x for x in (
            "NEW" if p["path"] not in seen else None,
            sev, f"{p['chunks']} chunk{'s' if p['chunks'] != 1 else ''}",
        ) if x)
        link = f"{web_base}/{p['path']}" if web_base else p["path"]
        plain += [f"• {p['title']} — `{p['slug']}` ({meta})", f"  {p['pitch']}",
                  f"  {link}", ""]
        rich.append(
            f"<li><b>{html.escape(p['title'])}</b> — <code>{html.escape(p['slug'])}</code>"
            f" <i>({html.escape(meta)})</i><br>{html.escape(p['pitch'])}"
            f"<br><a href=\"{html.escape(link)}\">read the proposal</a></li>")
    rich.append("</ol>")
    if active:
        line = "Approved / in progress: " + ", ".join(p["slug"] for p in active)
        plain.append(line)
        rich.append(f"<p>{html.escape(line)}</p>")
    howto = ("Reply `approve <name>`, `park <name>` (hide it, keep it on file) "
             "or `abandon <name>` — any unique part of the name works, e.g. "
             f"`approve {pending[0]['slug'].split('-')[-1]}`. "
             "Or just ask me about any of them.")
    plain.append(howto)
    rich.append(f"<p>{html.escape(howto)}</p>")
    return "\n".join(plain), "".join(rich), [p["path"] for p in pending]


def _web_base(root: Path, runner: Runner) -> str | None:
    rc, out, _ = runner(["gh", "repo", "view", "--json", "url", "-q", ".url"], root)
    return f"{out.strip()}/blob/main" if rc == 0 and out.strip() else None


def cmd_digest(args, *, root: Path, state_path: Path, runner: Runner,
               matrix: Matrix | None) -> int:
    proposals = load_proposals(read_proposal_files(root, "origin/main", runner))
    state = load_state(state_path)
    msg = compose_digest(proposals, state, root=root,
                         web_base=_web_base(root, runner))
    if msg is None:
        print(json.dumps({"digest": "nothing pending"}))
        return 0
    plain, rich, paths = msg
    sent = matrix.send(plain, rich) if matrix and not args.dry_run else False
    if args.dry_run or not matrix:
        print(plain)
    if sent:
        state["digested"] = sorted(set(state.get("digested", [])) | set(paths))
        state["last_digest"] = time.time()
        save_state(state_path, state)
    print(json.dumps({"digest": "sent" if sent else "not sent",
                      "pending": len(paths)}))
    return 0


def cmd_list(args, *, root: Path, state_path: Path, runner: Runner, **_) -> int:
    proposals = load_proposals(read_proposal_files(root, "origin/main", runner))
    parked = set(load_state(state_path).get("parked", []))
    for p in proposals:
        if p["status"] not in ("proposed", "approved", "implementing"):
            continue
        tag = "parked" if p["path"] in parked else p["status"]
        print(f"[{tag}] {p['slug']} — {p['title']}\n    {p['pitch']}\n    {p['path']}")
    return 0


# --------------------------------------------------------------------------- #
# Decide
# --------------------------------------------------------------------------- #
def apply_decision(text: str, verb: str, today: str, note: str | None) -> str:
    """Flip frontmatter status and insert a Decision note under the title."""
    new_status = {"approve": "approved", "abandon": "abandoned"}[verb]
    out, n = re.subn(r"^status:(\s*)proposed\b", rf"status:\g<1>{new_status}",
                     text, count=1, flags=re.M)
    if n != 1:
        raise ValueError("frontmatter has no `status: proposed`")
    if verb == "approve":
        out = re.sub(r"^approved:(\s*)null\b", rf"approved:\g<1>{today}", out,
                     count=1, flags=re.M)
    label = "approved" if verb == "approve" else "abandoned"
    decision = f"> **Decision (human, {today}, via Matrix): {label}.**"
    if note:
        decision += " " + re.sub(r"\s+", " ", note).strip()
    return re.sub(r"(\n---\n\n# [^\n]+\n)", lambda m: m.group(1) + "\n" + decision + "\n",
                  out, count=1)


def _gh_json(runner: Runner, root: Path, args: list[str],
             stdin: str | None = None) -> dict:
    """`runner` takes an optional third arg: text piped to stdin."""
    cmd = ["gh", "api", *args]
    if stdin is None:
        rc, out, err = runner(cmd, root)
    else:
        rc, out, err = runner(cmd + ["--input", "-"], root, stdin)
    if rc != 0:
        raise RuntimeError(f"gh api {args[0]} failed: {(err or out).strip()[:300]}")
    return json.loads(out or "{}")


def open_decision_pr(p: dict, verb: str, note: str | None, *, root: Path,
                     runner: Runner, today: str) -> str:
    """Branch + commit + PR + auto-merge, entirely through the GitHub API, so
    the shared working tree (and the tick's sync) are never disturbed."""
    rc, nwo, err = runner(["gh", "repo", "view", "--json", "nameWithOwner",
                           "-q", ".nameWithOwner"], root)
    if rc != 0:
        raise RuntimeError(f"gh repo view failed: {err.strip()[:200]}")
    nwo = nwo.strip()
    cur = _gh_json(runner, root, [f"repos/{nwo}/contents/{p['path']}?ref=main"])
    text = base64.b64decode(cur["content"]).decode()
    new_text = apply_decision(text, verb, today, note)
    head = _gh_json(runner, root, [f"repos/{nwo}/git/ref/heads/main"])["object"]["sha"]
    branch = f"proposal/{verb}-{p['slug']}-{int(time.time())}"
    _gh_json(runner, root, [f"repos/{nwo}/git/refs", "-X", "POST",
                            "-f", f"ref=refs/heads/{branch}", "-f", f"sha={head}"])
    label = "approve" if verb == "approve" else "abandon"
    try:
        # PUT is required: `gh api --input` defaults to POST, which the
        # contents endpoint answers with a misleading 404 (2026-11-25).
        _gh_json(runner, root, [f"repos/{nwo}/contents/{p['path']}", "-X", "PUT"],
                 stdin=json.dumps({
                     "message": f"proposal({p['repo']}): {label} {p['slug']}\n\n"
                                f"Human decision sent over Matrix.",
                     "content": base64.b64encode(new_text.encode()).decode(),
                     "sha": cur["sha"], "branch": branch,
                 }))
        rc, url, err = runner(["gh", "pr", "create", "--repo", nwo, "--base", "main",
                               "--head", branch,
                               "--title", f"proposal({p['repo']}): {label} {p['slug']}",
                               "--body", f"Human decision ({verb}) sent over Matrix for "
                                         f"`{p['path']}`." + (f"\n\nNote: {note}" if note else "")],
                               root)
        if rc != 0:
            raise RuntimeError(f"gh pr create failed: {(err or url).strip()[:300]}")
    except RuntimeError:
        # Don't leave a half-made branch behind for the next attempt.
        runner(["gh", "api", f"repos/{nwo}/git/refs/heads/{branch}", "-X", "DELETE"], root)
        raise
    url = url.strip().splitlines()[-1]
    rc, out, err = runner(["gh", "pr", "merge", url, "--auto", "--squash",
                           "--delete-branch"], root)
    if rc != 0:
        raise RuntimeError(f"PR {url} opened but auto-merge failed: "
                           f"{(err or out).strip()[:200]}")
    return url


def cmd_decide(args, *, root: Path, state_path: Path, runner: Runner,
               matrix: Matrix | None, now_ms: int | None = None) -> int:
    verb = args.verb.lower()
    proposals = load_proposals(read_proposal_files(root, "origin/main", runner))
    p, err = resolve(args.ref, proposals)
    if not p:
        print(f"ERROR: {err}")
        return 2
    if p["status"] != "proposed":
        print(f"ERROR: `{p['slug']}` is `{p['status']}`, not `proposed` — nothing to do")
        return 2
    if matrix is None:
        print("ERROR: Matrix env missing — cannot verify the human's command "
              "(run via /opt/data/profiles/autonomous-coder/scripts/dolios-approvals.sh)")
        return 2
    state = load_state(state_path)
    consumed = set(state.get("consumed_events", []))
    try:
        events = matrix.recent_messages()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not read the Matrix room to verify: {exc}")
        return 2
    eid, why = find_authorization(events, verb, p, proposals, matrix.allowed,
                                  now_ms or int(time.time() * 1000), consumed)
    if not eid:
        print(f"REFUSED: {why}")
        return 3

    if verb == "park":
        state["parked"] = sorted(set(state.get("parked", [])) | {p["path"]})
        result = (f"Parked `{p['slug']}`: it stays `proposed` (so the loop won't "
                  f"redraft it) but leaves the morning digest.")
    else:
        try:
            url = open_decision_pr(p, verb, args.note, root=root, runner=runner,
                                   today=date.today().isoformat())
        except RuntimeError as exc:
            print(f"ERROR: {exc}")
            return 1
        result = (f"{'Approved' if verb == 'approve' else 'Abandoned'} "
                  f"`{p['slug']}` — {url} (auto-merges when CI is green).")
        if verb == "approve":
            result += " The coder picks it up on its next overnight tick."
        else:
            result += (" Note: an abandoned proposal no longer covers its gap, "
                       "so the loop may draft a fresh proposal for it later.")
    state["consumed_events"] = (sorted(consumed | {eid}))[-200:]
    save_state(state_path, state)
    print(result)
    return 0


# --------------------------------------------------------------------------- #
def main(argv=None, *, runner: Runner | None = None, matrix=None,
         root: Path = DOLIOS_ROOT, state_path: Path = DEFAULT_STATE) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("digest", help="send the pending-proposal digest")
    d.add_argument("--dry-run", action="store_true", help="print, don't send")
    sub.add_parser("list", help="print active/pending proposals")
    x = sub.add_parser("decide", help="apply a human decision")
    x.add_argument("ref")
    x.add_argument("verb", choices=VERBS)
    x.add_argument("--note", help="one-line reason, recorded in the proposal")
    args = ap.parse_args(argv)

    runner = runner or _real_runner
    if matrix is None:
        matrix = Matrix.from_env()
    fn = {"digest": cmd_digest, "list": cmd_list, "decide": cmd_decide}[args.cmd]
    return fn(args, root=root, state_path=state_path, runner=runner, matrix=matrix)


if __name__ == "__main__":
    sys.exit(main())
