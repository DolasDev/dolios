# Employee: sim-mover (stub)

**Role:** operates a *simulated* moving-and-storage company against the Pegasus
API, generating realistic activity for testing/demo/dev.

- **Identity:** [`SOUL.md`](SOUL.md)
- **Model:** local `qwen3.6:35b-a3b` on dolo-llm.

## Status: 🔒 blocked

Pegasus exposes only customers/documents today; the jobs/moves domain is still
being built. This is a **stub** — identity + base config only. The Pegasus MCP
toolset (server-side Bearer auth, curated read-only first) lands in
[`ROADMAP.md`](../../ROADMAP.md) Phase 4 once the jobs/moves endpoints ship.

You can still materialize the profile (`make employee ROLE=sim-mover`) to reserve
the identity, but it has no Pegasus tools yet.
