"""llama.cpp inference backend — llama-cpp-python server API."""

from __future__ import annotations

from datetime import datetime, timezone
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

logger = setup_logging("inference.llamacpp")


class LlamaCppBackend(InferenceBackend):
    """llama-cpp-python server backend (OpenAI-compatible API)."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.inference.llamacpp_host
        self.client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(120.0),
        )
        try:
            resp = await self.client.get("/v1/models")
            resp.raise_for_status()
            logger.info(f"llama.cpp connected at {self.base_url}")
        except Exception as e:
            logger.warning(f"llama.cpp not available at {self.base_url}: {e}")

    async def shutdown(self) -> None:
        if self.client:
            await self.client.aclose()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        assert self.client is not None
        payload = {
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
        }

        resp = await self.client.post("/v1/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})

        return ChatResponse(
            id=data.get("id", generate_id("chat")),
            model=data.get("model", "llamacpp"),
            message=Message(
                role=Role.ASSISTANT,
                content=choice["message"]["content"],
            ),
            usage=TokenUsage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            ),
            created_at=datetime.now(timezone.utc),
        )

    async def chat_stream(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        assert self.client is not None
        payload = {
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
        }

        import json

        chat_id = generate_id("chat")
        async with self.client.stream("POST", "/v1/chat/completions", json=payload) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload_str = line[6:]
                if payload_str == "[DONE]":
                    break
                data = json.loads(payload_str)
                choice = data["choices"][0]
                delta = choice.get("delta", {}).get("content", "")
                yield StreamChunk(
                    id=chat_id,
                    model="llamacpp",
                    delta=delta,
                    finish_reason=choice.get("finish_reason"),
                )

    async def embed(self, model: str, texts: list[str]) -> dict:
        assert self.client is not None
        resp = await self.client.post(
            "/v1/embeddings",
            json={"input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "embeddings": [item["embedding"] for item in data.get("data", [])],
            "model": model,
        }

    async def list_models(self) -> list[ModelInfo]:
        assert self.client is not None
        try:
            resp = await self.client.get("/v1/models")
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        return [
            ModelInfo(
                id=m["id"],
                name=m["id"],
                backend=ModelBackend.LLAMACPP,
                loaded=True,
                node="",
            )
            for m in data.get("data", [])
        ]
