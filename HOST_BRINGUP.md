# Host bring-up

Everything in this repo is built and unit-tested on a dev box, but the live
fleet runs across **two machines**:

- **dolo-llm** (RTX 3060) — serves the model only.
- **dolo-docker** — runs the hermes-agents, the `services/`, and Postgres.

This is the ordered checklist threading the Phase 1–3 steps from
[`ROADMAP.md`](ROADMAP.md). Each step label says **which machine** to run it on,
and each is gated by the one before — don't enable the autonomous loop until the
manual steps pass.

## 0. Prerequisites

On **dolo-llm**:
- [ ] `docker` available and the RTX 3060 visible (`nvidia-smi`).
- [ ] This repo checked out (for `make llm-*` / `gpu-stack.sh`).

On **dolo-docker**:
- [ ] `docker` available; this repo checked out. Build the agent image (`make up`
      builds it, or `docker compose build hermes-autonomous-coder`). No native
      `hermes` install needed — the container is the runtime.
- [ ] Claude Code logged in on the host (`~/.claude/.credentials.json` present) —
      it's mounted into the container, and the usage gate reads it too.
- [ ] `GH_TOKEN` in the profile `.env` (for PRs) — `gh` runs inside the image, so
      no host gh install/auth needed. See [env.example](employees/autonomous-coder/env.example).
- [ ] Python 3 on the host (gate/dispatcher are stdlib + pyyaml); the target repo
      checkouts present (mounted into the agent for the dispatcher).
- [ ] dolo-llm reachable on the LAN (`curl http://dolo-llm:11434/api/tags`).

## 1. Local model (dolo-llm) + Postgres (dolo-docker)

- [ ] On **dolo-llm**: `make llm-up` then `make llm-logs` (wait for the puller to exit).
- [ ] On **dolo-docker**: `make env` (edit secrets in `.env`), then `make up` (Postgres).

> Steps 2–6 all run on **dolo-docker**.

## 2. Capacity gate (services/usage-gate)

- [ ] `make usage` → returns a normalized snapshot (`overall_status: allowed`).
- [ ] `make usage-decide` → `decision: dispatch`, exit 0.
- [ ] **Token refresh** (only when ready — rotates real creds):
  - [ ] `python3 services/usage-gate/usage_gate.py --refresh-dry-run` (inspect request).
  - [ ] `python3 services/usage-gate/usage_gate.py --refresh` → confirm
        `~/.claude/.credentials.json` updated and `.bak` written; then
        `make usage` still works with the rotated token.

## 3. Materialize the employee (Phase 2 smoke-test)

- [ ] `DRY_RUN=1 make employee ROLE=autonomous-coder` (review the plan).
- [ ] `make employee ROLE=autonomous-coder`.
- [ ] Confirm `~/.hermes/profiles/autonomous-coder/` has `SOUL.md`, `config.yaml`, `.env`.
- [ ] `docker compose run --rm hermes-autonomous-coder chat -q "who are you?" --profile autonomous-coder`
      → identity reflects SOUL.md, and the request hits the **local** model on dolo-llm.

## 4. OpenRouter provider path — N/A under current policy

**Skipped.** Fleet policy is **$0 marginal API spend**, so the supervisor does
NOT fail over to OpenRouter (metered, outside the subscription). The fallback
has been removed from `employees/autonomous-coder/config.yaml`; if dolo-llm is
unreachable the supervisor halts cleanly until it returns. Re-enable only if
the policy changes.

## 5. Coder dispatcher (Phase 3 manual run)

- [ ] `cp services/coder/coder.example.yaml services/coder/coder.yaml`; edit the
      `allowlist` (real repo paths) and `budget`.
- [ ] `make coder-preflight` → gate + budget pass.
- [ ] Manual dispatch on a trivial task in an allowlisted repo:
      `python3 services/coder/dispatch.py --repo dolios --task SMOKE-1
      --instructions "Add a comment to the top of README.md"`.
- [ ] Verify: work landed on an `auto/coder/SMOKE-1-…` branch, a **PR was opened**
      (never a push to `main`), and the run is in `services/coder/.ledger.jsonl`.
- [ ] Negatives: a non-allowlisted `--repo` is refused; with the gate forced to
      hold it refuses; clean up the smoke branch/PR.

## 6. Go autonomous (Phase 3 loop) — last

Only after 1–5 pass:

- [ ] Decide the task-selection layer — expose `dispatch.py` to the hermes model
      as a guarded tool + a backlog source (so the supervisor picks work).
- [ ] Uncomment the `cron.coder_loop` block in the profile `config.yaml` and
      finalize its prompt.
- [ ] Flip `approvals.mode` from `manual` once you trust an unattended run.
- [ ] Watch the first scheduled runs; confirm holds, budgets, and PRs behave.
- [ ] (Phase 5) Record runs to Postgres instead of / alongside the JSONL ledger.
