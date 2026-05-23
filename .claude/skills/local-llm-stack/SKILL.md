---
name: local-llm-stack
description: >-
  Select a local/self-hosted LLM (GGUF or similar) that fits THIS machine's
  hardware for a stated purpose supplied at invocation — e.g. "pick a coding
  model", "pick a chat/roleplay model", "pick a model for automation/agents",
  "pick a summarization model". Detects the GPU/VRAM (and RAM) budget, sizes
  candidates to it via quant math, researches current options on Hugging Face,
  and recommends a primary plus tiered alternatives with explicit tradeoffs.
  Use whenever the user wants help choosing, sizing, or swapping a model they
  will run locally. NOT for choosing a hosted API model (Claude/OpenAI/etc.).
---

# Selecting a local LLM that fits this machine

This skill captures a repeatable reasoning method for picking a model to run
locally. The **purpose** (coding, chat, roleplay, automation/agents,
summarization, vision, …) is supplied when the skill is invoked; the
**hardware budget** is discovered, not assumed. The output is a recommendation,
not just a list — one primary pick plus fallbacks, each justified.

If the purpose was not given, ask for it first (one line). Then work the steps
below in order; do not skip the constraint step — every later choice keys off it.

## 1. Find the binding constraint (the hardware budget)

Almost always VRAM. Detect it; never guess. Try in order, stop at first success:

```bash
nvidia-smi --query-gpu=name,memory.total --format=csv,nounits   # NVIDIA
rocm-smi --showmeminfo vram                                      # AMD ROCm
system_profiler SPDisplaysDataType | grep -i vram                # macOS dGPU
sysctl hw.memsize                                                # macOS unified mem (Apple Silicon shares it)
```

Also note **system RAM** (`free -g` / `sysctl hw.memsize`) — it's the fallback
budget for CPU offload, and it caps how far you can spill when VRAM is tight.

State the budget back to the user before recommending anything, e.g.
"12GB VRAM (RTX 3060), 48GB RAM — VRAM is the binding constraint."

If no usable GPU is found, say so and plan for CPU/RAM-bound inference (smaller
models, expect slower tokens/sec).

## 2. Translate the budget into a model-size envelope

The goal is the **largest capable model that still fits the budget**, because
within a use-case bigger generally beats smaller. Fit is governed by quant:

- A GGUF model's on-disk size ≈ its loaded weight size. Rule of thumb for
  bits-per-weight: `Q8≈8.5`, `Q6_K≈6.6`, `Q5_K_M≈5.7`, `Q4_K_M≈4.8`,
  `IQ4_XS≈4.3`, `IQ3_M≈3.7`, `IQ3_S/IQ3_XXS≈3.3`, `IQ2≈2.5`.
  `weights_GB ≈ params_billion × bpw / 8`.
- Leave headroom for the **KV cache + compute buffers** — budget roughly
  10–25% of VRAM, more for large context windows. KV scales linearly with
  context length; an 8-bit (Q8) KV cache roughly halves that cost.
- Fully GPU-offloaded is the target. If the best-fit model only fits by
  spilling layers to CPU, flag the speed cost and offer the next size down.

Work the math out loud for the user's actual numbers. Example (12GB VRAM):
a 24B model at IQ3_M ≈ 24×3.7/8 ≈ 11.1GB weights — fits with a modest context;
a 12B at Q4_K_M ≈ 7.2GB — fits with lots of room for context. Present the
real tradeoff: **bigger model at a lower quant vs. smaller model at a higher
quant.** Below ~IQ3 fidelity degrades fast — prefer a smaller param count at
Q4+ over a large model at IQ2 unless the user insists on size.

## 3. Match the model to the stated purpose

The purpose dictates *which* models are even candidates. Map it before searching:

- **Coding** — code-specialized or strong-reasoning instruct models
  (e.g. Qwen-Coder, DeepSeek-Coder/V-class, Codestral-lineage). Weight
  context window heavily (repos need it) and instruction-following accuracy.
