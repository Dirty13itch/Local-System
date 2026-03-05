"""Prometheus metrics for Local-System services.

Provides shared metrics and a /metrics endpoint factory for FastAPI.
Uses prometheus-client which is already in requirements.
"""

from __future__ import annotations

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from fastapi import Response

# --- Shared metrics ---

REQUEST_COUNT = Counter(
    "ls_request_total",
    "Total requests processed",
    ["service", "method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "ls_request_duration_seconds",
    "Request latency in seconds",
    ["service", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
)

LLM_CALLS = Counter(
    "ls_llm_calls_total",
    "Total LLM inference calls",
    ["service", "model", "status"],
)

LLM_LATENCY = Histogram(
    "ls_llm_duration_seconds",
    "LLM call latency in seconds",
    ["service", "model"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
)

LLM_TOKENS = Counter(
    "ls_llm_tokens_total",
    "Total LLM tokens processed",
    ["service", "model", "direction"],
)

TOOL_CALLS = Counter(
    "ls_tool_calls_total",
    "Total tool executions",
    ["service", "tool", "status"],
)

TOOL_LATENCY = Histogram(
    "ls_tool_duration_seconds",
    "Tool execution latency in seconds",
    ["service", "tool"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0],
)

MEMORY_OPS = Counter(
    "ls_memory_ops_total",
    "Total memory operations",
    ["tier", "operation", "status"],
)

MEMORY_SEARCH_LATENCY = Histogram(
    "ls_memory_search_duration_seconds",
    "Memory search latency in seconds",
    ["tier"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

ACTIVE_CONVERSATIONS = Gauge(
    "ls_active_conversations",
    "Number of active conversations",
    ["service"],
)

WORKSPACE_SWITCHES = Counter(
    "ls_workspace_switches_total",
    "Total workspace switches",
    ["workspace"],
)

SERVICE_INFO = Gauge(
    "ls_service_info",
    "Service metadata",
    ["service", "version", "node"],
)


def metrics_response() -> Response:
    """Generate a Prometheus-compatible metrics response."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
