"""MIND service event bus — re-exports shared EventBus.

Kept as a module so existing mind imports continue to work.
The EventBus class and STREAM_PREFIX are defined in the shared library.
"""

from local_system.events import EventBus, STREAM_PREFIX

__all__ = ["EventBus", "STREAM_PREFIX"]
