# coder — guardrailed dispatcher + deterministic picker

Two modules, one job: the autonomous-coder's per-tick decision.

- **`backlog.py`** — the deterministic picker. Reads the audit history +
  `proposals/` + `coder.yaml`'s allowlist; emits the next task as structured
  JSON (`kind ∈ {audit, propose, empty}`). Keeps the "what to work on next"
  logic in code rather than in the 35B's prompt. See `test_backlog.py` (10
  tests).
- **`dispatch.py`** — the guardrailed dispatcher. The picker (or a human)
  hands it a repo + task + instructions; it enforces every safety rule in
  code rather than trusting the model:

1. **Capacity gate** — won't start unless [`usage-gate`](../usage-gate/) says
   *dispatch*. Any gate failure (token expired, network) is treated as *hold*.
2. **Allowlist** — refuses any repo not listed in `coder.yaml`.
3. **Never the base branch** — branches off `base_branch`, asserts HEAD actually
   moved onto the work branch before running Claude Code. No path commits to base.
4. **Budget** — refuses to start if the rolling-window spend cap is already hit;
   flags a run whose cost exceeds the per-run cap.
5. **PR, never merge** — work lands as a pull request. There is no merge path.

```sh
cp services/coder/coder.example.yaml services/coder/coder.yaml   # then edit (git-ignored)
make coder-preflight     # gate + budget check only
make coder-test          # guardrail unit tests (mocked git/claude/gh)
make backlog-next        # what would the next tick do? structured JSON
make backlog-test        # picker tests (no model, no network)

python3 services/coder/dispatch.py \
  --repo dolios --task TASK-1 --instructions "Add a docstring to foo()"
```

## How it fits

```
hermes-agent (local model, supervisor — drives the loop, mechanically)
   │
   ├─▶ dispatch.py --preflight-only          (capacity gate, pacing-aware)
   │
   ├─▶ backlog.py --next                     (kind ∈ {audit, propose, empty})
   │        │
   │        ├─ "audit":  audit.py → appends a row to history.jsonl
   │        ├─ "propose": claude -p (research+template) → writes proposal MD
   │        └─ "empty":  report and exit
   │
   └─▶ dispatch.py (execute path — V1, when chunk-state lands)
              │
              ──gate──▶ usage-gate (per-window pacing)
              ──guard─▶ allowlist / branch / budget   (safety, in code)
              ▼
         claude -p … --output-format json     (the engineering)
              ▼
         branch → commit → push → gh pr create  (human reviews the PR)
              ▼
         .ledger.jsonl                         (run + cost history)
```

All effects go through injectable `Runners`, so guardrails are unit-tested with
fakes — no real git/claude/gh/network. See `test_dispatch.py` (9 tests).

## Status (ROADMAP Phase 3)

- ✅ Dispatcher + guardrails + tests (`dispatch.py`).
- ✅ Per-window pacing in the gate (`usage-gate/`).
- ✅ Deterministic auditor + proposal scaffolding (`auditor/` + `proposals/`).
- ✅ Deterministic picker for the audit→propose half (`backlog.py`).
- ⏳ **Execute / remeasure paths in the picker** — need chunk-completion
  tracking (sidecar JSONL or open-PR scan via `gh`). Once landed, the loop
  closes end-to-end.
- ⏳ **Token refresh** in usage-gate — until done, an expired token makes the
  gate *hold* (fail closed), so the loop pauses rather than acting on a dead token.
- ⏳ **Host run** — needs an allowlisted repo to actually live at the
  configured path; the `autonomous-coder` cron stays disabled (and
  `approvals: manual`) until validated.
