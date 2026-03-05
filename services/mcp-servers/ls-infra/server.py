"""ls-infra — Cluster infrastructure MCP server.

Monitor cluster health, GPU status, Docker containers, and service
endpoints from any coding tool. Provides the infrastructure awareness
needed for autonomous operation decisions.

Nodes:
  FOUNDRY (192.168.1.244) — 5 GPUs, vLLM inference
  WORKSHOP (192.168.1.225) — RTX 5090, vLLM fast
  VAULT (192.168.1.203)   — 26 containers, all databases
  DEV (192.168.1.189)     — Application services

Framework: FastMCP 2.0
Transport: stdio (over SSH from DESK/DEV)
"""
from __future__ import annotations

import os
import subprocess

import httpx
from fastmcp import FastMCP

# --- Configuration ---

FOUNDRY_HOST = os.environ.get("FOUNDRY_HOST", "192.168.1.244")
WORKSHOP_HOST = os.environ.get("WORKSHOP_HOST", "192.168.1.225")
VAULT_HOST = os.environ.get("VAULT_HOST", "192.168.1.203")
DEV_HOST = os.environ.get("DEV_HOST", "192.168.1.189")
LITELLM_URL = os.environ.get("LITELLM_URL", f"http://{VAULT_HOST}:4000")
LITELLM_KEY = os.environ.get("LITELLM_KEY", "sk-athanor-litellm-2026")

MEMORY_PORT = int(os.environ.get("MEMORY_PORT", "8720"))
GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", "8700"))
ORCHESTRATOR_PORT = int(os.environ.get("ORCHESTRATOR_PORT", "8703"))

# --- MCP Server ---

mcp = FastMCP(
    "ls-infra",
    instructions=(
        "Monitor cluster infrastructure. Check GPU health, service status, "
        "database connectivity, and Docker containers across all nodes."
    ),
)


@mcp.tool()
async def cluster_health() -> dict:
    """Check health of all services across the cluster.

    Tests every critical endpoint: vLLM instances, LiteLLM gateway,
    application services, and databases.
    """
    checks = {
        "inference": {
            "reasoning (FOUNDRY:8000)": f"http://{FOUNDRY_HOST}:8000/health",
            "coding (FOUNDRY:8002)": f"http://{FOUNDRY_HOST}:8002/health",
            "embedding (FOUNDRY:8001)": f"http://{FOUNDRY_HOST}:8001/health",
            "reranker (FOUNDRY:8003)": f"http://{FOUNDRY_HOST}:8003/health",
            "fast (WORKSHOP:8000)": f"http://{WORKSHOP_HOST}:8000/health",
        },
        "services": {
            "litellm (VAULT:4000)": f"{LITELLM_URL}/health",
            "gateway (DEV:8700)": f"http://{DEV_HOST}:{GATEWAY_PORT}/health",
            "memory (VAULT:8720)": f"http://{VAULT_HOST}:{MEMORY_PORT}/health",
            "mind (DEV:8710)": f"http://{DEV_HOST}:8710/health",
        },
        "databases": {
            "qdrant (VAULT:6333)": f"http://{VAULT_HOST}:6333/healthz",
            "meilisearch (VAULT:7700)": f"http://{VAULT_HOST}:7700/health",
            "neo4j (VAULT:7474)": f"http://{VAULT_HOST}:7474",
        },
    }

    results: dict = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for category, endpoints in checks.items():
            results[category] = {}
            for name, url in endpoints.items():
                try:
                    headers = {}
                    if "litellm" in name:
                        headers["Authorization"] = f"Bearer {LITELLM_KEY}"
                    resp = await client.get(url, headers=headers)
                    results[category][name] = "healthy" if resp.status_code == 200 else f"unhealthy ({resp.status_code})"
                except Exception:
                    results[category][name] = "unreachable"

    return results


