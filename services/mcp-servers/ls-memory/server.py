"""ls-memory — Shared memory MCP server for coding tool interchangeability.

Full 6-tier memory access via the Memory service HTTP API (:8720).
Also retains direct Redis access for fast working-memory operations.

Tiers:
  1. Working    — Active context (Redis, fast R/W)
  2. Episodic   — Timestamped events (Qdrant)
  3. Semantic   — Knowledge graph (Neo4j)
  4. Procedural — How-to patterns (PostgreSQL)
  5. Resource   — Ingested documents (Qdrant + Meilisearch)
  6. Vault      — Validated facts (PostgreSQL + Qdrant)

Framework: FastMCP 2.0
Transport: stdio (over SSH from DESK/DEV)
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import httpx
import redis.asyncio as aioredis
from fastmcp import FastMCP
from pydantic import BaseModel, Field

# --- Configuration ---

REDIS_URL = os.environ.get("REDIS_URL", "redis://192.168.1.203:6379/1")
MEMORY_API = os.environ.get("MEMORY_API", "http://192.168.1.189:8720")
PERCEPTION_API = os.environ.get("PERCEPTION_API", "http://192.168.1.189:8730")
KEY_PREFIX = "ls:memory"
SESSION_KEY = "ls:sessions"

# --- Redis connection ---

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


async def _api(method: str, path: str, **kwargs) -> dict:
    """Call Memory service API."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await getattr(client, method)(f"{MEMORY_API}{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()


async def _perception_api(method: str, path: str, **kwargs) -> dict:
    """Call Perception service API."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await getattr(client, method)(f"{PERCEPTION_API}{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()


# --- MCP Server ---

mcp = FastMCP(
    "ls-memory",
    instructions=(
        "Shared memory for coding tool interchangeability. "
        "Provides access to all 6 memory tiers: working (active context), "
        "episodic (what happened), semantic (knowledge graph), "
        "procedural (how-to patterns), resource (ingested documents), "
        "and vault (validated facts). Also supports cross-tier search "
        "and content ingestion via the Perception pipeline."
    ),
)


# ===================================================================
# TIER 1: WORKING MEMORY — Fast Redis-backed active context
# ===================================================================

@mcp.tool()
async def memory_store(
    key: str,
    value: str,
    tags: list[str] | None = None,
    session_id: str | None = None,
    tool_name: str | None = None,
) -> str:
    """Store a working memory entry (decision, pattern, context, or note).

    Use this to record:
    - Architecture decisions ("Switched from JWT to session cookies")
    - Implementation patterns ("Using FastMCP 2.0 for all MCP servers")
    - Context for the next tool ("Auth refactor 80% done, tests still failing")

    Args:
        key: Short identifier (e.g., "auth-refactor", "gpu-layout")
        value: The actual content to remember
        tags: Categorization tags (e.g., ["gateway", "auth"])
        session_id: Group related memories in a session
        tool_name: Which tool stored this (auto-detected if possible)
    """
    r = await get_redis()
    tags = tags or []

    entry = {
        "key": key,
        "value": value,
        "tags": tags,
        "session_id": session_id,
        "tool_name": tool_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    entry_key = f"{KEY_PREFIX}:{key}"
    await r.set(entry_key, json.dumps(entry))

    for tag in tags:
        await r.sadd(f"ls:tags:{tag}", key)

    if session_id:
        await r.sadd(f"ls:session:{session_id}:memories", key)
        await r.zadd(SESSION_KEY, {session_id: time.time()})
        if tool_name:
            await r.hset(f"ls:session:{session_id}:meta", "tool_name", tool_name)

    return f"Stored working memory '{key}' with {len(tags)} tags"


@mcp.tool()
async def memory_search(
    query: str,
    tags: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search working memories by keyword and/or tags.

    Use when switching tools to find what the previous tool decided.

    Args:
        query: Search term (matches against key and value)
        tags: Tags to filter by (all must match)
        limit: Maximum results (default: 10)
    """
    r = await get_redis()
    results: list[dict] = []
    query_lower = query.lower()

    if tags:
        candidate_keys: set[str] = set()
        for i, tag in enumerate(tags):
            tag_members = await r.smembers(f"ls:tags:{tag}")
            if i == 0:
                candidate_keys = tag_members
            else:
                candidate_keys &= tag_members
    else:
        candidate_keys = set()
        async for k in r.scan_iter(match=f"{KEY_PREFIX}:*", count=200):
            candidate_keys.add(k.removeprefix(f"{KEY_PREFIX}:"))

    for mem_key in candidate_keys:
        raw = await r.get(f"{KEY_PREFIX}:{mem_key}")
        if not raw:
            continue
        entry = json.loads(raw)
        if query_lower in entry.get("key", "").lower() or query_lower in entry.get("value", "").lower():
            results.append(entry)
            if len(results) >= limit:
                break

    results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return results[:limit]


@mcp.tool()
async def memory_recall(session_id: str) -> list[dict]:
    """Recall all memories from a specific tool session.

    Args:
        session_id: The session ID to recall
    """
    r = await get_redis()
    memory_keys = await r.smembers(f"ls:session:{session_id}:memories")

    results: list[dict] = []
    for mem_key in memory_keys:
        raw = await r.get(f"{KEY_PREFIX}:{mem_key}")
        if raw:
            results.append(json.loads(raw))

    results.sort(key=lambda x: x.get("timestamp", ""))
    return results


@mcp.tool()
async def memory_list_sessions(limit: int = 10) -> list[dict]:
    """List recent tool sessions.

    Args:
        limit: Maximum sessions to return
    """
    r = await get_redis()
    session_ids = await r.zrevrange(SESSION_KEY, 0, limit - 1, withscores=True)

    sessions: list[dict] = []
    for sid, score in session_ids:
        memory_count = await r.scard(f"ls:session:{sid}:memories")
        meta = await r.hgetall(f"ls:session:{sid}:meta") or {}
        sessions.append({
            "session_id": sid,
            "tool_name": meta.get("tool_name"),
            "started_at": datetime.fromtimestamp(score, tz=timezone.utc).isoformat(),
            "memory_count": memory_count,
        })
    return sessions


@mcp.tool()
async def memory_delete(key: str) -> str:
    """Delete a working memory entry.

    Args:
        key: The key to delete
    """
    r = await get_redis()
    entry_key = f"{KEY_PREFIX}:{key}"
    raw = await r.get(entry_key)
    if not raw:
        return f"Memory '{key}' not found"

    entry = json.loads(raw)
    for tag in entry.get("tags", []):
        await r.srem(f"ls:tags:{tag}", key)
    session_id = entry.get("session_id")
    if session_id:
        await r.srem(f"ls:session:{session_id}:memories", key)

    await r.delete(entry_key)
    return f"Deleted memory '{key}'"


@mcp.tool()
async def memory_list_tags() -> list[dict]:
    """List all tags and their counts."""
    r = await get_redis()
    tags: list[dict] = []
    async for k in r.scan_iter(match="ls:tags:*", count=200):
        tag_name = k.removeprefix("ls:tags:")
        count = await r.scard(k)
        if count > 0:
            tags.append({"tag": tag_name, "count": count})
    tags.sort(key=lambda x: x["count"], reverse=True)
    return tags


# ===================================================================
# TIER 2: EPISODIC MEMORY — What happened when
# ===================================================================

@mcp.tool()
async def episodic_store(
    event_type: str,
    content: str,
    source: str = "mcp",
    importance: float = 0.5,
    tags: list[str] | None = None,
) -> dict:
    """Store an episodic event (something that happened).

    Use for: decisions made, errors encountered, solutions found,
    milestones reached, user preferences observed.

    Args:
        event_type: Category (e.g., "decision", "error", "discovery", "preference")
        content: What happened
        source: Where this came from (default: "mcp")
        importance: 0.0-1.0 how important (default: 0.5)
        tags: Optional categorization tags
    """
    return await _api("post", "/v1/memory/episodic", json={
        "event_type": event_type,
        "content": content,
        "source": source,
        "importance": importance,
        "tags": tags or [],
    })


@mcp.tool()
async def episodic_list(
    event_type: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List recent episodic events.

    Args:
        event_type: Filter by type (e.g., "decision", "error")
        limit: Maximum results
    """
    params = {"limit": limit}
    if event_type:
        params["event_type"] = event_type
    return await _api("get", "/v1/memory/episodic", params=params)


# ===================================================================
# TIER 3: SEMANTIC MEMORY — Knowledge graph
# ===================================================================

@mcp.tool()
async def semantic_add_entity(
    name: str,
    entity_type: str,
    content: str,
    properties: dict | None = None,
) -> dict:
    """Add an entity to the knowledge graph.

    Entities are nodes: people, services, concepts, files, components.

    Args:
        name: Entity name (e.g., "LiteLLM", "Gateway Service", "Shaun")
        entity_type: Category (e.g., "service", "person", "concept", "file")
        content: Description or key information
        properties: Additional key-value properties
    """
    return await _api("post", "/v1/memory/semantic/entity", json={
        "name": name,
        "entity_type": entity_type,
        "content": content,
        "properties": properties or {},
    })


@mcp.tool()
async def semantic_add_relation(
    source_id: str,
    target_id: str,
    relation_type: str,
    properties: dict | None = None,
) -> dict:
    """Add a relationship between two entities in the knowledge graph.

    Args:
        source_id: Source entity ID
        target_id: Target entity ID
        relation_type: Relationship (e.g., "depends_on", "calls", "manages", "authored_by")
        properties: Additional properties
    """
    return await _api("post", "/v1/memory/semantic/relation", json={
        "source_id": source_id,
        "target_id": target_id,
        "relation_type": relation_type,
        "properties": properties or {},
    })


@mcp.tool()
async def semantic_neighbors(
    entity_id: str,
    max_depth: int = 1,
) -> dict:
    """Get neighbors of an entity in the knowledge graph.

    Use to explore relationships: what depends on this service?
    Who works on this component? What concepts are related?

    Args:
        entity_id: Entity ID to explore from
        max_depth: How many hops to traverse (1 = direct neighbors)
    """
    return await _api("get", f"/v1/memory/semantic/neighbors/{entity_id}", params={
        "max_depth": max_depth,
    })


# ===================================================================
# TIER 4: PROCEDURAL MEMORY — How to do things
# ===================================================================

@mcp.tool()
async def procedural_store(
    task_type: str,
    description: str,
    steps: list[str],
    prerequisites: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Store a procedure (how to do something).

    Use for: deployment steps, debugging recipes, setup instructions,
    recurring workflows.

    Args:
        task_type: Category (e.g., "deploy-vllm", "debug-oom", "setup-mcp")
        description: What this procedure achieves
        steps: Ordered list of steps
        prerequisites: What's needed before starting
        tags: Categorization
    """
    return await _api("post", "/v1/memory/procedural", json={
        "task_type": task_type,
        "description": description,
        "steps": steps,
        "prerequisites": prerequisites or [],
        "tags": tags or [],
    })


@mcp.tool()
async def procedural_search(task_type: str) -> list[dict]:
    """Search for procedures by task type.

    Args:
        task_type: The type of task to find procedures for
    """
    return await _api("get", f"/v1/memory/procedural/{task_type}")


@mcp.tool()
async def procedural_record_outcome(
    entry_id: str,
    success: bool,
    notes: str = "",
) -> dict:
    """Record whether a procedure worked or failed.

    This helps the system learn which procedures are reliable.

    Args:
        entry_id: ID of the procedural entry
        success: Did it work?
        notes: What happened
    """
    return await _api("post", f"/v1/memory/procedural/{entry_id}/outcome", json={
        "success": success,
        "notes": notes,
    })


# ===================================================================
# TIER 6: VAULT — Validated high-confidence facts
# ===================================================================

@mcp.tool()
async def vault_store(
    content: str,
    category: str,
    confidence: float = 0.9,
    source: str = "mcp",
    tags: list[str] | None = None,
) -> dict:
    """Store a validated fact in the knowledge vault.

    Only store things you're confident are correct and stable.
    The vault is the system's long-term truth store.

    Args:
        content: The fact or knowledge to store
        category: Category (e.g., "architecture", "hardware", "config")
        confidence: 0.0-1.0 how confident (default: 0.9)
        source: Provenance
        tags: Categorization
    """
    return await _api("post", "/v1/memory/vault", json={
        "content": content,
        "category": category,
        "confidence": confidence,
        "source": source,
        "tags": tags or [],
    })


# ===================================================================
# CROSS-TIER: Search across all memory tiers
# ===================================================================

@mcp.tool()
async def deep_search(
    query: str,
    tiers: list[str] | None = None,
    limit: int = 10,
) -> dict:
    """Search across ALL memory tiers simultaneously.

    This is the most powerful search — it queries working memory,
    episodic events, knowledge graph, procedures, documents, and
    the vault all at once, then ranks results by relevance.

    Args:
        query: Natural language search query
        tiers: Specific tiers to search (default: all).
               Options: working, episodic, semantic, procedural, resource, vault
        limit: Maximum results per tier
    """
    return await _api("post", "/v1/memory/search", json={
        "query": query,
        "tiers": tiers,
        "limit": limit,
    })


# ===================================================================
# INGESTION: Feed content into the memory pipeline
# ===================================================================

@mcp.tool()
async def ingest_text(
    content: str,
    source: str = "mcp",
    content_type: str = "text",
    tags: list[str] | None = None,
) -> dict:
    """Ingest text content into the resource memory tier.

    Chunks the text, generates embeddings, and indexes for search.
    Use for: documentation, notes, code snippets, findings.

    Args:
        content: The text to ingest
        source: Where this came from
        content_type: "text", "markdown", or "code"
        tags: Categorization tags
    """
    return await _perception_api("post", "/ingest/text", json={
        "content": content,
        "source": source,
        "content_type": content_type,
        "tags": tags or [],
    })


@mcp.tool()
async def ingest_url(
    url: str,
    tags: list[str] | None = None,
) -> dict:
    """Ingest content from a URL into the resource memory tier.

    Fetches the URL, chunks the content, embeds and indexes it.

    Args:
        url: URL to fetch and ingest
        tags: Categorization tags
    """
    return await _perception_api("post", "/ingest/url", json={
        "url": url,
        "tags": tags or [],
    })


# ===================================================================
# UTILITIES
# ===================================================================

@mcp.tool()
async def memory_stats() -> dict:
    """Get statistics across all memory tiers.

    Shows counts, health, and storage usage for each tier.
    """
    return await _api("get", "/v1/memory/stats")


@mcp.tool()
async def memory_consolidate() -> dict:
    """Trigger memory consolidation.

    Promotes important episodic memories to the vault,
    extracts patterns into procedural memory, etc.
    """
    return await _api("post", "/v1/memory/consolidate")


@mcp.tool()
async def memory_export(format: str = "markdown") -> str:
    """Export working memories as markdown (for DECISIONS.md) or JSON.

    Bridges MCP tools with non-MCP tools like Aider. The exported
    DECISIONS.md can be committed so any tool reading the codebase
    gets the context.

    Args:
        format: "markdown" for DECISIONS.md, "json" for raw data
    """
    r = await get_redis()
    entries: list[dict] = []

    async for k in r.scan_iter(match=f"{KEY_PREFIX}:*", count=200):
        raw = await r.get(k)
        if raw:
            entries.append(json.loads(raw))

    entries.sort(key=lambda x: x.get("timestamp", ""))

    if format == "json":
        return json.dumps(entries, indent=2)

    lines = [
        "# Decisions & Context",
        "",
        f"*Auto-exported from ls-memory on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
    ]

    tagged: dict[str, list[dict]] = {}
    untagged: list[dict] = []
    for entry in entries:
        if entry.get("tags"):
            for tag in entry["tags"]:
                tagged.setdefault(tag, []).append(entry)
        else:
            untagged.append(entry)

    for tag, tag_entries in sorted(tagged.items()):
        lines.append(f"## {tag.title()}")
        lines.append("")
        for e in tag_entries:
            ts = e.get("timestamp", "")[:10]
            tool = e.get("tool_name", "unknown")
            lines.append(f"- **{e['key']}** ({ts}, {tool}): {e['value']}")
        lines.append("")

    if untagged:
        lines.append("## Uncategorized")
        lines.append("")
        for e in untagged:
            ts = e.get("timestamp", "")[:10]
            tool = e.get("tool_name", "unknown")
            lines.append(f"- **{e['key']}** ({ts}, {tool}): {e['value']}")
        lines.append("")

    return "\n".join(lines)


def main():
    """Run the MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
