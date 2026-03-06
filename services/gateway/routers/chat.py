"""Chat & inference routes — proxy to LiteLLM with content-aware routing."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from local_system.config import get_settings
from local_system.models import (
    ChatRequest,
    ChatResponse,
    Message,
    TokenUsage,
)

settings = get_settings()
router = APIRouter(tags=["chat"])

# ─── Content Routing ──────────────────────────────────────────────────────

# Workspaces that should always use the uncensored/creative model
_CREATIVE_WORKSPACES = {"media-library", "eobq", "creative-studio", "creative"}

# Tags that signal uncensored content is needed
_NSFW_TAGS = {"nsfw", "uncensored", "adult", "explicit", "abliterated"}

# Tags that signal creative but censored content
_CREATIVE_TAGS = {"creative", "fiction", "roleplay", "story", "writing"}

# Task types for code-focused routing
_CODING_TASKS = {"coding", "refactor", "debug", "code-review", "implementation"}

# Task types for deep reasoning
_DEEP_REASONING_TASKS = {"architecture", "deep-debug", "analysis", "math", "logic", "planning"}


def select_model(body: ChatRequest) -> str:
    """Select the best model based on request metadata.

    Only overrides the model when:
    - model is "auto" (explicit auto-routing request)
    - model is the outdated default ("llama-70b")

    When an explicit alias is set (reasoning, coding, creative, etc.),
    the user's choice is respected.

    Routing priority:
    1. NSFW tags or creative workspaces → creative (abliterated)
    2. Creative tags → creative (could be upgraded to creative-alt later)
    3. Coding task types → coding
    4. Deep reasoning task types → reasoning
    5. Default → reasoning
    """
    # If user explicitly chose a valid model alias, respect it
    explicit_aliases = {
        "reasoning", "coding", "creative", "fast",
        "coding-alt", "creative-alt", "reasoning-alt", "dev-local",
        "claude", "gpt", "deepseek", "gemini",
        "embedding", "reranker",
    }
    if body.model in explicit_aliases:
        return body.model

    # Auto-route based on metadata
    meta = body.metadata or {}
    tags = set(meta.get("tags", []))
    workspace = meta.get("workspace", "").lower()
    task_type = meta.get("task_type", "").lower()

    # 1. Uncensored content
    if tags & _NSFW_TAGS or workspace in _CREATIVE_WORKSPACES:
        return "creative"

    # 2. Creative but potentially censored
    if tags & _CREATIVE_TAGS:
        return "creative"

    # 3. Coding tasks
    if task_type in _CODING_TASKS:
        return "coding"

    # 4. Deep reasoning
    if task_type in _DEEP_REASONING_TASKS:
        return "reasoning"

    # 5. Default — reasoning is the most capable general model
    return "reasoning"


# ─── Helpers ──────────────────────────────────────────────────────────────


def _client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


def _litellm_url() -> str:
    return settings.inference.litellm_host


def _litellm_headers() -> dict:
    return {"Authorization": f"Bearer {settings.inference.litellm_key}"}


def _chat_payload(body: ChatRequest, stream: bool = False) -> dict:
    return {
        "model": body.model,
        "messages": [{"role": m.role.value, "content": m.content} for m in body.messages],
        "temperature": body.temperature,
        "max_tokens": body.max_tokens,
        "stream": stream,
    }


# ─── Routes ───────────────────────────────────────────────────────────────


@router.post("/v1/chat/completions", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """Route chat through LiteLLM with content-aware model selection."""
    # Apply content routing if model is auto or default
    body.model = select_model(body)

    client = _client(request)
    try:
        resp = await client.post(
            f"{_litellm_url()}/v1/chat/completions",
            json=_chat_payload(body),
            headers=_litellm_headers(),
            timeout=300.0,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        return ChatResponse(
            id=data["id"],
            model=data["model"],
            message=Message(role=choice["message"]["role"], content=choice["message"]["content"]),
            usage=TokenUsage(**data.get("usage", {})),
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e)) from e
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"LiteLLM unavailable: {e}") from e


@router.post("/v1/chat/completions/stream")
async def chat_stream(request: Request, body: ChatRequest) -> StreamingResponse:
    """Stream chat via SSE through LiteLLM with content-aware routing."""
    body.model = select_model(body)

    client = _client(request)

    async def event_stream():
        async with client.stream(
            "POST",
            f"{_litellm_url()}/v1/chat/completions",
            json=_chat_payload(body, stream=True),
            headers=_litellm_headers(),
            timeout=300.0,
        ) as resp:
            async for chunk in resp.aiter_text():
                yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.websocket("/v1/chat/ws")
async def chat_websocket(websocket: WebSocket):
    """WebSocket for interactive chat sessions."""
    await websocket.accept()
    # Use the shared app-level HTTP client instead of creating a new one per connection
    client = websocket.app.state.http_client
    try:
        while True:
            data = await websocket.receive_json()
            body = ChatRequest(**data)
            body.model = select_model(body)
            async with client.stream(
                "POST",
                f"{_litellm_url()}/v1/chat/completions",
                json=_chat_payload(body, stream=True),
                headers=_litellm_headers(),
                timeout=300.0,
            ) as resp:
                async for chunk in resp.aiter_text():
                    await websocket.send_text(chunk)
            await websocket.send_json({"type": "done"})
    except WebSocketDisconnect:
        pass


@router.get("/v1/models")
async def list_models(request: Request) -> list[dict]:
    """List all available models via LiteLLM."""
    client = _client(request)
    try:
        resp = await client.get(
            f"{_litellm_url()}/v1/models",
            headers=_litellm_headers(),
        )
        resp.raise_for_status()
        return resp.json().get("data", [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
