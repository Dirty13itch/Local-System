"""Ollama inference backend — 7B-14B fast models + CPU fallback.

Two instances:
  - GPU (hydra-compute:11434) — 5070 Ti x2 for fast 7B-14B inference
  - CPU (hydra-storage:11434) — EPYC 56-core fallback when GPUs busy
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import AsyncGenerator

import httpx

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


class OllamaBackend(InferenceBackend):
    """Ollama REST API backend."""

    def __init__(self, host: str, name: str = "ollama") -> None:
        self.base_url = host
        self.name = name
        self.logger = setup_logging(f"inference.{name}")
        self.client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(120.0),
        )
        try:
            resp = await self.client.get("/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
            self.logger.info(
                f"Ollama ({self.name}) connected at {self.base_url}, "
                f"{len(models)} models available"
            )
        except Exception as e:
            self.logger.warning(f"Ollama ({self.name}) not available at {self.base_url}: {e}")

    async def shutdown(self) -> None:
        if self.client:
            await self.client.aclose()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        assert self.client is not None
        payload = {
            "model": request.model,
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }

        resp = await self.client.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

        return ChatResponse(
            id=generate_id("chat"),
            model=request.model,
            message=Message(
                role=Role.ASSISTANT,
                content=data.get("message", {}).get("content", ""),
            ),
            usage=TokenUsage(
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
                total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            ),
            created_at=datetime.now(timezone.utc),
        )

    async def chat_stream(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        assert self.client is not None
        payload = {
            "model": request.model,
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
            "stream": True,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }

        chat_id = generate_id("chat")
        async with self.client.stream("POST", "/api/chat", json=payload) as resp:
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                content = data.get("message", {}).get("content", "")
                done = data.get("done", False)
                yield StreamChunk(
                    id=chat_id,
                    model=request.model,
                    delta=content,
                    finish_reason="stop" if done else None,
                )

    async def embed(self, model: str, texts: list[str]) -> dict:
        assert self.client is not None
        resp = await self.client.post(
            "/api/embed",
            json={"model": model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "embeddings": data.get("embeddings", []),
            "model": model,
        }

    async def list_models(self) -> list[ModelInfo]:
        assert self.client is not None
        try:
            resp = await self.client.get("/api/tags")
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        models = []
        for m in data.get("models", []):
            models.append(
                ModelInfo(
                    id=m["name"],
                    name=m["name"],
                    backend=ModelBackend.OLLAMA,
                    size_bytes=m.get("size", 0),
                    parameter_count=m.get("details", {}).get("parameter_size", ""),
                    quantization=m.get("details", {}).get("quantization_level", ""),
                    loaded=True,
                    node=self.name,
                )
            )
        return models
