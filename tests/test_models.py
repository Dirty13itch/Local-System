"""Tests for shared data models."""

from local_system.models import (
    ChatRequest,
    ChatResponse,
    Document,
    Message,
    ModelBackend,
    ModelInfo,
    Role,
    SearchRequest,
    SearchResult,
    StreamChunk,
    Task,
    TaskStatus,
    TokenUsage,
)
from local_system.utils import generate_id


def test_message_creation():
    msg = Message(role=Role.USER, content="Hello")
    assert msg.role == Role.USER
    assert msg.content == "Hello"


def test_chat_request_defaults():
    req = ChatRequest(
        model="llama3.1:8b",
        messages=[Message(role=Role.USER, content="Hi")],
    )
    assert req.temperature == 0.7
    assert req.max_tokens == 4096
    assert req.stream is False


def test_chat_response():
    resp = ChatResponse(
        id="chat_abc123",
        model="llama3.1:8b",
        message=Message(role=Role.ASSISTANT, content="Hello!"),
        usage=TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
    )
    assert resp.usage.total_tokens == 8


def test_model_info():
    model = ModelInfo(
        id="llama3.1:8b",
        name="llama3.1:8b",
        backend=ModelBackend.OLLAMA,
        loaded=True,
    )
    assert model.backend == ModelBackend.OLLAMA


def test_document():
    doc = Document(id="doc_1", source="test.txt", content="Hello world")
    assert doc.chunk_index == 0
    assert doc.embedding is None


def test_search_request_defaults():
    req = SearchRequest(query="test query")
    assert req.collection == "default"
    assert req.top_k == 10


def test_task_lifecycle():
    task = Task(id="task_1", description="Test task")
    assert task.status == TaskStatus.PENDING
    task.status = TaskStatus.RUNNING
    assert task.status == TaskStatus.RUNNING


def test_stream_chunk():
    chunk = StreamChunk(id="chat_1", model="test", delta="Hello")
    assert chunk.finish_reason is None


def test_generate_id():
    id1 = generate_id("test")
    id2 = generate_id("test")
    assert id1.startswith("test_")
    assert id1 != id2
    assert len(generate_id()) == 12
