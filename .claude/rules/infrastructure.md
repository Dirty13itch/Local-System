# Infrastructure Rules

## Node Naming
- All node names FULLY CAPITALIZED: FOUNDRY, WORKSHOP, VAULT, DEV, DESK, MOBILE
- In code: use environment variables (`${NODE_NAME}`) not hardcoded names
- In SSH config: lowercase aliases (foundry, workshop, vault)
- In Docker Compose: service names lowercase, node references via env vars

## Docker
- One `docker-compose.yml` per node under `deploy/<node>/`
- Use `network_mode: host` for cross-node communication (simplest)
- Pin image versions in compose files (no `:latest` in production)
- GPU access: `deploy.resources.reservations.devices` with `capabilities: [gpu]`
- vLLM sleep mode: set `VLLM_SERVER_DEV_MODE=1` in container env

## Ansible
- Inventory at `ansible/inventory.yml` with variables per node
- Roles for: base-config, nvidia-driver, docker, monitoring, inference
- Never hardcode IPs — use inventory variables
- Test with `--check --diff` before applying

## Secrets
- `.env` files per node (NOT committed to git)
- `.env.example` committed with `changeme` placeholders
- Generate real passwords: `openssl rand -base64 32`

## Monitoring
- Grafana Alloy for log shipping (NOT Promtail — EOL Feb 2026)
- DCGM exporter for GPU metrics on compute nodes
- node_exporter on all Linux nodes

## Mixed VRAM GPUs
- Tensor Parallelism (TP) requires identical VRAM across all GPUs
- For mixed VRAM: use Pipeline Parallelism (PP) or separate vLLM instances
- LiteLLM handles load-balancing between instances transparently
