# Local-System — Full System Architecture & Implementation Plan

## Context & Philosophy

**What this is**: A sovereign AI platform running across 5 physical nodes on a home LAN. Personal system for one user — not a product, not multi-tenant. Every component must work at full quality or be fixed at root cause.

**Core principle — NO FALLBACK**: If face-ID generation fails, we don't fall back to text-only. We fix face-ID. If a model OOMs, we don't route to a weaker model. We fix the memory budget. If a service is down, we don't skip it. We fix the service. This applies everywhere, at every layer. Degraded quality is useless.

**What changed**: Previous plan (Phases 0-7) was a project-management timeline. This plan is the **system architecture reference** — how every layer connects, how the user interacts with it, where every component lives, and what needs fixing next.

---

## 1. The Five Nodes

```
                        ┌─────────────────────┐
                        │  UniFi Dream Machine │
                        │  Pro (Router/GW)     │
                        └──────────┬──────────┘
                                   │
                     ┌─────────────▼───────────────┐
                     │  USW Pro 24 PoE              │
                     │  24×1GbE RJ45 + 2×10G SFP+   │
                     │  (Primary Distribution)       │
                     └──┬──────┬──────┬─────────────┘
                        │      │      │
                        │      │   ┌──▼──────────────────────┐
                        │      │   │  10GbE SFP+ uplink      │
                        │      │   │                          │
                        │      │   │  USW Pro XG 10 PoE       │
                        │      │   │  8×10GbE RJ45 + 4×SFP+   │
                        │      │   │  (10 Gigabit Backbone)    │
                        │      │   └──┬───┬───┬───┬──────────┘
                        │      │      │   │   │   │
                  1GbE  │      │      │   │   │   │  10GbE
                        │      │      │   │   │   │
                   ┌────▼─┐ ┌─▼────┐   ┌─▼───▼┐ ┌▼─────────┐ ┌──────────┐
                   │ DESK │ │ DEV  │   │VAULT │ │WORKSHOP  │ │FOUNDRY   │
                   │ .50  │ │ .189 │   │ .203 │ │ .225     │ │ .244     │
                   │ 1GbE │ │1GbE* │   │10GbE │ │ 10GbE    │ │ 10GbE ×2 │
                   └──────┘ └──────┘   └──────┘ └──────────┘ └──────────┘

  * DEV has 1GbE onboard — 3× spare 10GbE PCIe cards available
    DESK on 1GbE — can be upgraded if needed
    FOUNDRY has 2nd 10GbE port available (dual Intel X550)
```

### Complete Hardware Inventory

#### FOUNDRY — 192.168.1.244

| Component | Detail |
|-----------|--------|
| **CPU** | AMD EPYC 7663 (SP3, 56C/112T, 2.0/3.54 GHz, Zen 3 Milan, 240W) |
| **Motherboard** | ASRock Rack ROMED8-2T — 128 PCIe 4.0 lanes, NO lane sharing |
| **RAM** | **228GB DDR4 ECC RDIMM** (8× Samsung 32GB @ 3200 MT/s) — ⚠️ **1 stick not working, missing ~28GB from 256GB target** |
| **GPU 0** (Slot 2) | RTX 5070 Ti 16GB GDDR7 (MSI) — Bus `01:00.0` — Blackwell sm_120 |
| **GPU 1** (Slot 3) | RTX 5070 Ti 16GB GDDR7 (MSI) — Bus `47:00.0` — Blackwell sm_120 |
| **GPU 2** (Slot 4) | **RTX 4090 24GB GDDR6X** — Bus `81:00.0` — Ada sm_89, shares PHB with GPU 3 |
| **GPU 3** (Slot 5) | RTX 5070 Ti 16GB GDDR7 (Gigabyte) — Bus `82:00.0` — display attached, shares PHB with GPU 2 |
| **GPU 4** (Slot 1) | RTX 5070 Ti 16GB GDDR7 (Gigabyte) — Bus TBD |
| **Total VRAM** | 88GB (4×16 + 24) |
| **NIC** | 2× Intel X550 **10GbE** RJ45 (onboard) |
| **Storage** | Crucial P3 4TB Gen3 (OS) + Samsung 990 PRO 4TB Gen4 (hot models) |
| **PSU** | Corsair 1600W |
| **PCIe topology** | Single NUMA node. GPU0,1 on separate root complexes (NODE). GPU2,3 share PHB. GPU4 separate. **4090 between 5070 Ti's is NOT a TP issue** — each gets full x16, no lane sharing. |
| **Currently running** | vllm-reasoning (GPU 0,1 TP=2), vllm-coding (GPU 2), vllm-creative (GPU 3). GPU 4 idle. |

#### WORKSHOP — 192.168.1.225

| Component | Detail |
|-----------|--------|
| **CPU** | AMD Threadripper 7960X (sTR5, 24C/48T, 4.2/5.665 GHz, Zen 4, 350W) |
| **Motherboard** | Gigabyte TRX50 AERO D — PCIe 5.0 slots |
| **RAM** | 128GB DDR5 ECC RDIMM (4× Kingston 32GB @ 5600 MT/s, running 4800, EXPO not enabled) |
| **GPU 0** | ⚠️ **NEEDS VERIFICATION** — discover.sh shows RTX 4090 24GB (Bus `01:00.0`), but ComfyUI API reports RTX 5060 Ti and MEMORY.md says 5090. **Hardware may have been swapped since last discover run.** |
| **GPU 1** | RTX 5090 32GB GDDR7 (Bus `03:00.0`) — Blackwell sm_120 |
| **Total VRAM** | ~48-56GB (depends on GPU 0 identity) |
| **NIC** | Aquantia **10GbE** + RTL8125 2.5GbE + Thunderbolt 4 |
| **Storage** | 3× Crucial T700 Gen5 1TB (Docker, scratch, ComfyUI) + 1× Crucial T700 Gen5 4TB (OS) |
| **PSU** | Corsair 1600W |
| **PCIe topology** | Single NUMA node. PHB interconnect. **Cannot do TP across GPUs** (different architectures if 4090+5090). |
| **Currently running** | vllm-fast (Qwen3-14B, systemd not Docker), ComfyUI (Docker). SSH from DEV broken. |

#### VAULT — 192.168.1.203

| Component | Detail |
|-----------|--------|
| **CPU** | AMD Ryzen 9 9950X (AM5, 16C/32T, 4.3/5.75 GHz, Zen 5, 170W) |
| **Motherboard** | ASUS ProArt X870E-CREATOR WIFI |
| **RAM** | 128GB DDR5 UDIMM (4× Micron 32GB @ 5600 MT/s) |
| **GPU** | **Intel Arc A380 6GB GDDR6** — QSV encode only (h264/hevc/av1), used by Tdarr. **NOT CUDA.** |
| **NIC** | Aquantia **10GbE** + Intel I225-V 2.5GbE + WiFi 7 |
| **Storage Array** | **164TB** Unraid array (85-93% full, 146T/164T — monitor closely) |
| **NVMe 1** | 932GB → `/mnt/appdatacache` (appdata cache, 36% used) |
| **NVMe 2** | 932GB → `/mnt/transcode` (Tdarr temp, nearly empty) |
| **NVMe 3** | 932GB → `/mnt/docker` → bind-mounted to `/var/lib/docker` (2% used) |
| **OS** | Unraid 6.12.54 |
| **Currently running** | 15+ Docker containers (databases, LiteLLM, monitoring, Tdarr, n8n, ntfy, etc.) |

#### DEV — 192.168.1.189

| Component | Detail |
|-----------|--------|
| **CPU** | AMD Ryzen 9 9900X (AM5, 12C/24T) |
| **RAM** | 60GB DDR5 |
| **GPU 0** | RTX 5060 Ti 16GB GDDR7 — embedding + reranker vLLM containers |
| **GPU 1** | ASUS ROG STRIX RX 5700 XT 8GB GDDR6 — display output only |
| **NIC** | Intel I225-V **1GbE** + WiFi 6 |
| **OS** | Ubuntu 24.04, kernel 6.17 |
| **Currently running** | 5 systemd services (Gateway, MIND, Memory, Perception, UI) + 2 vLLM containers |

#### DESK — 192.168.1.50

| Component | Detail |
|-----------|--------|
| **OS** | Windows 11 |
| **NIC** | **1GbE** (on USW Pro 24 PoE) |
| **Role** | User's workstation. Claude Code + 25 plugins, browser, VS Code |

#### Loose / Spare Hardware

| Item | Detail | Potential Use |
|------|--------|---------------|
| 3× 10GbE PCIe cards | Intel X540-T2 + 2× SR-PT02 clones (6 ports total) | Upgrade DEV/DESK to 10GbE |
| FOUNDRY RAM stick | 1× Samsung 32GB DDR4 3200 MT/s — not working right | RMA or replace to restore 256GB |
| FOUNDRY GPU 4 | RTX 5070 Ti 16GB — idle | Future TP=4 reasoning, or additional workload |

### Network Topology (Detailed)

```
                         Internet
                            │
                    ┌───────▼────────┐
                    │ UniFi Dream    │
                    │ Machine Pro    │
                    │ (Router + FW)  │
                    └───────┬────────┘
                            │
                ┌───────────▼────────────┐
                │ USW Pro 24 PoE          │
                │ 24×1GbE + 2×10G SFP+    │
                │ (Primary Distribution)   │
                ├─────────────────────────┤
                │                         │
                │  1GbE ports:            │
                │  ├── DESK (.50)         │
                │  ├── DEV (.189) *       │
                │  └── (other LAN devices)│
                │                         │
                │  10G SFP+ uplink:       │
                └────────┬────────────────┘
                         │ 10GbE
              ┌──────────▼──────────────┐
              │ USW Pro XG 10 PoE        │
              │ 8×10GbE RJ45 + 4×SFP+   │
              │ (10 Gigabit Backbone)     │
              ├──────────────────────────┤
              │                          │
              │  10GbE ports:            │
              │  ├── FOUNDRY (.244) ×2   │
              │  ├── WORKSHOP (.225)     │
              │  └── VAULT (.203)        │
              └──────────────────────────┘
```

**Bandwidth implications**:
- FOUNDRY ↔ VAULT (10GbE direct via XG switch): ~1.2 GB/s — NFS model loading is fast
- WORKSHOP ↔ VAULT (10GbE direct via XG switch): ~1.2 GB/s — gen-output writes, model loading
- FOUNDRY ↔ WORKSHOP (10GbE direct via XG switch): ~1.2 GB/s — if needed for cross-node work
- DEV → anything on XG switch (1GbE → 10GbE uplink): ~125 MB/s — bottlenecked by DEV's 1GbE NIC, not the uplink
- DESK ↔ DEV (both on 24-port, 1GbE): ~125 MB/s — adequate for SSH/MCP, UI browsing
- **Key insight**: The 10GbE uplink between switches means DEV and DESK *can* reach the 10GbE nodes, but are limited by their own 1GbE NICs. The uplink itself is not the bottleneck.
- **Recommendation**: DEV should get a 10GbE card from the spare pool and move to the XG switch — it's the services hub connecting to everything. DESK's 1GbE is fine for UI/SSH use.

### What Each Node Currently Does (Not Fixed Roles — Can Be Reconfigured)

