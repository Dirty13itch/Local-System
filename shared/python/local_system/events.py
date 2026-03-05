"""Redis-backed event bus for inter-service communication.

Uses Redis Streams for reliable, ordered event delivery. Services
publish events and subscribe to channels they care about.

Channel naming: ls:events.{domain}.{action}
Examples: ls:events.task.created, ls:events.memory.stored, ls:events.mind.decision
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from local_system.config import get_settings
from local_system.utils import generate_id

logger = logging.getLogger("local_system.events")

STREAM_PREFIX = "ls:events"


class EventBus:
    """Publish/subscribe event bus backed by Redis Streams.

    Usage:
        bus = EventBus(service_name="my-service")
        await bus.init()
        await bus.publish("task.created", "task_created", {"id": "123"})
        events = await bus.read_latest("task.created", count=5)
        await bus.close()
    """

    def __init__(self, service_name: str = "unknown") -> None:
        self._redis = None
        self._settings = get_settings()
        self._consumer_group = f"{service_name}-service"
        self._consumer_name = f"{service_name}-{generate_id('c')[:8]}"

    async def init(self) -> None:
        """Connect to Redis."""
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                self._settings.redis.url, decode_responses=True
            )
            await self._redis.ping()
            logger.info("Event bus initialized (Redis Streams)")
        except Exception as e:
            logger.warning(f"Event bus init failed: {e}")

    async def close(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.aclose()

    @property
    def ready(self) -> bool:
        """Whether the bus is connected to Redis."""
        return self._redis is not None

    async def publish(
        self,
        channel: str,
        event_type: str,
        data: dict[str, Any],
        *,
        source: str | None = None,
    ) -> str | None:
        """Publish an event to a Redis Stream.

        Args:
            channel: Stream name suffix (e.g., "task.created").
            event_type: Event type label.
            data: Event payload.
            source: Originating service (defaults to consumer group name).

        Returns:
            The stream entry ID, or None if publish failed.
        """
        if not self._redis:
            return None

        stream = f"{STREAM_PREFIX}.{channel}"
        event = {
            "id": generate_id("evt"),
            "type": event_type,
            "source": source or self._consumer_group,
            "timestamp": datetime.utcnow().isoformat(),
            "data": json.dumps(data),
        }

        try:
            entry_id = await self._redis.xadd(stream, event, maxlen=10000)
            logger.debug(f"Published {event_type} to {stream}: {entry_id}")
            return entry_id
        except Exception as e:
            logger.warning(f"Event publish failed: {e}")
            return None

    async def read_latest(
        self, channel: str, count: int = 10
    ) -> list[dict[str, Any]]:
        """Read latest events from a stream (no consumer group)."""
        if not self._redis:
            return []

        stream = f"{STREAM_PREFIX}.{channel}"
        try:
            entries = await self._redis.xrevrange(stream, count=count)
            results = []
            for entry_id, fields in entries:
                event = dict(fields)
                if "data" in event:
                    try:
                        event["data"] = json.loads(event["data"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                event["stream_id"] = entry_id
                results.append(event)
            return list(reversed(results))  # chronological order
        except Exception as e:
            logger.warning(f"Event read failed: {e}")
            return []

    async def subscribe(
        self,
        channels: list[str],
        *,
        last_id: str = "$",
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[dict[str, Any]]:
        """Block-read new events from multiple streams.

        Args:
            channels: Stream suffixes to listen on.
            last_id: Start position ("$" for new events, "0" for all).
            count: Max events to read per call.
            block_ms: How long to block waiting (ms).

        Returns:
            List of events from all channels.
        """
        if not self._redis:
            return []

        streams = {f"{STREAM_PREFIX}.{ch}": last_id for ch in channels}

        try:
            results = await self._redis.xread(streams, count=count, block=block_ms)
            events = []
            for stream_name, entries in results:
                for entry_id, fields in entries:
                    event = dict(fields)
                    if "data" in event:
                        try:
                            event["data"] = json.loads(event["data"])
                        except (json.JSONDecodeError, TypeError):
                            pass
                    event["stream_id"] = entry_id
                    event["channel"] = stream_name.replace(f"{STREAM_PREFIX}.", "")
                    events.append(event)
            return events
        except Exception as e:
            logger.warning(f"Event subscribe failed: {e}")
            return []
