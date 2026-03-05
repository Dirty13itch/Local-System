"""Chat & inference routes — proxy to LiteLLM."""
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


@router.post("/v1/chat/completions", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """Route chat through LiteLLM for intelligent model routing."""
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
    """Stream chat via SSE through LiteLLM."""
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
    client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
    try:
        while True:
            data = await websocket.receive_json()
            body = ChatRequest(**data)
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
    finally:
        await client.aclose()


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
