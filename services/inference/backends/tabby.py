"""TabbyAPI + ExLlamaV2 backend — primary 70B inference.

Handles tensor parallel across RTX 5090 (32GB) + RTX 4090 (24GB) = 56GB VRAM.
ExLlamaV2 is the ONLY engine supporting TP across heterogeneous GPUs.
"""

from __future__ import annotations

from typing import AsyncGenerator

import httpx

from local_system.config import Settings
from local_system.models import (
    ChatRequest,
    ChatResponse,
    Message,
    ModelBackend,
    ModelInfo,
    Role,
    StreamChunk,
    TokenUsage,
)
from local_system.utils import generate_id, setup_logging

from .base import InferenceBackend

logger = setup_logging("inference.tabby")


class TabbyBackend(InferenceBackend):
    """TabbyAPI backend — OpenAI-compatible API on top of ExLlamaV2.

    Deployed on FOUNDRY.
    Provides direct model management (load/unload) and inference.
    For normal chat requests, prefer routing through LiteLLM.
    """

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.inference.tabby_host
        self.client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(300.0),  # 5 min — model loading can be slow
        )
        try:
            resp = await self.client.get("/health")
            resp.raise_for_status()
            logger.info(f"TabbyAPI connected at {self.base_url}")
        except Exception as e:
            logger.warning(f"TabbyAPI not available at {self.base_url}: {e}")

    async def shutdown(self) -> None:
        if self.client:
            await self.client.aclose()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Chat via TabbyAPI's OpenAI-compatible endpoint."""
        assert self.client is not None
        payload = {
            "model": "default",
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
        }

        resp = await self.client.post("/v1/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()

        choice = data.get("choices", [{}])[0]
        usage = data.get("usage", {})

        return ChatResponse(
            id=data.get("id", generate_id("chat")),
            model=data.get("model", "tabby"),
            message=Message(
                role=Role.ASSISTANT,
                content=choice.get("message", {}).get("content", ""),
            ),
            usage=TokenUsage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            ),
        )

    async def chat_stream(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        """Stream via TabbyAPI's SSE endpoint."""
        assert self.client is not None
        import json

        payload = {
            "model": "default",
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
        }

        chat_id = generate_id("chat")
        async with self.client.stream("POST", "/v1/chat/completions", json=payload) as resp:
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                raw = line[6:]
                if raw == "[DONE]":
                    break
                data = json.loads(raw)
                delta = data.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                finish = data.get("choices", [{}])[0].get("finish_reason")
                if content or finish:
                    yield StreamChunk(
                        id=chat_id,
                        model="tabby",
                        delta=content,
                        finish_reason=finish,
                    )

    async def embed(self, model: str, texts: list[str]) -> dict:
        """TabbyAPI doesn't handle embeddings — use Ollama instead."""
        raise NotImplementedError("Use Ollama for embeddings")

    async def list_models(self) -> list[ModelInfo]:
        """List models available on TabbyAPI."""
        assert self.client is not None
        try:
            resp = await self.client.get("/v1/models")
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        models = []
        for m in data.get("data", []):
            models.append(
                ModelInfo(
                    id=m.get("id", "unknown"),
                    name=m.get("id", "unknown"),
                    backend=ModelBackend.TABBY,
                    context_length=m.get("max_model_len", 32768),
                    loaded=True,
                    node="foundry",
                )
            )
        return models

    # --- TabbyAPI-specific management ---

    async def get_status(self) -> dict:
        """Get current model status from TabbyAPI."""
        assert self.client is not None
        try:
            resp = await self.client.get("/v1/model")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    async def load_model(self, model_name: str) -> dict:
        """Load a specific EXL2 model on TabbyAPI."""
        assert self.client is not None
        resp = await self.client.post(
            "/v1/model/load",
            json={"model_name": model_name},
            timeout=httpx.Timeout(600.0),  # 10 min for large models
        )
        resp.raise_for_status()
        return resp.json()

    async def unload_model(self) -> dict:
        """Unload the current model from TabbyAPI."""
        assert self.client is not None
        resp = await self.client.post("/v1/model/unload")
        resp.raise_for_status()
        return resp.json()
