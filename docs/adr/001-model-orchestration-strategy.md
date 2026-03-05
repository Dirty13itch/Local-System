# ADR-001: Model Orchestration & GPU Layout Strategy

**Status**: Accepted
**Date**: 2026-03-05
**Context**: Phase 3 of Local-System v4 implementation

## Decision

### GPU Layout (March 2026)

| GPU | Node | Card | VRAM | Model | Port | Quant |
|-----|------|------|------|-------|------|-------|
| 0 | FOUNDRY | RTX 5070 Ti | 16GB | Qwen3-32B-AWQ TP0 | 8000 | AWQ 4-bit |
| 1 | FOUNDRY | RTX 5070 Ti | 16GB | Qwen3-32B-AWQ TP1 | 8000 | AWQ 4-bit |
| 2 | FOUNDRY | RTX 4090 | 24GB | GLM-4.7-Flash-GPTQ-4bit | 8002 | GPTQ 4-bit |
| 3 | FOUNDRY | RTX 5070 Ti | 16GB | Huihui-Qwen3-8B-abliterated-v2 | 8004 | FP8 dynamic |
| 4 | FOUNDRY | RTX 5070 Ti | 16GB | FREE | - | - |
| 0 | WORKSHOP | RTX 5090 | 32GB | Qwen3-14B FP8 (fast) | 8000 | FP8 |
| 0 | DEV | RTX 5060 Ti | 16GB | Embedding (0.6B) + Reranker (0.6B) | 8001/8003 | FP16 |

### Model Aliases via LiteLLM

| Alias | Model | Use Case |
|-------|-------|----------|
| reasoning | Qwen3-32B-AWQ | General reasoning, default route |
| coding | GLM-4.7-Flash-GPTQ | Code gen, refactoring, debugging |
| creative | Huihui-Qwen3-8B-abliterated-v2 | Uncensored creative, EoBQ, NSFW |
| fast | Qwen3-14B FP8 | Quick iteration, drafting |
| embedding | Qwen3-Embedding-0.6B | Text embeddings |
| reranker | Qwen3-Reranker-0.6B | Search reranking |
| claude/gpt/deepseek/gemini | Cloud APIs | Fallback chain |

### Content Routing

Gateway middleware (services/gateway/routers/chat.py) auto-selects model when model=auto:

1. NSFW tags or creative workspaces -> creative (abliterated)
2. Creative tags -> creative
3. Coding task types -> coding
4. Deep reasoning tasks -> reasoning
5. Default -> reasoning

Clients set explicit alias to override.

## Qwen3.5 GDN Architecture - 16GB GPU Incompatibility

Critical finding: Qwen3.5 models use Gated Delta Networks (GDN/Mamba hybrid).
The mamba_ssm_dtype: float32 config forces all GDN layers (24 of 32 in a 9B
model) to use FP32 instead of FP16, roughly doubling effective memory. A Qwen3.5-9B
model needs ~27GB - impossible on 16GB GPUs even with TP=2.

Impact: ANY Qwen3_5ForCausalLM / Qwen3NextForCausalLM / qwen3_5_text model
is unusable on 16GB GPUs (5070 Ti, 5060 Ti). Only 4090 (24GB) or 5090 (32GB)
could host them, and even then only small variants.

Resolution: Use standard transformer models (Qwen3ForCausalLM / qwen3) for
16GB GPUs. The abliterated slot uses Huihui-Qwen3-8B-abliterated-v2 which is
standard Qwen3 architecture, fitting at ~8.8GB FP8 on a single 5070 Ti.

### Future Qwen3.5 Path

When vLLM adds FP16 support for GDN/Mamba layers (overriding mamba_ssm_dtype),
Qwen3.5-9B would drop from ~27GB to ~18GB - possible on 4090 single GPU or TP=2
on 5070 Ti. Monitor vLLM issues for this.

## vLLM Operational Notes

- FlashInfer version mismatch: athanor/vllm:v2 needs FLASHINFER_DISABLE_VERSION_CHECK=1
- FP8 quant + FP8 KV cache incompatible: Use one or the other, not both
- VRAM leak (Issue #28230): Mitigated via daily restart cron (scripts/vllm-health-restart.sh)
- Sleep mode: All instances use --enable-sleep-mode for dynamic GPU sharing
