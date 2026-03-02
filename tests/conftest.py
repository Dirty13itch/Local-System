"""Shared test fixtures for Local-System."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set default env vars for tests so config loading doesn't fail."""
    defaults = {
        "NODE_NAME": "desk",
        "NODE_ROLE": "orchestrator",
        "NODE1_HOST": "127.0.0.1",
        "NODE2_HOST": "127.0.0.1",
        "VAULT_HOST": "127.0.0.1",
        "DESK_HOST": "127.0.0.1",
        "DEV_HOST": "127.0.0.1",
        "MOBILE_HOST": "127.0.0.1",
        "POSTGRES_PASSWORD": "test",
        "REDIS_PASSWORD": "test",
        "API_SECRET_KEY": "test-secret",
    }
    for key, value in defaults.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def sample_messages() -> list[dict]:
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, how are you?"},
    ]
