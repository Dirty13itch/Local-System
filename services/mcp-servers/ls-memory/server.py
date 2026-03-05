"""ls-memory — Shared memory MCP server for coding tool interchangeability.

This server is the backbone of tool switching. Every MCP-capable coding tool
(Claude Code, Kimi Code, Codex CLI, etc.) connects to this server to read/write
shared memory. When you switch tools, the new tool picks up exactly where the
last one left off.

Storage: Redis on VAULT (192.168.1.203:6379/1)
Framework: FastMCP 2.0
Transport: stdio (over SSH from DESK/DEV)

Redis key layout:
  ls:memory:{key}           — individual memory entries (JSON hashes)
  ls:sessions               — sorted set of sessions by timestamp
  ls:session:{id}:memories  — set of memory keys belonging to a session
  ls:tags:{tag}             — set of memory keys with this tag
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastmcp import FastMCP
from pydantic import BaseModel, Field

# --- Configuration ---

REDIS_URL = os.environ.get("REDIS_URL", "redis://192.168.1.203:6379/1")
KEY_PREFIX = "ls:memory"
SESSION_KEY = "ls:sessions"
MAX_SEARCH_RESULTS = 50

# --- Models ---


class MemoryEntry(BaseModel):
    """A single memory entry stored by any coding tool."""

    key: str
    value: str
    tags: list[str] = Field(default_factory=list)
    session_id: str | None = None
    tool_name: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SessionInfo(BaseModel):
    """Summary of a tool session."""

    session_id: str
    tool_name: str | None = None
    started_at: str
    memory_count: int = 0
    summary: str | None = None


# --- Redis connection ---

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Get or create Redis connection."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


# --- MCP Server ---

mcp = FastMCP(
    "ls-memory",
    instructions=(
        "Shared memory for coding tool interchangeability. "
        "Store decisions, patterns, and context that persist across "
        "Claude Code, Kimi Code, Codex CLI, and other tools."
    ),
)


@mcp.tool()
async def memory_store(
    key: str,
    value: str,
    tags: list[str] | None = None,
    session_id: str | None = None,
    tool_name: str | None = None,
) -> str:
    """Store a memory entry (decision, pattern, context, or note).

    Use this to record:
    - Architecture decisions ("Switched from JWT to session cookies")
    - Implementation patterns ("Using FastMCP 2.0 for all MCP servers")
    - Context for the next tool ("Auth refactor 80% done, tests still failing")
    - Important findings ("Qwen3.5-27B outperforms Qwen2.5-Coder-32B")

    Args:
        key: Short identifier for this memory (e.g., "auth-refactor", "gpu-layout")
        value: The actual content to remember
        tags: Optional categorization tags (e.g., ["gateway", "auth", "architecture"])
        session_id: Optional session ID to group related memories
        tool_name: Name of the tool storing this (auto-detected if possible)
    """
    r = await get_redis()
    tags = tags or []

    entry = MemoryEntry(
        key=key,
        value=value,
        tags=tags,
        session_id=session_id,
        tool_name=tool_name,
    )

    entry_key = f"{KEY_PREFIX}:{key}"
    await r.set(entry_key, entry.model_dump_json())

    # Index by tags
    for tag in tags:
        await r.sadd(f"ls:tags:{tag}", key)

    # Track in session if provided
    if session_id:
        await r.sadd(f"ls:session:{session_id}:memories", key)
        await r.zadd(SESSION_KEY, {session_id: time.time()})
        if tool_name:
            await r.hset(f"ls:session:{session_id}:meta", "tool_name", tool_name)

    return f"Stored memory '{key}' with {len(tags)} tags"


@mcp.tool()
async def memory_search(
    query: str,
    tags: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search stored memories by keyword and/or tags.

    Use this when switching tools to find what the previous tool decided,
    or to recall context about a specific topic.

    Args:
        query: Search term (matches against key and value)
        tags: Optional tags to filter by (all must match)
        limit: Maximum results to return (default: 10)
    """
    r = await get_redis()
    results: list[dict] = []
    query_lower = query.lower()

    # If tags specified, get intersection of tag sets
    if tags:
        candidate_keys: set[str] = set()
        for i, tag in enumerate(tags):
            tag_members = await r.smembers(f"ls:tags:{tag}")
            if i == 0:
                candidate_keys = tag_members
            else:
                candidate_keys &= tag_members
    else:
        # Scan all memory keys
        candidate_keys = set()
        async for k in r.scan_iter(match=f"{KEY_PREFIX}:*", count=200):
            # Extract the key part after prefix
            candidate_keys.add(k.removeprefix(f"{KEY_PREFIX}:"))

    # Search through candidates
    for mem_key in candidate_keys:
        entry_key = f"{KEY_PREFIX}:{mem_key}"
        raw = await r.get(entry_key)
        if not raw:
            continue

        entry = json.loads(raw)
        # Match query against key and value
        if query_lower in entry.get("key", "").lower() or query_lower in entry.get("value", "").lower():
            results.append(entry)
            if len(results) >= limit:
                break

    # Sort by timestamp (newest first)
    results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return results[:limit]


