"""Inference backends: LiteLLM (primary gateway), TabbyAPI, Ollama."""

from __future__ import annotations

from typing import AsyncGenerator

from local_system.config import Settings
from local_system.models import (
    ChatRequest,
    ChatResponse,
    ModelBackend,
    ModelInfo,
    StreamChunk,
)

from .base import InferenceBackend
from .litellm_router import LiteLLMRouter
from .tabby import TabbyBackend
from .ollama import OllamaBackend


class BackendRouter:
    """Routes inference requests through the correct backend.

    Architecture:
      - LiteLLM is the primary gateway for all chat/completion requests.
        It handles model routing (70B→TabbyAPI, 7B→Ollama GPU, fallback→Ollama CPU).
      - TabbyAPI is accessed directly for model management (load/unload/status).
      - Ollama GPU is accessed directly for embeddings.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.litellm = LiteLLMRouter(settings)
        self.tabby = TabbyBackend(settings)
        self.ollama_gpu = OllamaBackend(
            host=settings.inference.ollama_gpu_host,
            name="ollama-gpu",
        )
        self.ollama_cpu = OllamaBackend(
            host=settings.inference.ollama_cpu_host,
            name="ollama-cpu",
        )

    async def initialize(self) -> None:
        """Initialize all backends."""
        await self.litellm.initialize()
        await self.tabby.initialize()
        await self.ollama_gpu.initialize()
        await self.ollama_cpu.initialize()

    async def shutdown(self) -> None:
        await self.litellm.shutdown()
        await self.tabby.shutdown()
        await self.ollama_gpu.shutdown()
        await self.ollama_cpu.shutdown()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Route chat through LiteLLM (handles model→backend routing)."""
        return await self.litellm.chat(request)

    async def chat_stream(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        """Route streaming chat through LiteLLM."""
        async for chunk in self.litellm.chat_stream(request):
            yield chunk

    async def embed(self, model: str, texts: list[str]) -> dict:
        """Embeddings go directly to Ollama GPU (nomic-embed-text)."""
        return await self.ollama_gpu.embed(model, texts)

    async def list_models(self) -> list[ModelInfo]:
        """Aggregate models from all backends."""
        all_models: list[ModelInfo] = []
        for backend in [self.tabby, self.ollama_gpu, self.ollama_cpu]:
            try:
                models = await backend.list_models()
                all_models.extend(models)
            except Exception:
                continue
        return all_models

    # --- TabbyAPI direct management ---

    async def tabby_status(self) -> dict:
        return await self.tabby.get_status()

    async def tabby_load_model(self, model_name: str) -> dict:
        return await self.tabby.load_model(model_name)

    async def tabby_unload_model(self) -> dict:
        return await self.tabby.unload_model()
