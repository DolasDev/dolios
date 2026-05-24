# dolios

IaC and agent specifications for a **fleet of AI employees** — long-running
[hermes-agent](https://hermes-agent.nousresearch.com) profiles, each configured
for a specific job, that we provision reproducibly from this repo.

## Mission

Stand up and manage a fleet of autonomous AI "employees." Each employee is a
hermes-agent **profile** with its own identity, model, tools, guardrails, and
schedule. The fleet is **extensible by design** — new roles are new profiles.
Initial roles:

- **`sim-mover`** — runs a *simulated* moving-and-storage company against the
  [Pegasus](https://api.pegasus.dolas.dev) API (our move-management SaaS),
  acting as a power user to generate realistic activity for testing, demo, and
  dev. *Blocked:* Pegasus currently exposes only customers/documents — the
  jobs/moves domain is still being built out, so this role waits.
- **`autonomous-coder`** — does autonomous engineering on the various Dolios
  applications (work on branches, open PRs), gated by spare Anthropic capacity.

## Core concepts

| Concept | What it is | Where it lives |
|---|---|---|
| **Employee** | One hermes-agent profile = one isolated agent (own `SOUL.md`, `config.yaml`, model, tools, cron, memory, state DB). | `~/.hermes/profiles/<role>/` on the host; **specs checked into this repo** so the fleet is reproducible. |
| **Identity** | `SOUL.md` — who the employee is; first thing in its system prompt. | Per profile; versioned here. |
| **Model / provider** | Per-employee choice: **local** model on dolo-llm *or* an **external** model via **OpenRouter** (with optional fallback). | `config.yaml` per profile. |
| **Tools** | Capabilities exposed to the employee as **MCP servers** (e.g. Pegasus). | `services/` (on hold until Pegasus jobs land). |
| **Capacity gate** | Pre-dispatch check of Anthropic subscription headroom for the coding role. | `services/usage-gate/`. |
| **Shared state** | Fleet registry, task/run history, schedules. | Postgres (`docker-compose.yml`). |

## Architecture

Two machines on the LAN:

- **host** (RTX 3060 12GB, this repo's primary target)
  - `hermes-agent` — Nous Research's CLI/TUI agent, installed natively. This
    *is* the employee runtime; one **profile per employee**. We don't wrap it.
  - `docker compose up -d` brings up Postgres for fleet state (registry, run
    history) and MCP tool-server state.
- **dolo-llm** (separate box on the LAN)
  - Ollama, deployed via `compose.dolo-llm.yml` — serves the **local** model
    option. Pulls the models in [`infra/ollama/models.txt`](infra/ollama/models.txt)
    (currently `qwen3.6:35b-a3b` — see [`MODEL_OPTIONS.md`](MODEL_OPTIONS.md)).
  - The single RTX 3060 serves one model at a time; `make llm-up` frees the GPU
    (stops any other container reserving it) before starting Ollama.

### Model providers — local *or* OpenRouter, per employee

Each employee picks its model in its profile `config.yaml`. hermes-agent routes
natively:

- **Local** (default for always-on, cheap, private work): a custom endpoint
  `base_url: http://dolo-llm:11434/v1` → `qwen3.6:35b-a3b` on Ollama. Constrained
  by the single 12GB GPU (one model at a time).
- **External via OpenRouter** (for heavier/frontier work, or to avoid GPU
  contention): the built-in OpenRouter provider + API key. No local GPU cost.

Because routing is per profile, the `autonomous-coder` can run a frontier model
through OpenRouter while a `sim-mover` runs the local model — simultaneously,
since only the local one touches the 3060. See
[`MODEL_OPTIONS.md`](MODEL_OPTIONS.md) for the local-model decision and the
local-vs-OpenRouter tradeoff.

> We *don't* use Nous's Hermes-3/4 models — they're conversational, not agentic,
> and hermes-agent itself warns against them (no native tool calling, which the
> fleet needs for MCP-driven work).

## First-time setup

### 1. Bring up the local model (on the dolo-llm machine)

```sh
git clone <this repo>
cd dolios
make llm-up        # frees the GPU, starts Ollama, pulls qwen3.6:35b-a3b
make llm-logs      # watch the model-puller until it exits
```

### 2. Bring up Postgres (on the host)

```sh
make env           # creates .env from .env.example; edit secrets
make up
```

### 3. Install hermes-agent (on the host)

```sh
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
source ~/.bashrc   # or ~/.zshrc
```

### 4. Create an employee profile and point it at a model

```sh
hermes profile create sim-mover     # one profile per employee
hermes model                        # configure its model:
#   Local:      Custom Endpoint → http://dolo-llm:11434/v1 → qwen3.6:35b-a3b
#   External:   OpenRouter → <model> (uses your OPENROUTER_API_KEY)
```

Profile identity/config templates will be checked into this repo (see roadmap)
so a profile can be materialized rather than hand-built.

### 5. Run it

```sh
hermes --tui                        # or run a specific profile
```

## Layout

```
.
├── compose.dolo-llm.yml    # Ollama stack, deployed to the dolo-llm machine
├── docker-compose.yml      # Host stack: Postgres (fleet state)
├── MODEL_OPTIONS.md        # Local-model decision + local-vs-OpenRouter tradeoff
├── ROADMAP.md              # Phased plan toward the fleet
├── employees/              # Checked-in employee specs (one dir per role)
│   ├── autonomous-coder/   #   SOUL.md + config.yaml + env.example
│   └── sim-mover/          #   (stub — blocked on Pegasus jobs)
├── infra/
│   ├── ollama/models.txt   # Models the dolo-llm Ollama instance will pull
│   └── gpu-stack.sh        # Free the GPU + serve our model (up/down/status)
├── scripts/
│   └── materialize-employee.sh  # Spec → ~/.hermes/profiles/<role>/
├── services/
│   ├── usage-gate/         # Spare-capacity gate (pre-dispatch usage check)
│   └── coder/              # Guardrailed dispatcher for autonomous-coder
└── Makefile                # `up`, `llm-up`, `usage`, `employee`, `coder-*`, ...
```

Planned (see [`ROADMAP.md`](ROADMAP.md)): `services/pegasus-mcp/` (once Pegasus
jobs exist).

## Status & next steps

See [`ROADMAP.md`](ROADMAP.md). In short:

- **Done:** local model selected + verified; GPU single-tenant switching;
  spare-capacity gate (`services/usage-gate/`); employee/profile framework
  (`employees/`, `make employee ROLE=…`).
- **Now:** OpenRouter provider path (Phase 1); then flesh out the
  `autonomous-coder` loop + guardrails (Phase 3).
- **Blocked:** Pegasus MCP server + `sim-mover` role — waiting on Pegasus
  jobs/moves endpoints.
