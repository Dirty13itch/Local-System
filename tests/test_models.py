"""Tests for Local-System shared data models."""

from datetime import datetime

from local_system.models import (
    AgentState,
    BidRequest,
    ChatRequest,
    ChatResponse,
    CognitiveState,
    Document,
    EpisodicEvent,
    MemoryEntry,
    MemoryTier,
    Message,
    ModelBackend,
    ModelInfo,
    Role,
    SearchRequest,
    SpecialistType,
    StreamChunk,
    Task,
    TaskStatus,
    TokenUsage,
    WorkingContext,
)
from local_system.utils import generate_id


def test_message_creation():
    msg = Message(role=Role.USER, content="Hello")
    assert msg.role == Role.USER
    assert msg.content == "Hello"


def test_chat_request_defaults():
    req = ChatRequest(
        messages=[Message(role=Role.USER, content="test")],
    )
    assert req.model == "auto"
    assert req.temperature == 0.7
    assert req.max_tokens == 4096
    assert req.stream is False


def test_chat_response():
    resp = ChatResponse(
        id="chat-123",
        model="llama-70b",
        message=Message(role=Role.ASSISTANT, content="Hi!"),
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    assert resp.usage.total_tokens == 15


def test_model_backends():
    """Model backends should include TabbyAPI, Ollama, LiteLLM."""
    assert ModelBackend.TABBY == "tabby"
    assert ModelBackend.OLLAMA == "ollama"
    assert ModelBackend.LITELLM == "litellm"


def test_model_info():
    info = ModelInfo(
        id="llama-70b",
        name="Llama-3.1-70B-EXL2-3.5bpw",
        backend=ModelBackend.TABBY,
        parameter_count="70B",
        quantization="EXL2-3.5bpw",
        context_length=32768,
        loaded=True,
        node="foundry",
    )
    assert info.backend == ModelBackend.TABBY
    assert info.context_length == 32768


def test_memory_tiers():
    """All 6 memory tiers should exist."""
    assert len(MemoryTier) == 6
    assert MemoryTier.PROCEDURAL == "procedural"
    assert MemoryTier.WORKING == "working"
    assert MemoryTier.EPISODIC == "episodic"
    assert MemoryTier.SEMANTIC == "semantic"
    assert MemoryTier.RESOURCE == "resource"
    assert MemoryTier.KNOWLEDGE_VAULT == "vault"


def test_memory_entry():
    entry = MemoryEntry(
        id="mem-123",
        tier=MemoryTier.EPISODIC,
        content="Discovered that ExLlamaV2 is the only option for heterogeneous TP",
        source="learnings",
        confidence=0.95,
        tags=["inference", "exllamav2"],
    )
    assert entry.tier == MemoryTier.EPISODIC
    assert entry.confidence == 0.95


def test_working_context():
    ctx = WorkingContext(
        active_task="Restructure scaffold",
        active_priorities=["Align with system-bible vision"],
        unresolved_questions=["Which node topology for desk?"],
    )
    assert ctx.active_task == "Restructure scaffold"


def test_episodic_event():
    event = EpisodicEvent(
        id="ep-001",
        event_type="task_outcome",
        summary="Completed scaffold restructure",
        outcome="success",
    )
    assert event.event_type == "task_outcome"


def test_specialist_types():
    """All specialist types should exist."""
    assert SpecialistType.RESEARCH == "research"
    assert SpecialistType.CODING == "coding"
    assert SpecialistType.CREATIVE == "creative"
    assert SpecialistType.BUILDING_SCIENCE == "building_science"
    assert SpecialistType.MEDIA == "media"
    assert SpecialistType.INFRASTRUCTURE == "infrastructure"


def test_cognitive_state():
    state = CognitiveState(
        active_specialist=SpecialistType.CODING,
        attention_focus="implementing memory service",
        cycle_count=42,
    )
    assert state.active_specialist == SpecialistType.CODING
    assert state.cycle_count == 42


def test_bid_request():
    bid = BidRequest(
        specialist=SpecialistType.RESEARCH,
        relevance_score=0.9,
        reasoning="User asked about ExLlamaV3 migration",
        proposed_action="Research latest ExLlamaV3 releases",
    )
    assert bid.relevance_score == 0.9


def test_search_request_hybrid():
    req = SearchRequest(
        query="ExLlamaV2 tensor parallel",
        use_hybrid=True,
        alpha=0.7,
    )
    assert req.use_hybrid is True
    assert req.alpha == 0.7


def test_task_lifecycle():
    task = Task(
        id="task-001",
        specialist=SpecialistType.CODING,
        description="Implement memory service",
    )
    assert task.status == TaskStatus.PENDING
    task.status = TaskStatus.RUNNING
    assert task.status == TaskStatus.RUNNING


def test_generate_id():
    id1 = generate_id("test")
    id2 = generate_id("test")
    assert id1.startswith("test-")
    assert id1 != id2
