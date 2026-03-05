"""Semantic Memory — Neo4j knowledge graph.

Stores entities (people, projects, concepts, services, hardware) and their
relationships. Provides graph traversal, path queries, and neighborhood
exploration. Entities have temporal validity (valid_from / valid_until).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from local_system.config import get_settings
from local_system.models import (
    MemoryEntry,
    MemoryTier,
    SemanticEntity,
    SemanticRelation,
)
from local_system.utils import generate_id

from .base import BaseTier

logger = logging.getLogger("memory.tiers.semantic")


class SemanticTier(BaseTier):
    tier = MemoryTier.SEMANTIC

    def __init__(self) -> None:
        self._driver = None
        self._settings = get_settings()

    async def init(self) -> None:
        try:
            from neo4j import AsyncGraphDatabase

            self._driver = AsyncGraphDatabase.driver(
                self._settings.neo4j.bolt_url,
                auth=(self._settings.neo4j.user, self._settings.neo4j.password),
            )
            async with self._driver.session() as session:
                await session.run("RETURN 1")
            self._ready = True
            logger.info("Semantic tier initialized (Neo4j)")
        except Exception as e:
            logger.warning(f"Semantic tier init failed: {e}")

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()

    async def store(self, entry: MemoryEntry) -> str:
        if not self._driver:
            raise RuntimeError("Neo4j not available")
        if not entry.id:
            entry.id = generate_id("sem")

        async with self._driver.session() as session:
            await session.run(
                "MERGE (n:Memory {id: $id}) "
                "SET n.content = $content, "
                "    n.source = $source, "
                "    n.tier = $tier, "
                "    n.confidence = $confidence, "
                "    n.tags = $tags, "
                "    n.created_at = $created_at, "
                "    n.updated_at = datetime()",
                id=entry.id,
                content=entry.content,
                source=entry.source,
                tier=MemoryTier.SEMANTIC.value,
                confidence=entry.confidence,
                tags=entry.tags,
                created_at=entry.created_at.isoformat(),
            )
        return entry.id

    async def store_entity(self, entity: SemanticEntity) -> str:
        """Store a typed entity node."""
        if not self._driver:
            raise RuntimeError("Neo4j not available")
        if not entity.id:
            entity.id = generate_id("ent")

        async with self._driver.session() as session:
            await session.run(
                "MERGE (n:Entity {id: $id}) "
                "SET n.name = $name, "
                "    n.entity_type = $entity_type, "
                "    n.properties = $properties, "
                "    n.valid_from = $valid_from, "
                "    n.valid_until = $valid_until, "
                "    n.updated_at = datetime()",
                id=entity.id,
                name=entity.name,
                entity_type=entity.entity_type,
                properties=str(entity.properties),
                valid_from=entity.valid_from.isoformat() if entity.valid_from else None,
                valid_until=entity.valid_until.isoformat() if entity.valid_until else None,
            )
        logger.info(f"Entity stored: {entity.name} ({entity.entity_type})")
        return entity.id

    async def store_relation(self, relation: SemanticRelation) -> None:
        """Create a typed relationship between two entities."""
        if not self._driver:
            raise RuntimeError("Neo4j not available")
        rel_type = relation.relation_type.upper().replace(" ", "_")

        async with self._driver.session() as session:
            query = (
                "MATCH (a:Entity {id: $source_id}) "
                "MATCH (b:Entity {id: $target_id}) "
                f"MERGE (a)-[r:{rel_type}]->(b) "
                "SET r.confidence = $confidence, "
                "    r.properties = $properties, "
                "    r.updated_at = datetime()"
            )
            await session.run(
                query,
                source_id=relation.source_id,
                target_id=relation.target_id,
                confidence=relation.confidence,
                properties=str(relation.properties),
            )

    async def retrieve(self, entry_id: str) -> MemoryEntry | None:
        if not self._driver:
            return None
        async with self._driver.session() as session:
            result = await session.run("MATCH (n {id: $id}) RETURN n", id=entry_id)
            record = await result.single()
            if not record:
                return None
            node = record["n"]
            return MemoryEntry(
                id=node.get("id", entry_id),
                tier=MemoryTier.SEMANTIC,
                content=node.get("content", node.get("name", "")),
                metadata=dict(node),
                source=node.get("source", ""),
                confidence=node.get("confidence", 1.0),
            )

    async def search(
        self,
        query: str,
        *,
        embedding: list[float] | None = None,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[MemoryEntry]:
        """Full-text search on entity names and content."""
        if not self._driver:
            return []

        entity_type_filter = ""
        params: dict[str, Any] = {"query": f"(?i).*{query}.*", "limit": top_k}

        if filters and "entity_type" in filters:
            entity_type_filter = "AND n.entity_type = $entity_type"
            params["entity_type"] = filters["entity_type"]

        async with self._driver.session() as session:
            cypher = (
                "MATCH (n) "
                "WHERE (n.name =~ $query OR n.content =~ $query) "
                f"{entity_type_filter} "
                "RETURN n LIMIT $limit"
            )
            result = await session.run(cypher, **params)
            records = await result.data()

        results = []
        for record in records:
            node = record["n"]
            results.append(MemoryEntry(
                id=node.get("id", ""),
                tier=MemoryTier.SEMANTIC,
                content=node.get("content", node.get("name", "")),
                metadata=dict(node),
                source=node.get("source", ""),
                confidence=1.0,
            ))
        return results

    async def get_neighbors(self, entity_id: str, depth: int = 1) -> list[dict]:
        """Get entity neighborhood — connected entities and relationships."""
        if not self._driver:
            return []
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (n:Entity {id: $id})-[r]-(m:Entity) "
                "RETURN n.name AS source, type(r) AS relation, "
                "m.id AS target_id, m.name AS target_name, "
                "m.entity_type AS target_type LIMIT 50",
                id=entity_id,
            )
            return await result.data()

    async def delete(self, entry_id: str) -> bool:
        if not self._driver:
            return False
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (n {id: $id}) DETACH DELETE n RETURN count(n) AS deleted",
                id=entry_id,
            )
            record = await result.single()
            return bool(record and record["deleted"] > 0)

    async def count(self) -> int:
        if not self._driver:
            return 0
        async with self._driver.session() as session:
            result = await session.run("MATCH (n) RETURN count(n) AS c")
            record = await result.single()
            return record["c"] if record else 0

    async def health(self) -> str:
        if not self._driver:
            return "not_initialized"
        try:
            async with self._driver.session() as session:
                await session.run("RETURN 1")
            return "ok"
        except Exception:
            return "error"
