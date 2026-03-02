"""Shared data models used across all services."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --- Chat / Inference ---


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    role: Role
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    temperature: float = 0.7
    max_tokens: int = 4096
    stream: bool = False
    tools: list[ToolDefinition] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    id: str
    model: str
    message: Message
    usage: TokenUsage
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class StreamChunk(BaseModel):
    id: str
    model: str
    delta: str
    finish_reason: str | None = None


# --- Tools / Agents ---


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class AgentConfig(BaseModel):
    name: str
    system_prompt: str
    model: str
    tools: list[str] = Field(default_factory=list)
    max_iterations: int = 10
    temperature: float = 0.7


class AgentState(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    EXECUTING_TOOL = "executing_tool"
    WAITING = "waiting"
    COMPLETED = "completed"
    ERROR = "error"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(BaseModel):
    id: str
    agent_id: str | None = None
    description: str
    status: TaskStatus = TaskStatus.PENDING
    result: Any | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None


# --- RAG / Documents ---


class Document(BaseModel):
    id: str
    source: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = None
    chunk_index: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SearchResult(BaseModel):
    document: Document
    score: float
    highlights: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str
    collection: str = "default"
    top_k: int = 10
    score_threshold: float = 0.0
    filters: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    results: list[SearchResult]
    query: str
    total: int


# --- Models ---


class ModelBackend(str, Enum):
    OLLAMA = "ollama"
    VLLM = "vllm"
    LLAMACPP = "llamacpp"


class ModelInfo(BaseModel):
    id: str
    name: str
    backend: ModelBackend
    size_bytes: int = 0
    parameter_count: str = ""  # e.g. "7B", "70B"
    quantization: str = ""  # e.g. "Q4_K_M", "FP16"
    context_length: int = 4096
    loaded: bool = False
    node: str = ""
    gpu_layers: int = 0
    vram_usage_mb: int = 0


class ModelPullRequest(BaseModel):
    name: str
    backend: ModelBackend = ModelBackend.OLLAMA
    target_node: str = "node1"


# --- System ---


class NodeStatus(BaseModel):
    name: str
    role: str
    online: bool = True
    uptime_seconds: float = 0
    cpu_percent: float = 0
    ram_used_gb: float = 0
    ram_total_gb: float = 0
    gpu_info: list[GPUInfo] = Field(default_factory=list)
    disk_used_gb: float = 0
    disk_total_gb: float = 0
    services: list[ServiceStatus] = Field(default_factory=list)


class GPUInfo(BaseModel):
    index: int
    name: str
    vram_used_mb: int = 0
    vram_total_mb: int = 0
    utilization_percent: float = 0
    temperature_c: int = 0


class ServiceStatus(BaseModel):
    name: str
    running: bool
    port: int
    uptime_seconds: float = 0
    healthy: bool = True


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str
    version: str = "0.1.0"
    node: str
    uptime_seconds: float = 0
