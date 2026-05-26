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
| **Employee** | One hermes-agent profile = one isolated agent (own `SOUL.md`, `config.yaml`, model, tools, cron, memory, state DB). | `~/.hermes/profiles/<role>/` on **dolo-docker**; **specs checked into this repo** so the fleet is reproducible. |
| **Identity** | `SOUL.md` — who the employee is; first thing in its system prompt. | Per profile; versioned here. |
| **Model / provider** | Per-employee choice: **local** model on dolo-llm *or* an **external** model via **OpenRouter** (with optional fallback). | `config.yaml` per profile. |
| **Tools** | Capabilities exposed to the employee as **MCP servers** (e.g. Pegasus). | `services/` (on hold until Pegasus jobs land). |
| **Capacity gate** | Pre-dispatch check of Anthropic subscription headroom for the coding role. | `services/usage-gate/`. |
| **Shared state** | Fleet registry, task/run history, schedules. | Postgres (`docker-compose.yml`) on **dolo-docker**. |

## Architecture

Two machines on the LAN, with distinct jobs:

- **dolo-llm** (RTX 3060 12GB) — **the model, and nothing else.** Ollama,
  deployed via `compose.dolo-llm.yml`, serves the local model from
  [`infra/ollama/models.txt`](infra/ollama/models.txt) (`qwen3.6:35b-a3b` — see
  [`MODEL_OPTIONS.md`](MODEL_OPTIONS.md)) on `:11434`. The single RTX 3060 serves
  one model at a time; `make llm-up` frees the GPU (stops any other container
  reserving it) before starting Ollama. `make llm-*` / `gpu-stack.sh` run here.
- **dolo-docker** — **the employees.** Runs the `hermes-agent` profiles (one per
  employee), in Docker. Here you materialize employee specs into
  `~/.hermes/profiles/<role>/`, run the `services/` (the spare-capacity gate and
  the coder dispatcher), and host the fleet **Postgres** (`docker-compose.yml`).
  The coder dispatcher needs `claude` + `gh` + the target repo checkouts here.
  Agents reach the model over the LAN at `http://dolo-llm:11434/v1`.

The local model on dolo-llm runs no agent logic; all employee runtime — hermes,
tools, dispatch, state — lives on dolo-docker.

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

Steps 2–5 run on **dolo-docker** (the employee host).

### 2. Bring up Postgres (on dolo-docker)

```sh
make env           # creates .env from .env.example; edit secrets
make up
```

### 3. Install hermes-agent (on dolo-docker)

```sh
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
source ~/.bashrc   # or ~/.zshrc
```

### 4. Materialize an employee (on dolo-docker)

```sh
make employee ROLE=autonomous-coder   # writes the checked-in spec into ~/.hermes/profiles/
```

This installs the profile's `SOUL.md` + `config.yaml` (model already set to the
local endpoint `http://dolo-llm:11434/v1`, with an OpenRouter fallback) and seeds
its `.env`. See [`employees/`](employees/) and [`HOST_BRINGUP.md`](HOST_BRINGUP.md).

### 5. Run it (on dolo-docker)

```sh
hermes -p autonomous-coder chat -q "who are you?"   # or: hermes -p <role> --tui
```

## Layout

```
.
├── compose.dolo-llm.yml    # Ollama stack — runs on dolo-llm (the model)
├── docker-compose.yml      # Postgres (fleet state) — runs on dolo-docker
├── MODEL_OPTIONS.md        # Local-model decision + local-vs-OpenRouter tradeoff
├── ROADMAP.md              # Phased plan toward the fleet
├── HOST_BRINGUP.md         # Ordered checklist to stand the fleet up on the host
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
