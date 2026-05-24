# usage-gate

The orchestrator's **spare-capacity gate**: before dispatching a Claude Code
task, ask whether the Anthropic subscription has headroom. Emits a normalized,
**unit-labelled** JSON contract so the orchestrator model never has to interpret
a raw, ambiguously-scaled utilization number.

```sh
make usage          # normalized usage snapshot (JSON)
make usage-decide   # dispatch/hold decision; exits 1 on hold
make usage-test     # offline regression tests
```

Or directly:

```sh
python3 services/usage-gate/usage_gate.py [--decide] [--max-utilization 85] [--no-enrich]
```

## Why it exists — the bug it fixes

The undocumented `GET /api/oauth/usage` endpoint reports utilization on a
**percent** scale (0-100): `five_hour: 1.0` = 1% used. The orchestrator model,
pattern-matching on the far more common **0-1** rate-limit-header convention,
read `1.0` as "100% used" and wrongly refused to dispatch. Two sources, two
scales, no units — a data-presentation trap. Proven live (same instant):

| Window | Header `…-5h-utilization` | Endpoint `five_hour.utilization` |
|---|---|---|
| five_hour | `0.09`  (**0-1 scale**) | `10.0`  (**0-100 scale**) |

Same ~10% reality, 100× apart. The gate normalizes everything to one contract
with named units (`percent_used`, `percent_remaining`) and, better, gates on
Anthropic's **authoritative `…-status: allowed|rejected`** signal rather than
asking the model to threshold a number at all.

## Sources (approach "B + enrichment")

- **PRIMARY — rate-limit headers** off a 1-token `/v1/messages` ping. Same
  numbers Claude Code's own `/usage` shows. Carries per-window
  `…-utilization` (0-1), `…-status`, `…-reset`, and `representative-claim`
  (which window currently binds). The gate **fails closed** if the OAuth token
  is rejected.
- **ENRICH — `GET /api/oauth/usage`** (undocumented). Adds per-model
  breakdowns (`seven_day_sonnet`/`opus`) the headers lack. Best-effort; never
  required; kept under `endpoint_raw` so its different scale can't be confused
  with the normalized windows. Skip with `--no-enrich`.

## Auth

Reads the OAuth token from `~/.claude/.credentials.json` (`claudeAiOauth`).
Requests use `Authorization: Bearer <token>`, `anthropic-beta:
oauth-2025-04-20`, and a Claude-Code system-prompt preamble (required for the
OAuth path to resolve a model). The ping model is a current Haiku — OAuth
subscription tokens only resolve models Claude Code itself uses.

## Output contract

```json
{
  "ok": true,
  "checked_at": "2026-05-24T01:46:14Z",
  "source": "headers+endpoint",
  "overall_status": "allowed",
  "binding_window": "five_hour",
  "windows": {
    "five_hour": {
      "status": "allowed",
      "percent_used": 9.0,
      "percent_remaining": 91.0,
      "resets_at": "2026-05-24T02:20:00Z",
      "resets_in_seconds": 2026
    },
    "seven_day": { "...": "..." }
  },
  "overage": { "status": "rejected", "disabled_reason": "org_level_disabled" },
  "retry_after_seconds": null
}
```

`--decide` wraps this in `{ "decision": "dispatch"|"hold", "reason", ...,
"snapshot" }` and sets exit code 1 on `hold`.

## Token refresh

For unattended operation the gate can refresh the OAuth token itself:

```sh
python3 usage_gate.py --refresh-dry-run   # show the request; send/write nothing
python3 usage_gate.py --refresh           # DESTRUCTIVE: rotate + rewrite creds
python3 usage_gate.py --decide --auto-refresh   # refresh only if expired, then check
```

It POSTs a `refresh_token` grant to `https://api.anthropic.com/v1/oauth/token`
(the `console.anthropic.com` endpoint is behind a Cloudflare challenge that
blocks programmatic clients) with Claude Code's public `client_id`. On success
it **rotates** the refresh token and **rewrites `~/.claude/.credentials.json`** —
so it backs up the old file to `.credentials.json.bak` first and writes the new
one atomically (temp file + rename) at `0600`. A bad/empty response aborts
*before* any write, leaving the file intact.

> ⚠️ This rotates your real Claude credentials. The endpoint and `client_id` are
> undocumented. Validate with `--refresh-dry-run` first; run a real `--refresh`
> only when you're ready. Logic is unit-tested with a mocked endpoint + temp
> file (`test_usage_gate.py`); the dry-run is verified against the real file.

## Known limitations / open work
- The `/api/oauth/usage` endpoint is **undocumented** and can change without
  notice. The gate degrades gracefully (headers alone are sufficient).
- The ping consumes a negligible slice of quota (`max_tokens: 1`); it is itself
  reflected in the very numbers it reads.
