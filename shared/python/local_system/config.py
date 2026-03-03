"""Centralized configuration for Local-System."""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class NodeName(str, Enum):
    HYDRA_AI = "hydra-ai"
    HYDRA_COMPUTE = "hydra-compute"
    HYDRA_STORAGE = "hydra-storage"
    HYDRA_DEV = "hydra-dev"
    DESK = "desk"
    MOBILE = "mobile"


class NodeRole(str, Enum):
    INFERENCE = "inference"          # hydra-ai: TabbyAPI/ExLlamaV2 70B
    COMPUTE = "compute"              # hydra-compute: Ollama GPU, ComfyUI, TTS
    ORCHESTRATOR = "orchestrator"    # hydra-storage: EPYC brain, DBs, services
    DEV = "dev"                      # hydra-dev: development VM
    CLIENT = "client"                # desk/mobile: thin clients


class NodeConfig(BaseSettings):
    """Identity and role of this node."""

    name: NodeName = Field(default=NodeName.HYDRA_STORAGE, alias="NODE_NAME")
    role: NodeRole = Field(default=NodeRole.ORCHESTRATOR, alias="NODE_ROLE")


class NetworkConfig(BaseSettings):
    """Addresses of all nodes in the cluster."""

    hydra_ai: str = Field(default="192.168.1.250", alias="HYDRA_AI_HOST")
    hydra_compute: str = Field(default="192.168.1.203", alias="HYDRA_COMPUTE_HOST")
    hydra_storage: str = Field(default="192.168.1.244", alias="HYDRA_STORAGE_HOST")

    def host_for(self, node: NodeName) -> str:
        return {
            NodeName.HYDRA_AI: self.hydra_ai,
            NodeName.HYDRA_COMPUTE: self.hydra_compute,
            NodeName.HYDRA_STORAGE: self.hydra_storage,
            NodeName.HYDRA_DEV: self.hydra_storage,  # VM on storage
            NodeName.DESK: "0.0.0.0",
            NodeName.MOBILE: "0.0.0.0",
        }[node]


class ServicePorts(BaseSettings):
    """Port assignments for Local-System services."""

    gateway: int = Field(default=8700, alias="GATEWAY_PORT")
    memory: int = Field(default=8702, alias="MEMORY_PORT")
    orchestrator: int = Field(default=8703, alias="ORCHESTRATOR_PORT")
    rag: int = Field(default=8704, alias="RAG_PORT")
    ui: int = Field(default=3200, alias="UI_PORT")

    # External services (not managed by us, but we connect to them)
    litellm: int = Field(default=4000)
    tabby: int = Field(default=5000)
    ollama_gpu: int = Field(default=11434)
    ollama_cpu: int = Field(default=11434)


class InferenceConfig(BaseSettings):
    """Inference stack configuration — LiteLLM + TabbyAPI + Ollama."""

    # LiteLLM is the single entry point for all inference
    litellm_host: str = Field(default="http://192.168.1.244:4000", alias="LITELLM_HOST")
    litellm_key: str = Field(default="changeme", alias="LITELLM_KEY")

    # TabbyAPI + ExLlamaV2 (primary — 70B models via tensor parallel)
    tabby_host: str = Field(default="http://192.168.1.250:5000", alias="TABBY_HOST")
    tabby_model_dir: str = Field(default="/mnt/models/exl2", alias="TABBY_MODEL_DIR")
    tabby_gpu_split: str = Field(default="auto", alias="TABBY_GPU_SPLIT")
    tabby_max_seq_len: int = Field(default=32768, alias="TABBY_MAX_SEQ_LEN")

    # Ollama GPU (secondary — 7B-14B on 5070 Ti)
    ollama_gpu_host: str = Field(default="http://192.168.1.203:11434", alias="OLLAMA_GPU_HOST")

    # Ollama CPU (fallback — EPYC 56-core)
    ollama_cpu_host: str = Field(default="http://192.168.1.244:11434", alias="OLLAMA_CPU_HOST")


class DatabaseConfig(BaseSettings):
    """PostgreSQL configuration."""

    host: str = Field(default="192.168.1.244", alias="POSTGRES_HOST")
    port: int = Field(default=5432, alias="POSTGRES_PORT")
    name: str = Field(default="athanor", alias="POSTGRES_DB")
    user: str = Field(default="hydra", alias="POSTGRES_USER")
    password: str = Field(default="changeme", alias="POSTGRES_PASSWORD")

    @property
    def url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def sync_url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class RedisConfig(BaseSettings):
    """Redis configuration — cache, sessions, working memory, pub/sub."""

    host: str = Field(default="192.168.1.244", alias="REDIS_HOST")
    port: int = Field(default=6379, alias="REDIS_PORT")
    password: str = Field(default="changeme", alias="REDIS_PASSWORD")

    @property
    def url(self) -> str:
        return f"redis://:{self.password}@{self.host}:{self.port}/0"


class QdrantConfig(BaseSettings):
    """Qdrant vector database — episodic + resource memory."""

    host: str = Field(default="192.168.1.244", alias="QDRANT_HOST")
    port: int = Field(default=6333, alias="QDRANT_PORT")
    grpc_port: int = Field(default=6334, alias="QDRANT_GRPC_PORT")


class Neo4jConfig(BaseSettings):
    """Neo4j knowledge graph — semantic memory via Graphiti."""

    host: str = Field(default="192.168.1.244", alias="NEO4J_HOST")
    http_port: int = Field(default=7474, alias="NEO4J_HTTP_PORT")
    bolt_port: int = Field(default=7687, alias="NEO4J_BOLT_PORT")
    user: str = Field(default="neo4j", alias="NEO4J_USER")
    password: str = Field(default="changeme", alias="NEO4J_PASSWORD")

    @property
    def bolt_url(self) -> str:
        return f"bolt://{self.host}:{self.bolt_port}"


class MeilisearchConfig(BaseSettings):
    """Meilisearch — BM25 full-text search for hybrid search."""

    host: str = Field(default="192.168.1.244", alias="MEILISEARCH_HOST")
    port: int = Field(default=7700, alias="MEILISEARCH_PORT")
    key: str = Field(default="changeme", alias="MEILISEARCH_KEY")

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


class RAGConfig(BaseSettings):
    """RAG pipeline configuration — hybrid search."""

    embedding_model: str = Field(default="nomic-embed-text", alias="EMBEDDING_MODEL")
    embedding_dimensions: int = Field(default=768, alias="EMBEDDING_DIMENSIONS")
    chunk_size: int = Field(default=512, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=64, alias="CHUNK_OVERLAP")
    hybrid_search_alpha: float = Field(default=0.7, alias="HYBRID_SEARCH_ALPHA")


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
    meilisearch: MeilisearchConfig = Field(default_factory=MeilisearchConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")
    api_secret_key: str = Field(default="changeme", alias="API_SECRET_KEY")


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
