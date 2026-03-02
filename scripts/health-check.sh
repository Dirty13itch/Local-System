#!/usr/bin/env bash
# Athanor — Health check across all nodes
# Usage: ./scripts/health-check.sh [node]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# Node IPs (actual network)
HYDRA_AI="${HYDRA_AI_HOST:-192.168.1.250}"
HYDRA_COMPUTE="${HYDRA_COMPUTE_HOST:-192.168.1.203}"
HYDRA_STORAGE="${HYDRA_STORAGE_HOST:-192.168.1.244}"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

check_service() {
    local name="$1"
    local url="$2"
    local timeout="${3:-5}"

    if curl -sf --connect-timeout "$timeout" --max-time "$timeout" "$url" >/dev/null 2>&1; then
        printf "  ${GREEN}[OK]${NC}  %-25s %s\n" "$name" "$url"
    else
        printf "  ${RED}[--]${NC}  %-25s %s\n" "$name" "$url"
    fi
}

echo "========================================"
echo "  Athanor Health Check"
echo "========================================"
echo ""

FILTER="${1:-all}"

if [ "$FILTER" = "all" ] || [ "$FILTER" = "hydra-ai" ]; then
    echo "HYDRA-AI ($HYDRA_AI) — Primary Inference (5090+4090)"
    check_service "TabbyAPI"       "http://$HYDRA_AI:5000/health"
    check_service "Node Exporter"  "http://$HYDRA_AI:9100/metrics"
    check_service "GPU Metrics"    "http://$HYDRA_AI:9835/metrics"
    echo ""
fi

if [ "$FILTER" = "all" ] || [ "$FILTER" = "hydra-compute" ]; then
    echo "HYDRA-COMPUTE ($HYDRA_COMPUTE) — Secondary Inference (2x5070Ti)"
    check_service "Ollama GPU"     "http://$HYDRA_COMPUTE:11434/api/tags"
    check_service "ComfyUI"        "http://$HYDRA_COMPUTE:8188"
    check_service "Node Exporter"  "http://$HYDRA_COMPUTE:9100/metrics"
    echo ""
fi

if [ "$FILTER" = "all" ] || [ "$FILTER" = "hydra-storage" ]; then
    echo "HYDRA-STORAGE ($HYDRA_STORAGE) — Orchestration Brain (EPYC 56C)"
    echo "  -- Core Services --"
    check_service "Gateway"        "http://$HYDRA_STORAGE:8700/health"
    check_service "Cognitive"      "http://$HYDRA_STORAGE:8701/health"
    check_service "Memory"         "http://$HYDRA_STORAGE:8702/health"
    check_service "Orchestrator"   "http://$HYDRA_STORAGE:8703/health"
    check_service "RAG"            "http://$HYDRA_STORAGE:8704/health"
    echo "  -- Inference Gateway --"
    check_service "LiteLLM"        "http://$HYDRA_STORAGE:4000/health"
    check_service "Ollama CPU"     "http://$HYDRA_STORAGE:11434/api/tags"
    echo "  -- Databases --"
    check_service "Qdrant"         "http://$HYDRA_STORAGE:6333/collections"
    check_service "Meilisearch"    "http://$HYDRA_STORAGE:7700/health"
    check_service "Neo4j"          "http://$HYDRA_STORAGE:7474"
    check_service "MinIO"          "http://$HYDRA_STORAGE:9000/minio/health/live"
    echo "  -- Monitoring --"
    check_service "Prometheus"     "http://$HYDRA_STORAGE:9090/-/healthy"
    check_service "Grafana"        "http://$HYDRA_STORAGE:3003/api/health"
    check_service "Uptime Kuma"    "http://$HYDRA_STORAGE:3004"
    echo "  -- Automation --"
    check_service "n8n"            "http://$HYDRA_STORAGE:5678/healthz"
    echo "  -- UI --"
    check_service "Command Center" "http://$HYDRA_STORAGE:3200"
    echo ""
fi

echo "========================================"
echo "  Done."
echo "========================================"
