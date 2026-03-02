"""Tests for shared configuration."""

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
    assert settings.node.name == NodeName.DESK
    assert settings.node.role == NodeRole.ORCHESTRATOR
    assert settings.log_level == "INFO"


def test_network_host_lookup():
    """NetworkConfig.host_for() should return the correct IP."""
    net = NetworkConfig()
    assert net.host_for(NodeName.NODE1) == "127.0.0.1"
    assert net.host_for(NodeName.VAULT) == "127.0.0.1"


def test_service_ports_defaults():
    """ServicePorts should have correct defaults."""
    ports = ServicePorts()
    assert ports.gateway == 8000
    assert ports.inference == 8001
    assert ports.orchestrator == 8002
    assert ports.rag == 8003
    assert ports.storage == 8004
    assert ports.model_manager == 8005
    assert ports.ui == 3000


def test_database_url():
    """DatabaseConfig should build a valid async URL."""
    db = DatabaseConfig()
    assert db.url.startswith("postgresql+asyncpg://")
    assert "local_system" in db.url
