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

## Phase 1 — Provider path (local **+** OpenRouter) ⏳

Make "pick local or external per employee" real and tested.

- [ ] Add the OpenRouter provider to a throwaway profile; verify a live model
      call end-to-end through hermes-agent.
- [ ] Confirm fallback-provider behavior (prefer local → fall back to OpenRouter).
- [ ] Decide default model per role (local supervisor vs frontier coder).
- [ ] Document secret handling: `OPENROUTER_API_KEY` lives in each profile's
      `~/.hermes/profiles/<role>/.env`, **never** in this repo.

## Phase 2 — Employee / profile framework ⏳

The reproducibility backbone: define an employee as a checked-in spec, not a
hand-built profile.

- [ ] Decide the on-disk layout for checked-in specs — proposed `employees/<role>/`
      holding `SOUL.md` (identity) + a `config.yaml` template (model/provider,
      tools, cron) **minus secrets**.
- [ ] Separate repo-tracked (SOUL.md, config template) from per-host/runtime
      (`.env`, sessions, memory, state DB) — the latter stays out of git.
- [ ] Write a materializer (`make employee ROLE=…` / script) that creates/updates
      `~/.hermes/profiles/<role>/` from `employees/<role>/`.
- [ ] Land two role templates as stubs: `sim-mover`, `autonomous-coder`.

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
