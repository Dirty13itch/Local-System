"""Shared data models for the Athanor cognitive architecture."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# =============================================================================
# Chat / Inference
# =============================================================================


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


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class ChatRequest(BaseModel):
    model: str = "llama-70b"
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


# =============================================================================
# Memory — 6-Tier Cognitive System
# =============================================================================


class MemoryTier(str, Enum):
    PROCEDURAL = "procedural"    # How to do things (versioned files)
    WORKING = "working"          # Active context (Redis + YAML, volatile)
    EPISODIC = "episodic"        # What happened when (Qdrant + Graphiti)
    SEMANTIC = "semantic"        # Knowledge graph (Neo4j/Graphiti)
    RESOURCE = "resource"        # Ingested documents (Qdrant chunks)
    KNOWLEDGE_VAULT = "vault"    # Validated high-confidence facts


class MemoryEntry(BaseModel):
    """A single memory across any tier."""

    id: str
    tier: MemoryTier
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    confidence: float = 1.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    accessed_at: datetime | None = None
    expires_at: datetime | None = None
    embedding: list[float] | None = None
    tags: list[str] = Field(default_factory=list)


class WorkingContext(BaseModel):
    """Current working memory state."""

    active_task: str | None = None
    recent_messages: list[Message] = Field(default_factory=list)
    active_priorities: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    session_start: datetime = Field(default_factory=datetime.utcnow)


class EpisodicEvent(BaseModel):
    """A timestamped event in episodic memory."""

    id: str
    event_type: str  # conversation, task_outcome, discovery, error, feedback
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    participants: list[str] = Field(default_factory=list)
    outcome: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    embedding: list[float] | None = None


class SemanticEntity(BaseModel):
    """An entity in the semantic knowledge graph."""

    id: str
    name: str
    entity_type: str  # person, project, concept, service, hardware
    properties: dict[str, Any] = Field(default_factory=dict)
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class SemanticRelation(BaseModel):
    """A relationship between semantic entities."""

    source_id: str
    target_id: str
    relation_type: str  # uses, depends_on, created_by, part_of, etc.
    properties: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0


class MemorySearchRequest(BaseModel):
    """Search across memory tiers."""

    query: str
    tiers: list[MemoryTier] | None = None  # None = search all
    top_k: int = 10
    score_threshold: float = 0.0
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None


class MemorySearchResponse(BaseModel):
    results: list[MemoryEntry]
    query: str
    total: int


# =============================================================================
# Cognitive Workspace (GWT)
# =============================================================================


class SpecialistType(str, Enum):
    RESEARCH = "research"
    CODING = "coding"
    CREATIVE = "creative"
    BUILDING_SCIENCE = "building_science"
    MEDIA = "media"
    INFRASTRUCTURE = "infrastructure"
    GENERAL = "general"


class BidRequest(BaseModel):
    """A specialist bids for attention in the cognitive workspace."""

    specialist: SpecialistType
    relevance_score: float  # 0.0 to 1.0 — how relevant this specialist is
    reasoning: str
    proposed_action: str
    estimated_tokens: int = 0


class BroadcastMessage(BaseModel):
    """Message broadcast to all specialists from the winning coalition."""

    source_specialist: SpecialistType
    content: str
    context: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class CognitiveState(BaseModel):
    """The Continuous State Tensor — current cognitive awareness."""

    active_specialist: SpecialistType | None = None
    attention_focus: str = ""
    working_context: WorkingContext = Field(default_factory=WorkingContext)
    recent_broadcasts: list[BroadcastMessage] = Field(default_factory=list)
    cycle_count: int = 0


# =============================================================================
# Agents / Orchestration
# =============================================================================


class AgentConfig(BaseModel):
    name: str
    specialist: SpecialistType = SpecialistType.GENERAL
    system_prompt: str
    model: str = "llama-70b"
    tools: list[str] = Field(default_factory=list)
    max_iterations: int = 10
    temperature: float = 0.7
    memory_enabled: bool = True


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
    specialist: SpecialistType = SpecialistType.GENERAL
    description: str
    status: TaskStatus = TaskStatus.PENDING
    result: Any | None = None
    error: str | None = None
    memory_context: list[str] = Field(default_factory=list)  # memory IDs used
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None


# =============================================================================
# RAG / Documents
# =============================================================================


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
    source: str = "vector"  # "vector", "bm25", or "hybrid"
    highlights: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str
    collection: str = "default"
    top_k: int = 10
    score_threshold: float = 0.0
    use_hybrid: bool = True  # combine Qdrant + Meilisearch
    alpha: float = 0.7       # weight toward vector search
    filters: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    results: list[SearchResult]
    query: str
    total: int


# =============================================================================
# Models / Inference
# =============================================================================


class ModelBackend(str, Enum):
    TABBY = "tabby"       # TabbyAPI + ExLlamaV2 (primary 70B)
    OLLAMA = "ollama"      # Ollama (7B-14B GPU + CPU fallback)
    LITELLM = "litellm"   # LiteLLM unified gateway


class ModelInfo(BaseModel):
    id: str
    name: str
    backend: ModelBackend
    size_bytes: int = 0
    parameter_count: str = ""       # e.g. "7B", "70B"
    quantization: str = ""          # e.g. "EXL2-3.5bpw", "Q4_K_M"
    context_length: int = 4096
    loaded: bool = False
    node: str = ""
    vram_usage_mb: int = 0


# =============================================================================
# System / Node Status
# =============================================================================


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
    power_draw_w: float = 0


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
