"""Tests for Local-System shared configuration."""

from local_system.config import (
    NodeName,
    NodeRole,
    Settings,
    NetworkConfig,
    ServicePorts,
    DatabaseConfig,
)


def test_settings_load():
    """Settings should load with defaults."""
    settings = Settings()
    assert settings.node.name == NodeName.DEV
    assert settings.node.role == NodeRole.OPERATIONS
    assert settings.log_level == "INFO"


def test_network_host_lookup():
    """NetworkConfig.host_for() should return the correct IP for each node."""
    net = NetworkConfig()
    assert net.host_for(NodeName.FOUNDRY) == net.foundry
    assert net.host_for(NodeName.VAULT) == net.vault
    assert net.host_for(NodeName.WORKSHOP) == net.workshop


def test_service_ports_defaults():
    """ServicePorts should have correct defaults."""
    ports = ServicePorts()
    assert ports.gateway == 8700
    assert ports.memory == 8702
    assert ports.orchestrator == 8703
    assert ports.ui == 3001


def test_database_url():
    """DatabaseConfig should build a valid async URL."""
    db = DatabaseConfig()
    assert db.url.startswith("postgresql+asyncpg://")
    assert "local_system" in db.url
    assert db.sync_url.startswith("postgresql://")


def test_inference_config_defaults():
    """InferenceConfig should have correct LiteLLM and vLLM URLs."""
    settings = Settings()
    assert "4000" in settings.inference.litellm_host
    assert "8000" in settings.inference.vllm_reasoning_host
    assert "8001" in settings.inference.vllm_embedding_host
