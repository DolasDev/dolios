# hooks

Versioned event hooks for the autonomous-coder. Currently empty; the
directory exists so the convention is in place when we need it.

Two distinct things go under the "hooks" umbrella; both can live here:

## 1. Hermes-agent hooks (`~/.hermes/hooks/`)

hermes-agent has its own event-hook system that fires on agent-level events
(pre-message, post-tool-call, on-error, etc.) — see the
`hermes-agent-skill-authoring` bundled skill for the schema.

When we want to install one, the file lives here in the repo and is
symlinked into `~/.hermes/hooks/` on the host (see `make install-coder-cron`
for the same pattern with the cron wrapper).

## 2. Per-dispatch / per-tick hooks

Hooks our own pipeline might call:

- `pre-dispatch`: a script `services/coder/dispatch.py` could call before
  branching, to e.g. verify a repo precondition.
- `post-merge`: fired after the agent's PR merges, before the next tick —
  useful for e.g. notifying a webhook.

None of these exist today; the hook *system* in `dispatch.py` / `tick.py`
isn't built yet. The directory is here as the canonical home for them when
we do build them, and the convention is documented so the agent (which can
read this README at propose time) knows the pattern.

## What hooks do NOT replace

Hooks are for *event-triggered side effects*, not guardrails. The dispatcher's
safety rules (allowlist, branch off main, PR-not-merge, gh idempotency, atomic
box flip) live in dispatch.py code, not in hooks — they're load-bearing
properties and must always run, not opt-in via a hook directory.

If a learning emerges that says "we should always do X before claude runs,"
the right home is a hardcoded line in `dispatch.py` with a regression test,
NOT a hook here.
