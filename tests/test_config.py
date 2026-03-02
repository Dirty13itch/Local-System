"""Tests for Athanor shared configuration."""

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
    assert settings.node.name == NodeName.HYDRA_STORAGE
    assert settings.node.role == NodeRole.ORCHESTRATOR
    assert settings.log_level == "INFO"


def test_network_host_lookup():
    """NetworkConfig.host_for() should return the correct IP."""
    net = NetworkConfig()
    assert net.host_for(NodeName.HYDRA_AI) == "127.0.0.1"
    assert net.host_for(NodeName.HYDRA_STORAGE) == "127.0.0.1"
    assert net.host_for(NodeName.HYDRA_COMPUTE) == "127.0.0.1"


def test_service_ports_defaults():
    """ServicePorts should have correct defaults for Athanor."""
    ports = ServicePorts()
    assert ports.gateway == 8700
    assert ports.cognitive == 8701
    assert ports.memory == 8702
    assert ports.orchestrator == 8703
    assert ports.ui == 3200


def test_database_url():
    """DatabaseConfig should build a valid async URL."""
    db = DatabaseConfig()
    assert db.url.startswith("postgresql+asyncpg://")
    assert "athanor" in db.url
    assert db.sync_url.startswith("postgresql://")


def test_inference_config_defaults():
    """InferenceConfig should have correct backend URLs."""
    settings = Settings()
    assert "4000" in settings.inference.litellm_host
    assert "5000" in settings.inference.tabby_host
    assert "11434" in settings.inference.ollama_gpu_host
