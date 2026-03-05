"""ls-inference — Local model access MCP server.

Gives any MCP-capable coding tool access to the full model pool
without knowing infrastructure details. Routes directly to vLLM
instances on FOUNDRY and WORKSHOP. Falls back to LiteLLM on VAULT
for cloud API models when available.

Available model aliases:
  "reasoning"  -> Qwen3-32B-AWQ on FOUNDRY TP=2 (GPUs 0,1) :8000
  "coding"     -> Qwen3-32B-AWQ on FOUNDRY 4090 (GPU 2) :8002
  "fast"       -> Qwen3-14B FP8 on WORKSHOP (5090) :8000
  "embedding"  -> Qwen3-Embedding-0.6B on FOUNDRY (GPU 3) :8001
  "reranker"   -> Qwen3-Reranker-0.6B on FOUNDRY (GPU 3) :8003
  "local"      -> Ollama on DEV :11434

Framework: FastMCP 2.0
Transport: stdio (over SSH from DESK/DEV)
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastmcp import FastMCP

# --- Configuration ---

FOUNDRY_HOST = os.environ.get("FOUNDRY_HOST", "192.168.1.244")
WORKSHOP_HOST = os.environ.get("WORKSHOP_HOST", "192.168.1.225")
DEV_HOST = os.environ.get("DEV_HOST", "192.168.1.189")
LITELLM_URL = os.environ.get("LITELLM_URL", "http://192.168.1.203:4000")
LITELLM_KEY = os.environ.get("LITELLM_KEY", "sk-athanor-litellm-2026")
REQUEST_TIMEOUT = float(os.environ.get("INFERENCE_TIMEOUT", "120"))

# --- Direct routing table ---

MODEL_ROUTES: dict[str, dict[str, Any]] = {
    # Local vLLM models (zero cost, full privacy)
    "reasoning": {
        "base_url": f"http://{FOUNDRY_HOST}:8000/v1",
        "model_id": "/models/Qwen3-32B-AWQ",
        "type": "vllm",
        "description": "Qwen3-32B-AWQ TP=2 on FOUNDRY (general reasoning)",
    },
    "coding": {
        "base_url": f"http://{FOUNDRY_HOST}:8002/v1",
        "model_id": "/models/Qwen3-32B-AWQ",
        "type": "vllm",
        "description": "Qwen3-32B-AWQ on FOUNDRY 4090 (coding tasks)",
    },
    "fast": {
        "base_url": f"http://{WORKSHOP_HOST}:8000/v1",
        "model_id": "fast",
        "type": "vllm",
        "description": "Qwen3-14B FP8 on WORKSHOP 5090 (quick tasks)",
    },
    "embedding": {
        "base_url": f"http://{FOUNDRY_HOST}:8001/v1",
        "model_id": "/models/Qwen3-Embedding-0.6B",
        "type": "vllm",
        "description": "Qwen3-Embedding-0.6B on FOUNDRY (vector embeddings)",
    },
    "reranker": {
        "base_url": f"http://{FOUNDRY_HOST}:8003/v1",
        "model_id": "/models/Qwen3-Reranker-0.6B",
        "type": "vllm",
        "description": "Qwen3-Reranker-0.6B on FOUNDRY (search reranking)",
    },
    "local": {
        "base_url": f"http://{DEV_HOST}:11434/v1",
        "model_id": "dolphin-mistral:7b",
        "type": "ollama",
        "description": "Ollama fallback on DEV (lightweight)",
    },
    # Cloud models (routed through LiteLLM when available)
    "claude": {
        "base_url": f"{LITELLM_URL}/v1",
        "model_id": "claude",
        "type": "litellm",
        "description": "Claude via Anthropic API",
    },
    "deepseek": {
        "base_url": f"{LITELLM_URL}/v1",
        "model_id": "deepseek",
        "type": "litellm",
        "description": "DeepSeek V3 API ($0.28/M)",
    },
    "gemini": {
        "base_url": f"{LITELLM_URL}/v1",
        "model_id": "gemini",
        "type": "litellm",
        "description": "Gemini 2.5 Pro API (1M context)",
    },
}

# --- HTTP client pool ---

_clients: dict[str, httpx.AsyncClient] = {}


async def get_client(base_url: str, use_litellm_key: bool = False) -> httpx.AsyncClient:
    """Get or create an HTTP client for the given base URL."""
    if base_url not in _clients:
        headers = {"Content-Type": "application/json"}
        if use_litellm_key:
            headers["Authorization"] = f"Bearer {LITELLM_KEY}"
        _clients[base_url] = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(REQUEST_TIMEOUT),
            headers=headers,
        )
    return _clients[base_url]


def resolve_route(model: str) -> dict[str, Any]:
    """Resolve a model alias to its routing info."""
    if model in MODEL_ROUTES:
        return MODEL_ROUTES[model]
    # Unknown alias — try LiteLLM as fallback
    return {
        "base_url": f"{LITELLM_URL}/v1",
        "model_id": model,
        "type": "litellm",
        "description": f"Unknown model '{model}' — trying LiteLLM",
    }


# --- MCP Server ---

mcp = FastMCP(
    "ls-inference",
    instructions=(
        "Access local and cloud AI models. Route completions, embeddings, "
        "and reranking directly to vLLM on FOUNDRY/WORKSHOP. Use aliases: "
        "reasoning, fast, coding, embedding, reranker, claude, deepseek, gemini."
    ),
)


@mcp.tool()
async def complete(
    model: str = "reasoning",
    messages: list[dict[str, str]] | None = None,
    prompt: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    system_prompt: str | None = None,
) -> dict:
    """Generate a chat completion using any available model.

    Routes directly to vLLM instances — no LiteLLM dependency for local models.

    Args:
        model: Model alias. Local (free): reasoning, fast, coding, local.
               Cloud (paid): claude, deepseek, gemini.
        messages: Chat messages as [{"role": "user", "content": "..."}]
        prompt: Simple text prompt (alternative to messages)
        temperature: Sampling temperature (0.0-2.0, default 0.7)
        max_tokens: Maximum tokens to generate (default 4096)
        system_prompt: Optional system prompt (prepended to messages)
    """
    route = resolve_route(model)
    use_key = route["type"] == "litellm"
    client = await get_client(route["base_url"], use_litellm_key=use_key)

    # Build messages from either messages list or simple prompt
    full_messages: list[dict[str, str]] = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    if messages:
        full_messages.extend(messages)
    elif prompt:
        full_messages.append({"role": "user", "content": prompt})
    else:
        return {"error": "Provide either 'messages' or 'prompt'"}

    payload = {
        "model": route["model_id"],
        "messages": full_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        resp = await client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text[:500]}"}
    except Exception as e:
        return {"error": f"Request failed: {e}"}

    choice = data.get("choices", [{}])[0]
    return {
        "content": choice.get("message", {}).get("content", ""),
        "model": data.get("model", model),
        "usage": data.get("usage", {}),
        "finish_reason": choice.get("finish_reason"),
        "route": route["description"],
    }


@mcp.tool()
async def embed(
    text: str | list[str],
    model: str = "embedding",
) -> dict:
    """Generate embeddings for text.

    Uses Qwen3-Embedding-0.6B on FOUNDRY by default (free, local).
    Returns 1024-dimensional vectors for semantic search.

    Args:
        text: Text string or list of strings to embed
        model: Model alias (default: "embedding")
    """
    route = resolve_route(model)
    use_key = route["type"] == "litellm"
    client = await get_client(route["base_url"], use_litellm_key=use_key)

    if isinstance(text, str):
        text = [text]

    payload = {
        "model": route["model_id"],
        "input": text,
    }

    try:
        resp = await client.post("/embeddings", json=payload)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"error": f"Embedding request failed: {e}"}

    embeddings = [item["embedding"] for item in data.get("data", [])]
    return {
        "embeddings": embeddings,
        "model": data.get("model", model),
        "dimensions": len(embeddings[0]) if embeddings else 0,
        "count": len(embeddings),
        "route": route["description"],
    }


@mcp.tool()
async def rerank(
    query: str,
    documents: list[str],
    model: str = "reranker",
    top_k: int | None = None,
) -> list[dict]:
    """Rerank documents by relevance to a query.

    Uses Qwen3-Reranker-0.6B cross-encoder on FOUNDRY (free, local).
    Returns documents sorted by relevance score.

    Args:
        query: The search query
        documents: List of document texts to rerank
        model: Model alias (default: "reranker")
        top_k: Return only top K results (default: all)
    """
    route = resolve_route(model)
    results = []

    try:
        client = await get_client(route["base_url"], use_litellm_key=False)
        for i, doc in enumerate(documents):
            payload = {
                "model": route["model_id"],
                "text_1": query,
                "text_2": doc,
            }
            resp = await client.post("/score", json=payload)
            resp.raise_for_status()
            score = resp.json().get("data", [{}])[0].get("score", 0.0)
            results.append({"document": doc, "score": score, "index": i})
    except Exception as e:
        return [{"error": f"Reranking failed: {e}"}]

    results.sort(key=lambda x: x["score"], reverse=True)

    if top_k:
        results = results[:top_k]

    return results


@mcp.tool()
async def list_models() -> list[dict]:
    """List all available model aliases and their health status.

    Checks each vLLM endpoint directly for health (no LiteLLM dependency).
    """
    results = []

    for alias, route in MODEL_ROUTES.items():
        health = "unknown"

        if route["type"] in ("vllm", "ollama"):
            try:
                async with httpx.AsyncClient(timeout=3.0) as c:
                    if route["type"] == "vllm":
                        health_url = route["base_url"].replace("/v1", "/health")
                        resp = await c.get(health_url)
                    else:
                        resp = await c.get(f"{route['base_url']}/models")
                    health = "healthy" if resp.status_code == 200 else f"unhealthy ({resp.status_code})"
            except Exception:
                health = "unreachable"
        elif route["type"] == "litellm":
            health = "requires LiteLLM (VAULT:4000)"

        results.append({
            "alias": alias,
            "description": route["description"],
            "model_id": route["model_id"],
            "type": route["type"],
            "health": health,
        })

    return results


@mcp.tool()
async def gpu_status() -> list[dict]:
    """Check health of all inference endpoints across the cluster."""
    checks = [
        ("FOUNDRY", FOUNDRY_HOST, 8000, "reasoning", "Qwen3-32B-AWQ TP=2"),
        ("FOUNDRY", FOUNDRY_HOST, 8001, "embedding", "Qwen3-Embedding-0.6B"),
        ("FOUNDRY", FOUNDRY_HOST, 8002, "coding", "Qwen3-32B-AWQ (4090)"),
        ("FOUNDRY", FOUNDRY_HOST, 8003, "reranker", "Qwen3-Reranker-0.6B"),
        ("WORKSHOP", WORKSHOP_HOST, 8000, "fast", "Qwen3-14B FP8 (5090)"),
    ]

    results = []
    for node, host, port, alias, desc in checks:
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                resp = await c.get(f"http://{host}:{port}/health")
                status = "healthy" if resp.status_code == 200 else f"unhealthy ({resp.status_code})"
        except Exception:
            status = "unreachable"

        results.append({
            "node": node,
            "host": host,
            "port": port,
            "alias": alias,
            "model": desc,
            "status": status,
        })

    return results


def main():
    """Run the MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