@mcp.tool()
async def gpu_status() -> list[dict]:
    """Check GPU utilization and memory across FOUNDRY and WORKSHOP.

    Shows which GPUs are loaded, memory usage, and running models.
    Requires SSH access to FOUNDRY.
    """
    results = []

    # Check FOUNDRY GPUs via nvidia-smi over SSH
    try:
        output = subprocess.run(
            ["ssh", f"athanor@{FOUNDRY_HOST}",
             "nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu "
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        for line in output.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 6:
                results.append({
                    "node": "FOUNDRY",
                    "gpu_index": int(parts[0]),
                    "name": parts[1],
                    "memory_used_mb": int(parts[2]),
                    "memory_total_mb": int(parts[3]),
                    "utilization_pct": int(parts[4]),
                    "temperature_c": int(parts[5]),
                })
    except Exception as e:
        results.append({"node": "FOUNDRY", "error": str(e)})

    # WORKSHOP has a single GPU — check via vLLM health
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://{WORKSHOP_HOST}:8000/health")
            results.append({
                "node": "WORKSHOP",
                "gpu_index": 0,
                "name": "RTX 5090",
                "status": "healthy" if resp.status_code == 200 else "unhealthy",
                "model": "Qwen3-14B FP8",
            })
    except Exception:
        results.append({"node": "WORKSHOP", "gpu_index": 0, "status": "unreachable"})

    return results


@mcp.tool()
async def litellm_models() -> dict:
    """List all models available through LiteLLM with health status.

    Shows both local (free) and cloud (paid) model aliases,
    their routing, and current health.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{LITELLM_URL}/v1/models",
                headers={"Authorization": f"Bearer {LITELLM_KEY}"},
            )
            resp.raise_for_status()
            models = resp.json()
        except Exception as e:
            return {"error": f"LiteLLM unreachable: {e}"}

        try:
            health_resp = await client.get(
                f"{LITELLM_URL}/health",
                headers={"Authorization": f"Bearer {LITELLM_KEY}"},
            )
            health_resp.raise_for_status()
            health = health_resp.json()
        except Exception:
            health = {}

    return {"models": models, "health": health}


@mcp.tool()
async def service_logs(
    service: str = "gateway",
    lines: int = 50,
) -> dict:
    """Get recent logs from a DEV service via journalctl or process output.

    Args:
        service: Service name (gateway, memory, mind, perception)
        lines: Number of log lines to retrieve (default: 50)
    """
    try:
        output = subprocess.run(
            ["journalctl", "-u", f"ls-{service}", "-n", str(lines), "--no-pager"],
            capture_output=True, text=True, timeout=10,
        )
        if output.returncode == 0 and output.stdout.strip():
            return {"service": service, "logs": output.stdout}

        # Fallback: try direct process grep
        output = subprocess.run(
            ["bash", "-c", f"ps aux | grep {service} | grep -v grep"],
            capture_output=True, text=True, timeout=5,
        )
        return {"service": service, "process_info": output.stdout or "Not found"}
    except Exception as e:
        return {"service": service, "error": str(e)}


@mcp.tool()
async def docker_status(node: str = "vault") -> dict:
    """List Docker containers on a node.

    Args:
        node: Node name — "vault", "foundry", or "dev" (default: "vault")
    """
    host_map = {
        "vault": f"root@{VAULT_HOST}",
        "foundry": f"athanor@{FOUNDRY_HOST}",
        "dev": None,  # local
    }

    ssh_target = host_map.get(node)
    if ssh_target is None and node == "dev":
        cmd = ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"]
    elif ssh_target:
        cmd = ["ssh", ssh_target, "docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'"]
    else:
        return {"error": f"Unknown node: {node}"}

    try:
        output = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        containers = []
        for line in output.stdout.strip().splitlines():
            parts = line.split("\t", 2)
            if len(parts) >= 2:
                containers.append({
                    "name": parts[0],
                    "status": parts[1],
                    "ports": parts[2] if len(parts) > 2 else "",
                })
        return {"node": node, "containers": containers, "count": len(containers)}
    except Exception as e:
        return {"node": node, "error": str(e)}


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
