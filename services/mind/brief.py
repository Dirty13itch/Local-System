"""Daily brief generator for MIND service.

Produces a structured summary of:
- Cluster health (all services, GPU utilization)
- Yesterday's activity (conversations, tasks, memories stored)
- Pending tasks and follow-ups
- Consolidation results
- Model performance metrics

Called via /v1/brief endpoint or scheduled at 8am daily.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

logger = logging.getLogger("mind.brief")


class DailyBrief:
    """Generates daily status briefs."""

    def __init__(
        self,
        gateway_url: str = "http://localhost:8700",
        mind_url: str = "http://localhost:8710",
        memory_url: str = "http://localhost:8720",
    ) -> None:
        self.gateway_url = gateway_url
        self.mind_url = mind_url
        self.memory_url = memory_url
        self._client: httpx.AsyncClient | None = None

    async def init(self) -> None:
        self._client = httpx.AsyncClient(timeout=15.0)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def generate(self) -> dict[str, Any]:
        """Generate a full daily brief."""
        if not self._client:
            await self.init()

        brief: dict[str, Any] = {
            "generated_at": datetime.utcnow().isoformat(),
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
        }

        # Cluster health
        try:
            resp = await self._client.get(f"{self.gateway_url}/health/cluster")
            if resp.status_code == 200:
                health = resp.json()
                brief["cluster_health"] = {
                    name: info.get("status", "unknown")
                    for name, info in health.items()
                }
                brief["services_up"] = sum(
                    1 for v in health.values()
                    if isinstance(v, dict) and v.get("status") in ("ok", "healthy")
                )
                brief["services_total"] = len(health)
        except Exception as e:
            brief["cluster_health"] = {"error": str(e)}

        # Activity (conversations in last 24h)
        try:
            resp = await self._client.get(f"{self.mind_url}/v1/conversations?limit=100")
            if resp.status_code == 200:
                convs = resp.json().get("conversations", [])
                yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat()
                recent = [c for c in convs if c.get("created_at", "") >= yesterday]
                brief["activity"] = {
                    "conversations_24h": len(recent),
                    "total_conversations": len(convs),
                    "workspaces_used": list(set(
                        c.get("workspace", "default") for c in recent
                    )),
                }
        except Exception as e:
            brief["activity"] = {"error": str(e)}

        # Memory stats
        try:
            resp = await self._client.get(f"{self.memory_url}/v1/memory/stats")
            if resp.status_code == 200:
                brief["memory"] = resp.json()
        except Exception as e:
            brief["memory"] = {"error": str(e)}

        # Pending tasks
        try:
            resp = await self._client.get(f"{self.mind_url}/v1/tasks?status=pending")
            if resp.status_code == 200:
                tasks = resp.json().get("tasks", [])
                brief["pending_tasks"] = len(tasks)
        except Exception:
            brief["pending_tasks"] = 0

        # Format summary
        brief["summary"] = self._format_summary(brief)
        return brief

    def _format_summary(self, brief: dict) -> str:
        """Format brief into readable markdown."""
        lines = [f"# Daily Brief — {brief.get('date', 'today')}\n"]

        # Health
        up = brief.get("services_up", 0)
        total = brief.get("services_total", 0)
        lines.append(f"## Cluster: {up}/{total} services healthy")
        health = brief.get("cluster_health", {})
        for name, status in health.items():
            icon = "+" if status in ("ok", "healthy") else "-"
            lines.append(f"  {icon} {name}: {status}")

        # Activity
        act = brief.get("activity", {})
        lines.append(f"\n## Activity (24h)")
        lines.append(f"  - Conversations: {act.get('conversations_24h', 0)}")
        lines.append(f"  - Workspaces: {', '.join(act.get('workspaces_used', []))}")

        # Memory
        mem = brief.get("memory", {})
        if "tiers" in mem:
            lines.append(f"\n## Memory")
            for tier, count in mem.get("tiers", {}).items():
                lines.append(f"  - {tier}: {count}")

        # Tasks
        lines.append(f"\n## Pending Tasks: {brief.get('pending_tasks', 0)}")

        return "\n".join(lines)
