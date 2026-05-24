# Employee: autonomous-coder

**Role:** supervisor that spends *spare* Anthropic capacity on backlog
engineering across the Dolios apps. The local model orchestrates; Claude Code
does the actual coding. Work lands as PRs, never direct pushes to `main`.

- **Identity:** [`SOUL.md`](SOUL.md)
- **Model:** local `qwen3.6:35b-a3b` on dolo-llm (supervisor). OpenRouter
  fallback available once a key is set (Phase 1).
- **Capacity gate:** [`services/usage-gate/`](../../services/usage-gate/) — run
  before every dispatch.

## Materialize

```sh
make employee ROLE=autonomous-coder
```

Writes `SOUL.md` + `config.yaml` into `~/.hermes/profiles/autonomous-coder/` and
seeds `.env` from `env.example` (fill in secrets). Re-runnable; never touches
sessions/memory/state.

## Status

Profile spec is ready. **Not yet autonomous** — `approvals.mode: manual` and the
supervisor `cron` loop is commented out until Phase 3 guardrails (branch+PR,
repo allowlist, token budget) and usage-gate token-refresh are done. See
[`ROADMAP.md`](../../ROADMAP.md) Phase 3.