| Node | IP | What It Currently Does | How User Reaches It |
|------|-----|----------------------|---------------------|
| **FOUNDRY** | .244 | 3 vLLM inference containers on 4/5 GPUs. Mounts models from VAULT via NFS | LiteLLM routes transparently |
| **WORKSHOP** | .225 | vLLM-fast (systemd) + ComfyUI (Docker). 2 GPUs | ComfyUI :8188, vLLM :8000 via LiteLLM |
| **VAULT** | .203 | 15+ Docker containers: 5 databases, LiteLLM, monitoring, Tdarr, n8n, ntfy, minio. 164TB storage. Intel ARC A380 for QSV transcode | LiteLLM :4000, Grafana :3000, ntfy :8880 |
| **DEV** | .189 | 5 systemd services (Gateway/MIND/Memory/Perception/UI). 2 vLLM containers (embed/rerank). Dev environment | UI :3001, API :8700, MCP (SSH from DESK) |
| **DESK** | .50 | User's Windows workstation. Claude Code + 25 plugins, browser | User sits here |

### Inter-Node Communication

```
DESK → DEV:      1GbE (both on USW Pro 24) — SSH (MCP), HTTP (UI:3001, API:8700)
DEV → VAULT:     1GbE → 10G uplink → 10GbE — HTTP (DBs, LiteLLM:4000, Redis, PG)
DEV → FOUNDRY:   1GbE → 10G uplink → 10GbE — HTTP (vLLM:8000, :8002, :8004)
DEV → WORKSHOP:  1GbE → 10G uplink → 10GbE — HTTP (ComfyUI:8188, vLLM:8000). SSH BROKEN
FOUNDRY ↔ VAULT: 10GbE direct (both on XG switch) — NFS model files
FOUNDRY ↔ WORKSHOP: 10GbE direct (both on XG switch)
WORKSHOP ↔ VAULT: 10GbE direct (both on XG switch) — NFS gen-drops/gen-output
VAULT → all:     10GbE/1GbE — NFS exports (models, data, media, backups)
```

All 10GbE nodes (FOUNDRY, WORKSHOP, VAULT) interconnect at wire speed on the XG switch.
DEV and DESK connect via the 24-port 1GbE switch, reaching 10GbE nodes through the SFP+ uplink.

### Shared Filesystem (NFS from VAULT)

| Mount | Content | Who Mounts It |
|-------|---------|---------------|
| `/mnt/vault/models` | LLM weights (HuggingFace format) | FOUNDRY, WORKSHOP |
| `/mnt/vault/data/gen-drops` | User drops photos here → auto-gen trigger | DEV (Gateway), user via `\\VAULT\data` |
| `/mnt/vault/data/gen-refs` | Cropped reference faces | DEV (Gateway) |
| `/mnt/vault/data/gen-output` | Generated images | DEV (Gateway), UI gallery |
| `/mnt/vault/data/media` | Media library (movies, TV) | Tdarr on VAULT |
| `/mnt/vault/data/documents` | User documents → Perception ingestion | DEV (Perception watcher) |
| `/mnt/vault/data/backups` | PG, Neo4j, Qdrant backups | VAULT cron jobs |

---

## 2. Service Architecture

**All services run on DEV as systemd units** (not Docker — direct uvicorn for fast iteration):

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER (DESK .50)                          │
│  Claude Code → MCP servers (SSH to DEV)                         │
│  Browser → UI (DEV:3001)                                        │
│  File explorer → \\VAULT\data\gen-drops (SMB/NFS)              │
└───────────┬──────────────────┬──────────────────┬───────────────┘
            │                  │                  │
     ┌──────▼──────┐    ┌─────▼──────┐     ┌─────▼──────┐
     │ MCP Servers  │    │  Next.js   │     │  Drop      │
     │ (7 servers,  │    │  UI :3001  │     │  Folder    │
     │  54 tools)   │    │            │     │            │
     └──────┬───────┘    └─────┬──────┘     └─────┬──────┘
            │                  │                  │
┌───────────▼──────────────────▼──────────────────▼───────────────┐
│  GATEWAY :8700                                                   │
│  API hub — REST/SSE. Routes to MIND, Memory, ComfyUI            │
│  Hosts: auto_gen scanner, gen_scheduler, pipeline presets        │
│  Routers: /chat, /generate, /queens, /health, /memory,          │
│           /tasks, /workspaces                                    │
└──────┬─────────────────┬─────────────────┬──────────────────────┘
       │                 │                 │
┌──────▼──────┐   ┌──────▼──────┐   ┌─────▼──────────┐
│ MIND :8710  │   │ MEMORY :8720│   │ PERCEPTION     │
│             │   │             │   │ :8730           │
│ Reasoning   │   │ 6-tier      │   │                │
│ engine      │   │ memory      │   │ Chunk→embed→   │
│ Agent       │   │ CRUD        │   │ index pipeline │
│ workflows   │   │ Deep search │   │ File watchers  │
│ Capability  │   │ Cross-tier  │   │ URL/batch      │
│ routing     │   │ rerank      │   │ ingest         │
│ Task mgmt   │   │ Consolidate │   │                │
│ Workspaces  │   │             │   │                │
│ Daily brief │   │             │   │                │
└──────┬──────┘   └──────┬──────┘   └──────┬─────────┘
       │                 │                 │
       └────────┬────────┘                 │
                ▼                          ▼
┌──────────────────────────────────────────────────────┐
│  VAULT :203 — All databases + LiteLLM                │
│  ┌─────────┐ ┌───────┐ ┌──────┐ ┌──────┐ ┌────────┐ │
│  │ Postgres │ │ Redis │ │Qdrant│ │Neo4j │ │Meili   │ │
│  │ :5432   │ │ :6379 │ │:6333 │ │:7687 │ │:7700   │ │
│  └─────────┘ └───────┘ └──────┘ └──────┘ └────────┘ │
│  ┌──────────────────────────────────────────────────┐ │
│  │ LiteLLM :4000 — inference routing to all GPUs    │ │
│  └──────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
                │
   ┌────────────┼────────────────────────┐
   ▼            ▼                        ▼
