# ADR-001: Staying on Qwen3-32B-AWQ (Qwen3.5 Vision Encoder OOM)

**Status:** Accepted
**Date:** 2026-03-04
**Decision makers:** Shaun, Claude (COO)

## Context

All Qwen3.5 models (1.7B through 235B) are VLMs with a fused vision encoder
(SigLip ~878M params, ~1.5 GiB weights). The vision encoder must be loaded and
profiled by vLLM regardless of `--limit-mm-per-prompt` settings.

## Decision

Stay on **Qwen3-32B-AWQ** for all local inference until one of the revisit
conditions below is met.

## Attempted Configurations (all OOM)

| Config | GPUs | Result |
|--------|------|--------|
| Qwen3.5-32B FP16, TP=2 | 2x 5070 Ti 16GB | OOM during vision encoder profiling |
| Qwen3.5-32B-AWQ, TP=2 | 2x 5070 Ti 16GB | Model loads at 14.70 GiB/GPU, ~220 MiB free, OOM on profiling |
| Qwen3.5-32B-AWQ, single | 1x 4090 24GB | Vision encoder + model exceeds 24GB |
| Qwen3.5-32B FP8 | 1x 5090 32GB | Not tested (WORKSHOP is busy with Qwen3-14B) |

### Root Cause

vLLM's multimodal profiling runs dummy forward passes through the vision encoder
to determine memory requirements. Even with `--limit-mm-per-prompt image=0`, the
encoder weights must be resident in GPU memory. On TP=2 with 5070 Ti (16 GiB
each), the AWQ model consumes 14.70 GiB/GPU leaving only ~220 MiB — not enough
for the profiling pass.

### Additional Issue: flashinfer + Blackwell

The 5070 Ti (SM 12.0, Blackwell architecture) requires:
- `FLASHINFER_DISABLE_VERSION_CHECK=1` (cubin 0.6.0 vs flashinfer 0.6.3 mismatch)
- `--enforce-eager` (CUDA forward compatibility fails on compute capability 12.0)

These workarounds work fine with Qwen3-32B-AWQ.

## Current GPU Layout

| GPU | Card | Role | Model |
|-----|------|------|-------|
| 0,1 | 2x RTX 5070 Ti 16GB | reasoning TP=2 | Qwen3-32B-AWQ |
| 2 | RTX 4090 24GB | coding | Qwen3-32B-AWQ |
| 3 | RTX 5070 Ti 16GB | embedding + reranker | Qwen3-Embedding-0.6B + Qwen3-Reranker-0.6B |
| 4 | RTX 5070 Ti 16GB | spare | — |
| WORKSHOP | RTX 5090 32GB | fast | Qwen3-14B FP8 |

## Consequences

- Local inference quality is Qwen3-level, not Qwen3.5-level
- Cloud APIs (Claude, GPT, DeepSeek, Gemini) available via LiteLLM for tasks
  requiring higher capability
- GPU 4 (spare 5070 Ti) available for future use

## Revisit Conditions

1. **Text-only Qwen3.5 variant released** — Alibaba ships a model without the
   fused vision encoder
2. **vLLM adds lazy vision encoder loading** — encoder only loaded when
   multimodal content is present
3. **Bigger GPUs acquired** — e.g., replacing 5070 Ti with 5090 (32 GiB) on
   FOUNDRY
4. **New quantization** — GPTQ/EXL2 that fits Qwen3.5+encoder in 16 GiB/GPU
