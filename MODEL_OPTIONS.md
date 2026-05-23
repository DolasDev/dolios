# Model options for the dolios orchestrator

Reasoning record for which local model `hermes-agent` should run. Revisit when
hardware changes or a newer model lands. **Model is a config value, not code** —
swapping is: add the tag to `infra/ollama/models.txt` → `make llm-up` →
re-point `hermes model`. Nothing here is wired up yet.

## Purpose (this is NOT a coding model)

`hermes-agent` is the **orchestrator**, not the coder. Claude Code (Opus/Sonnet,
via the Anthropic subscription) does the actual engineering. The local model is
the cheap, always-on supervisor that, on a schedule:

1. checks Anthropic usage limits (spare-capacity gate),
2. picks a backlog task (cleanup / tests / refactor / tech-debt / devops / research),
3. dispatches it to Claude Code headless (`claude -p ... --output-format json`),
4. records the outcome and loops.

So the qualities that matter are **reliable native tool-calling**, **sound
judgment/reasoning** for task selection and failure recovery, and **determinism**
— *not* raw coding skill. It runs 24/7, so it must stay responsive.

## Hardware budget (binding constraint)

- **dolo-llm** (where the model runs): RTX 3060, **12GB VRAM**, **48GB system RAM**.
- 12GB VRAM is the binding constraint; 48GB RAM is generous fallback for CPU
  offload (this is what makes the >12GB MoE pick viable).

## Primary pick — `qwen3.6:35b-a3b` (Q4)

Best reasoning that's realistically runnable here, and a great fit for the
orchestrator role.

> **Verified 2026-05-23 (CPU-only smoke test on dolo-llm).** Pulled cleanly
> (23GB). Tool calling through Ollama's OpenAI-compatible `/v1/chat/completions`
> works end-to-end: emitted valid `tool_calls` for both a no-arg tool
> (`check_anthropic_usage`) and a required-multi-arg tool
> (`dispatch_claude_code_task` → valid `{"task_id","repo"}` JSON). Agentic
> gating reasoning was sound (checked usage *before* dispatching; declined to
> dispatch when it believed capacity was exhausted). The IQ3-breaks-JSON risk
> did not materialize at Q4. CPU-only latency was ~24–43s/call incl. first-load;
> on GPU it'll be far faster.

- **Arch:** 35B-A3B MoE — 35B total, **only 3B active per token**. This is the
  whole trick: ~24GB of Q4 weights, ~12GB spills to RAM on a 12GB card, but
  because only 3B params are active per token the spill costs little speed.
  48GB RAM absorbs it with room to spare.
- **Reasoning:** unified **thinking / non-thinking mode** with a thinking-budget
  knob, plus "thinking preservation" (retains reasoning context across messages
  — useful across a multi-step orchestration loop). Let it think hard on task
  prioritization / failure recovery; dial it down for routine capacity checks.
- **Agentic:** 73.4 SWE-bench Verified, 51.5 Terminal-Bench 2.0; Apache 2.0.
- **Context:** 262K (KV cache costs RAM/VRAM — cap `num_ctx`, see config below).

### Two caveats that shaped this choice

1. **Text-only in Ollama, and that's fine.** Qwen3.5/3.6 ship a separate vision
   projector (`mmproj`) that Ollama's GGUF flow doesn't load — so *image* input
   fails, but **text generation and tool calling work normally**. The
   orchestrator is text-only, so we lose nothing.
2. **Must be Q4 or higher — never IQ3.** Reports are explicit that **IQ3 can
   emit broken function-call JSON**. Tool calls are this model's entire job, so
   the low quant that would have eased the VRAM spill is off the table. Pin Q4+
   (Q4_K_M / UD-Q4_K_XL, or Q6 if you want more fidelity and have RAM).

### Config notes

- **Template:** ChatML (Qwen native). Ollama tool-call parser: `qwen3_coder`.
- **Samplers (Qwen-recommended):** thinking mode `temperature 0.6, top_p 0.95,
  top_k 20`; non-thinking `temperature 0.7, top_p 0.8, top_k 20`. For agentic
  tool-calling, bias lower temp for determinism. **Do not use greedy decoding
  in thinking mode.**
