"""ls-knowledge — RAG search & knowledge graph MCP server.

Gives any coding tool access to the cluster's document knowledge base
and memory search. Routes to the Memory service on VAULT.

Features:
  - Hybrid search (vector + BM25) across ingested documents
  - Memory tier search (episodic, resource, knowledge vault)
  - Document ingestion
  - Collection management

Framework: FastMCP 2.0
Transport: stdio (over SSH from DESK/DEV)
"""
from __future__ import annotations

import os

import httpx
from fastmcp import FastMCP

# --- Configuration ---

DEV_HOST = os.environ.get("DEV_HOST", "192.168.1.189")
MEMORY_PORT = int(os.environ.get("MEMORY_PORT", "8720"))
PERCEPTION_PORT = int(os.environ.get("PERCEPTION_PORT", "8730"))
MEMORY_URL = os.environ.get("MEMORY_API", f"http://{DEV_HOST}:{MEMORY_PORT}")
PERCEPTION_URL = os.environ.get("PERCEPTION_API", f"http://{DEV_HOST}:{PERCEPTION_PORT}")
REQUEST_TIMEOUT = float(os.environ.get("KNOWLEDGE_TIMEOUT", "30"))

_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT))
    return _client


# --- MCP Server ---

mcp = FastMCP(
    "ls-knowledge",
    instructions=(
        "Search the local knowledge base. Hybrid search combines vector "
        "similarity (Qdrant) with keyword matching (Meilisearch). Also search "
        "across memory tiers (episodic, resource, knowledge vault)."
    ),
)


@mcp.tool()
async def search(
    query: str,
    collection: str = "default",
    top_k: int = 5,
    use_hybrid: bool = True,
    alpha: float = 0.7,
) -> dict:
    """Search the document knowledge base using hybrid search.

    Combines vector similarity (semantic meaning) with BM25 keyword matching.
    Alpha controls the blend: 1.0 = pure vector, 0.0 = pure keyword.

    Args:
        query: Natural language search query
        collection: Document collection to search (default: "default")
        top_k: Number of results to return (default: 5)
        use_hybrid: Enable hybrid vector+BM25 search (default: True)
        alpha: Vector vs keyword weight (0.0-1.0, default: 0.7)
    """
    client = await get_client()
    try:
        resp = await client.post(
            f"{MEMORY_URL}/v1/search",
            json={
                "query": query,
                "collection": collection,
                "top_k": top_k,
                "use_hybrid": use_hybrid,
                "alpha": alpha,
            },
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": f"Search failed: {e}"}


@mcp.tool()
async def search_memory(
    query: str,
    tiers: list[str] | None = None,
    top_k: int = 5,
) -> dict:
    """Search across memory tiers using semantic similarity.

    Searches episodic memories, resource documents, and knowledge vault
    entries. Returns results ranked by relevance.

    Args:
        query: Natural language search query
        tiers: Memory tiers to search (default: all).
               Options: "episodic", "resource", "knowledge_vault"
        top_k: Number of results to return (default: 5)
    """
    client = await get_client()
    body: dict = {"query": query, "top_k": top_k}
    if tiers:
        body["tiers"] = tiers
    try:
        resp = await client.post(f"{MEMORY_URL}/v1/memory/search", json=body)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": f"Memory search failed: {e}"}


@mcp.tool()
async def ingest(
    texts: list[str],
    sources: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Ingest documents into the knowledge base via Perception service.

    Chunks, embeds (via Qwen3-Embedding), and stores in both Qdrant
    (vector search) and Meilisearch (keyword search).

    Args:
        texts: List of text documents to ingest
        sources: Optional source labels for each text (e.g., filenames)
        tags: Optional tags to apply to all ingested documents
    """
    client = await get_client()
    results = []
    for i, text in enumerate(texts):
        source = sources[i] if sources and i < len(sources) else f"mcp-ingest-{i}"
        body: dict = {
            "content": text,
            "source": source,
            "content_type": "text",
            "tags": tags or [],
        }
        try:
            resp = await client.post(f"{PERCEPTION_URL}/ingest/text", json=body)
            resp.raise_for_status()
            results.append(resp.json())
        except Exception as e:
            results.append({"error": f"Ingestion failed for item {i}: {e}"})
    return {"results": results, "total": len(results)}


@mcp.tool()
async def list_collections() -> dict:
    """List memory tier statistics and collection info.

    Returns stats from all 6 memory tiers including entry counts
    and health status.
    """
    client = await get_client()
    try:
        resp = await client.get(f"{MEMORY_URL}/v1/memory/stats")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": f"Failed to get memory stats: {e}"}


@mcp.tool()
async def get_working_memory() -> dict:
    """Get current working memory context.

    Returns the active task state, conversation context, and other
    volatile data stored in Redis.
    """
    client = await get_client()
    try:
        resp = await client.get(f"{MEMORY_URL}/v1/memory/working")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": f"Failed to get working memory: {e}"}


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