- **General chat / assistant** — current general instruct models (Qwen,
  Llama, Mistral, Gemma lineages). Balance quality and speed.
- **Roleplay / creative / NSFW** — RP finetunes and merges (Mistral-Small /
  Nemo bases; finetuners like TheDrummer, zerofata, mradermacher merges).
  "Abliterated"/"uncensored" = refusal direction removed, genuinely
  unrestricted vs. merely permissively prompted.
- **Automation / agents / tool-use** — models with strong, reliable
  structured-output and function-calling behavior; small fast models win when
  the task is narrow and called in a loop. Determinism > flair.
- **Summarization / RAG / long-context** — prioritize large, high-quality
  context windows and faithfulness; a smaller model at high quant with a big
  context often beats a bigger model you must shrink context for.
- **Vision / multimodal** — needs a model with a vision projector (mmproj);
  account for the extra VRAM the vision tower costs.

State the 1–2 model qualities that matter most for THIS purpose, then let those
drive the pick (e.g. coding ⇒ context + accuracy; agents ⇒ structured output + speed).

## 4. Research current candidates (don't rely on memory)

Model rankings move fast — verify rather than recall. Search the open web and
Hugging Face for *current* options in the chosen family/size, then confirm the
exact quant file exists before recommending it:

- Find GGUF quant repos from reputable quantizers — `bartowski`,
  `mradermacher`, `TheBloke` (older), official org repos. Read the model card
  for the intended use, base model, and prompt/instruct template.
- Confirm the precise filename on the repo's files page — quant naming varies
  (`...-IQ3_M.gguf` vs `...i1-IQ3_M.gguf`), and recommending a name that
  doesn't exist wastes a multi-GB download.
- Note the **prompt template / instruct format** (ChatML, Mistral V7-Tekken,
  Llama-3, etc.) and sane sampler defaults — these are part of the
  recommendation, not an afterthought.
- Check the license and whether the repo is gated (needs an HF token).

Use WebSearch/WebFetch for "best <purpose> LLM <month/year>" and the HF repo
pages. Prefer recent sources; the field's six-month-old advice is often stale.

## 5. Recommend: one primary + tiered alternatives

Don't hand back a single answer with no escape hatch. Give:

1. **Primary pick** — best fit for budget × purpose, with the exact HF repo,
   filename, quant, approximate size, and template/samplers.
2. **2–3 alternatives**, each labeled by *why you'd switch*: "more capable but
   tighter context", "faster / roomier context", "darker/less filtered",
   "higher fidelity at smaller size". Keep them in the same size class where
   possible so switching is just a download + a config change.
3. The **fit math** for each, so the user can re-derive it if their hardware
   changes.

## 6. Keep switching cheap (if there's a stack to wire it into)

If the project has a model-runner config (KoboldCpp/llama.cpp/Ollama/LM Studio,
a `docker-compose`, an `.env`), make the model a **configuration value, not
code**: a download script + a single `MODEL_FILE`/model-name setting + a
restart. Models live on a host volume, never baked into images or committed to
git. Document the swap as: download → set the variable → restart. If the user
asks, write the chosen options into a short `MODEL_OPTIONS.md` (purpose,
budget, primary, alternatives, switch instructions) so the reasoning is
preserved for next time.

## Reasoning principles (the throughline)

- **Constraint first.** Discover the real hardware budget; let it bound everything.
- **Largest capable model that fits** — but never chase params past the quant
  cliff (~IQ3) when a smaller, higher-quant model serves the purpose better.
- **Purpose picks the family**, budget picks the size/quant.
- **Verify, don't recall** — confirm current models and exact filenames live.
- **Always offer tiered fallbacks** with the explicit tradeoff that distinguishes them.
- **Separate model from infrastructure** so swapping is cheap and reversible.
