# Athanor — Sovereign Cognitive Architecture

> *"A second mind — a sovereign cognitive architecture running on privately owned hardware, implementing consciousness-inspired processing patterns, persistent multi-layered memory, autonomous agency, and deep personalization for a single human operator."*

This is not a chatbot. It is not an inference server. It is not a homelab project that happens to run LLMs.

It is a **sovereign cognitive architecture** implementing [Global Workspace Theory](https://en.wikipedia.org/wiki/Global_workspace_theory) — specialized processors competing for access to a shared cognitive workspace, with winners broadcasting their content to all other processors. It accumulates knowledge, context, and capability over months of continuous operation. It doesn't just answer questions; it asks better ones than you would have thought to ask.

---

## Architecture

```
                              ┌─────────────────────┐
                              │   COGNITIVE WORKSPACE │
                              │   (Global Broadcast)  │
                              │                       │
                              │  Continuous State      │
                              │  Tensor (CST)          │
                              │                       │
                              │  Attention Mechanism   │
                              │  Specialist Bidding    │
                              └──────────┬────────────┘
                                         │
           ┌──────────┬──────────┬───────┴───────┬──────────┬──────────┐
           ▼          ▼          ▼               ▼          ▼          ▼
     ┌──────────┐┌──────────┐┌──────────┐┌──────────┐┌──────────┐┌──────────┐
     │ Research  ││ Coding   ││ Creative ││ Building ││ Media    ││ Infra    │
     │ Agent    ││ Agent    ││ Agent    ││ Science  ││ Agent    ││ Agent    │
     │          ││          ││(EoBQ)    ││(HERS)    ││          ││          │
     └────┬─────┘└────┬─────┘└────┬─────┘└────┬─────┘└────┬─────┘└────┬─────┘
          │           │           │           │           │           │
          └───────────┴───────────┼───────────┴───────────┴───────────┘
                                  ▼
                         ┌─────────────────┐
                         │  MEMORY FABRIC  │
                         │                 │
                         │  6-Tier System  │
                         │  Procedural     │
                         │  Working        │
                         │  Episodic       │
                         │  Semantic       │
                         │  Resource       │
                         │  Knowledge Vault│
                         └────────┬────────┘
                                  │
     ┌──────────┬─────────┬───────┴───────┬─────────┬──────────┐
     ▼          ▼         ▼               ▼         ▼          ▼
  ┌──────┐  ┌──────┐  ┌──────┐     ┌──────┐  ┌──────┐  ┌──────┐
  │Qdrant│  │Neo4j │  │Postgres│   │Redis │  │Meili │  │MinIO │
  │Vector│  │Graph │  │Relat. │   │Cache │  │Search│  │Files │
  └──────┘  └──────┘  └──────┘     └──────┘  └──────┘  └──────┘
```

---

## Hardware Topology

Six hardware-specialized nodes connected via 10GbE backbone (9.4 Gbps validated):

| Node | Hardware | Role | OS | IP |
|------|----------|------|----|----|
| **hydra-ai** | TR 7960X · 128GB DDR5 · **RTX 5090 32GB + RTX 4090 24GB** | Primary inference (70B+ TP) | NixOS | 192.168.1.250 |
| **hydra-compute** | R9 9950X · 64GB DDR5 · **2× RTX 5070 Ti 16GB** | Secondary inference, ComfyUI, TTS | NixOS | 192.168.1.203 |
| **hydra-storage** | EPYC 7663 56C · 256GB DDR4 ECC · Arc A380 | Orchestration brain, databases, services | Unraid | 192.168.1.244 |
| **hydra-dev** | 16 vCPU · 64GB (VM on EPYC) | Development, IDE, Claude Code | Ubuntu 24.04 | DHCP |
| **DESK** | i7-13700K · 64GB DDR5 | Workstation, Parsec remote desktop | TBD | TBD |
| **MOBILE** | Laptop | Mobile access, thin client | TBD | TBD |

### GPU Allocation (138GB VRAM total)

| GPU | Node | Purpose |
|-----|------|---------|
| RTX 5090 32GB + RTX 4090 24GB | hydra-ai | 56GB tensor parallel via ExLlamaV2/TabbyAPI (70B models) |
| 2× RTX 5070 Ti 16GB | hydra-compute | Ollama (7B-14B fast), ComfyUI image gen, Kokoro TTS |
| Arc A380 6GB | hydra-storage | Plex transcoding (Quick Sync), frees EPYC for orchestration |

### Inference Stack (Proven Architecture)

```
                    Clients
                       │
                       ▼
              ┌─────────────────┐
              │     LiteLLM     │  OpenAI-compatible gateway
              │  storage:4000   │  Model routing + fallback
              └──┬──────┬───┬──┘
                 │      │   │
     ┌───────────┘      │   └───────────┐
     ▼                  ▼               ▼
┌──────────┐    ┌──────────┐    ┌──────────┐
│ TabbyAPI  │    │  Ollama  │    │  Ollama  │
│  + ExL2   │    │   GPU    │    │   CPU    │
│ ai:5000   │    │compute:  │    │storage:  │
│           │    │ 11434    │    │ 11434    │
│ 70B models│    │ 7B-14B   │    │ fallback │
│ 5090+4090 │    │ 5070 Ti  │    │ EPYC     │
└──────────┘    └──────────┘    └──────────┘
```

**Why ExLlamaV2**: Only engine supporting tensor parallelism across heterogeneous GPUs (5090 32GB + 4090 24GB). Battle-tested. vLLM does NOT work for this use case.

---

## Service Map

### Core Cognitive Services
| Service | Port | Node | Purpose |
|---------|------|------|---------|
| Gateway API | 8700 | storage | REST/SSE/WebSocket entry point |
| Cognitive Workspace | 8701 | storage | GWT attention mechanism, specialist routing |
| Memory Service | 8702 | storage | 6-tier memory read/write/consolidation |
| Orchestrator | 8703 | storage | Agent lifecycle, task management |

### Inference
| Service | Port | Node | Purpose |
|---------|------|------|---------|
| LiteLLM | 4000 | storage | Unified API gateway, model routing |
| TabbyAPI | 5000 | ai | ExLlamaV2 70B inference (TP across 5090+4090) |
| Ollama GPU | 11434 | compute | Fast 7B-14B models on 5070 Ti |
| Ollama CPU | 11434 | storage | Fallback on EPYC 56-core |

### Knowledge & Memory
| Service | Port | Node | Purpose |
|---------|------|------|---------|
| PostgreSQL 16 | 5432 | storage | Relational data, agent state |
| Qdrant | 6333 | storage | Vector embeddings (768d, nomic-embed-text) |
| Neo4j | 7474/7687 | storage | Knowledge graphs (Graphiti) |
| Redis 7 | 6379 | storage | Cache, sessions, pub/sub, working memory |
| Meilisearch | 7700 | storage | Full-text BM25 search |
| MinIO | 9000 | storage | S3-compatible file/model storage |

### Creative Pipeline
| Service | Port | Node | Purpose |
|---------|------|------|---------|
| ComfyUI | 8188 | compute | Image generation (PonyXL, LoRA, ControlNet) |
| Kokoro TTS | 8880 | storage | Voice synthesis with per-character emotion |

### Monitoring & Automation
| Service | Port | Node | Purpose |
|---------|------|------|---------|
| Prometheus | 9090 | storage | Metrics collection |
| Grafana | 3003 | storage | Dashboards |
| n8n | 5678 | storage | Visual workflow automation |
| Uptime Kuma | 3004 | storage | Service health monitoring |

---

## Memory Architecture (6-Tier Cognitive System)

| Tier | Purpose | Storage | Volatility |
|------|---------|---------|------------|
| **Procedural** | How to do things (conventions, commands, routing rules) | Versioned files | Permanent |
| **Working** | Active context, current task state, recent operations | Redis + YAML | Volatile |
| **Episodic** | What happened when (conversations, task outcomes, events) | Qdrant + Graphiti | Consolidates |
| **Semantic** | Knowledge graph — entities, relationships, temporal validity | Neo4j (Graphiti) | Grows |
| **Resource** | Ingested documents, code, research papers | Qdrant (chunked+embedded) | Permanent |
| **Knowledge Vault** | Validated high-confidence facts promoted from other tiers | PostgreSQL + Qdrant | Permanent |

Memory consolidation happens during idle periods — episodic memories distill into semantic knowledge, connections are discovered, and the system's understanding deepens.

---

## Project Structure

```
Local-System/
├── README.md                          # You are here
├── VISION.md                          # North star — what this system becomes
├── CONSTITUTION.yaml                  # Immutable safety constraints
├── .env.example                       # Configuration template
├── Makefile                           # Build, deploy, test commands
├── pyproject.toml                     # Python tooling config
│
├── shared/python/local_system/        # Shared library
│   ├── config.py                      # Pydantic Settings — nodes, network, services
│   ├── models.py                      # Shared data models — cognitive types, memory, agents
│   └── utils.py                       # Logging, timers, client helpers
│
├── proto/                             # gRPC service definitions
│   ├── common.proto
│   ├── inference.proto
│   ├── cognitive.proto                # GWT workspace protocol
│   ├── memory.proto                   # Memory tier operations
│   ├── rag.proto
│   └── storage.proto
│
├── services/
│   ├── gateway/                       # API gateway — REST, SSE, WebSocket
│   ├── inference/                     # LiteLLM integration + backend routing
│   │   └── backends/
│   │       ├── tabby.py               # TabbyAPI/ExLlamaV2 (primary 70B)
│   │       ├── ollama.py              # Ollama (7B-14B GPU + CPU fallback)
│   │       └── litellm_router.py      # LiteLLM unified routing
│   ├── memory/                        # 6-tier cognitive memory system
│   ├── cognitive/                     # GWT workspace — attention, broadcast, CST
│   ├── orchestrator/                  # Agent lifecycle — tools, tasks, crews
│   ├── rag/                           # Hybrid search: Qdrant vectors + Meilisearch BM25
│   └── storage/                       # File/model management, MinIO integration
│
├── ui/                                # Next.js 15 + React 19 command center
│   └── src/
│       ├── app/                       # Pages: Chat, Memory, Agents, Nodes, Knowledge
│       ├── components/                # Sidebar, Chat, MemoryViewer, NodeStatus
│       └── lib/                       # API client, SSE helpers
│
├── deploy/                            # Per-node Docker Compose
│   ├── hydra-ai/                      # TabbyAPI, inference service
│   ├── hydra-compute/                 # Ollama, ComfyUI, TTS
│   ├── hydra-storage/                 # Everything else (EPYC orchestration brain)
│   ├── hydra-dev/                     # Development tools
│   ├── desk/                          # Workstation services
│   └── mobile/                        # Mobile access
│
├── scripts/                           # Setup, health checks, deployment
│   ├── setup.sh
│   ├── health-check.sh
│   └── deploy.sh
│
├── tests/                             # Test suite
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_models.py
│   └── integration/
│
└── knowledge/                         # Domain knowledge (from Hydra)
    ├── infrastructure.md
    ├── inference-stack.md
    ├── databases.md
    └── learnings.md
```

---

## Quick Start

```bash
# 1. Clone and configure
git clone <repo-url> && cd Local-System
cp .env.example .env
# Edit .env with your node IPs, credentials, model paths

# 2. Install shared library
pip install -e shared/python/

# 3. Start services on each node
make deploy NODE=hydra-storage   # Databases, orchestration, gateway
make deploy NODE=hydra-ai        # TabbyAPI inference
make deploy NODE=hydra-compute   # Ollama, ComfyUI

# 4. Verify
make health                      # Check all nodes
```

---

## Lineage

This project is the successor to:
- **Hydra** — First active implementation (Dec 2025, 65 commits, 370+ API endpoints, 12 phases completed)
- **Kaizen** (改善) — The design philosophy of continuous improvement
- **Athanor** — Current codename (alchemical furnace that transmutes base materials into gold)
- **System Bible** — Canonical documentation repository for the vision

---

*Status: Restructuring scaffold to align with sovereign cognitive architecture vision*
*Last updated: March 2026*
