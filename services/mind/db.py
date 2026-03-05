"""PostgreSQL persistence for MIND service.

Stores conversation history, task state, agent execution logs,
and workspace configuration. Uses asyncpg for async access.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import asyncpg

from local_system.config import get_settings

logger = logging.getLogger("mind.db")

SCHEMA_SQL = """
-- MIND conversations: multi-turn exchanges
CREATE TABLE IF NOT EXISTS mind_conversations (
    id TEXT PRIMARY KEY,
    workspace TEXT DEFAULT 'default',
    title TEXT DEFAULT '',
    model TEXT DEFAULT 'reasoning',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- MIND messages within conversations
CREATE TABLE IF NOT EXISTS mind_messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES mind_conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,  -- system, user, assistant, tool
    content TEXT NOT NULL DEFAULT '',
    tool_calls JSONB DEFAULT '[]',
    tool_call_id TEXT,
    model TEXT,
    tokens_in INT DEFAULT 0,
    tokens_out INT DEFAULT 0,
    latency_ms INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mind_messages_conv ON mind_messages(conversation_id, created_at);

-- MIND tasks: agent work items
CREATE TABLE IF NOT EXISTS mind_tasks (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES mind_conversations(id),
    specialist TEXT DEFAULT 'general',
    description TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    result TEXT,
    error TEXT,
    agent_id TEXT,
    model TEXT DEFAULT 'reasoning',
    iterations INT DEFAULT 0,
    memory_context JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_mind_tasks_status ON mind_tasks(status);

-- MIND agent execution logs (for debugging and improvement)
CREATE TABLE IF NOT EXISTS mind_agent_logs (
    id SERIAL PRIMARY KEY,
    task_id TEXT REFERENCES mind_tasks(id),
    iteration INT NOT NULL,
    action TEXT NOT NULL,  -- 'llm_call', 'tool_exec', 'memory_read', 'decision'
    detail JSONB DEFAULT '{}',
    duration_ms INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mind_agent_logs_task ON mind_agent_logs(task_id, iteration);
"""


class MindDB:
    """Async PostgreSQL interface for MIND service state."""

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None
        self._settings = get_settings()

    async def init(self) -> None:
        try:
            self._pool = await asyncpg.create_pool(
                host=self._settings.database.host,
                port=self._settings.database.port,
                database=self._settings.database.name,
                user=self._settings.database.user,
                password=self._settings.database.password,
                min_size=2,
                max_size=10,
            )
            async with self._pool.acquire() as conn:
                await conn.execute(SCHEMA_SQL)
            logger.info("MIND database initialized (PostgreSQL)")
        except Exception as e:
            logger.warning(f"MIND database init failed: {e}")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    @property
    def ready(self) -> bool:
        return self._pool is not None

    # --- Conversations ---

    async def create_conversation(
        self, conv_id: str, workspace: str = "default", model: str = "reasoning"
    ) -> None:
        if not self._pool:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO mind_conversations (id, workspace, model) VALUES ($1, $2, $3) "
                "ON CONFLICT (id) DO UPDATE SET updated_at = NOW()",
                conv_id, workspace, model,
            )

    async def get_conversation(self, conv_id: str) -> dict | None:
        if not self._pool:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM mind_conversations WHERE id = $1", conv_id
            )
            return dict(row) if row else None

    async def list_conversations(
        self, workspace: str | None = None, limit: int = 50
    ) -> list[dict]:
        if not self._pool:
            return []
        async with self._pool.acquire() as conn:
            if workspace:
                rows = await conn.fetch(
                    "SELECT * FROM mind_conversations WHERE workspace = $1 "
                    "ORDER BY updated_at DESC LIMIT $2",
                    workspace, limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM mind_conversations ORDER BY updated_at DESC LIMIT $1",
                    limit,
                )
            return [dict(r) for r in rows]

    # --- Messages ---

    async def store_message(
        self,
        msg_id: str,
        conversation_id: str,
        role: str,
        content: str,
        *,
        tool_calls: list[dict] | None = None,
        tool_call_id: str | None = None,
        model: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: int = 0,
    ) -> None:
        if not self._pool:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO mind_messages"
                "(id, conversation_id, role, content, tool_calls, tool_call_id, "
                "model, tokens_in, tokens_out, latency_ms) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
                msg_id, conversation_id, role, content,
                json.dumps(tool_calls or []),
                tool_call_id, model, tokens_in, tokens_out, latency_ms,
            )
            # Update conversation timestamp
            await conn.execute(
                "UPDATE mind_conversations SET updated_at = NOW() WHERE id = $1",
                conversation_id,
            )

    async def get_messages(
        self, conversation_id: str, limit: int = 100
    ) -> list[dict]:
        if not self._pool:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM mind_messages WHERE conversation_id = $1 "
                "ORDER BY created_at ASC LIMIT $2",
                conversation_id, limit,
            )
            return [dict(r) for r in rows]

    # --- Tasks ---

    async def store_task(self, task: dict) -> None:
        if not self._pool:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO mind_tasks"
                "(id, conversation_id, specialist, description, status, agent_id, model, memory_context) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
                "ON CONFLICT (id) DO UPDATE SET "
                "status = EXCLUDED.status, result = EXCLUDED.result, error = EXCLUDED.error",
                task.get("id"), task.get("conversation_id"),
                task.get("specialist", "general"), task.get("description", ""),
                task.get("status", "pending"), task.get("agent_id"),
                task.get("model", "reasoning"),
                json.dumps(task.get("memory_context", [])),
            )

    async def update_task(
        self, task_id: str, **kwargs: Any
    ) -> None:
        if not self._pool:
            return
        sets = []
        params = []
        idx = 1
        for key, value in kwargs.items():
            if key in ("status", "result", "error", "iterations"):
                sets.append(f"{key} = ${idx}")
                params.append(value)
                idx += 1
            elif key == "completed_at":
                sets.append(f"completed_at = ${idx}")
                params.append(value)
                idx += 1
        if not sets:
            return
        params.append(task_id)
        sql = f"UPDATE mind_tasks SET {', '.join(sets)} WHERE id = ${idx}"
        async with self._pool.acquire() as conn:
            await conn.execute(sql, *params)

    async def get_task(self, task_id: str) -> dict | None:
        if not self._pool:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM mind_tasks WHERE id = $1", task_id)
            return dict(row) if row else None

    async def list_tasks(
        self, status: str | None = None, limit: int = 50
    ) -> list[dict]:
        if not self._pool:
            return []
        async with self._pool.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    "SELECT * FROM mind_tasks WHERE status = $1 "
                    "ORDER BY created_at DESC LIMIT $2",
                    status, limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM mind_tasks ORDER BY created_at DESC LIMIT $1",
                    limit,
                )
            return [dict(r) for r in rows]

    # --- Agent logs ---

    async def log_agent_action(
        self,
        task_id: str,
        iteration: int,
        action: str,
        detail: dict | None = None,
        duration_ms: int = 0,
    ) -> None:
        if not self._pool:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO mind_agent_logs (task_id, iteration, action, detail, duration_ms) "
                "VALUES ($1, $2, $3, $4, $5)",
                task_id, iteration, action,
                json.dumps(detail or {}), duration_ms,
            )

    async def get_agent_logs(self, task_id: str) -> list[dict]:
        if not self._pool:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM mind_agent_logs WHERE task_id = $1 ORDER BY iteration, created_at",
                task_id,
            )
            return [dict(r) for r in rows]

    # --- Stats ---

    async def stats(self) -> dict:
        if not self._pool:
            return {"ready": False}
        async with self._pool.acquire() as conn:
            convs = await conn.fetchval("SELECT count(*) FROM mind_conversations")
            msgs = await conn.fetchval("SELECT count(*) FROM mind_messages")
            tasks = await conn.fetchval("SELECT count(*) FROM mind_tasks")
            return {
                "ready": True,
                "conversations": convs,
                "messages": msgs,
                "tasks": tasks,
            }
