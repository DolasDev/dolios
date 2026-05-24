# coder — guardrailed dispatcher for the autonomous-coder employee

The `autonomous-coder` employee's local model decides **which** backlog task and
repo to work on. This module decides **how**, and enforces every safety rule in
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

python3 services/coder/dispatch.py \
  --repo dolios --task TASK-1 --instructions "Add a docstring to foo()"
```

## How it fits

```
hermes-agent (local model, supervisor)
   │  picks task + repo  (judgment)
   ▼
dispatch.py  ──gate──▶ usage-gate         (capacity)
   │         ──guard─▶ allowlist/branch/budget   (safety, in code)
   ▼
claude -p … --output-format json          (the actual engineering)
   ▼
branch → commit → push → gh pr create     (human reviews the PR)
   ▼
.ledger.jsonl                              (run + cost history; window accounting)
```

All effects go through injectable `Runners`, so guardrails are unit-tested with
fakes — no real git/claude/gh/network. See `test_dispatch.py` (9 tests).

## Status (ROADMAP Phase 3)

- ✅ Dispatcher + guardrails + tests (this module).
- ⏳ **Token refresh** in usage-gate — until done, an expired token makes the gate
  *hold* (fail closed), so the loop pauses rather than acting on a dead token.
- ⏳ **Task-selection layer** — exposing `dispatch.py` to the hermes model as a
  guarded tool, and a backlog source, so the supervisor can pick work.
- ⏳ **Host run** — needs `hermes` + `claude` + `gh` on the host; the
  `autonomous-coder` cron stays disabled (and `approvals: manual`) until validated.
