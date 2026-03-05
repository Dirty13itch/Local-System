"""Filesystem watchers for automatic content ingestion.

Watches configured directories (primarily NFS mounts from VAULT) for
new or modified files, and triggers the ingest pipeline.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Awaitable

from local_system.utils import setup_logging

logger = setup_logging("perception.watchers")


@dataclass
class WatchConfig:
    """Configuration for a single directory watch."""
    path: str
    patterns: list[str] = field(default_factory=lambda: ["*"])
    recursive: bool = True
    poll_interval: float = 30.0  # seconds


@dataclass
class FileChange:
    """A detected file change."""
    path: str
    event_type: str  # "created", "modified"
    size: int
    mtime: float


class DirectoryWatcher:
    """Poll-based directory watcher (NFS-safe, no inotify dependency).

    Uses polling instead of inotify because:
    1. NFS mounts don't support inotify reliably
    2. Simpler, fewer failure modes
    3. 30s poll interval is fine for document ingestion
    """

    def __init__(self, config: WatchConfig):
        self.config = config
        self._known_files: dict[str, float] = {}  # path -> mtime
        self._running = False

    async def scan_once(self) -> list[FileChange]:
        """Scan directory and return list of new/modified files."""
        changes: list[FileChange] = []
        root = Path(self.config.path)

        if not root.exists():
            logger.warning(f"Watch path does not exist: {root}")
            return changes

        try:
            if self.config.recursive:
                files = root.rglob("*")
            else:
                files = root.glob("*")

            current_files: dict[str, float] = {}
            for fpath in files:
                if not fpath.is_file():
                    continue
                # Check against patterns
                if not self._matches_patterns(fpath.name):
                    continue

                try:
                    stat = fpath.stat()
                    fstr = str(fpath)
                    current_files[fstr] = stat.st_mtime

                    if fstr not in self._known_files:
                        changes.append(FileChange(
                            path=fstr,
                            event_type="created",
                            size=stat.st_size,
                            mtime=stat.st_mtime,
                        ))
                    elif stat.st_mtime > self._known_files[fstr]:
                        changes.append(FileChange(
                            path=fstr,
                            event_type="modified",
                            size=stat.st_size,
                            mtime=stat.st_mtime,
                        ))
                except (PermissionError, OSError):
                    continue

            self._known_files = current_files

        except Exception as e:
            logger.error(f"Error scanning {root}: {e}")

        return changes

    def _matches_patterns(self, filename: str) -> bool:
        """Check if filename matches any of the watch patterns."""
        import fnmatch
        if self.config.patterns == ["*"]:
            return True
        return any(fnmatch.fnmatch(filename, p) for p in self.config.patterns)

    async def watch(
        self,
        callback: Callable[[list[FileChange]], Awaitable[None]],
    ) -> None:
        """Start watching with a callback for changes."""
        self._running = True
        logger.info(f"Watching {self.config.path} (poll={self.config.poll_interval}s)")

        # Initial scan to build baseline
        await self.scan_once()

        while self._running:
            await asyncio.sleep(self.config.poll_interval)
            try:
                changes = await self.scan_once()
                if changes:
                    logger.info(f"Detected {len(changes)} changes in {self.config.path}")
                    await callback(changes)
            except Exception as e:
                logger.error(f"Watch callback error: {e}")

    def stop(self) -> None:
        """Stop the watcher."""
        self._running = False
