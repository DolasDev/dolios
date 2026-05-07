# dolios

IaC and agent specifications for a fleet of AI moving-and-storage entity
representatives that act as power users inside Pegasus, our move-and-storage
SaaS platform. Used for testing, demo, and dev.

## Architecture

Two machines on the LAN:

- **host** (RTX 3060 12GB, this repo's primary target)
  - `hermes-agent` — Nous Research's CLI/TUI agent, installed natively. This
    *is* the agent runtime; we no longer wrap it.
  - `docker compose up -d` brings up Postgres for future agent memory and MCP
    tool-server state.
- **dolo-llm** (separate box on the LAN)
  - Ollama, deployed via `compose.dolo-llm.yml`.
  - Pulls the models listed in [`infra/ollama/models.txt`](infra/ollama/models.txt).

`hermes-agent` on the host points at Ollama on dolo-llm via its
"Custom Endpoint" provider. Personality (the "Hermes" persona — a Pegasus
power user) is configured inside hermes-agent, not in this repo. Pegasus
tooling will land as **MCP servers** under `services/` once the first one
exists.

> "Hermes" the persona ≠ Hermes-3 the model. They share a name; that's why
> we run Hermes-3-Llama-3.1-8B (`hermes3:8b`) — it natively meets
> hermes-agent's 64K context floor.

## First-time setup

### 1. Bring up the LLM (on the dolo-llm machine)

```sh
git clone <this repo>
cd dolios
make llm-up        # starts Ollama + pulls hermes3:8b
make llm-logs      # watch the model-puller until it exits
```

### 2. Bring up Postgres (on the host)

```sh
make env           # creates .env from .env.example; edit POSTGRES_PASSWORD
make up
```

### 3. Install hermes-agent (on the host)

```sh
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
source ~/.bashrc   # or ~/.zshrc
```

### 4. Point hermes-agent at our Ollama

```sh
hermes model
# Select "Custom Endpoint"
# Base URL: http://dolo-llm:11434/v1   (or whatever the LAN resolves to)
# API key:  ollama                      (any non-empty string works)
# Model:    hermes3:8b
```

### 5. Use it

```sh
hermes --tui
```

## Layout

```
.
├── compose.dolo-llm.yml    # Ollama stack, deployed to the dolo-llm machine
├── docker-compose.yml      # Host stack: Postgres only (for now)
├── infra/
│   └── ollama/models.txt   # Models the dolo-llm Ollama instance will pull
└── Makefile                # `up`, `down`, `llm-up`, `llm-down`, ...
```

## What's next

- First MCP tool server for Pegasus (read-only: list jobs, get job).
- Persona configs as hermes-agent personalities, checked into this repo so
  the fleet is reproducible.
- Agent-memory schema in Postgres once an MCP server actually needs it.
