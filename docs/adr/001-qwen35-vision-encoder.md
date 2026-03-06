# ADR-001: Qwen3.5 Upgrade Blocked — Vision Encoder + vLLM Compatibility

**Status:** Accepted (updated 2026-03-06)
**Date:** 2026-03-04, updated 2026-03-06
**Decision makers:** Shaun, Claude (COO)

## Context

All Qwen3.5 models (1.7B through 235B) are VLMs with a fused vision encoder
(SigLip ~878M params, ~1.5 GiB weights). The vision encoder must be loaded and
profiled by vLLM regardless of `--limit-mm-per-prompt` settings.

vLLM has a `--language-model-only` flag that skips the vision encoder entirely,
reclaiming ~1.5 GiB/GPU. However, this flag is NOT available in either of our
current vLLM builds (both are vLLM 0.16.0).

## Decision

Stay on current model lineup until a vLLM build with `--language-model-only`
support is available. Current lineup is functional and performant:

- **Reasoning**: Qwen3-32B-AWQ (TP=2, GPUs 0,1) — proven stable
- **Coding**: GLM-4.7-Flash GPTQ-4bit (GPU 2, 4090) — 91.2% SWE-bench
- **Creative**: Huihui-Qwen3-8B-abliterated-v2 FP8 (GPU 3) — uncensored
- **Embed/Rerank**: Qwen3-Embedding/Reranker-0.6B (DEV, 5060 Ti)
- **Fast**: Qwen3-14B (WORKSHOP, 5090)

## Findings

### Qwen3.5 OOM (2026-03-04)

| Config | GPUs | Result |
|--------|------|--------|
| Qwen3.5-32B FP16, TP=2 | 2x 5070 Ti 16GB | OOM during vision encoder profiling |
| Qwen3.5-32B-AWQ, TP=2 | 2x 5070 Ti 16GB | Loads at 14.70 GiB/GPU, OOM on profiling |
| Qwen3.5-32B-AWQ, single | 1x 4090 24GB | Vision encoder + model exceeds 24GB |

**Root Cause**: vLLM multimodal profiling runs dummy forward passes through the
vision encoder. Even with `--limit-mm-per-prompt image=0`, encoder weights must
be GPU-resident. ~220 MiB free is insufficient.

### FP8 KV Cache Image Incompatibility (2026-03-06)

| Image | FP8 KV Cache | Notes |
|-------|-------------|-------|
| `athanor/vllm:custom` | ✅ Works | Used by vllm-reasoning |
| `athanor/vllm:v2` (NVIDIA 0.16.0) | ❌ Crashes | RuntimeError during EngineCore init |

**Root Cause**: `--kv-cache-dtype fp8_e5m2` causes `athanor/vllm:v2` to crash
during model weight loading (MarlinLinearKernel for GPTQ Marlin). Only the
custom-built image supports this flag.

### flashinfer Version Mismatch (2026-03-06)

`athanor/vllm:v2` has flashinfer cubin 0.6.0 vs library 0.6.3. Requires
`FLASHINFER_DISABLE_VERSION_CHECK=1` on all containers using this image.

### `--language-model-only` Flag (2026-03-06)

Checked both vLLM images — neither supports this flag despite being vLLM 0.16.0.
This blocks ALL Qwen3.5 model upgrades including:
- Qwen3.5-122B-A10B (plan's primary reasoning target)
- Qwen3.5-27B-AWQ (available on NFS)
- Qwen3.5-9B-abliterated (available on NFS)

## Current GPU Layout (verified 2026-03-06)

| GPU | Card | Container | Image | Model | Flags |
|-----|------|-----------|-------|-------|-------|
| 0,1 | 2x 5070 Ti | vllm-reasoning | athanor/vllm:custom | Qwen3-32B-AWQ | TP=2, FP8 KV, prefix cache |
| 2 | 4090 | vllm-coding | athanor/vllm:v2 | GLM-4.7-Flash-GPTQ-4bit | sleep mode, prefix cache |
| 3 | 5070 Ti | vllm-creative | athanor/vllm:v2 | Huihui-Qwen3-8B-abl-v2 | FP8, sleep mode, prefix cache |
| 4 | 5070 Ti | — | — | SPARE | — |
| DEV | 5060 Ti | vllm-embedding/reranker | systemd | Qwen3-Embed/Rerank-0.6B | — |
| WORKSHOP | 5090 | vllm-fast | — | Qwen3-14B | — |

## Consequences

- Local inference stays at Qwen3 level (not Qwen3.5)
- Cloud APIs (Claude, GPT, DeepSeek, Gemini) available via LiteLLM
- GPU 4 (5070 Ti 16GB) remains spare
- GLM-4.7-Flash is an excellent coding model regardless

## Revisit Conditions

1. **vLLM build with `--language-model-only`** — enables Qwen3.5 models
2. **Text-only Qwen3.5 variant released** — no vision encoder
3. **New vLLM custom image built** — with both FP8 KV cache + language-model-only
4. **Bigger GPUs acquired** — sufficient VRAM for model + vision encoder
5. **vLLM adds lazy vision encoder loading** — encoder only on multimodal input
