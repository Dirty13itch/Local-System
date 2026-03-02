"""Shared utilities for Local-System services."""

from __future__ import annotations

import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
import redis.asyncio as redis

from local_system.config import Settings, get_settings


def generate_id(prefix: str = "") -> str:
    """Generate a unique ID with optional prefix."""
    uid = uuid.uuid4().hex[:12]
    return f"{prefix}_{uid}" if prefix else uid


def setup_logging(service_name: str, settings: Settings | None = None) -> logging.Logger:
    """Configure structured logging for a service."""
    settings = settings or get_settings()
    logger = logging.getLogger(service_name)
    logger.setLevel(getattr(logging, settings.log_level.upper()))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        if settings.log_format == "json":
            fmt = (
                '{"time":"%(asctime)s","level":"%(levelname)s",'
                '"service":"%(name)s","message":"%(message)s"}'
            )
        else:
            fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        handler.setFormatter(logging.Formatter(fmt))
        logger.addHandler(handler)

    return logger


class Timer:
    """Context manager for timing operations."""

    def __init__(self) -> None:
        self.start_time: float = 0
        self.elapsed: float = 0

    def __enter__(self) -> Timer:
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        self.elapsed = time.perf_counter() - self.start_time

    @property
    def elapsed_ms(self) -> float:
        return self.elapsed * 1000


@asynccontextmanager
async def get_redis_client(
    settings: Settings | None = None,
) -> AsyncGenerator[redis.Redis, None]:
    """Get a Redis client connection."""
    settings = settings or get_settings()
    client = redis.from_url(settings.redis.url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@asynccontextmanager
async def get_http_client(**kwargs: object) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Get an HTTP client with default settings."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), **kwargs) as client:
        yield client