┌──────┐  ┌──────────┐           ┌────────────┐
│FOUND.│  │WORKSHOP  │           │DEV GPU     │
│:8000 │  │:8000     │           │:8001 embed │
│:8002 │  │:8188     │           │:8003 rerank│
│:8004 │  │ComfyUI   │           └────────────┘
└──────┘  └──────────┘
```

### Service Details

| Service | Port | Systemd Unit | What It Does |
|---------|------|-------------|-------------|
| **Gateway** | 8700 | `local-system-gateway` | API dispatcher. Thin routing layer. Also hosts auto_gen scanner + gen_scheduler (autonomous image generation). Pipeline presets for ComfyUI. Scene builder for queen prompts. |
| **MIND** | 8710 | `local-system-mind` | Central reasoning engine. 8-step reasoning loop. Agent workflows with tool use. Capability routing (chat/code/search/creative/infra). Conversation persistence in PG. Workspace-aware context. Daily brief generation. |
| **Memory** | 8720 | `local-system-memory` | 6-tier memory system. Working (Redis), Episodic (Qdrant), Semantic (Neo4j), Procedural (PG), Resource (Qdrant+Meili), Vault (PG+Qdrant). Cross-tier deep search with reranking. Consolidation pipeline. |
| **Perception** | 8730 | `local-system-perception` | Ingestion pipeline. Chunk→embed→index into Memory tiers. Directory watchers (docs/, vault documents). URL/batch ingest. Handles text, markdown, code. |
| **UI** | 3001 | `local-system-ui` | Next.js 15.1 Command Center. Pages: Chat, Generate Studio, Models, Memory, Agents, Documents, Nodes. |

### MIND Service Internals

**8-Step Reasoning Loop** (`reasoning.py` → `ReasoningEngine.process()`):

| Step | Name | What Happens |
|------|------|-------------|
| 1 | CONTEXTUALIZE | Load conversation (up to 50 prior messages from PG) |
| 2 | ROUTE | Classify capability, resolve model/tools. Priority: explicit params > workspace defaults > capability defaults > agent presets |
| 3 | ASSEMBLE | Fetch memory context (top 5 results, 10s timeout), build system prompt with workspace + memory injection |
| 4 | THINK | LLM inference via LiteLLM `/v1/chat/completions`. Temp 0.7, max_tokens 4096, timeout 120s |
| 5 | ACT | Execute tool calls in sequence, append results as "tool" role messages |
| 6 | OBSERVE | Log agent action to `mind_agent_logs` table (LLM call or tool exec with duration) |
| 7 | RESPOND | Store assistant message + tokens + latency to `mind_messages` table |
| 8 | REMEMBER | Publish `mind.response:reasoning_complete` event via Redis Streams |

Max iterations: 10. Returns: `{response, conversation_id, model, capability, workspace, tool_calls, tokens: {in, out}, latency_ms}`

**6 Capabilities** (`router.py` → `CapabilityRouter`):

| Capability | Model | Tools | Trigger Keywords |
|-----------|-------|-------|-----------------|
| CHAT | reasoning | memory_search, calculator | (default) |
| SEARCH | fast | memory_search, web_fetch | "search", "find", "recall", "remember" |
| CODE | coding | memory_search, memory_store | "code", "debug", "implement", "python" |
| CREATIVE | reasoning | memory_search, memory_store | "write", "story", "character", "comfyui" |
| INFRASTRUCTURE | fast | memory_search | "server", "docker", "gpu", "deploy", "foundry" |
| ANALYSIS | reasoning | memory_search, calculator | "analyze", "calculate", "statistics" |

**4 Built-in Tools** (`tools.py` → `ToolRegistry`):

| Tool | Function | Details |
|------|----------|---------|
| calculator | `eval()` with restricted chars | Safe math: `0-9+-*/().% ` |
| memory_search | HTTP → Memory:8720 | query + top_k (default 5), returns [{content, source, confidence}] |
| memory_store | HTTP → Memory:8720 | content + tier (episodic/procedural/resource/vault) + source + tags |
| web_fetch | HTTP GET | URL → text, capped at 10,000 chars, 30s timeout |

**10 Workspace Types** (`workspace_manager.py`):

| Workspace | Default Model | Memory Tiers | Notes |
|-----------|--------------|-------------|-------|
| infrastructure | reasoning | procedural, vault, episodic, resource | Cluster ops |
| app_dev | reasoning | procedural, resource, episodic, vault | App development |
| game_dev | reasoning | procedural, resource, episodic | EoBQ game dev |
| data_science | reasoning | resource, procedural, vault, episodic | Data analysis |
| creative_studio | reasoning | episodic, resource | Creative writing/gen |
| media_library | reasoning | resource, episodic | Media management |
| home_automation | reasoning | procedural, vault, episodic | Home systems |
| research | reasoning | resource, vault, semantic, episodic | Research projects |
| business_finance | reasoning | vault, procedural, resource | Business/finance |
| travel_lifestyle | reasoning | episodic, resource | Travel/lifestyle |

Each workspace injects persona + context into MIND's system prompt. Active workspace stored in Redis with 24h TTL per session.

**PostgreSQL Schema** (`db.py` → `MindDB`, 4 tables):

```
mind_conversations: id, workspace, title, model, created_at, updated_at
mind_messages: id, conversation_id(FK), role, content, tool_calls(JSONB), tool_call_id, model, tokens_in, tokens_out, latency_ms, created_at
mind_tasks: id, conversation_id(FK), specialist, description, status(pending/running/completed/failed), result, error, agent_id, model, iterations, memory_context(JSONB), created_at, completed_at
mind_agent_logs: id(SERIAL), task_id(FK), iteration, action(llm_call/tool_exec/memory_read/decision), detail(JSONB), duration_ms, created_at
```

### Complete API Endpoint Map (80+ endpoints)

**Gateway :8700** — 60+ endpoints across 7 router modules:

| Router | Path | Method | Purpose |
|--------|------|--------|---------|
| chat | `/v1/chat/completions` | POST | LLM completion with content-aware model routing |
| chat | `/v1/chat/completions/stream` | POST | SSE streaming chat |
| chat | `/v1/chat/ws` | WS | WebSocket interactive chat |
| chat | `/v1/models` | GET | List all LiteLLM models |
| generate | `/v1/generate/image` | POST | Text-to-image (Flux/RealVisXL) |
| generate | `/v1/generate/face` | POST | Face-ID generation (PuLID/IPAdapter) |
| generate | `/v1/generate/swap` | POST | Face swap (ReActor) |
| generate | `/v1/generate/img2img` | POST | Image-to-image |
| generate | `/v1/generate/inpaint` | POST | Inpainting with mask |
| generate | `/v1/generate/from-template` | POST | Generate from prompt template |
| generate | `/v1/generate/upload` | POST | Upload image to ComfyUI |
| generate | `/v1/generate/upload-ref` | POST | Upload performer ref photo |
| generate | `/v1/generate/preview-prompts` | POST | Preview LLM-generated prompts |
| generate | `/v1/generate/train` | POST | Start LoRA training |
| generate | `/v1/generate/cancel` | POST | Cancel generation by prompt_id |
| generate | `/v1/generate/view` | GET | Proxy ComfyUI image viewer |
| generate | `/v1/generate/history` | GET | Generation history |
| generate | `/v1/generate/queue` | GET | ComfyUI queue status |
| generate | `/v1/generate/status` | GET | Generation service status |
| generate | `/v1/generate/models` | GET | List checkpoints, LoRAs |
| generate | `/v1/generate/pipelines` | GET | List pipeline presets |
| generate | `/v1/generate/templates` | GET | List prompt templates |
| generate | `/v1/generate/train/{job_id}` | GET | Training job status |
| generate | `/v1/generate/performers` | GET | Search performer database |
| generate | `/v1/generate/drops` | GET | List drop folders |
| generate | `/v1/generate/drops/{name}` | GET | Drop detail |
| generate | `/v1/generate/drops/{name}/images` | GET | Generated images for drop |
| generate | `/v1/generate/drops/{name}/image/{f}` | GET | Serve generated image |
| generate | `/v1/generate/drops/{name}/ref/{f}` | GET | Serve ref image |
| generate | `/v1/generate/drops/{name}/process` | POST | Process drop |
| generate | `/v1/generate/drops/{name}/retry` | POST | Retry failed drop |
| generate | `/v1/generate/drops/scan` | POST | Force scan all drops |
| generate | `/v1/generate/gallery` | GET | Aggregated gallery data |
| generate | `/v1/generate/performer-refs/{slug}` | GET | List performer refs |
| generate | `/v1/generate/scheduler` | GET | Scheduler status |
| generate | `/v1/generate/scheduler/start` | POST | Start scheduler |
| generate | `/v1/generate/scheduler/stop` | POST | Stop scheduler |
| generate | `/v1/generate/scheduler/trigger` | POST | Trigger immediate gen |
| generate | `/v1/generate/scheduler/subjects` | GET/POST | List/add subjects |
| generate | `/v1/generate/scheduler/subjects/{n}` | DELETE | Remove subject |
| generate | `/v1/generate/scheduler/config` | PUT | Update scheduler config |
| generate | `/v1/generate/ws` | WS | WebSocket ComfyUI progress |
| queens | `/v1/generate/queens` | GET | List queen profiles |
| queens | `/v1/generate/queens/{id}` | GET | Queen detail |
| queens | `/v1/generate/queens/reload` | POST | Reload from Master Doc |
| queens | `/v1/generate/queen` | POST | Generate queen portrait/scene |
| health | `/health` | GET | Service health + uptime |
| health | `/health/cluster` | GET | All cluster services health |
| health | `/emergency/stop` | POST | Emergency kill switch |
| memory | `/v1/memory/working` | GET | Working memory context |
| memory | `/v1/memory/search` | POST | Search memory tiers |
| memory | `/v1/search` | POST | Hybrid RAG search |
| tasks | `/v1/tasks` | POST | Create agent task (→ MIND) |
| tasks | `/v1/tasks/{id}` | GET | Task status (→ MIND) |
| workspaces | `/v1/workspaces` | GET | List workspaces |
| workspaces | `/v1/workspaces/{slug}` | GET | Get workspace |
| workspaces | `/v1/workspaces/active/{sid}` | GET/PUT | Get/set active workspace |
| main | `/gallery` | GET | Serve gallery HTML |
| main | `/metrics` | GET | Prometheus metrics |

**MIND :8710** — 18 endpoints:

| Path | Method | Purpose |
|------|--------|---------|
| `/v1/chat/completions` | POST | OpenAI-compatible chat |
| `/v1/mind/process` | POST | Full reasoning (model, specialist, tools, workspace) |
| `/v1/mind/stats` | GET | DB + event + tool + workspace stats |
| `/v1/mind/cluster-status` | GET | Aggregate health (queries all services) |
| `/v1/workspaces` | GET | List workspaces |
| `/v1/workspaces/{slug}` | GET | Get workspace |
| `/v1/workspaces/active/{sid}` | GET/PUT | Session workspace |
| `/v1/agents` | GET | List preset agents |
| `/v1/tasks` | POST/GET | Create task / list tasks |
| `/v1/tasks/{id}` | GET | Task detail |
| `/v1/conversations` | GET | List conversations |
| `/v1/conversations/{id}/messages` | GET | Conversation messages |
| `/v1/events/{channel}` | GET | Read Redis Stream events |
| `/v1/brief` | GET | Generate daily brief |
| `/v1/consolidate` | POST | Trigger memory consolidation |
| `/health` | GET | Service health |
| `/metrics` | GET | Prometheus metrics |

**Memory :8720** — Tier CRUD + search:

| Path | Method | Purpose |
|------|--------|---------|
| `/v1/memory/store` | POST | Store to any tier |
| `/v1/memory/search` | POST | Cross-tier search |
| `/v1/memory/stats` | GET | Stats per tier |
| `/v1/memory/working` | GET | Working memory context |
| `/v1/search` | POST | Hybrid RAG search |
| `/health` | GET | Service health |
| `/metrics` | GET | Prometheus metrics |

**Perception :8730** — Ingestion pipeline:

| Path | Method | Purpose |
|------|--------|---------|
| `/v1/ingest/file` | POST | Upload + ingest file |
| `/v1/ingest/text` | POST | Ingest raw text |
| `/v1/ingest/url` | POST | Ingest from URL |
| `/v1/ingest/stats` | GET | Ingestion statistics |
| `/health` | GET | Service health |
| `/metrics` | GET | Prometheus metrics |

---

## 3. User Interaction — How You Use the System

### 3.1 From DESK (Primary)

**Claude Code + MCP Servers** (most powerful interface):
- 7 MCP servers, 54 tools — all via SSH to DEV
- `ls-memory`: Store/search/consolidate across all 6 memory tiers
- `ls-inference`: Run LLM completions, embeddings, reranking
- `ls-knowledge`: RAG search, knowledge graph queries
- `ls-workspace`: Project context, file tree, code search
- `ls-infra`: Cluster health, GPU status, Docker management
- `ls-creative`: ComfyUI image generation, queen management
- `ls-tools`: Tool discovery, script execution, service management
- Config: `.mcp.json` at repo root, shared via git

**Browser — Command Center UI** (`http://192.168.1.189:3001`):
- Chat page: Conversational interface backed by MIND reasoning engine
- Generate Studio: Submit generation jobs, view progress, browse gallery
- Models page: See active LLM models, GPU utilization, switch models
- Memory page: Browse/search across all 6 memory tiers
- Agents page: View agent task history, active workflows
- Documents page: Uploaded docs, ingestion status, search
- Nodes page: Cluster health dashboard, per-node status

