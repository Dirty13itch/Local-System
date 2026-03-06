"""Seed procedural memory with operational procedures."""
import httpx

MEMORY = "http://localhost:8720"
client = httpx.Client(timeout=30.0)

procedures = [
    {
        "tier": "procedural",
        "content": "Restart a DEV service (gateway, mind, memory, perception, ui). All services run as systemd user units on DEV (192.168.1.189).",
        "source": "ops/day-one-seed",
        "confidence": 1.0,
        "tags": ["operations", "restart", "systemd", "dev"],
        "metadata": {
            "task_type": "service-restart",
            "title": "Restart DEV Services (systemd)",
            "steps": [
                "SSH to DEV: ssh shaun@192.168.1.189",
                "Check status: systemctl --user status local-system-{service}",
                "Restart: systemctl --user restart local-system-{service}",
                "Verify: curl -s http://localhost:{port}/health",
                "Ports: gateway=8700, mind=8710, memory=8720, perception=8730, ui=3001",
            ],
            "prerequisites": ["SSH access to DEV"],
        },
    },
    {
        "tier": "procedural",
        "content": "Restart a vLLM container on FOUNDRY. Containers run via Docker on FOUNDRY (192.168.1.244, SSH user: athanor).",
        "source": "ops/day-one-seed",
        "confidence": 1.0,
        "tags": ["operations", "restart", "docker", "foundry", "vllm"],
        "metadata": {
            "task_type": "container-restart",
            "title": "Restart vLLM Containers on FOUNDRY",
            "steps": [
                "SSH via DEV: ssh shaun@192.168.1.189, then ssh athanor@192.168.1.244",
                "Check container: docker ps | grep vllm",
                "Restart: docker restart vllm-{name}",
                "Verify: curl -s http://192.168.1.244:{port}/v1/models",
                "Containers: vllm-reasoning (:8000), vllm-coding (:8002), vllm-creative (:8004)",
                "Check GPU: nvidia-smi",
            ],
            "prerequisites": ["SSH access to DEV then FOUNDRY"],
        },
    },
    {
        "tier": "procedural",
        "content": "Check cluster health across all nodes. Quick verification of all services, containers, and GPUs.",
        "source": "ops/day-one-seed",
        "confidence": 1.0,
        "tags": ["operations", "health-check", "monitoring"],
        "metadata": {
            "task_type": "health-check",
            "title": "Full Cluster Health Check",
            "steps": [
                "Gateway: curl http://192.168.1.189:8700/health",
                "Cluster: curl http://192.168.1.189:8700/health/cluster",
                "Memory: curl http://192.168.1.189:8720/health",
                "Stats: curl http://192.168.1.189:8720/v1/memory/stats",
                "MIND: curl http://192.168.1.189:8710/health",
                "Perception: curl http://192.168.1.189:8730/health",
                "LiteLLM: curl -H Auth http://192.168.1.203:4000/v1/models",
                "vLLM reasoning: curl http://192.168.1.244:8000/v1/models",
                "vLLM coding: curl http://192.168.1.244:8002/v1/models",
                "vLLM creative: curl http://192.168.1.244:8004/v1/models",
                "vLLM fast: curl http://192.168.1.225:8000/v1/models",
            ],
            "prerequisites": [],
        },
    },
    {
        "tier": "procedural",
        "content": "Deploy a new model on FOUNDRY using vLLM Docker containers.",
        "source": "ops/day-one-seed",
        "confidence": 1.0,
        "tags": ["operations", "deployment", "model", "vllm"],
        "metadata": {
            "task_type": "model-deployment",
            "title": "Deploy New Model on FOUNDRY",
            "steps": [
                "Check GPUs: ssh athanor@192.168.1.244 nvidia-smi",
                "Pull model weights to /mnt/nfs/models/vllm/{model}",
                "Choose image: athanor/vllm:custom (FP8 KV) or athanor/vllm:v2 (NVIDIA 0.16.0)",
                "docker run -d --gpus device=N --name vllm-{name} -v /mnt/nfs/models/vllm:/models -p {port}:8000 {image} --model /models/{model}",
                "Flags: --enable-prefix-caching --enable-sleep-mode --trust-remote-code",
                "Verify: curl http://192.168.1.244:{port}/v1/models",
                "Register in LiteLLM config, restart litellm container",
            ],
            "prerequisites": ["GPU available", "Model weights downloaded"],
        },
    },
    {
        "tier": "procedural",
        "content": "Troubleshoot vLLM OOM errors. When containers crash with CUDA out of memory.",
        "source": "ops/day-one-seed",
        "confidence": 1.0,
        "tags": ["troubleshooting", "vllm", "oom", "gpu"],
        "metadata": {
            "task_type": "troubleshooting",
            "title": "Fix vLLM CUDA OOM",
            "steps": [
                "Check GPU: nvidia-smi on FOUNDRY",
                "Check logs: docker logs vllm-{name} --tail 50",
                "Fix 1: Reduce --max-model-len (16384 or 8192)",
                "Fix 2: Lower --gpu-memory-utilization (0.85 or 0.80)",
                "Fix 3: --enforce-eager to disable CUDA graphs (saves ~2GB)",
                "Fix 4: --kv-cache-dtype fp8_e5m2 (only athanor/vllm:custom)",
                "Fix 5: --cpu-offload-gb N (FOUNDRY has 256GB RAM)",
                "Fix 6: Use smaller quantization (AWQ/GPTQ 4-bit)",
                "Known: vLLM VRAM leak (#28230) - daily restart via cron",
            ],
            "prerequisites": ["Container in crash loop"],
        },
    },
    {
        "tier": "procedural",
        "content": "Ingest documents into memory via Perception service.",
        "source": "ops/day-one-seed",
        "confidence": 1.0,
        "tags": ["operations", "memory", "ingestion"],
        "metadata": {
            "task_type": "data-ingestion",
            "title": "Ingest Content into Memory",
            "steps": [
                "Text: POST http://192.168.1.189:8730/ingest/text",
                "File: POST http://192.168.1.189:8730/ingest/file (multipart)",
                "URL: POST http://192.168.1.189:8730/ingest/url",
                "Batch: POST http://192.168.1.189:8730/ingest/batch",
                "Content types: text, markdown, code",
                "Pipeline: chunk -> embed -> index (Qdrant + Meilisearch)",
                "Stats: GET http://192.168.1.189:8730/stats",
                "Auto-watch: /mnt/vault/data/documents and docs/",
            ],
            "prerequisites": ["Perception service running"],
        },
    },
    {
        "tier": "procedural",
        "content": "Run memory consolidation to promote memories between tiers.",
        "source": "ops/day-one-seed",
        "confidence": 1.0,
        "tags": ["operations", "memory", "consolidation"],
        "metadata": {
            "task_type": "consolidation",
            "title": "Run Memory Consolidation",
            "steps": [
                "Manual: POST http://192.168.1.189:8720/v1/memory/consolidate",
                "Auto: daily 3am via DEV cron",
                "Working->Episodic: access_count>=3 or importance>=0.7",
                "Episodic->Vault: entries older than 30 days",
                "Verify: GET http://192.168.1.189:8720/v1/memory/stats",
            ],
            "prerequisites": ["Memory service running"],
        },
    },
    {
        "tier": "procedural",
        "content": "SSH to VAULT requires hop through DEV. Manage Docker containers.",
        "source": "ops/day-one-seed",
        "confidence": 1.0,
        "tags": ["operations", "ssh", "vault", "docker"],
        "metadata": {
            "task_type": "vault-access",
            "title": "SSH to VAULT and Manage Docker",
            "steps": [
                "From DESK: ssh shaun@192.168.1.189 (DEV)",
                "Then: ssh root@192.168.1.203 (VAULT)",
                "Key containers: litellm, postgres, redis, qdrant, neo4j, meilisearch",
                "Docker on NVMe: /mnt/docker (932GB)",
                "App data: /mnt/user/appdata/local-system/vault/",
                "Backups: PG daily 1:30am, Neo4j Sun 2am, Qdrant Wed 2am",
            ],
            "prerequisites": ["SSH access to DEV"],
        },
    },
    {
        "tier": "procedural",
        "content": "Add or modify LiteLLM model aliases for inference routing.",
        "source": "ops/day-one-seed",
        "confidence": 1.0,
        "tags": ["operations", "litellm", "configuration"],
        "metadata": {
            "task_type": "litellm-config",
            "title": "Configure LiteLLM Model Alias",
            "steps": [
                "Edit: deploy/vault/litellm/config.yaml",
                "Add model_name + litellm_params (model, api_base, api_key)",
                "Push config to VAULT",
                "Restart: docker restart litellm",
                "Verify: curl with auth to VAULT:4000/v1/models",
            ],
            "prerequisites": ["VAULT access"],
        },
    },
    {
        "tier": "procedural",
        "content": "SOAR operating loop for each COO session. Systematic cluster management.",
        "source": "ops/day-one-seed",
        "confidence": 1.0,
        "tags": ["methodology", "soar", "coo"],
        "metadata": {
            "task_type": "methodology",
            "title": "SOAR Operating Loop",
            "steps": [
                "SCAN: SSH health checks, docker ps, services, disk, GPU",
                "ORIENT: P0 broken > P1 toil > P2 risk > P3 foundation > P4 capability",
                "ACT: One thing, test it, commit it",
                "RECORD: Update MEMORY.md, git commit, progress summary",
                "Autonomy: restart, monitor, config tweaks, code fixes",
                "Inform after: infra changes, deployments",
                "Ask first: delete data, spending, security changes",
            ],
            "prerequisites": [],
        },
    },
]

results = []
for proc in procedures:
    resp = client.post(f"{MEMORY}/v1/memory/procedural", json=proc)
    title = proc["metadata"]["title"]
    if resp.status_code == 200:
        data = resp.json()
        results.append(data)
        print(f"OK: {title} -> {data.get('id', 'stored')}")
    else:
        print(f"FAIL ({resp.status_code}): {title} -> {resp.text[:200]}")

print(f"\n--- Seeded: {len(results)} procedures ---")