- **Context:** don't set `num_ctx` to 262K — the KV cache would balloon. Start
  ~32–40K; raise only if a task needs it.
- **Fallback variant:** if 3.6's tool-call template misbehaves on your Ollama
  version, drop to **`qwen3.5:35b`** — same 35B-A3B MoE, same text-only profile,
  slightly older/weaker. Strict-dominated by 3.6 otherwise.

## Alternatives (by why you'd switch)

| Model | Tag | Why switch to it | Fit on 12GB |
|---|---|---|---|
| **Smaller, no RAM gamble** | `devstral:24b` | Purpose-built agentic tool-use model (Apache 2.0, 68% SWE-bench). Dense 24B, ~14GB Q4 → only ~2–3GB spill. Rock-solid on Ollama. Pick if the 35B feels too slow. | ~14GB, light spill |
| **Fast / keep-it-simple** | `qwen3:8b` (current) | Already deployed, fully in VRAM, fast. Genuinely enough if the loop stays tightly structured and the model only sequences pre-defined tasks. Zero change. | ~5GB, full offload |
| **Bleeding edge** | `qwen3.5:35b` | Fallback for the primary if 3.6 tool templates break. | same as primary |

## Fit math (re-derive if hardware changes)

`weights_GB ≈ params_B × bpw/8`, Q4_K_M ≈ 4.8 bpw. Leave ~2–3GB VRAM for KV/compute.

- `qwen3.6:35b-a3b` Q4 ≈ 35 × 4.8/8 ≈ 21GB weights (Ollama lists ~24GB w/ overhead)
  → ~12GB spills to RAM. MoE (3B active) keeps it responsive; 48GB RAM covers it.
- `devstral:24b` Q4 ≈ 24 × 4.8/8 ≈ 14.4GB → ~2–3GB spill, dense.
- `qwen3:8b` Q4 ≈ 8 × 4.8/8 ≈ 4.8GB → fully in VRAM.

## How to switch (when ready)

```sh
# on the dolo-llm machine
echo "qwen3.6:35b-a3b" >> infra/ollama/models.txt   # or edit the file
make llm-up                                          # pulls it
make llm-logs                                        # watch model-puller exit

# on the host
hermes model        # Custom Endpoint → http://dolo-llm:11434/v1 → qwen3.6:35b-a3b
```

Then **smoke-test tool calling through hermes-agent specifically** before
trusting it for unattended runs — Ollama's tool support for these models was
patched recently.

## GPU is single-tenant

The RTX 3060 hosts **one model server at a time** — the ~24GB Q4 model needs the
full 12GB VRAM (plus RAM spill). `make llm-up` (→ `infra/gpu-stack.sh up`) frees
the GPU by stopping any other container that reserves it, then serves our model.
The runtime is the **docker** Ollama (`compose.dolo-llm.yml`), bind-mounted to
the host's `~/.ollama` so the already-pulled model is reused (no re-download).

## Open dependencies (not model choices, but block the full system)

- **Usage gate** — `GET /api/oauth/usage` (`anthropic-beta: oauth-2025-04-20`):
  **verified working 2026-05-23** (HTTP 200, returns `five_hour`/`seven_day`
  utilization + `resets_at` + per-model `sonnet`/`opus`). Still *undocumented* —
  can break without notice; no official `claude usage --json` yet.
  **Unit gotcha (proven live):** the `utilization` scale is ambiguous —
  `five_hour: 1.0` alongside `seven_day: 18.0` only reconciles as *percent*, but
  the model read `1.0` as "100% used" and wrongly refused to dispatch. The gate
  MUST normalize this to an explicit `percent_used` (or `remaining`) with clear
  units before handing it to the model, and confirm the scale once against the
  `/usage` widget. Token comes from `~/.claude/.credentials.json`
  (`claudeAiOauth.accessToken`); unattended use needs refresh handling
  (`refreshToken`/`expiresAt` are in the same file).
- **Guardrails** for autonomous Claude Code runs: work on branches + open PRs
  (not direct push to `main`), per-repo allowlist, hard per-window token budget.
- **Backlog store:** Postgres (already in `docker-compose.yml`) is the natural
  task-queue + run-history home.