@mcp.tool()
async def memory_recall(session_id: str) -> list[dict]:
    """Recall all memories from a specific tool session.

    Use this to see everything that happened in a previous session,
    e.g., what Claude Code decided before you switched to Kimi Code.

    Args:
        session_id: The session ID to recall memories from
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
    """List recent tool sessions with summaries.

    Shows which tools were used recently and how many memories each stored.
    Useful for understanding the history of tool switches.

    Args:
        limit: Maximum sessions to return (default: 10)
    """
    r = await get_redis()

    # Get most recent sessions
    session_ids = await r.zrevrange(SESSION_KEY, 0, limit - 1, withscores=True)

    sessions: list[dict] = []
    for sid, score in session_ids:
        memory_count = await r.scard(f"ls:session:{sid}:memories")
        meta = await r.hgetall(f"ls:session:{sid}:meta") or {}

        sessions.append(
            SessionInfo(
                session_id=sid,
                tool_name=meta.get("tool_name"),
                started_at=datetime.fromtimestamp(score, tz=timezone.utc).isoformat(),
                memory_count=memory_count,
            ).model_dump()
        )

    return sessions


@mcp.tool()
async def memory_delete(key: str) -> str:
    """Delete a specific memory entry.

    Args:
        key: The key of the memory to delete
    """
    r = await get_redis()
    entry_key = f"{KEY_PREFIX}:{key}"

    # Get entry to find tags for cleanup
    raw = await r.get(entry_key)
    if not raw:
        return f"Memory '{key}' not found"

    entry = json.loads(raw)

    # Remove from tag indexes
    for tag in entry.get("tags", []):
        await r.srem(f"ls:tags:{tag}", key)

    # Remove from session if applicable
    session_id = entry.get("session_id")
    if session_id:
        await r.srem(f"ls:session:{session_id}:memories", key)

    # Delete the entry
    await r.delete(entry_key)
    return f"Deleted memory '{key}'"


@mcp.tool()
async def memory_list_tags() -> list[dict]:
    """List all tags and their memory counts.

    Useful for discovering what categories of memories exist.
    """
    r = await get_redis()
    tags: list[dict] = []

    async for k in r.scan_iter(match="ls:tags:*", count=200):
        tag_name = k.removeprefix("ls:tags:")
        count = await r.scard(k)
        if count > 0:
            tags.append({"tag": tag_name, "count": count})

    tags.sort(key=lambda x: x["count"], reverse=True)
    return tags


@mcp.tool()
async def memory_export(format: str = "markdown") -> str:
    """Export all memories as markdown (for DECISIONS.md) or JSON.

    This bridges MCP-capable tools with non-MCP tools like Aider.
    The exported DECISIONS.md can be committed to the repo so any
    tool reading the codebase gets the context.

    Args:
        format: Output format — "markdown" for DECISIONS.md, "json" for raw data
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

    # Markdown format for DECISIONS.md
    lines = [
        "# Decisions & Context",
        "",
        f"*Auto-exported from ls-memory on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
    ]

    # Group by tags
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
