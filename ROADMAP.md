# Roadmap

Phased plan toward the dolios fleet (see [`README.md`](README.md) for the
mission). Each employee is a hermes-agent **profile**; the fleet is built by
making the profile framework solid first, then filling in roles.

Legend: ✅ done · 🔨 in progress · ⏳ next · 🔒 blocked

---

## Phase 0 — Foundation ✅

- ✅ Local model selected + verified (`qwen3.6:35b-a3b`; see `MODEL_OPTIONS.md`).
- ✅ Single-GPU switching (`infra/gpu-stack.sh`, `make llm-up`).
- ✅ Spare-capacity gate (`services/usage-gate/`) — normalized usage contract.
- ✅ Postgres scaffold (`docker-compose.yml`).

## Phase 1 — Provider path (local **+** OpenRouter) 🔨 (host smoke-test pending)

Make "pick local or external per employee" real and tested.

- ✅ Default OpenRouter model chosen + slug verified against the live models API:
      `qwen/qwen3-235b-a22b-2507` (same family as local qwen3.6, `tools=True`).
      Alternatives recorded in `MODEL_OPTIONS.md`.
- ✅ OpenRouter wired into `autonomous-coder` config as a local-primary fallback;
      `config.yaml` snippets (OpenRouter-primary and fallback) in `MODEL_OPTIONS.md`.
- ✅ Secret handling documented: `OPENROUTER_API_KEY` in each profile's
      `~/.hermes/profiles/<role>/.env` (via `env.example`), **never** in this repo.
- [ ] **Host smoke-test** (needs hermes installed + a real key — can't run on the
      dev box). On the host:
  1. Put `OPENROUTER_API_KEY=sk-or-…` in `~/.hermes/profiles/autonomous-coder/.env`.
  2. Temporarily set `model.provider: openrouter` /
     `default: openrouter/qwen/qwen3-235b-a22b-2507`; run
     `hermes -p autonomous-coder chat -q "call a tool"` → confirm a real call +
     tool-calling works. **Confirm the `openrouter/` prefix convention here.**
  3. Restore local primary; stop dolo-llm Ollama (`make llm-down`) and run again →
     confirm it **fails over** to the OpenRouter fallback.
  4. Bring Ollama back up; confirm it prefers local again.

## Phase 2 — Employee / profile framework ✅ (host smoke-test pending)

The reproducibility backbone: an employee is a checked-in spec, not a
hand-built profile.

- ✅ Probed hermes-agent mechanics — `config.yaml`/`SOUL.md` are read on startup,
      so file-based materialization works; full schema captured.
- ✅ On-disk layout: `employees/<role>/` holds `SOUL.md` + `config.yaml` template
      + `env.example` + `README.md`, **minus secrets**.
- ✅ Tracked (SOUL.md, config, env.example) vs runtime (`.env`, sessions, memory,
      state DB) split; runtime stays out of git.
- ✅ Materializer `scripts/materialize-employee.sh` (`make employee ROLE=…`):
      idempotent, backs up + diffs drift, seeds `.env` only if absent, never
      touches runtime state. `DRY_RUN=1` supported. Verified against a temp base.
- ✅ Two role specs: `autonomous-coder` (fleshed out) + `sim-mover` (stub).
- [ ] **Pending:** live smoke-test on the actual host (hermes not installed on
      the dev box) — materialize a profile and confirm hermes loads SOUL.md +
      model config.

## Phase 3 — Role: `autonomous-coder` ⏳

Builds directly on the usage gate. Local model supervises; Claude Code (or an
OpenRouter model) does the engineering.

- [ ] **Usage-gate token refresh** (open item) — implement the OAuth
      `refresh_token` grant so unattended runs survive token expiry.
- [ ] Guardrails: work on branches + open PRs (never push `main`), per-repo
      allowlist, hard per-window token budget.
- [ ] Repo registry — which Dolios applications the coder may touch.
- [ ] The supervisor loop (profile cron): gate → pick backlog task → dispatch
      `claude -p … --output-format json` → record outcome to Postgres → loop.

## Phase 4 — Role: `sim-mover` 🔒 (blocked on Pegasus)

Blocked: the Pegasus API exposes only customers/documents today; the jobs/moves
domain is still being built out.

- [ ] (When jobs land) Pegasus MCP server under `services/pegasus-mcp/` —
      generated from the OpenAPI spec, **curated** to the verbs a rep needs,
      wrapped for `Authorization: Bearer` auth (server-side secret) + guardrails
      (read-only first, allowlist, validation).
- [ ] `sim-mover` SOUL.md + config (local model + Pegasus MCP tools).
- [ ] Optional early start: a read-only customers/documents MCP server now, as
      foundation that carries over when jobs ship.

## Phase 5 — Fleet orchestration & state ⏳

- [ ] Postgres schema: employee registry, task queue/backlog, run history,
      schedules.
- [ ] Fleet status/observability (`make fleet-status`): who's running, on which
      model, recent runs, capacity.
- [ ] Cost/usage accounting per employee (local "free" vs OpenRouter spend).

---

## Cross-cutting concerns

- **Secrets** — per-profile `.env` only; nothing sensitive in this repo.
- **Guardrails** — every employee with write/dispatch power needs an explicit
  allowlist + budget before it runs unattended.
- **Reproducibility** — the fleet must be rebuildable from this repo +
  per-host secrets, nothing hand-tweaked and forgotten.

## Immediate next step

Phase 1 + 2 are the unblocked, highest-leverage work: prove the OpenRouter path,
then define the `employees/<role>/` framework so every later role is just a spec.
`autonomous-coder` (Phase 3) is the first role we can fully build today, since
`sim-mover` waits on Pegasus.
