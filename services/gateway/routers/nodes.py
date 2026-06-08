"""Cluster node metrics — queries Prometheus for real-time node status."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Request

from local_system.config import get_settings
from local_system.utils import setup_logging

settings = get_settings()
logger = setup_logging("gateway.nodes", settings)
router = APIRouter(prefix="/v1/nodes", tags=["nodes"])

PROMETHEUS_URL = f"http://{settings.network.vault}:9090"

# ── Node lookup tables ───────────────────────────────────────────────────

# Map Prometheus node_exporter instance labels to node names
_NODE_EXPORTER_MAP: dict[str, str] = {
    f"{settings.network.foundry}:9100": "FOUNDRY",
    f"{settings.network.workshop}:9100": "WORKSHOP",
    f"{settings.network.vault}:9100": "VAULT",
    f"{settings.network.dev}:9100": "DEV",
    "192.168.1.50:9100": "DESK",
}

# Map DCGM GPU exporter instance labels to node names
_DCGM_INSTANCE_MAP: dict[str, str] = {
    f"{settings.network.foundry}:9400": "FOUNDRY",
    f"{settings.network.workshop}:9400": "WORKSHOP",
}

# Canonical node definitions
_NODES: list[dict[str, str]] = [
    {"name": "FOUNDRY", "ip": settings.network.foundry},
    {"name": "WORKSHOP", "ip": settings.network.workshop},
    {"name": "VAULT", "ip": settings.network.vault},
    {"name": "DEV", "ip": settings.network.dev},
    {"name": "DESK", "ip": "192.168.1.50"},
]


def _client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


# ── Prometheus helpers ───────────────────────────────────────────────────


async def _prom_query(client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
    """Execute a Prometheus instant query and return the result vector."""
    try:
        resp = await client.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": query},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "success":
            return data["data"]["result"]
    except Exception as e:
        logger.warning("Prometheus query failed", extra={"query": query, "error": str(e)})
    return []


def _instance_to_node(instance: str, mapping: dict[str, str]) -> str | None:
    """Resolve a Prometheus instance label to a node name."""
    return mapping.get(instance)


def _val(result: dict[str, Any]) -> float:
    """Extract the float value from a Prometheus result entry."""
    try:
        return float(result["value"][1])
    except (KeyError, IndexError, ValueError, TypeError):
        return 0.0


# ── Endpoint ─────────────────────────────────────────────────────────────


@router.get("/status")
async def node_status(request: Request) -> dict:
    """Comprehensive cluster node metrics from Prometheus."""
    client = _client(request)

    # Fire all queries in parallel
    queries = {
        "cpu": '100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)',
        "ram_total": "node_memory_MemTotal_bytes",
        "ram_avail": "node_memory_MemAvailable_bytes",
        "disk_size": 'node_filesystem_size_bytes{mountpoint="/",fstype!="tmpfs"}',
        "disk_avail": 'node_filesystem_avail_bytes{mountpoint="/",fstype!="tmpfs"}',
        "uptime": "node_time_seconds - node_boot_time_seconds",
        "gpu_util": "DCGM_FI_DEV_GPU_UTIL",
        "gpu_vram_used": "DCGM_FI_DEV_FB_USED",
        "gpu_vram_free": "DCGM_FI_DEV_FB_FREE",
        "gpu_temp": "DCGM_FI_DEV_GPU_TEMP",
        "gpu_power": "DCGM_FI_DEV_POWER_USAGE",
    }

    tasks = {name: _prom_query(client, q) for name, q in queries.items()}
    results = dict(zip(tasks.keys(), await asyncio.gather(*tasks.values())))

    # ── Index node_exporter metrics by node name ─────────────────────

    def _index_by_node(
        data: list[dict[str, Any]],
        mapping: dict[str, str] | None = None,
    ) -> dict[str, float]:
        """Map a Prometheus vector to {node_name: value}."""
        m = mapping or _NODE_EXPORTER_MAP
        out: dict[str, float] = {}
        for entry in data:
            instance = entry.get("metric", {}).get("instance", "")
            node = _instance_to_node(instance, m)
            if node:
                out[node] = _val(entry)
        return out

    cpu_by_node = _index_by_node(results["cpu"])
    ram_total_by_node = _index_by_node(results["ram_total"])
    ram_avail_by_node = _index_by_node(results["ram_avail"])
    disk_size_by_node = _index_by_node(results["disk_size"])
    disk_avail_by_node = _index_by_node(results["disk_avail"])
    uptime_by_node = _index_by_node(results["uptime"])

    # ── Index GPU metrics by node + gpu index ────────────────────────

    # gpus_by_node: {node_name: {gpu_index: {metric: value}}}
    gpus_by_node: dict[str, dict[int, dict[str, Any]]] = {}

    gpu_metric_keys = [
        ("gpu_util", "utilization_percent"),
        ("gpu_vram_used", "vram_used_mb"),
        ("gpu_vram_free", "vram_free_mb"),
        ("gpu_temp", "temperature_c"),
        ("gpu_power", "power_watts"),
    ]

    for query_key, field_name in gpu_metric_keys:
        for entry in results[query_key]:
            metric = entry.get("metric", {})
            instance = metric.get("instance", "")
            node = _instance_to_node(instance, _DCGM_INSTANCE_MAP)
            if not node:
                continue
            try:
                gpu_idx = int(metric.get("gpu", "0"))
            except (ValueError, TypeError):
                gpu_idx = 0

            gpus_by_node.setdefault(node, {}).setdefault(gpu_idx, {})
            gpus_by_node[node][gpu_idx][field_name] = _val(entry)

            # Capture GPU name from DCGM label if present
            gpu_name = metric.get("modelName", "") or metric.get("GPU_I_PROFILE", "")
            if gpu_name:
                gpus_by_node[node][gpu_idx]["name"] = gpu_name

    # ── Assemble response ────────────────────────────────────────────

    BYTES_TO_GB = 1 / (1024 ** 3)
    nodes_out: list[dict[str, Any]] = []

    for node_def in _NODES:
        name = node_def["name"]
        ip = node_def["ip"]

        has_data = name in cpu_by_node or name in uptime_by_node
        ram_total = ram_total_by_node.get(name, 0)
        ram_avail = ram_avail_by_node.get(name, 0)
        disk_total = disk_size_by_node.get(name, 0)
        disk_avail = disk_avail_by_node.get(name, 0)

        # Build GPU list
        gpu_list: list[dict[str, Any]] = []
        if name in gpus_by_node:
            for idx in sorted(gpus_by_node[name]):
                g = gpus_by_node[name][idx]
                vram_used = g.get("vram_used_mb", 0)
                vram_free = g.get("vram_free_mb", 0)
                gpu_list.append({
                    "index": idx,
                    "name": g.get("name", f"GPU {idx}"),
                    "utilization_percent": round(g.get("utilization_percent", 0)),
                    "vram_used_mb": round(vram_used),
                    "vram_total_mb": round(vram_used + vram_free),
                    "temperature_c": round(g.get("temperature_c", 0)),
                    "power_watts": round(g.get("power_watts", 0)),
                })

        nodes_out.append({
            "name": name,
            "ip": ip,
            "online": has_data,
            "uptime_hours": round(uptime_by_node.get(name, 0) / 3600, 1),
            "cpu_percent": round(cpu_by_node.get(name, 0), 1),
            "ram_used_gb": round((ram_total - ram_avail) * BYTES_TO_GB, 1),
            "ram_total_gb": round(ram_total * BYTES_TO_GB, 1),
            "disk_used_gb": round((disk_total - disk_avail) * BYTES_TO_GB, 1),
            "disk_total_gb": round(disk_total * BYTES_TO_GB, 1),
            "gpus": gpu_list,
            "services": [],
        })

    return {
        "nodes": nodes_out,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
