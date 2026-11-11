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

## Phase 1 — Provider path ✅ (local only, by policy)

- ✅ Local model is the only provider: `qwen3.6:35b-a3b` on dolo-llm.
- ✅ OpenRouter fallback **dropped** (`7bf819f`) — fleet policy is **$0 marginal
      spend**. If dolo-llm is down the supervisor halts cleanly until it returns.
      (OpenRouter notes in `MODEL_OPTIONS.md` are kept as reference only.)
- ⚠️ dolo-llm's single GPU is shared with other model servers (koboldcpp etc.);
      `make llm-up` must be re-run after anything else claims the card, or the
      fleet has no model.

## Phase 2 — Employee / profile framework ✅

- ✅ Employee = checked-in spec in `employees/<role>/` (`SOUL.md`, `config.yaml`,
      `env.example`), materialized by `make employee ROLE=…`; secrets stay in
      the per-host `.env`.
- ✅ **Containerized** hermes-agent employees (`infra/hermes/Dockerfile`,
      `docker-compose.yml`) running on dolo-docker; cont-init hooks set up
      `gh`/git credentials.
- ✅ Repo-versioned self-modification surface: `infra/hermes/memories/`,
      `skills/`, `hooks/`.
- ✅ Two role specs: `autonomous-coder` (live) + `sim-mover` (stub).

## Phase 3 — Role: `autonomous-coder` 🔨 (loop built; stalled since 2026-06-01)

Local model supervises; Claude Code does the engineering; humans merge.

- ✅ **Guardrailed dispatcher** (`services/coder/dispatch.py`): capacity gate →
      allowlist → never-base-branch → budget → PR (never merge) → ledger.
      Chunk mode: deterministic branch, idempotency precheck, atomic
      checkbox flip.
- ✅ **Usage gate** (`services/usage-gate/`) with OAuth token refresh and
      per-window pacing (nightly catch-up model).
- ✅ **Auditor** (`services/auditor/`) — deterministic repo audit → metrics
      history (`.dolios/metrics/`) + framework-tagged gaps (DORA, SSDF, OpenSSF).
- ✅ **Proposal lifecycle** (`proposals/`) — agent-authored proposals from audit
      gaps; human approves; work runs chunk-by-chunk; remeasure closes it.
- ✅ **Backlog picker + tick orchestrator** (`backlog.py`, `tick.py`) — one
      deterministic tick per cron fire: `audit | propose | execute | remeasure |
      reflect | empty`. Tick log at `.dolios/tick-log.jsonl`.
- ✅ **Auto-reviewer** (`reviewer.py`) — Claude reviews agent PRs.
- ✅ Cron wired via `hermes cron create` (`make install-coder-cron`);
      approvals flipped to auto.
- ✅ First proposal end-to-end: *adopt GitHub Actions CI* — chunks 1–2 merged
      (#1, #2), `.github/workflows/ci.yml` live.
- [ ] **Chunk 3** (`services/auditor/ci_api.py`) — last tick (2026-06-01) failed
      on `git push` (no creds in container; hook fixed in `baa1d08`). PR #3
      closed for re-creation; stale branch
      `auto/coder/dolios-2026-05-28-adopt-github-actions-ci-chunk-3` must be
      deleted before the coder can retry.
- [ ] Confirm the cron is actually firing on dolo-docker and ticks resume.
- [ ] Remeasure + close the CI proposal; let the next audit gap
      (LICENSE / SECURITY.md / gitleaks / Dependabot / coverage) flow through.

### Chat front-end ✅

- ✅ Self-hosted Matrix (Conduit) homeserver (`infra/matrix/`), TLS via
      `tailscale serve`; admin-room recovery documented.
- ✅ `make ask` / `make ask-q` CLI shortcuts to query an employee.

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

1. Keep dolo-llm serving (`make llm-up`) whenever the fleet should run.
2. On dolo-docker: delete the stale chunk-3 branch, verify the coder cron, and
   let it finish the CI proposal autonomously.
3. Phase 5 (Postgres state + `make fleet-status`) once the loop is running
   unattended reliably; `sim-mover` stays blocked on Pegasus.
