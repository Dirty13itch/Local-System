"""Agent server routes — proxy to LangGraph agent server on FOUNDRY:9000.

Bridges the old Athanor agent system (9 agents, 72 tools, proactive scheduling,
trust/escalation, activity logging) into the Local-System Gateway API surface.

The agent server handles:
- Sonarr/Radarr/Plex media management (media-agent)
- Home Assistant automation (home-agent)
- System health monitoring (general-assistant)
- Knowledge indexing (knowledge-agent, data-curator)
- ComfyUI generation (creative-agent)
- Web research (research-agent)
- Code inspection (coding-agent)
- Content management (stash-agent)
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from local_system.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/v1/agents", tags=["agents"])

# Agent server lives on FOUNDRY
AGENT_SERVER_URL = f"http://{settings.network.foundry}:{settings.ports.agent_server}"


def _client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


# ─── Request Models ────────────────────────────────────────────────────


class AgentTaskRequest(BaseModel):
    """Submit a task to a specific agent."""
    agent: str = Field(..., description="Agent name (e.g., 'media-agent', 'home-agent')")
    prompt: str = Field(..., description="What the agent should do")
    priority: str = Field(default="normal", description="Task priority: low, normal, high")
    stream: bool = Field(default=False, description="Stream the response via SSE")


class FeedbackRequest(BaseModel):
    """Submit feedback on an agent's output (feeds trust system)."""
    agent: str
    task_id: str = ""
    vote: str = Field(..., description="'up' or 'down'")
    comment: str = ""


# ─── Agent List & Status ──────────────────────────────────────────────


@router.get("")
async def list_agents(request: Request) -> dict:
    """List all agents with their status, tools, schedules, and trust grades."""
    client = _client(request)
    try:
        # Fetch agents + trust in parallel
        agents_resp, trust_resp = await _parallel_get(
            client,
            f"{AGENT_SERVER_URL}/v1/agents",
            f"{AGENT_SERVER_URL}/v1/trust",
        )

        agents = agents_resp.get("agents", [])
        trust_data = trust_resp.get("agents", {})

        # Merge trust info into agent data
        for agent in agents:
            name = agent["name"]
            if name in trust_data:
                agent["trust"] = trust_data[name]

        return {"agents": agents, "server_url": AGENT_SERVER_URL}
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail=f"Agent server unreachable at {AGENT_SERVER_URL}",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/health")
async def agent_server_health(request: Request) -> dict:
    """Quick health check of the agent server."""
    client = _client(request)
    try:
        resp = await client.get(f"{AGENT_SERVER_URL}/health", timeout=5.0)
        return {"status": "online", "server": AGENT_SERVER_URL, "detail": resp.json()}
    except httpx.ConnectError:
        return {"status": "offline", "server": AGENT_SERVER_URL}
    except Exception as e:
        return {"status": "error", "server": AGENT_SERVER_URL, "error": str(e)}


# ─── Agent Activity & History ─────────────────────────────────────────


@router.get("/activity")
async def get_activity(request: Request, limit: int = 20) -> dict:
    """Get recent agent activity — what agents have been doing proactively."""
    client = _client(request)
    try:
        resp = await client.get(
            f"{AGENT_SERVER_URL}/v1/activity",
            params={"limit": limit},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/trust")
async def get_trust(request: Request) -> dict:
    """Get trust levels for all agents."""
    client = _client(request)
    try:
        resp = await client.get(f"{AGENT_SERVER_URL}/v1/trust")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/schedules")
async def get_schedules(request: Request) -> dict:
    """Get the proactive scheduler status — what's scheduled, when it last ran."""
    client = _client(request)
    try:
        resp = await client.get(f"{AGENT_SERVER_URL}/v1/tasks/schedules")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ─── Task Submission ──────────────────────────────────────────────────


@router.post("/task")
async def submit_task(request: Request, body: AgentTaskRequest) -> dict:
    """Submit a task to a specific agent for background execution."""
    client = _client(request)
    try:
        resp = await client.post(
            f"{AGENT_SERVER_URL}/v1/tasks",
            json={
                "agent": body.agent,
                "prompt": body.prompt,
                "priority": body.priority,
            },
            timeout=httpx.Timeout(180.0),  # Agent tasks can take a while
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail=f"Agent server unreachable at {AGENT_SERVER_URL}",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{agent_name}/chat")
async def chat_with_agent(request: Request, agent_name: str) -> dict:
    """Send a message to a specific agent and get a response."""
    body = await request.json()
    client = _client(request)
    try:
        resp = await client.post(
            f"{AGENT_SERVER_URL}/v1/chat/completions",
            json={
                "agent": agent_name,
                "message": body.get("message", body.get("prompt", "")),
            },
            timeout=httpx.Timeout(180.0),
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ─── Feedback / Trust ─────────────────────────────────────────────────


@router.post("/feedback")
async def submit_feedback(request: Request, body: FeedbackRequest) -> dict:
    """Submit feedback on an agent's output — feeds the trust system."""
    client = _client(request)
    vote_map = {"up": "thumbs_up", "down": "thumbs_down"}
    try:
        resp = await client.post(
            f"{AGENT_SERVER_URL}/v1/feedback",
            json={
                "agent": body.agent,
                "feedback_type": vote_map.get(body.vote, body.vote),
                "message_content": body.comment or body.task_id,
                "response_content": "",
            },
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ─── Work Plan ────────────────────────────────────────────────────────


@router.get("/workplan")
async def get_workplan(request: Request) -> dict:
    """Get the current autonomous work plan."""
    client = _client(request)
    try:
        resp = await client.get(f"{AGENT_SERVER_URL}/v1/workplan")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ─── Escalation Queue ────────────────────────────────────────────────


@router.get("/pending")
async def get_pending_actions(request: Request) -> dict:
    """Get actions waiting for user approval (escalation/notification queue)."""
    client = _client(request)
    try:
        resp = await client.get(f"{AGENT_SERVER_URL}/v1/notifications")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/pending/{action_id}/resolve")
async def resolve_pending(request: Request, action_id: str) -> dict:
    """Approve or reject a pending escalated action."""
    body = await request.json()
    client = _client(request)
    try:
        resp = await client.post(
            f"{AGENT_SERVER_URL}/v1/notifications/{action_id}/resolve",
            json=body,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ─── Helpers ──────────────────────────────────────────────────────────


async def _parallel_get(
    client: httpx.AsyncClient, *urls: str
) -> list[dict]:
    """Fetch multiple URLs in parallel, returning their JSON responses."""
    import asyncio

    async def _fetch(url: str) -> dict:
        try:
            resp = await client.get(url, timeout=10.0)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {}

    results = await asyncio.gather(*[_fetch(url) for url in urls])
    return list(results)
