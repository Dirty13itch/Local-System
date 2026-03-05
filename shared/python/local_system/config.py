"""Centralized configuration for Local-System."""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class NodeName(str, Enum):
    FOUNDRY = "foundry"
    WORKSHOP = "workshop"
    VAULT = "vault"
    DEV = "dev"
    DESK = "desk"
    MOBILE = "mobile"


class NodeRole(str, Enum):
    INFERENCE = "inference"          # FOUNDRY: vLLM heavy models (5090 + 4090)
    CREATIVE = "creative"            # WORKSHOP: vLLM fast, ComfyUI, TTS
    ORCHESTRATOR = "orchestrator"    # VAULT: EPYC brain, DBs, services
    OPERATIONS = "operations"        # DEV: Claude Code, Ansible, ops center
    CLIENT = "client"                # DESK/MOBILE: thin clients


class NodeConfig(BaseSettings):
    """Identity and role of this node."""

    name: NodeName = Field(default=NodeName.DEV, alias="NODE_NAME")
    role: NodeRole = Field(default=NodeRole.OPERATIONS, alias="NODE_ROLE")


class NetworkConfig(BaseSettings):
    """Addresses of all nodes in the cluster."""

    foundry: str = Field(default="192.168.1.244", alias="FOUNDRY_HOST")
    workshop: str = Field(default="192.168.1.225", alias="WORKSHOP_HOST")
    vault: str = Field(default="192.168.1.203", alias="VAULT_HOST")
    dev: str = Field(default="192.168.1.189", alias="DEV_HOST")

    def host_for(self, node: NodeName) -> str:
        return {
            NodeName.FOUNDRY: self.foundry,
            NodeName.WORKSHOP: self.workshop,
            NodeName.VAULT: self.vault,
            NodeName.DEV: self.dev,
            NodeName.DESK: "0.0.0.0",
            NodeName.MOBILE: "0.0.0.0",
        }[node]


class ServicePorts(BaseSettings):
    """Port assignments for Local-System services."""

    gateway: int = Field(default=8700, alias="GATEWAY_PORT")
    memory: int = Field(default=8720, alias="MEMORY_PORT")
    orchestrator: int = Field(default=8703, alias="ORCHESTRATOR_PORT")
    mind: int = Field(default=8710, alias="MIND_PORT")
    agent_server: int = Field(default=9000, alias="AGENT_SERVER_PORT")
    perception: int = Field(default=8730, alias="PERCEPTION_PORT")
    ui: int = Field(default=3001, alias="UI_PORT")

    # External services
    litellm: int = Field(default=4000)
    vllm_reasoning: int = Field(default=8000)
    vllm_fast: int = Field(default=8000)
    vllm_embedding: int = Field(default=8001)
    vllm_coding: int = Field(default=8002)
    vllm_reranker: int = Field(default=8003)


class InferenceConfig(BaseSettings):
    """Inference stack configuration — LiteLLM routing to vLLM instances."""

    # LiteLLM is the single entry point for all inference
    litellm_host: str = Field(default="http://192.168.1.203:4000", alias="LITELLM_HOST")
    litellm_key: str = Field(default="sk-athanor-litellm-2026", alias="LITELLM_KEY")

    # vLLM instances (ports set after GPU discovery)
    vllm_reasoning_host: str = Field(default="http://192.168.1.244:8000", alias="VLLM_REASONING_HOST")
    vllm_fast_host: str = Field(default="http://192.168.1.225:8000", alias="VLLM_FAST_HOST")
    vllm_embedding_host: str = Field(default="http://192.168.1.189:8001", alias="VLLM_EMBEDDING_HOST")
    vllm_coding_host: str = Field(default="http://192.168.1.244:8002", alias="VLLM_CODING_HOST")
    vllm_reranker_host: str = Field(default="http://192.168.1.189:8003", alias="VLLM_RERANKER_HOST")


class DatabaseConfig(BaseSettings):
    """PostgreSQL configuration."""

    host: str = Field(default="192.168.1.203", alias="POSTGRES_HOST")
    port: int = Field(default=5432, alias="POSTGRES_PORT")
    name: str = Field(default="local_system", alias="POSTGRES_DB")
    user: str = Field(default="local_system", alias="POSTGRES_USER")
    password: str = Field(default="changeme", alias="POSTGRES_PASSWORD")

    @property
    def url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def sync_url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class RedisConfig(BaseSettings):
    """Redis 8 — cache, sessions, working memory, task queue, pub/sub."""

    host: str = Field(default="192.168.1.203", alias="REDIS_HOST")
    port: int = Field(default=6379, alias="REDIS_PORT")
    password: str = Field(default="", alias="REDIS_PASSWORD")

    @property
    def url(self) -> str:
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/0"
        return f"redis://{self.host}:{self.port}/0"


class QdrantConfig(BaseSettings):
    """Qdrant v1.17 vector database — episodic + resource memory."""

    host: str = Field(default="192.168.1.203", alias="QDRANT_HOST")
    port: int = Field(default=6333, alias="QDRANT_PORT")
    grpc_port: int = Field(default=6334, alias="QDRANT_GRPC_PORT")


class Neo4jConfig(BaseSettings):
    """Neo4j knowledge graph — semantic memory."""

    host: str = Field(default="192.168.1.203", alias="NEO4J_HOST")
    http_port: int = Field(default=7474, alias="NEO4J_HTTP_PORT")
    bolt_port: int = Field(default=7687, alias="NEO4J_BOLT_PORT")
    user: str = Field(default="neo4j", alias="NEO4J_USER")
    password: str = Field(default="athanor2026", alias="NEO4J_PASSWORD")

    @property
    def bolt_url(self) -> str:
        return f"bolt://{self.host}:{self.bolt_port}"


class RAGConfig(BaseSettings):
    """RAG pipeline configuration — hybrid search."""

    embedding_model: str = Field(default="/models/Qwen3-Embedding-0.6B", alias="EMBEDDING_MODEL")
    embedding_dimensions: int = Field(default=1024, alias="EMBEDDING_DIMENSIONS")
    chunk_size: int = Field(default=512, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=64, alias="CHUNK_OVERLAP")
    hybrid_search_alpha: float = Field(default=0.7, alias="HYBRID_SEARCH_ALPHA")


class MeilisearchConfig(BaseSettings):
    """Meilisearch — BM25 full-text search for hybrid retrieval."""

    host: str = Field(default="192.168.1.203", alias="MEILISEARCH_HOST")
    port: int = Field(default=7700, alias="MEILISEARCH_PORT")
    key: str = Field(default="HJR568l_N9uK55CXrheDIWQOSqK3YtT1IOlLt4xhI7Q", alias="MEILISEARCH_KEY")

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


class Settings(BaseSettings):
    """Aggregated settings for the Local-System."""

    node: NodeConfig = Field(default_factory=NodeConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    ports: ServicePorts = Field(default_factory=ServicePorts)
    inference: InferenceConfig = Field(default_factory=InferenceConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    meilisearch: MeilisearchConfig = Field(default_factory=MeilisearchConfig)

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")
    api_secret_key: str = Field(default="changeme", alias="API_SECRET_KEY")


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
