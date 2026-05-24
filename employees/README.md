# employees/

Checked-in specs for the Dolios fleet. **Each employee is a hermes-agent
[profile](https://hermes-agent.nousresearch.com/docs/user-guide/profiles)** —
an isolated agent with its own identity, model, tools, and schedule. This
directory holds the *source of truth* for each one so the fleet is reproducible:
materialize a spec onto a host and you get a configured profile.

## Layout

```
employees/
├── README.md
└── <role>/
    ├── SOUL.md        # identity — first thing in the agent's system prompt
    ├── config.yaml    # profile config TEMPLATE: model/provider, agent, cron…
    ├── env.example    # required secrets (names only, no values)
    └── README.md      # what this employee does + status
```

## Tracked vs. runtime

| Tracked here (git) | Lives only on the host (not git) |
|---|---|
| `SOUL.md`, `config.yaml`, `env.example`, `README.md` | the real `.env` (secrets), `sessions/`, `memories/`, `skills/`, `logs/`, state DB |

Secrets never enter this repo. The runtime state lives under
`~/.hermes/profiles/<role>/` and is owned by hermes-agent.

## Materialize an employee

```sh
make employee ROLE=autonomous-coder          # or: scripts/materialize-employee.sh <role>
DRY_RUN=1 make employee ROLE=autonomous-coder # show what would change, do nothing
```

The materializer ([`scripts/materialize-employee.sh`](../scripts/materialize-employee.sh)):

- creates the hermes profile if missing (or just the dir, if hermes isn't
  installed yet — e.g. on a non-host machine),
- copies `SOUL.md` + `config.yaml` into `~/.hermes/profiles/<role>/`, backing up
  any existing copies to `*.bak` and showing a diff,
- seeds `.env` from `env.example` **only if** it doesn't already exist,
- **never** touches `sessions/`, `memories/`, or state.

It is idempotent and safe to re-run.

## Current roster

| Employee | Role | Status |
|---|---|---|
| [`autonomous-coder`](autonomous-coder/) | Spare-capacity engineering across Dolios apps | Spec ready; not yet autonomous (Phase 3 guardrails pending) |
| [`sim-mover`](sim-mover/) | Simulated moving-and-storage company on Pegasus | 🔒 Stub — blocked on Pegasus jobs/moves API (Phase 4) |
