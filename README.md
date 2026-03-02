# Local-System

A distributed local AI platform spanning 6 hardware-specialized nodes, connected via a 10GbE backbone.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        10GbE Backbone                           │
│              (Ubiquiti USW-Pro-XG + UDM Pro)                    │
├────────┬────────┬────────┬────────┬────────┬────────────────────┤
│        │        │        │        │        │                    │
│ Node 1 │ Node 2 │ VAULT  │  DESK  │  DEV   │     MOBILE        │
│ Infer  │ Infer+ │ Store  │  UI/GW │ CI/CD  │     Client        │
│ Primary│ Finetune│ + RAG │ + Orch │ + Mon  │                   │
│        │        │        │        │        │                    │
│ EPYC   │ TR     │ R9     │ i7     │ R9     │     R9 5900HX     │
│ 56C    │ 24C    │ 9950X  │ 13700K │ 9900X  │     Laptop        │
│ 224GB  │ 128GB  │ 128GB  │ 64GB   │ 64GB   │     64GB          │
│        │        │        │        │        │                    │
│ 4×5070T│ 5090   │ Arc380 │ 3060   │ 5060Ti │     3070M         │
│ 1×4090 │ 5060Ti │ 180TB  │ 12GB   │ 16GB   │     8GB           │
│ 16TB   │ 6TB    │ HDD    │ 3TB    │ 6TB    │     3TB           │
│ NVMe   │ NVMe   │ 9TB    │ NVMe   │ NVMe   │     NVMe          │
│        │        │ NVMe   │        │        │                    │
└────────┴────────┴────────┴────────┴────────┴────────────────────┘
```

## Node Roles

| Node | Role | Description |
|------|------|-------------|
| **Node 1** | Inference Primary | Multi-GPU model serving across 5 GPUs. Handles bulk inference, parallel requests, and large batch processing. |
| **Node 2** | Inference Secondary + Fine-tuning | RTX 5090 for large single-model inference. Fine-tuning, LoRA training, and overflow from Node 1. |
| **VAULT** | Storage + Vector DB + Data Pipeline | 180TB HDD array for bulk storage. Hosts vector databases, document ingestion pipeline, PostgreSQL, and model repository. |
| **DESK** | UI + API Gateway + Orchestrator | User-facing web UI, API gateway, and agent orchestration engine. Primary interaction point. |
| **DEV** | Development + CI/CD + Monitoring | Dev environment, testing, CI/CD pipelines, Prometheus/Grafana monitoring. Can serve inference with 5060 Ti. |
| **MOBILE** | Remote Client | Thin client for remote access. Can run small models locally for offline use. |

## Services

| Service | Port | Description |
|---------|------|-------------|
| `gateway` | 8000 | API Gateway — routes requests, auth, rate limiting |
| `inference` | 8001 | LLM inference with pluggable backends (Ollama, vLLM, llama.cpp) |
| `orchestrator` | 8002 | Agent orchestration, tool execution, workflow management |
| `rag` | 8003 | Document ingestion, embedding, retrieval pipeline |
| `storage` | 8004 | File management, model repository, S3-compatible API |
| `model-manager` | 8005 | Model lifecycle — download, convert, distribute, monitor |
| `ui` | 3000 | Next.js web interface |

## Tech Stack

- **Backend**: Python 3.12+ (FastAPI, gRPC)
- **Frontend**: Next.js 15 / React 19 / TypeScript
- **Inference**: Ollama, vLLM, llama-cpp-python (pluggable)
- **Vector DB**: Qdrant
- **Database**: PostgreSQL 16
- **Cache/Queue**: Redis 7
- **Inter-service**: gRPC (internal), REST (external), WebSocket (streaming)
- **Containers**: Docker + Docker Compose per node
- **Monitoring**: Prometheus + Grafana
- **Network**: 10GbE backbone (Ubiquiti)

## Quick Start

```bash
# 1. Clone and configure
git clone <repo-url> && cd Local-System
cp .env.example .env
# Edit .env with your node-specific settings

# 2. Install shared library
pip install -e shared/python

# 3. Start services on current node
make up NODE=desk  # or node1, node2, vault, dev, mobile

# 4. Deploy to all nodes
make deploy-all
```

## Development

```bash
# Run all tests
make test

# Run a specific service locally
make dev SERVICE=gateway

# Generate gRPC stubs from proto files
make proto

# Check system health across all nodes
make health

# View logs
make logs NODE=node1 SERVICE=inference
```

## Project Structure

```
Local-System/
├── proto/                  # gRPC protocol buffer definitions
├── shared/                 # Shared libraries
│   ├── python/             # Python shared package
│   └── typescript/         # TypeScript shared types
├── services/               # Backend microservices
│   ├── gateway/            # API Gateway
│   ├── inference/          # LLM Inference Engine
│   ├── orchestrator/       # Agent Orchestrator
│   ├── rag/                # RAG Pipeline
│   ├── storage/            # Storage Service
│   └── model-manager/      # Model Lifecycle Manager
├── ui/                     # Next.js Web UI
├── deploy/                 # Per-node deployment configs
│   ├── node1/
│   ├── node2/
│   ├── vault/
│   ├── desk/
│   ├── dev/
│   └── mobile/
├── scripts/                # Utility scripts
├── tests/                  # Integration & E2E tests
├── monitoring/             # Prometheus/Grafana configs
├── Makefile                # Build & deploy commands
└── docker-compose.yml      # Root compose file
```
