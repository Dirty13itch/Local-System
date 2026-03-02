"""Integration tests for the API Gateway.

These tests require running services.
Run with: pytest tests/integration/ -m integration
"""

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def gateway_url() -> str:
    return "http://localhost:8000"


async def test_gateway_health(gateway_url: str):
    """Gateway /health should return status ok."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{gateway_url}/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "gateway"


async def test_cluster_health(gateway_url: str):
    """Gateway /health/cluster should return status for all services."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{gateway_url}/health/cluster")
        assert resp.status_code == 200
        data = resp.json()
        assert "inference" in data
        assert "orchestrator" in data
        assert "rag" in data
        assert "storage" in data
