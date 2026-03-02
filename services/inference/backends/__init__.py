"""Pluggable inference backends."""

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
from local_system.utils import generate_id

from .base import InferenceBackend
from .ollama import OllamaBackend
from .vllm import VLLMBackend
from .llamacpp import LlamaCppBackend


class BackendRouter:
    """Routes inference requests to the appropriate backend based on the model."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.backends: dict[ModelBackend, InferenceBackend] = {}
        self._model_backend_map: dict[str, ModelBackend] = {}

    async def initialize(self) -> None:
        """Initialize all configured backends."""
        self.backends[ModelBackend.OLLAMA] = OllamaBackend(self.settings)
        self.backends[ModelBackend.VLLM] = VLLMBackend(self.settings)
        self.backends[ModelBackend.LLAMACPP] = LlamaCppBackend(self.settings)

        for backend in self.backends.values():
            await backend.initialize()

        await self._refresh_model_map()

    async def shutdown(self) -> None:
        for backend in self.backends.values():
            await backend.shutdown()

    async def _refresh_model_map(self) -> None:
        """Refresh the mapping of model names to backends."""
        self._model_backend_map.clear()
        for backend_type, backend in self.backends.items():
            try:
                models = await backend.list_models()
                for model in models:
                    self._model_backend_map[model.name] = backend_type
            except Exception:
                continue

    def _resolve_backend(self, model: str) -> InferenceBackend:
        """Find which backend serves a given model."""
        backend_type = self._model_backend_map.get(model)
        if backend_type is None:
            # Default to Ollama — it can auto-pull models
            backend_type = ModelBackend.OLLAMA
        return self.backends[backend_type]

    async def chat(self, request: ChatRequest) -> ChatResponse:
        backend = self._resolve_backend(request.model)
        return await backend.chat(request)

    async def chat_stream(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        backend = self._resolve_backend(request.model)
        async for chunk in backend.chat_stream(request):
            yield chunk

    async def embed(self, model: str, texts: list[str]) -> dict:
        backend = self._resolve_backend(model)
        return await backend.embed(model, texts)

    async def list_models(self) -> list[ModelInfo]:
        all_models: list[ModelInfo] = []
        for backend in self.backends.values():
            try:
                models = await backend.list_models()
                all_models.extend(models)
            except Exception:
                continue
        return all_models
