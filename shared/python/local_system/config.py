"""Centralized configuration for all Local-System services."""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class NodeName(str, Enum):
    NODE1 = "node1"
    NODE2 = "node2"
    VAULT = "vault"
    DESK = "desk"
    DEV = "dev"
    MOBILE = "mobile"


class NodeRole(str, Enum):
    INFERENCE = "inference"
    STORAGE = "storage"
    ORCHESTRATOR = "orchestrator"
    DEV = "dev"
    CLIENT = "client"


class NodeConfig(BaseSettings):
    """Identity and role of this node."""

    name: NodeName = Field(default=NodeName.DESK, alias="NODE_NAME")
    role: NodeRole = Field(default=NodeRole.ORCHESTRATOR, alias="NODE_ROLE")


class NetworkConfig(BaseSettings):
    """Addresses of all nodes in the cluster."""

    node1_host: str = Field(default="10.0.0.11", alias="NODE1_HOST")
    node2_host: str = Field(default="10.0.0.12", alias="NODE2_HOST")
    vault_host: str = Field(default="10.0.0.13", alias="VAULT_HOST")
    desk_host: str = Field(default="10.0.0.14", alias="DESK_HOST")
    dev_host: str = Field(default="10.0.0.15", alias="DEV_HOST")
    mobile_host: str = Field(default="10.0.0.16", alias="MOBILE_HOST")

    def host_for(self, node: NodeName) -> str:
        return {
            NodeName.NODE1: self.node1_host,
            NodeName.NODE2: self.node2_host,
            NodeName.VAULT: self.vault_host,
            NodeName.DESK: self.desk_host,
            NodeName.DEV: self.dev_host,
            NodeName.MOBILE: self.mobile_host,
        }[node]


class ServicePorts(BaseSettings):
    """Port assignments for each service."""

    gateway: int = Field(default=8000, alias="GATEWAY_PORT")
    inference: int = Field(default=8001, alias="INFERENCE_PORT")
    orchestrator: int = Field(default=8002, alias="ORCHESTRATOR_PORT")
    rag: int = Field(default=8003, alias="RAG_PORT")
    storage: int = Field(default=8004, alias="STORAGE_PORT")
    model_manager: int = Field(default=8005, alias="MODEL_MANAGER_PORT")
    ui: int = Field(default=3000, alias="UI_PORT")

    # gRPC ports
    inference_grpc: int = Field(default=50051, alias="INFERENCE_GRPC_PORT")
    orchestrator_grpc: int = Field(default=50052, alias="ORCHESTRATOR_GRPC_PORT")
    rag_grpc: int = Field(default=50053, alias="RAG_GRPC_PORT")
    storage_grpc: int = Field(default=50054, alias="STORAGE_GRPC_PORT")
    model_manager_grpc: int = Field(default=50055, alias="MODEL_MANAGER_GRPC_PORT")


class DatabaseConfig(BaseSettings):
    """PostgreSQL configuration."""

    host: str = Field(default="10.0.0.13", alias="POSTGRES_HOST")
    port: int = Field(default=5432, alias="POSTGRES_PORT")
    name: str = Field(default="local_system", alias="POSTGRES_DB")
    user: str = Field(default="local_system", alias="POSTGRES_USER")
    password: str = Field(default="changeme", alias="POSTGRES_PASSWORD")

    @property
    def url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class RedisConfig(BaseSettings):
    """Redis configuration."""

    host: str = Field(default="10.0.0.14", alias="REDIS_HOST")
    port: int = Field(default=6379, alias="REDIS_PORT")
    password: str = Field(default="changeme", alias="REDIS_PASSWORD")

    @property
    def url(self) -> str:
        return f"redis://:{self.password}@{self.host}:{self.port}/0"


class QdrantConfig(BaseSettings):
    """Qdrant vector database configuration."""

    host: str = Field(default="10.0.0.13", alias="QDRANT_HOST")
    port: int = Field(default=6333, alias="QDRANT_PORT")
    grpc_port: int = Field(default=6334, alias="QDRANT_GRPC_PORT")


class InferenceConfig(BaseSettings):
    """Inference backend configuration."""

    ollama_host: str = Field(default="http://localhost:11434", alias="OLLAMA_HOST")
    ollama_num_parallel: int = Field(default=4, alias="OLLAMA_NUM_PARALLEL")
    vllm_host: str = Field(default="http://localhost:8100", alias="VLLM_HOST")
    vllm_tensor_parallel_size: int = Field(default=4, alias="VLLM_TENSOR_PARALLEL_SIZE")
    vllm_gpu_memory_utilization: float = Field(default=0.90, alias="VLLM_GPU_MEMORY_UTILIZATION")
    llamacpp_host: str = Field(default="http://localhost:8200", alias="LLAMACPP_HOST")
    llamacpp_n_gpu_layers: int = Field(default=-1, alias="LLAMACPP_N_GPU_LAYERS")


class RAGConfig(BaseSettings):
    """RAG pipeline configuration."""

    embedding_model: str = Field(default="nomic-embed-text", alias="EMBEDDING_MODEL")
    embedding_dimensions: int = Field(default=768, alias="EMBEDDING_DIMENSIONS")
    chunk_size: int = Field(default=512, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=64, alias="CHUNK_OVERLAP")


class AuthConfig(BaseSettings):
    """Authentication configuration."""

    secret_key: str = Field(default="changeme", alias="API_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expiration_hours: int = Field(default=24, alias="JWT_EXPIRATION_HOURS")


class Settings(BaseSettings):
    """Aggregated settings for the entire system."""

    node: NodeConfig = Field(default_factory=NodeConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    ports: ServicePorts = Field(default_factory=ServicePorts)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    inference: InferenceConfig = Field(default_factory=InferenceConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")
    enable_metrics: bool = Field(default=True, alias="ENABLE_METRICS")


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
