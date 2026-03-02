"""Abstract base class for inference backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncGenerator

from local_system.models import ChatRequest, ChatResponse, ModelInfo, StreamChunk


class InferenceBackend(ABC):
    """Interface that all inference backends must implement."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the backend connection."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Cleanup backend resources."""

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Generate a chat completion."""

    @abstractmethod
    async def chat_stream(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        """Stream a chat completion."""

    @abstractmethod
    async def embed(self, model: str, texts: list[str]) -> dict:
        """Generate embeddings."""

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """List available models on this backend."""
