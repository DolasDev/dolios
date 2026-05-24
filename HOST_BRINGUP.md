# Host bring-up

Everything in this repo is built and unit-tested on a dev box, but the live
fleet runs on the **host** (the RTX-3060 machine with `hermes-agent`). This is
the ordered checklist that threads the Phase 1–3 steps from
[`ROADMAP.md`](ROADMAP.md) into one sequence you run on the host.

Each step is gated by the one before it — don't enable the autonomous loop until
the manual steps pass.

## 0. Prerequisites (host)

- [ ] `hermes-agent` installed (`hermes --version`) — see [README](README.md#3-install-hermes-agent-on-the-host).
- [ ] Claude Code installed (`claude --version`) and logged in (creates
      `~/.claude/.credentials.json`).
- [ ] `gh` installed and authed (`gh auth status`) — for opening PRs.
- [ ] `docker` available; dolo-llm reachable on the LAN (`curl http://dolo-llm:11434/api/tags`).
- [ ] Python 3 (the gate/dispatcher are stdlib + pyyaml only).

## 1. Local model + Postgres

- [ ] On **dolo-llm**: `make llm-up` then `make llm-logs` (wait for the puller to exit).
- [ ] On the **host**: `make env` (edit secrets in `.env`), then `make up` (Postgres).

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
- [ ] `hermes -p autonomous-coder chat -q "who are you?"` → identity reflects SOUL.md,
      and the request hits the **local** model on dolo-llm.

## 4. OpenRouter provider path (Phase 1 smoke + fallback)

- [ ] Put `OPENROUTER_API_KEY=sk-or-…` in `~/.hermes/profiles/autonomous-coder/.env`.
- [ ] **Confirm the slug prefix:** temporarily set `model.provider: openrouter` /
      `default: openrouter/qwen/qwen3-235b-a22b-2507`; run
      `hermes -p autonomous-coder chat -q "call a tool"` → real call + tool-calling
      works. (If the `openrouter/` prefix is rejected, drop it.)
- [ ] Restore local primary. **Fallback test:** `make llm-down` on dolo-llm, run a
      prompt → confirm it fails over to the OpenRouter fallback; `make llm-up` →
      confirm it prefers local again.

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
