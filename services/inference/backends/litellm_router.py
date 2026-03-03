"""LiteLLM Router — unified API gateway for all inference backends.

LiteLLM runs on VAULT:4000 and routes requests to vLLM instances:
  - reasoning → vLLM on FOUNDRY:8000
  - fast → vLLM on WORKSHOP:8000
  - embedding → vLLM on FOUNDRY:8001
"""

from __future__ import annotations

import json
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

logger = setup_logging("inference.litellm")


class LiteLLMRouter(InferenceBackend):
    """LiteLLM as the primary inference gateway.

    All chat requests go through LiteLLM, which handles:
    - Model-to-backend routing
    - Fallback chains
    - Usage tracking
    - OpenAI API compatibility
    """

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.inference.litellm_host
        self.api_key = settings.inference.litellm_key
        self.client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(300.0),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            resp = await self.client.get("/health")
            logger.info(f"LiteLLM connected at {self.base_url}")
        except Exception as e:
            logger.warning(f"LiteLLM not available at {self.base_url}: {e}")

    async def shutdown(self) -> None:
        if self.client:
            await self.client.aclose()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Send chat request through LiteLLM routing."""
        assert self.client is not None
        payload = {
            "model": request.model,
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
            model=data.get("model", request.model),
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
        """Stream via LiteLLM's SSE endpoint."""
        assert self.client is not None
        payload = {
            "model": request.model,
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
                        model=request.model,
                        delta=content,
                        finish_reason=finish,
                    )

    async def embed(self, model: str, texts: list[str]) -> dict:
        """LiteLLM can route embeddings too."""
        assert self.client is not None
        resp = await self.client.post(
            "/v1/embeddings",
            json={"model": model, "input": texts},
        )
        resp.raise_for_status()
        return resp.json()

    async def list_models(self) -> list[ModelInfo]:
        """List models registered in LiteLLM."""
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
                    backend=ModelBackend.LITELLM,
                    loaded=True,
                )
            )
        return models