**File Explorer — Drop Folder** (`\\VAULT\data\gen-drops\`):
- Drop photos into a named subfolder → auto-gen detects and processes
- Output appears in `\\VAULT\data\gen-output\<name>\`
- Zero UI needed — pure filesystem trigger

**Browser — Grafana** (`http://192.168.1.203:3000`):
- Dashboards: Athanor Operations, Local-System Cluster, Node Exporter Full, NVIDIA DCGM, VAULT Server Monitor
- GPU utilization, service latency, memory usage, disk space

**Browser — ComfyUI** (`http://192.168.1.225:8188`):
- Direct workflow editor when manual control needed
- Auto-gen uses it headlessly via API

**Push Notifications** (ntfy, `http://192.168.1.203:8880`):
- Generation complete notifications
- Daily brief summaries
- Service health alerts

### 3.2 From Any LAN Device

- UI: `http://192.168.1.189:3001`
- Gallery: `http://192.168.1.189:8700/gallery`
- Grafana: `http://192.168.1.203:3000`
- ComfyUI: `http://192.168.1.225:8188`

### 3.3 MCP from Other Tools

Same `.mcp.json` works with Kimi Code, Codex CLI, any MCP-compatible tool. All share the same memory/context via `ls-memory`. Tool switching doesn't lose context.

### 3.4 MCP Tool Inventory (54 Tools)

All servers use **FastMCP 2.0**, **stdio transport**, SSH tunnel from DESK to DEV:
```
ssh shaun@192.168.1.189 "source .env && cd services/mcp-servers/ls-X && uv run server.py"
```

**ls-memory** (21 tools):

| Tool | Purpose |
|------|---------|
| `memory_store` | Store content to any memory tier (working/episodic/procedural/resource/vault) |
| `memory_search` | Search across all or specific tiers with embedding similarity |
| `memory_recall` | Quick recall of recent memories by keyword |
| `memory_list_sessions` | List active working memory sessions |
| `memory_delete` | Remove a memory entry by ID |
| `memory_list_tags` | List all tags used across memory tiers |
| `episodic_store` | Store a timestamped event (conversation, task_outcome, discovery, error) |
| `episodic_list` | List recent episodic events with optional time filter |
| `semantic_add_entity` | Add an entity to the Neo4j knowledge graph |
| `semantic_add_relation` | Add a relationship between two entities |
| `semantic_neighbors` | Find entities connected to a given entity |
| `procedural_store` | Store a how-to procedure (restart, deploy, troubleshoot) |
| `procedural_search` | Search procedures by keyword |
| `procedural_record_outcome` | Record whether a procedure succeeded/failed when used |
| `vault_store` | Archive a high-confidence fact to the knowledge vault |
| `deep_search` | Cross-tier search with reranking — queries all tiers in parallel |
| `ingest_text` | Chunk + embed + index raw text into Resource tier |
| `ingest_url` | Fetch URL content, chunk, embed, index into Resource tier |
| `memory_stats` | Statistics per tier (counts, sizes, last activity) |
| `memory_consolidate` | Trigger manual consolidation (Working→Episodic→Vault) |
| `memory_export` | Export memory entries as JSON for backup/analysis |

**ls-inference** (5 tools):

| Tool | Purpose |
|------|---------|
| `complete` | LLM chat completion via LiteLLM (any model alias) |
| `embed` | Generate embeddings via Qwen3-Embedding-0.6B |
| `rerank` | Rerank search results via Qwen3-Reranker-0.6B |
| `list_models` | List all available LiteLLM model aliases |
| `gpu_status` | GPU utilization across all nodes (VRAM, temp, power) |

**ls-knowledge** (5 tools):

| Tool | Purpose |
|------|---------|
| `search` | Hybrid RAG search (Qdrant vector + Meilisearch BM25, alpha=0.7) |
| `search_memory` | Search specific memory tiers with filters |
| `ingest` | Ingest a document/file into the Resource tier |
| `list_collections` | List Qdrant collections with point counts |
| `get_working_memory` | Get current working memory context (active task, priorities) |

**ls-workspace** (5 tools):

| Tool | Purpose |
|------|---------|
| `get_project_context` | Get project structure, dependencies, README summary |
| `list_recent_changes` | Git log of recent changes with file diffs |
| `read_project_file` | Read a specific file from the project |
| `get_file_tree` | Directory tree with file sizes and types |
| `search_project` | Grep/ripgrep across the codebase |

**ls-infra** (5 tools):

| Tool | Purpose |
|------|---------|
| `cluster_health` | Health check of all services across all nodes |
| `gpu_status` | NVIDIA GPU info (VRAM, utilization, temperature, power) |
| `litellm_models` | List LiteLLM model groups with routing config |
| `service_logs` | Tail logs from any systemd service on DEV |
| `docker_status` | Docker container status on any node |

**ls-creative** (8 tools):

| Tool | Purpose |
|------|---------|
| `generate_image` | Text-to-image via ComfyUI (Flux/RealVisXL pipelines) |
| `generate_face` | Face-ID generation with reference photo (PuLID/IPAdapter) |
| `generate_queen` | Generate queen portrait or scene from profile + DNA |
| `list_pipelines` | List available ComfyUI pipeline presets |
| `list_queens` | List all queen profiles from Master Doc |
| `generation_status` | ComfyUI queue status (running/pending/completed) |
| `list_comfyui_models` | List checkpoints, LoRAs, VAEs on ComfyUI |
| `generation_history` | Recent generation history with parameters |

**ls-tools** (5 tools):

| Tool | Purpose |
|------|---------|
| `discover_tools` | List all available tools across all MCP servers |
| `run_script` | Execute a script from the `scripts/` directory |
| `cluster_quick_check` | Fast health ping of all services (< 5s) |
| `restart_service` | Restart a systemd service on DEV |
| `tail_logs` | Tail recent logs from any service |

---

## 4. Autonomous Generation Pipeline (Current Focus)

### How It Works End-to-End

```
User drops photos          Scheduler creates         Scanner detects
into gen-drops/            drops on timer            new drop folder
  \\VAULT\data\              (25 themes,              (30s poll)
  gen-drops\<name>\          cron-based)                   │
       │                        │                         │
       └────────────────────────┴─────────────────────────┘
                                │
                    ┌───────────▼────────────┐
                    │  Gateway auto_gen.py   │
                    │  process_drop()        │
                    │                        │
                    │  1. Find best ref      │
                    │     images (face crop) │
                    │  2. Upload refs to     │
                    │     ComfyUI            │
                    │  3. LLM generates      │
                    │     detailed prompts   │
                    │     (uncensored model) │
                    │  4. Submit to ComfyUI  │
                    │     face-ID pipeline   │
                    │  5. Wait for result    │
                    │  6. Save to gen-output │
                    │  7. Write manifest     │
                    │  8. Mark .done         │
                    └───────────┬────────────┘
                                │
           ┌────────────────────┼────────────────────┐
           ▼                    ▼                    ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │ FOUNDRY:8004 │  │ WORKSHOP     │  │ VAULT NFS    │
    │ vLLM creative│  │ ComfyUI:8188 │  │ gen-output/  │
    │ (Qwen3-8B    │  │              │  │              │
    │  abliterated)│  │ Face-ID pipe:│  │ Saved images │
    │              │  │ Flux FP8 +   │  │ + manifest   │
    │ Generates    │  │ PuLID +      │  │              │
    │ uncensored   │  │ InsightFace +│  │              │
    │ prompts      │  │ LoRA +       │  │              │
    │              │  │ GFPGAN       │  │              │
    └──────────────┘  └──────────────┘  └──────────────┘
```

### What's Working

- ✅ auto_gen.py: Scanner, ref selection, LLM prompt generation, ComfyUI submission, result waiting, output saving
- ✅ scheduler.py: 25 themed scenes (12 enhanced + 13 EoBQ-inspired), cron scheduling, drop creation
- ✅ scene_builder.py: Queen DNA → prompt conversion, portrait/scene prompt building
- ✅ dna_engine.py: 19-trait DNA system → prompt modifiers
- ✅ pipelines.py: 8 ComfyUI pipeline presets (flux-faceid, flux-uncensored, queen-portrait, queen-scene, sdxl-faceid, face-swap, custom-lora, realvis-xl)
- ✅ LLM prompt generation: Enhanced system prompt with Arri Alexa color science, camera/lens specs, body type preferences, lighting direction

### 4.1 DNA Engine — 19-Trait Personality System (`dna_engine.py`)

Maps queen personality traits (1-10 scale) to visual/mood prompt modifiers. Two modifier sets:

**Thresholds**: HIGH ≥ 7, LOW ≤ 4

**Aesthetic Modifiers** (always applied — SFW-safe visual qualities):

| Trait(s) | HIGH Modifier | LOW Modifier |
|----------|--------------|-------------|
| dominance | "commanding regal bearing, authoritative stance" | "approachable relaxed posture" |
| submission | "graceful yielding energy, devoted gaze" | "self-assured independent stance" |
| exhibitionism | "magnetic attention-drawing presence" | "subtle understated elegance" |
| corruption | "dark mysterious allure, dangerous beauty" | "wholesome radiant purity" |
| nurturing | "warm maternal softness, inviting warmth" | "cool composed detachment" |
| power_exchange | "electric tension of authority exchange" | — |
| intellectual_arousal | "knowing intelligent eyes, cerebral seduction" | — |
| sensory_focus | "rich tactile textures, sensual fabric details" | — |
| ritualism | "ceremonial presence, ritualistic adornment" | — |
| spontaneity | "windswept natural energy, caught mid-motion" | — |
| possessiveness | "fierce claiming intensity in the eyes" | — |
| intimacy_threshold (LOW) | — | "distant ethereal untouchable quality" |
| voyeurism | "aware of being watched, performative beauty" | — |
| emotional_openness | "warm expressive emotion on face" | "enigmatic masked expression" |
| guardedness | "armored elegant distance" | — |
| intensity+playfulness | Lighting: "dramatic chiaroscuro" (high intensity) or "soft golden playful" (high playfulness) | "neutral balanced" |

**Explicit Modifiers** (opt-in, NSFW — applied when `include_explicit=True`):

| Trait(s) | HIGH Modifier |
|----------|--------------|
| exhibitionism + taboo_comfort | Clothing: "partially undressed" / "fully nude artistic" / "strategically draped sheer" |
| submission/dominance + intensity | Body: "submissive kneeling" / "dominant standing over" / "intense dynamic pose" |
| sensory_focus + intensity | Expression: "parted lips heavy-lidded ecstasy" / "subtle knowing pleasure" |
| sensory_focus | Skin: "detailed skin texture, visible goosebumps, natural body details" |
| power_exchange + corruption + ritualism | Power: "leather restraint details, ritual binding elements" |
| voyeurism | Framing: "shot through doorway, mirror reflection, peeping angle" |
| spontaneity | Spontaneity: "caught undressing, interrupted intimate moment" |
| intimacy_threshold (LOW) | Closeness: "extreme close intimate framing, breath-distance proximity" |

### 4.2 Generation Scheduler (`scheduler.py`)

**25 Built-in Themes** — each with full photography direction including camera body, lens, color science:

| # | Theme | Mode | Context Summary |
|---|-------|------|----------------|
| 1 | portrait-studio | explicit | Classic portrait studio, Arri Alexa + Cooke S7/i 85mm, Kodak 2383 film |
| 2 | outdoor-golden | explicit | Golden hour meadow, Canon C70 + Sigma Art 35mm, warm tones |
| 3 | noir-cinematic | explicit | Film noir chiaroscuro, Arri Alexa + Zeiss Master Prime 50mm, desaturated |
| 4 | fantasy-warrior | explicit | Mythic warrior queen, RED Monstro + Angenieux Optimo 24-290mm, amber/steel |
| 5 | cyberpunk-neon | explicit | Rain-slicked neon city, Sony Venice + Leica Summilux-C 29mm, cyan-magenta push |
| 6 | bedroom-intimate | explicit | Private bedroom morning, Arri Alexa Mini + Cooke Panchro 40mm, warm skin tones |
| 7 | pool-summer | explicit | Luxury infinity pool, Sony FX6 + Sigma Art 24mm, turquoise-gold grade |
| 8 | gothic-dark | explicit | Dark gothic cathedral, Arri Alexa + Zeiss Super Speed 35mm, deep shadows |
| 9 | shower-steam | explicit | Steam-filled luxury shower, Canon C300 III + Canon CN-E 85mm, diffused warmth |
| 10 | office-professional | explicit | Executive power office, Sony Venice + Cooke Anamorphic 75mm, neutral-cool |
| 11 | art-model | explicit | Fine art figure study, Phase One IQ4 150MP + Schneider 80mm, museum-quality |
| 12 | beach-sunset | explicit | Tropical beach sunset, RED Komodo + Canon CN-E 35mm, golden-magenta grade |
| 13 | neon-club | explicit | VIP nightclub, neon wash, velvet couches, glass reflections |
| 14 | mirror-room | explicit | Infinity mirror room, fractured reflections, jewel tones |
| 15 | throne-room | explicit | Ornate throne, burgundy velvet, crown, gold leaf, candles |
| 16 | helipad-penthouse | explicit | Rooftop penthouse, city skyline at dusk, champagne |
| 17 | nordic-sauna | explicit | Scandinavian cedar sauna, steam, ice plunge, birch |
| 18 | island-private | explicit | Private island lagoon, turquoise water, overwater pavilion |
| 19 | casino-vip | explicit | High-roller casino suite, poker chips, whiskey, emerald felt |
| 20 | pole-performance | explicit | Professional pole studio, chrome pole, athletic artistry |
| 21 | executive-surrender | explicit | Corner office power reversal, desk, cityscape, loosened tie |
| 22 | luxury-bath | explicit | Marble soaking tub, rose petals, candlelight, champagne flute |
| 23 | boudoir-silk | explicit | French boudoir, silk drapes, vanity mirror, pearl strings |
| 24 | gym-sweat | explicit | Private gym, post-workout glow, boxing gloves, athletic wear |
| 25 | rain-window | explicit | Floor-to-ceiling window, thunderstorm, city lights blurred |

**Scheduler Logic**:
- `SubjectConfig`: name, display_name, enabled, themes (subset or all), images_per_drop (default 3), mode, priority (1-10), last_theme_index, last_generated, total_generated
- `SchedulerState`: enabled, interval_minutes (default 120), quiet_start (2am), quiet_end (7am), total_runs, last_run/subject/theme
- **Subject selection**: Weighted random — priority × time_since_last_generated (higher priority + longer wait = more likely)
- **Theme rotation**: Sequential per-subject (wraps around). Each subject cycles through its allowed themes
- **Quiet hours**: 2am–7am, no generation. Scheduler checks before creating drops
- **Drop creation**: Creates folder in `gen-drops/{subject_name}/` with theme context written to `prompt.txt`
- **Config persistence**: JSON file at `gen-drops/.scheduler-config.json`

### 4.3 ComfyUI Pipeline Presets (`pipelines.py`)

10 pipeline presets, each building a full ComfyUI workflow as a JSON node graph:

| Pipeline | Checkpoint | Resolution | Sampler | Steps | CFG | LoRA | Face Restore | Use Case |
|----------|-----------|-----------|---------|-------|-----|------|-------------|----------|
| `flux-uncensored` | FLUX.1 Dev FP8 | 1024×1024 | euler / simple | 25 | 1.0 | flux-uncensored.safetensors (auto) | No | Default text-to-image |
| `realvis-xl` | RealVisXL V5.0 | 1024×1024 | dpmpp_2m / karras | 25 | 5.0 | None | No | Photorealistic SDXL |
| `flux-faceid` | FLUX.1 Dev FP8 | 1024×1024 | euler / simple | 25 | 1.0 | flux-uncensored + PuLID | Yes (GFPGAN) | **Face-consistent generation** |
| `sdxl-faceid` | RealVisXL V5.0 | 1024×1024 | dpmpp_2m / karras | 25 | 5.0 | IPAdapter FaceID Plus V2 | Yes | SDXL face consistency |
| `face-swap` | — | — | — | — | — | — | Yes (GFPGAN) | ReActor post-process swap |
| `queen-portrait` | (delegates) | 832×1216 | (delegates) | (delegates) | (delegates) | (delegates) | (delegates) | Portrait aspect for queens |
| `queen-scene` | (delegates) | 1344×768 | (delegates) | (delegates) | (delegates) | (delegates) | (delegates) | Cinematic widescreen for scenes |
| `flux-img2img` | FLUX.1 Dev FP8 | from source | euler / simple | 25 | 1.0 | flux-uncensored | No | Image-to-image repaint |
| `realvis-img2img` | RealVisXL V5.0 | from source | dpmpp_2m / karras | 25 | 5.0 | None | No | SDXL img2img |
| `flux-inpaint` | FLUX.1 Dev FP8 | from source | euler / simple | 25 | 1.0 | flux-uncensored | No | Masked inpainting |

**Face-ID Pipeline Detail** (`flux_faceid`):
```
[LoadImage (ref)] → [PuLID EvaClip Loader] → [InsightFace Loader (CUDA)]
        ↓                    ↓                         ↓
[Apply PuLID Flux] ← ── ── ── ── ── ── ── ── ── ── ──┘
        ↓
[CLIP Text Encode (positive)] → [KSampler] → [VAE Decode] → [Face Restore (GFPGAN)]
[CLIP Text Encode (negative)] ──→    ↑                              ↓
                              [Empty Latent]                  [Save Image]
```

- PuLID model: `pulid_flux_v0.9.1.safetensors`
- InsightFace provider: CUDA
- EvaClip: loaded alongside PuLID for feature extraction
- Face restore: `ReActorRestoreFace` with `GFPGANv1.4.pth`, visibility=1.0, bg_upscaler=none
- All FLUX pipelines auto-prepend `flux-uncensored.safetensors` LoRA (strength from request, default 1.0)
- Queen pipelines delegate to `flux-faceid` (if ref images exist) or `flux-uncensored` (if no refs)

### What's Broken — ROOT CAUSES TO FIX

**🔴 CRITICAL: ComfyUI running on wrong GPU**
- WORKSHOP has 2 GPUs — **exact identity of GPU 0 needs verification** (discover.sh says RTX 4090, ComfyUI API reported RTX 5060 Ti, MEMORY.md says 5090 is primary). GPU 1 is RTX 5090 (32GB).
- vLLM-fast (Qwen3-14B) currently occupies one GPU, ComfyUI the other
- ComfyUI reported `cuda:0` as having 16.6GB total / 0.4GB free → face-ID pipeline OOMs
- docker-compose has `NVIDIA_VISIBLE_DEVICES=all` — sees both GPUs, PyTorch takes `cuda:0` which is the smaller GPU
- Result: CUDA OOM / invalid argument errors on face-ID workflow
- **FIX**: First, SSH to WORKSHOP and run `nvidia-smi` to verify exact GPU identities and bus IDs. Then pin ComfyUI to the RTX 5090 (32GB) by setting `NVIDIA_VISIBLE_DEVICES` to the correct device index. Pin vLLM-fast to the other GPU.
- **ALTERNATIVE FIX** (broader scope): Move ComfyUI to FOUNDRY's 4090 (24GB, idle-capable via sleep-swap with coding model). This puts image gen and LLM inference on the same 10GbE node, and the 4090's 24GB + 1,008 GB/s bandwidth is excellent for diffusion. Trade-off: ties up coding model GPU during generation.
- **WHY NOT FALLBACK**: Text-only generation without face-ID produces generic images with no identity consistency. The entire point is face-consistent characters across scenes. Without face-ID, the output is useless.

**🔴 CRITICAL: Fallback code in auto_gen.py must be removed**
- Lines 465-528: `faceid_failed` flag, text-only retry loop
- This was added as a workaround — violates the no-fallback principle
- **FIX**: Remove fallback code. When ComfyUI errors, log the error, mark the drop as `.error` with the error message, and move on. Fix the root cause (GPU assignment) instead.

**🟡 WORKSHOP SSH broken from DEV**
- `ssh shaun@192.168.1.225` → permission denied
- Blocks remote configuration/management of WORKSHOP
- **FIX**: Add DEV's SSH key to WORKSHOP's `authorized_keys`. May need physical access or KVM.

**🟡 Root .env is stale**
- `MEMORY_PORT=8702` → should be `8720`
- `DEV_HOST=changeme` → should be `192.168.1.189`
- `REDIS_PASSWORD=` (empty) → should have the rotated password
- `POSTGRES_PASSWORD=changeme` → should have real password
- `GRAFANA_PORT=3003` → should be `3000`
- References deleted services: `ORCHESTRATOR_PORT=8703`, `AGENT_SERVER_PORT=9000`, `GPU_ORCHESTRATOR_PORT=9200`
- `VLLM_EMBEDDING_HOST=http://192.168.1.244:8001` → should be DEV (192.168.1.189)
- `LETTA_HOST` referenced but Letta not used
- **FIX**: Rewrite entire .env with correct values. Single source of truth.

**🟡 Gateway not restarted after deployments**
- Updated auto_gen.py and scheduler.py deployed to DEV via SCP
- Gateway systemd unit not restarted → changes not active
- **FIX**: `sudo systemctl restart local-system-gateway` on DEV

**🟡 Cloud API keys not on VAULT .env**
- LiteLLM shows "degraded" because Anthropic, OpenAI, DeepSeek, Google keys missing
- Cloud API fallback chains configured in LiteLLM config but keys not populated
- **FIX**: User needs to add keys to VAULT's `/mnt/user/appdata/local-system/vault/.env`

**🟡 Stale ComfyUI queue**
- One job still showing as "running" after clear attempt
- **FIX**: Full ComfyUI restart on WORKSHOP (requires SSH fix first, or physical access)

---

## 5. GPU & Inference Layer

### Current GPU Layout (Verified 2026-03-06)

> ⚠️ **WORKSHOP GPU identities need verification** — see Section 1 hardware inventory for discrepancy details.
> discover.sh shows RTX 4090 + RTX 5090, but .env and MEMORY.md reference RTX 5090 + RTX 5060 Ti.
> Table below uses MEMORY.md values. **First action: `nvidia-smi` on WORKSHOP to resolve.**

| GPU | Node | VRAM | What's Running | Port | Status |
|-----|------|------|---------------|------|--------|
| GPU 0: RTX 5070 Ti | FOUNDRY | 16GB | vllm-reasoning TP0 (Qwen3-32B-AWQ) | 8000 | ✅ Working |
| GPU 1: RTX 5070 Ti | FOUNDRY | 16GB | vllm-reasoning TP1 | — | ✅ Working |
| GPU 2: RTX 4090 | FOUNDRY | 24GB | vllm-coding (GLM-4.7-Flash-GPTQ-4bit) | 8002 | ✅ Working |
| GPU 3: RTX 5070 Ti | FOUNDRY | 16GB | vllm-creative (Huihui-Qwen3-8B-abliterated) | 8004 | ✅ Working |
| GPU 4: RTX 5070 Ti | FOUNDRY | 16GB | SPARE | — | ⚪ Idle |
| GPU 0: ⚠️ unverified | WORKSHOP | ?GB | vllm-fast (Qwen3-14B FP8) | 8000 | ✅ Working |
| GPU 1: ⚠️ unverified | WORKSHOP | ?GB | ComfyUI (face-ID pipeline) | 8188 | 🔴 OOM |
| GPU 0: RTX 5060 Ti | DEV | 16GB | Embedding (0.6B) + Reranker (0.6B) | 8001/8003 | ✅ Working |

### Target GPU Layout (After Verification + Fix)

**Step 0**: SSH to WORKSHOP, run `nvidia-smi`, confirm exact GPU models and bus IDs. Then:

**Goal**: Pin ComfyUI to the larger GPU (5090 32GB or 4090 24GB — whichever is there), pin vLLM-fast to the smaller one.

| GPU | Node | VRAM | What Should Run | Port | Change |
|-----|------|------|----------------|------|--------|
| GPU 0: RTX 5070 Ti | FOUNDRY | 16GB | vllm-reasoning TP0 (Qwen3-32B-AWQ) | 8000 | No change |
| GPU 1: RTX 5070 Ti | FOUNDRY | 16GB | vllm-reasoning TP1 | — | No change |
| GPU 2: RTX 4090 | FOUNDRY | 24GB | vllm-coding (GLM-4.7-Flash-GPTQ-4bit) | 8002 | No change |
| GPU 3: RTX 5070 Ti | FOUNDRY | 16GB | vllm-creative (Huihui-Qwen3-8B-abliterated) | 8004 | No change |
| GPU 4: RTX 5070 Ti | FOUNDRY | 16GB | SPARE (future TP=4 reasoning) | — | No change |
| **WORKSHOP larger GPU** | **WORKSHOP** | **24-32GB** | **ComfyUI** (face-ID pipeline) | **8188** | **🔄 SWAP** |
| **WORKSHOP smaller GPU** | **WORKSHOP** | **16GB** | **vllm-fast** (Qwen3-14B FP8) | **8000** | **🔄 SWAP** |
| GPU 0: RTX 5060 Ti | DEV | 16GB | Embedding + Reranker | 8001/8003 | No change |

**Why this swap works** (regardless of exact GPU identity):
- ComfyUI face-ID pipeline (Flux FP8 + PuLID + InsightFace + LoRA + GFPGAN) needs ~15-16GB → the larger GPU (24 or 32GB) gives headroom
- Qwen3-14B FP8 needs ~14GB → fits on 16GB GPU
- The larger GPU's bandwidth is wasted on a small text model — ComfyUI diffusion actually benefits from it

**Implementation**:
1. SSH to WORKSHOP (requires SSH fix first)
2. Run `nvidia-smi` — record exact GPU models, VRAM, bus IDs. Update this plan + MEMORY.md
3. Stop both containers
4. Change ComfyUI docker-compose: `NVIDIA_VISIBLE_DEVICES=<larger GPU index>`
5. Change vLLM-fast: `NVIDIA_VISIBLE_DEVICES=<smaller GPU index>`, reduce `--gpu-memory-utilization` to 0.85
6. Restart both
7. Verify via `nvidia-smi` and test face-ID generation

### LiteLLM Model Routing (VAULT:4000)

13 model aliases route to the correct GPU:

| Alias | Model | Where | Use Case |
|-------|-------|-------|----------|
| `reasoning` | Qwen3-32B-AWQ | FOUNDRY:8000 | General reasoning, complex tasks |
| `coding` | GLM-4.7-Flash-GPTQ-4bit | FOUNDRY:8002 | Code generation, debugging |
| `creative` | Huihui-Qwen3-8B-abliterated | FOUNDRY:8004 | Uncensored prompts, creative writing |
| `fast` | Qwen3-14B FP8 | WORKSHOP:8000 | Quick responses, drafting |
| `embedding` | Qwen3-Embedding-0.6B | DEV:8001 | Text embeddings |
| `reranker` | Qwen3-Reranker-0.6B | DEV:8003 | Search reranking |
| `claude` | Claude Sonnet 4 | Anthropic API | Cloud (needs key) |
| `gpt` | GPT-4.1 | OpenAI API | Cloud (needs key) |
| `deepseek` | DeepSeek V3 | DeepSeek API | Cloud (needs key) |
| `gemini` | Gemini 2.5 Pro | Google API | Cloud (needs key) |

### LiteLLM Configuration Detail (`deploy/vault/litellm/config.yaml`)

**Routing Strategy**: `simple-shuffle` (round-robin across available models in a group)
- Retry policy: 2 retries on failure
- Timeout: 120 seconds per request
- `drop_params: true` — silently drops unsupported params instead of erroring

**Fallback Chains**:
```
reasoning  → [deepseek, claude]    (if local Qwen3-32B fails, try cloud)
coding     → [deepseek, claude]    (if local GLM-4 fails, try cloud)
fast       → [deepseek]            (if local Qwen3-14B fails, try cloud)
```

**Model Group Config**:

| Alias | Provider | API Base | Model Path | Notes |
|-------|----------|----------|-----------|-------|
| `reasoning` | hosted_vllm | FOUNDRY:8000/v1 | Qwen/Qwen3-32B-AWQ | api_key: "not-needed" |
| `coding` | hosted_vllm | FOUNDRY:8002/v1 | THUDM/GLM-4.7-Flash-GPTQ-4bit | api_key: "not-needed" |
| `creative` | hosted_vllm | FOUNDRY:8004/v1 | huihui-ai/Qwen3-8B-abliterated-v2 | api_key: "not-needed" |
| `fast` | hosted_vllm | WORKSHOP:8000/v1 | Qwen/Qwen3-14B | api_key: "not-needed" |
| `embedding` | hosted_vllm | DEV:8001/v1 | Qwen/Qwen3-Embedding-0.6B | api_key: "not-needed" |
| `reranker` | hosted_vllm | DEV:8003/v1 | Qwen/Qwen3-Reranker-0.6B | api_key: "not-needed" |
| `claude` | anthropic | — | claude-sonnet-4-20250514 | api_key from env ANTHROPIC_API_KEY |
| `gpt` | openai | — | gpt-4.1 | api_key from env OPENAI_API_KEY |
| `deepseek` | deepseek | — | deepseek/deepseek-chat | api_key from env DEEPSEEK_API_KEY |
| `gemini` | gemini | — | gemini/gemini-2.5-pro-preview-06-05 | api_key from env GEMINI_API_KEY |
| `gpt-4` | (alias) | — | → reasoning | Compatibility redirect |
| `gpt-3.5-turbo` | (alias) | — | → fast | Compatibility redirect |
| `text-embedding-ada-002` | (alias) | — | → embedding | Compatibility redirect |

**Health Checks**: Background health checks every 300s. Master key from `LITELLM_MASTER_KEY` env.
**Metrics**: `success_callback: ["prometheus"]`, `service_callback: ["prometheus_system"]`

### vLLM Container Parameters (per GPU)

**FOUNDRY containers** (`deploy/foundry/docker-compose.yml`):

| Parameter | vllm-reasoning | vllm-coding | vllm-creative |
|-----------|---------------|-------------|---------------|
| Image | `athanor/vllm:custom` | `athanor/vllm:v2` | `athanor/vllm:v2` |
| GPU(s) | 0,1 (TP=2) | 2 | 3 |
| Model | Qwen3-32B-AWQ | GLM-4.7-Flash-GPTQ-4bit | Qwen3-8B-abliterated-v2 |
| Quantization | `--quantization awq` | `--quantization gptq_marlin` | `--quantization fp8` |
| Dtype | (default) | `--dtype float16` | `--dtype float16` |
| Max model len | 8192 | 8192 | 32768 |
| GPU mem util | 0.85 | 0.92 | 0.90 |
| Max sequences | 32 | 8 | 8 |
| Tool calling | `--tool-call-parser hermes` | `--tool-call-parser hermes` | — |
| Swap space | 16 GB | 8 GB | 4 GB |
| Prefix caching | `--enable-prefix-caching` | — | — |
| KV cache dtype | `--kv-cache-dtype fp8_e5m2` | — | — |
| Sleep mode | — | `--scheduling-policy sleep` | `--scheduling-policy sleep` |
| Enforce eager | `--enforce-eager` | — | — |
| Trust remote | — | `--trust-remote-code` | `--trust-remote-code` |
| Network mode | host | host | host |
| IPC | host | host | host |
| Runtime | nvidia | nvidia | nvidia |
| Model source | NFS `/mnt/vault/models` | NFS `/mnt/vault/models` | NFS `/mnt/vault/models` |

**WORKSHOP** — vLLM-fast runs as **systemd** (not Docker):
- Model: Qwen3-14B FP8
- Port: 8000
- GPU: whichever GPU ComfyUI is NOT on (currently wrong — see Section 4 bugs)

**DEV containers** (Docker):
- vllm-embedding: Qwen3-Embedding-0.6B, port 8001, RTX 5060 Ti
- vllm-reranker: Qwen3-Reranker-0.6B, port 8003, RTX 5060 Ti (shared GPU)

### Future Model Upgrades (Blocked — See ADR-001)

Qwen3.5-122B-A10B upgrade requires `--language-model-only` flag which doesn't exist in vLLM 0.16.0. FP8 KV cache only works on `athanor/vllm:custom` image. Waiting for:
- vLLM to add `--language-model-only` flag, OR
- Qwen to release text-only Qwen3.5 variants

---

## 6. Memory System (6 Tiers)

All tiers operational as of 2026-03-06:

| Tier | Backend | Count | Purpose | TTL |
|------|---------|-------|---------|-----|
| **Working** | Redis | Ephemeral | Active conversation context, scratch space | Session |
| **Episodic** | Qdrant `episodic` | 6 | Timestamped events, session logs | Permanent |
| **Semantic** | Neo4j | 3,241 nodes | Knowledge graph, entity relationships | Permanent |
| **Procedural** | PostgreSQL | 10 | How-to procedures (restart, deploy, troubleshoot) | Permanent |
| **Resource** | Qdrant `resources` + Meilisearch | 347 | Ingested documents, codebase chunks | Permanent |
| **Vault** | PostgreSQL + Qdrant `knowledge_vault` | 40 | Long-term archive, important decisions | Permanent |

**Search**: Cross-tier deep search embeds query → searches tiers in parallel → reranks combined results.

**Consolidation**: Daily 3am cron — Working→Episodic (session summaries), Episodic→Vault (important events).

**Ingestion**: Perception service watches directories and ingests new docs → chunks → embeds → indexes into Resource tier.

---

## 7. Infrastructure

### Monitoring Stack (VAULT)

| Component | Port | Purpose |
|-----------|------|---------|
| Prometheus | :9090 | Metrics collection, 17/17 targets UP |
| Grafana | :3000 | Dashboards (5 dashboards), `localadmin` password |
| DCGM Exporter | FOUNDRY:9400, WORKSHOP:9400 | GPU metrics |
| Node Exporter | all:9100 | System metrics |
| cAdvisor | VAULT:9880 | Docker container metrics |

### Prometheus Scrape Targets (17 targets, 13 jobs)

All targets verified UP as of 2026-03-06. Config: `deploy/vault/prometheus/prometheus.yml`

| Job | Target | Port | Metrics Path | Scrape Interval |
|-----|--------|------|-------------|-----------------|
| `node-foundry` | FOUNDRY:9100 | 9100 | /metrics | 15s |
| `node-workshop` | WORKSHOP:9100 | 9100 | /metrics | 15s |
| `node-dev` | DEV:9100 | 9100 | /metrics | 15s |
| `node-vault` | VAULT:9100 | 9100 | /metrics | 15s |
| `dcgm-foundry` | FOUNDRY:9400 | 9400 | /metrics | 15s |
| `dcgm-workshop` | WORKSHOP:9400 | 9400 | /metrics | 15s |
| `gateway` | DEV:8700 | 8700 | /metrics | 15s |
| `memory` | DEV:8720 | 8720 | /metrics | 15s |
| `mind` | DEV:8710 | 8710 | /metrics | 15s |
| `perception` | DEV:8730 | 8730 | /metrics | 15s |
| `litellm` | VAULT:4000 | 4000 | /metrics/ | 15s (**trailing slash required — 307 redirect without it**) |
| `vllm-reasoning` | FOUNDRY:8000 | 8000 | /metrics | 15s |
| `vllm-coding` | FOUNDRY:8002 | 8002 | /metrics | 15s |
| `vllm-creative` | FOUNDRY:8004 | 8004 | /metrics | 15s |
| `vllm-fast` | WORKSHOP:8000 | 8000 | /metrics | 15s |
| `vllm-embedding` | DEV:8001 | 8001 | /metrics | 15s |
| `cadvisor` | VAULT:9880 | 9880 | /metrics | 15s |

Note: Qdrant (VAULT:6333) is also scraped but configured separately.

### Application Metrics (`shared/python/local_system/metrics.py`)

12 custom Prometheus metrics exposed by all services:

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `ls_request_total` | Counter | service, method, endpoint, status | HTTP request count |
| `ls_request_duration_seconds` | Histogram | service, endpoint | Request latency (buckets: 0.01→120s) |
| `ls_llm_calls_total` | Counter | service, model, status | LLM API call count |
| `ls_llm_duration_seconds` | Histogram | service, model | LLM inference latency (buckets: 0.5→120s) |
| `ls_llm_tokens_total` | Counter | service, model, direction | Token usage (direction: prompt/completion) |
| `ls_tool_calls_total` | Counter | service, tool, status | Tool invocation count |
| `ls_tool_duration_seconds` | Histogram | service, tool | Tool execution latency (buckets: 0.01→30s) |
| `ls_memory_ops_total` | Counter | tier, operation, status | Memory tier operations |
| `ls_memory_search_duration_seconds` | Histogram | tier | Memory search latency (buckets: 0.01→5s) |
| `ls_active_conversations` | Gauge | service | Currently active conversations |
| `ls_workspace_switches_total` | Counter | workspace | Workspace activation count |
| `ls_service_info` | Gauge | service, version, node | Service metadata (set to 1) |

### Event Bus (`shared/python/local_system/events.py`)

Redis Streams-based async event bus for inter-service communication:

| Property | Value |
|----------|-------|
| Transport | Redis Streams (XADD/XREAD/XREVRANGE) |
| Channel naming | `ls:events.{domain}.{action}` (e.g., `ls:events.mind.response`, `ls:events.memory.stored`) |
| Max stream length | 10,000 entries per channel (auto-trimmed) |
| Event schema | `{id, type, source, timestamp, data}` (data is JSON-serialized) |
| Consumer groups | Per-service isolation — each service reads independently |
| Blocking read | `XREAD BLOCK` for real-time event consumption |
| Publish method | `EventBus.publish(channel, event_type, data)` |
| Read latest | `EventBus.read_latest(channel, count)` → most recent N events |
| Subscribe | `EventBus.subscribe(channel, callback)` → blocking consumer loop |

**Known Event Channels**:
- `mind.response` → emitted after MIND reasoning loop completes (step 8: REMEMBER)
- `memory.stored` → emitted when any memory tier stores new content
- `generation.complete` → emitted when ComfyUI generation finishes

### Backups (VAULT cron)

| What | When | Retention | Where |
|------|------|-----------|-------|
| PostgreSQL | Daily 1:30am | 14 days | `/mnt/user/data/backups/postgres/` |
| Neo4j | Weekly Sun 2am | 30 days | `/mnt/user/data/backups/neo4j/` |
| Qdrant | Weekly Wed 2am | 30 days | `/mnt/user/data/backups/qdrant/` |

### Daily Maintenance (DEV cron, 3am)

- Memory consolidation (Working→Episodic→Vault)
- Daily brief generation
- Disk space check
- Service health check

### Media Processing (VAULT)

- **Tdarr** (:8265): H.265 QSV transcoding via Intel ARC A380
- Flow: Input→CheckStream→BeginCmd→SetEncoder(hevc_qsv)→Execute→ReplaceOriginal
- ~500 FPS encode speed
- Movies + TV libraries configured

### Notifications (VAULT)

- **ntfy** (:8880): Push notifications to phone/desktop
- Topics: generation-complete, daily-brief, service-alerts
- Supports image attachments (generation previews)

### Docker Layout

| Node | Docker? | Containers |
|------|---------|------------|
| FOUNDRY | Yes | 3 vLLM + 2 exporters = 5 |
| WORKSHOP | Yes | ComfyUI + 2 exporters = 3 |
| VAULT | Yes | 5 databases + LiteLLM + Prometheus + Grafana + n8n + ntfy + tdarr_server + tdarr_node + node-exporter + cAdvisor + minio ≈ 15 |
| DEV | No Docker | 5 systemd services (uvicorn direct) + 2 vLLM (embed/rerank) |

---

## 8. Codebase Structure

```
Local-System/
├── .env                          ← 🟡 STALE — needs full rewrite
├── .env.example                  ← Template with all vars
├── .mcp.json                     ← MCP server config (Claude Code, Kimi Code)
├── shared/python/local_system/   ← Shared library (pip install -e)
│   ├── config.py                 ← get_settings(), all config classes
│   ├── models.py                 ← Pydantic models (ChatRequest, QueenProfile, etc.)
│   ├── utils.py                  ← generate_id(), setup_logging(), Timer
│   ├── events.py                 ← Redis Streams event bus
│   └── metrics.py                ← Prometheus metrics helpers
├── services/
│   ├── gateway/                  ← API Gateway :8700
│   │   ├── main.py               ← FastAPI app, lifespan, CORS
│   │   ├── auto_gen.py           ← Autonomous generation engine
│   │   ├── scheduler.py          ← Generation scheduler (25 themes)
│   │   ├── scene_builder.py      ← Queen DNA → Flux prompts
│   │   ├── dna_engine.py         ← 19-trait DNA → prompt modifiers
│   │   ├── pipelines.py          ← 10 ComfyUI pipeline presets
│   │   └── routers/              ← Route handlers
│   │       ├── chat.py, generate.py, queens.py, health.py
│   │       ├── memory.py, tasks.py, workspaces.py
│   │       └── __init__.py
│   ├── mind/                     ← MIND Service :8710
│   │   ├── main.py               ← FastAPI app
│   │   ├── reasoning.py          ← 8-step reasoning loop
│   │   ├── router.py             ← Capability routing
│   │   ├── tools.py              ← Tool registry
│   │   ├── workspace_manager.py  ← 10 workspaces
│   │   ├── brief.py              ← Daily brief generation
│   │   ├── db.py                 ← PG persistence
│   │   └── events.py             ← Redis event bus
│   ├── memory/                   ← Memory Service :8720
│   │   ├── main.py               ← FastAPI app, tier routing
│   │   ├── search.py             ← Cross-tier deep search
│   │   ├── consolidation.py      ← Tier promotion/demotion
│   │   └── tiers/                ← Per-tier implementations
│   │       ├── working.py, episodic.py, semantic.py
│   │       ├── procedural.py, resource.py, vault.py
│   │       └── __init__.py
│   ├── perception/               ← Perception Service :8730
│   │   ├── main.py               ← FastAPI app, directory watchers
│   │   └── chunkers.py           ← Text/code/markdown splitting
│   └── mcp-servers/              ← 7 MCP servers (54 tools)
│       ├── ls-memory/server.py   ← 21 tools
│       ├── ls-inference/server.py← 5 tools
│       ├── ls-knowledge/server.py← 5 tools
│       ├── ls-workspace/server.py← 5 tools
│       ├── ls-infra/server.py    ← 5 tools
│       ├── ls-creative/server.py ← 8 tools
│       └── ls-tools/server.py    ← 5 tools
├── deploy/
│   ├── foundry/docker-compose.yml← 3 vLLM + 2 exporters
│   ├── workshop/docker-compose.yml← ComfyUI + 2 exporters
│   ├── vault/
│   │   ├── docker-compose.yml    ← All databases + services + monitoring
│   │   ├── litellm/config.yaml   ← 13 model aliases
│   │   ├── prometheus/           ← Prometheus config + rules
│   │   └── grafana/              ← Dashboard provisioning
│   └── dev/                      ← Systemd unit files
├── ui/                           ← Next.js 15.1 Command Center
│   └── src/app/                  ← 7 pages (chat, generate, models, memory, agents, documents, nodes)
├── scripts/                      ← Operational scripts
│   ├── discover.sh               ← Node discovery
│   └── daily-maintenance.sh      ← 3am cron
├── docs/
│   ├── adr/001-qwen35-vision-encoder.md ← Architecture Decision Record
│   └── soar-playbook.md          ← COO operating protocol
└── eobq/                         ← Empire of Beauty Queens game data
    └── master-doc.md             ← 21 queens, DNA, scenes
```

### 8.1 Shared Library Internals (`shared/python/local_system/`)

Installed via `pip install -e shared/python` on all nodes. Provides config, models, events, metrics, utilities.

**Config Classes** (`config.py` — 10 Pydantic BaseSettings classes):

| Class | Key Fields | Env Prefix |
|-------|-----------|-----------|
| `NodeName` (enum) | FOUNDRY, WORKSHOP, VAULT, DEV, DESK, MOBILE | — |
| `NodeRole` (enum) | INFERENCE, CREATIVE, VAULT_NODE, OPERATIONS, CLIENT | — |
| `NodeConfig` | name (default DEV), role (default OPERATIONS) | `NODE_` |
| `NetworkConfig` | foundry=192.168.1.244, workshop=.225, vault=.203, dev=.189 | `FOUNDRY_HOST`, `WORKSHOP_HOST`, etc. |
| `ServicePorts` | gateway=8700, memory=8720, mind=8710, perception=8730, ui=3001, litellm=4000, vllm_reasoning=8000, vllm_coding=8002, vllm_creative=8004, vllm_fast=8000, vllm_embed=8001, vllm_rerank=8003 | — |
| `InferenceConfig` | litellm_host (VAULT:4000), litellm_key, 5 vLLM URLs | `LITELLM_`, `VLLM_` |
| `DatabaseConfig` | host (VAULT), port=5432, name=local_system, user, password | `POSTGRES_` |
| `RedisConfig` | host (VAULT), port=6379, password | `REDIS_` |
| `QdrantConfig` | host (VAULT), port=6333, grpc_port=6334 | `QDRANT_` |
| `Neo4jConfig` | host (VAULT), http=7474, bolt=7687, user=neo4j, password | `NEO4J_` |
| `RAGConfig` | embedding_model, dimensions=1024, chunk_size=512, overlap=64, hybrid_alpha=0.7 | — |
| `MeilisearchConfig` | host (VAULT), port=7700, key | `MEILISEARCH_` |
| `Settings` | Aggregates ALL above + log_level, log_format, api_secret_key | — |

`get_settings()`: LRU-cached singleton — instantiated once, shared across all imports.

**Pydantic Data Models** (`models.py` — 30+ models, 6 categories):

*Chat/Inference*:
- `Role` enum: system, user, assistant, tool
- `Message`: role, content, name?, tool_call_id?, tool_calls?
- `ToolCall`: id, name, arguments (dict)
- `ToolDefinition`: name, description, parameters (JSON Schema)
- `ChatRequest`: model="auto", messages, temperature=0.7, max_tokens=4096, stream=False, tools?, metadata
- `ChatResponse`: id, model, message, usage, created_at
- `TokenUsage`: prompt_tokens, completion_tokens, total_tokens
- `StreamChunk`: id, model, delta, finish_reason?

*Memory (6-Tier)*:
- `MemoryTier` enum: procedural, working, episodic, semantic, resource, vault
- `MemoryEntry`: id, tier, content, metadata, source, confidence=1.0, created_at, accessed_at?, expires_at?, embedding?, tags
- `WorkingContext`: active_task?, recent_messages, active_priorities, unresolved_questions, session_start
- `EpisodicEvent`: id, event_type (conversation/task_outcome/discovery/error/feedback), summary, details, participants, outcome?, timestamp, embedding?
- `SemanticEntity`: id, name, entity_type (person/project/concept/service/hardware), properties, valid_from?, valid_until?
- `SemanticRelation`: source_id, target_id, relation_type (uses/depends_on/created_by/part_of), properties, confidence=1.0
- `MemorySearchRequest`: query, tiers?, top_k=10, score_threshold=0.0, time_range_start?, time_range_end?
- `MemorySearchResponse`: results, query, total

*Cognitive Workspace (GWT)*:
- `SpecialistType` enum: research, coding, creative, building_science, media, infrastructure, general
- `BidRequest`: specialist, relevance_score (0-1), reasoning, proposed_action, estimated_tokens
- `BroadcastMessage`: source_specialist, content, context, timestamp
- `CognitiveState`: active_specialist?, attention_focus, working_context, recent_broadcasts, cycle_count

*Agents/Orchestration*:
- `AgentConfig`: name, specialist, system_prompt, model="auto", tools, max_iterations=10, temperature=0.7, memory_enabled=True
- `AgentState` enum: idle, thinking, executing_tool, waiting, completed, error
- `TaskStatus` enum: pending, running, completed, failed, cancelled
- `Task`: id, agent_id?, specialist, description, status, result?, error?, memory_context, created_at, completed_at?

*RAG/Documents*:
- `Document`: id, source, content, metadata, embedding?, chunk_index, created_at
- `SearchResult`: document, score, source (vector/bm25/hybrid), highlights
- `SearchRequest`: query, collection="default", top_k=10, score_threshold=0.0, use_hybrid=True, alpha=0.7, filters
- `SearchResponse`: results, query, total

*System/Node*:
- `NodeStatus`: name, role, online, uptime, cpu%, ram_used/total, gpu_info, disk_used/total, services
- `GPUInfo`: index, name, vram_used/total, utilization%, temperature, power_draw
- `ServiceStatus`: name, running, port, uptime, healthy
- `HealthResponse`: status="ok", service, version, node, uptime
- `ModelBackend` enum: tabby, ollama, litellm
- `ModelInfo`: id, name, backend, size_bytes, parameter_count, quantization, context_length, loaded, node, vram_usage

*Generation/EoBQ*:
- `GenerateImageRequest`: prompt, negative_prompt, pipeline="flux-uncensored", width/height=1024, steps=25, cfg=3.5, seed=-1, lora_name?, lora_strength=1.0, batch_size=1
- `GenerateFaceRequest`: prompt, negative_prompt, pipeline="flux-faceid", reference_image, identity_strength=1.0, width/height/steps/cfg/seed
- `Img2ImgRequest`: prompt, source_image, denoise_strength=0.6, pipeline="flux-img2img", restore_face=False
- `InpaintRequest`: prompt, source_image, mask_image, denoise_strength=0.8
- `FaceSwapRequest`: source_image, face_image, restore_face=True
- `TrainLoraRequest`: trigger_word, model_type="sdxl", dataset_path?, epochs=20, network_dim=64
- `GenerateImageResponse`: prompt_id, client_id
- `GenerationStatus`: active_service, queue_running/pending, gpu_vram_used/total
- `QueenDNA`: 19 integer traits (all default 5): dominance, submission, exhibitionism, voyeurism, nurturing, corruption, possessiveness, devotion, playfulness, intensity, ritualism, spontaneity, emotional_openness, guardedness, sensory_focus, intellectual_arousal, power_exchange, intimacy_threshold, taboo_comfort
- `QueenScene`: title, description, flux_prompt
- `QueenProfile`: id, name, performer_ref, physical_blueprint, dna, flux_portrait_prompt, scenes, lora_name?, reference_images
- `QueenGenerateRequest`: queen_id, mode="portrait" (832×1216) or "scene" (1344×768), scene_index?, prompt_override?, identity_strength=1.0, seed=-1
- `PerformerInfo`: name, rating (1-10), gen_ready (1-5), height?, bust?, implants?, body_type?, ethnicity?, nationality?, career_start/end?, is_favorite, reference_count

---

## 9. Broader Scope Observations

Things where the current approach may be scoped too narrow, or where a better solution exists outside the current framing.

### 9.1 DEV is a bottleneck — both network and compute

DEV currently runs **all 5 services + 2 vLLM containers** on a 12C/24T CPU with 60GB RAM over **1GbE**. Every request from DESK → DEV → VAULT/FOUNDRY/WORKSHOP traverses 1GbE twice (in and back). For API JSON this is fine today, but:

- **Fix now**: Install a spare 10GbE card in DEV. It's the central services hub — every user action flows through it. The 3 spare cards are sitting unused.
- **Future consideration**: If service load grows, Gateway/MIND could move to VAULT (128GB RAM, 16C/32T, 10GbE native) and talk to databases on localhost instead of over the network. DEV becomes a dev/build machine rather than the production services host. No urgency — current load is fine — but the architecture shouldn't assume DEV is the permanent services host.

### 9.2 FOUNDRY GPU 4 is wasted

An idle RTX 5070 Ti 16GB is doing nothing. Options:
- **TP=3 reasoning** (GPU 0,1,4): Run a larger reasoning model (Qwen3-32B FP16 instead of AWQ, or a future 70B at 4-bit). The 3 GPUs are on separate root complexes, making TP clean.
- **Second creative model**: Run a larger uncensored model for better prompt generation quality.
- **Dedicated ComfyUI**: Move ComfyUI to FOUNDRY GPU 4 instead of WORKSHOP. Keeps image gen on the same node as creative LLM (GPU 3), eliminates cross-node latency for prompt→generate loops. Trade-off: only 16GB vs WORKSHOP's 24-32GB, so face-ID pipeline would be tight.
- **Batch inference**: Queue heavy batch jobs (document re-embedding, knowledge graph extraction) without affecting interactive inference.

### 9.3 ComfyUI could live on FOUNDRY instead of WORKSHOP

Currently: Gateway (DEV) → vLLM-creative (FOUNDRY:8004) for prompts → ComfyUI (WORKSHOP:8188) for generation. That's 3 nodes involved.

If ComfyUI moved to FOUNDRY's 4090 (24GB):
- Prompt gen (GPU 3) and image gen (GPU 2) on the same box — eliminates network hop
- 4090 has 24GB VRAM + 1,008 GB/s bandwidth — excellent for diffusion
- Trade-off: vllm-coding loses its GPU during generation. Could use a scheduling system (sleep coding container → wake ComfyUI → generate → sleep ComfyUI → wake coding), or move coding to GPU 4 permanently and dedicate GPU 2 to ComfyUI.
- This is worth considering **after** the WORKSHOP GPU fix is tried — if WORKSHOP's larger GPU gives reliable face-ID, no need to move.

### 9.4 Content viewing needs to be zero-friction

The user drops photos and gets content back. Viewing that content should be equally effortless:
- **Gallery page** exists as a route but has no HTML deployed — this should be a scrollable grid, auto-refreshing, accessible from phone/tablet/desktop. Not a developer tool — a consumer experience.
- **ntfy push with thumbnails**: Already configured. After generation completes, push a notification with a preview thumbnail. User taps → opens gallery on phone.
- **File explorer fallback**: `\\VAULT\data\gen-output\` already works from Windows. But scrolling through folders isn't the same as a curated gallery experience.
- **Longer term**: The UI's Generate page should become the primary content browser — filter by queen, sort by date, slideshow mode, favorites. This is where the system moves from "infrastructure project" to "product I use every day."

### 9.5 This plan IS the permanent system index

The user asked: "How can we best map out this full detail of all of it in a way that we can use as a permanent index of literally everything."

**This document is that index.** It should be:
- Kept in the repo at `docs/system-architecture.md` (not just in `.claude/plans/`)
- Updated whenever hardware changes, services move, or GPUs are reassigned
- Referenced by MEMORY.md (which stays concise) as the deep-dive source
- Ingested into the Resource memory tier so the system's own AI can answer questions about itself
- Machine-readable enough that a future `discover.sh` run could validate it against reality

After plan approval, we should:
1. Copy this document to `docs/system-architecture.md`
2. Ingest it via Perception into the Resource memory tier
3. Add a link from MEMORY.md: "Full system architecture: see `docs/system-architecture.md`"

### 9.6 WORKSHOP access is a single point of failure

WORKSHOP SSH is broken. If ComfyUI OOMs, if vLLM-fast crashes, if a GPU needs resetting — there's no remote path in. This isn't just a convenience issue, it's an operational gap.

Beyond fixing SSH keys:
- **Configure remote management**: If WORKSHOP has IPMI/BMC (Gigabyte TRX50 may have BIOS-level management), set it up
- **Web-based terminal**: Consider Cockpit, Portainer agent, or similar — gives a browser-based terminal from any LAN device
- **Monitoring alerts**: DCGM exporter + Prometheus already scrapes WORKSHOP:9400. Set up Grafana alerts for GPU memory > 90%, container restarts, service down — so you know something's wrong even without SSH

---

## 10. Implementation Sequence — What To Do Next

### Priority 1: Fix Generation Pipeline (1-2 sessions)

This is the active focus. Everything else works — generation is broken.

**Step 1: Fix WORKSHOP SSH** (prerequisite for everything on WORKSHOP)
- Option A: Physical access — add DEV's SSH pubkey to WORKSHOP `~/.ssh/authorized_keys`
- Option B: JetKVM if WORKSHOP has one configured
- Option C: If WORKSHOP has a web-based management interface
- Verify: `ssh shaun@192.168.1.225 nvidia-smi`

**Step 2: Swap GPU assignments on WORKSHOP**
```bash
# On WORKSHOP:
docker compose down  # stop both containers

# Edit docker-compose.yml:
# ComfyUI: NVIDIA_VISIBLE_DEVICES=0  (5090, 32GB)
# vLLM-fast: NVIDIA_VISIBLE_DEVICES=1  (5060 Ti, 16GB)

docker compose up -d
nvidia-smi  # verify correct assignment
```

**Step 3: Remove fallback code from auto_gen.py**
- Remove `faceid_failed` flag (line 465)
- Remove text-only retry block (lines 470-471, 497-528)
- Keep error detection in `_wait_for_result()` — errors should be logged and the drop marked `.error`
- When ComfyUI returns an error: mark drop as `.error` with error details, move to next drop. Don't retry with degraded pipeline.

**Step 4: Fix root .env**
- Rewrite with all correct values (ports, passwords, hosts, remove dead references)

**Step 5: Restart gateway on DEV**
```bash
sudo systemctl restart local-system-gateway
```

**Step 6: Test end-to-end**
1. Drop a test set of photos into `\\VAULT\data\gen-drops\test-person\`
2. Watch gateway logs: `journalctl -u local-system-gateway -f`
3. Verify: Scanner detects → refs selected → LLM generates prompts → ComfyUI face-ID pipeline runs on 5090 → images saved to gen-output → manifest written → .done marker created
4. Check gen-output for quality — face identity should be consistent across all generated images

### Priority 2: Housekeeping (same session or next)

- **Cloud API keys**: User adds Anthropic, OpenAI, DeepSeek, Google keys to VAULT `.env`
- **Clear ComfyUI stuck job**: After WORKSHOP SSH is fixed, restart ComfyUI container
- **Verify scheduler**: After gateway restart, check that gen_scheduler is creating drops on schedule

### Priority 3: Content Viewing (next session)

The user needs a convenient way to see generated content:
- **Gallery page** (`/gallery`): Already has a route in gateway. Needs the static HTML built to browse gen-output
- **UI Generate page**: Already exists at `/generate` in Next.js. May need enhancement to show auto-gen results
- **Mobile-friendly**: ntfy push notifications with image thumbnails for instant preview on phone

### Priority 4: Model Upgrades (when blockers clear)

- Qwen3.5-122B-A10B: Waiting for vLLM `--language-model-only` or text-only model release
- Bigger creative model: When 5090 is freed from ComfyUI time-sharing, consider larger abliterated models
- All tracked in ADR-001

### Priority 5: Ongoing

- Memory consolidation runs daily (automated)
- Monitoring via Grafana (automated)
- Perception watchers ingesting new docs (automated)
- Generation scheduler creating drops (automated)

---

## 11. Key Files to Modify (Next Session)

| File | Change | Priority |
|------|--------|----------|
| `deploy/workshop/docker-compose.yml` | Swap GPU assignments: ComfyUI→5090, vLLM-fast→5060Ti | P1 |
| `services/gateway/auto_gen.py` | Remove fallback code (lines 465-528). Keep error detection. | P1 |
| `.env` | Full rewrite — correct ports, passwords, hosts. Remove dead refs | P1 |
| `services/gateway/auto_gen.py` (restart) | `sudo systemctl restart local-system-gateway` on DEV | P1 |

---

## 12. Completed Phases (Reference)

| Phase | Status | What Was Done |
|-------|--------|---------------|
| 0: Stabilization | ✅ | LiteLLM auth, RAG URLs, config defaults, .env template |
| 1: Service Consolidation | ✅ | 4-service architecture, routers extracted, RAG merged into Memory |
| 2: MCP Platform | ✅ | 7 servers, 54 tools, .mcp.json, tool interchangeability |
| 3: Model Intelligence | ⚠️ Partial | FP8 KV + prefix caching done. Qwen3.5 blocked. Cloud keys not on VAULT |
| 4: Memory Pipeline | ✅ | 6 tiers, Perception service, day-one ingestion, procedural seed |
| 5: MIND Service | ✅ | Reasoning engine, router, tools, workspace mgr, daily brief |
| 6: Workspaces | ✅ | 10 workspaces configured in MIND |
| 7: Self-improvement | ⚠️ Partial | Prometheus+Grafana done, crons done, daily brief done |
