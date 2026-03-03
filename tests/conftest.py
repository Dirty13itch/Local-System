"""Shared test fixtures for Local-System."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set default env vars for tests so config loading doesn't fail."""
    defaults = {
        "NODE_NAME": "dev",
        "NODE_ROLE": "operations",
        "FOUNDRY_HOST": "127.0.0.1",
        "WORKSHOP_HOST": "127.0.0.1",
        "VAULT_HOST": "127.0.0.1",
        "DEV_HOST": "127.0.0.1",
        "POSTGRES_PASSWORD": "test",
        "REDIS_PASSWORD": "test",
        "LITELLM_KEY": "test-key",
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
