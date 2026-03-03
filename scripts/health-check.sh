#!/usr/bin/env bash
# Local-System — Health check across all nodes
# Usage: ./scripts/health-check.sh [node]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# Node IPs (from .env or defaults)
FOUNDRY="${FOUNDRY_HOST:-changeme}"
WORKSHOP="${WORKSHOP_HOST:-changeme}"
VAULT="${VAULT_HOST:-changeme}"
DEV="${DEV_HOST:-192.168.1.189}"

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
echo "  Local-System Health Check"
echo "========================================"
echo ""

FILTER="${1:-all}"

if [ "$FILTER" = "all" ] || [ "$FILTER" = "foundry" ]; then
    echo "FOUNDRY ($FOUNDRY) — Heavy Inference"
    check_service "vLLM Reasoning"  "http://$FOUNDRY:8000/health"
    check_service "vLLM Embedding"  "http://$FOUNDRY:8001/health"
    check_service "Letta"           "http://$FOUNDRY:8283/api/health"
    check_service "Node Exporter"   "http://$FOUNDRY:9100/metrics"
    check_service "GPU Metrics"     "http://$FOUNDRY:9835/metrics"
    echo ""
fi

if [ "$FILTER" = "all" ] || [ "$FILTER" = "workshop" ]; then
    echo "WORKSHOP ($WORKSHOP) — Fast Inference + Creative"
    check_service "vLLM Fast"       "http://$WORKSHOP:8000/health"
    check_service "ComfyUI"         "http://$WORKSHOP:8188"
    check_service "Node Exporter"   "http://$WORKSHOP:9100/metrics"
    check_service "GPU Metrics"     "http://$WORKSHOP:9835/metrics"
    echo ""
fi

if [ "$FILTER" = "all" ] || [ "$FILTER" = "vault" ]; then
    echo "VAULT ($VAULT) — Orchestration + Databases"
    echo "  -- Core Services --"
    check_service "Gateway"         "http://$VAULT:8700/health"
    check_service "Memory"          "http://$VAULT:8702/health"
    check_service "Orchestrator"    "http://$VAULT:8703/health"
    check_service "RAG"             "http://$VAULT:8704/health"
    echo "  -- Inference Gateway --"
    check_service "LiteLLM"         "http://$VAULT:4000/health"
    echo "  -- Databases --"
    check_service "Qdrant"          "http://$VAULT:6333/collections"
    check_service "Neo4j"           "http://$VAULT:7474"
    echo "  -- Monitoring --"
    check_service "Prometheus"      "http://$VAULT:9090/-/healthy"
    check_service "Grafana"         "http://$VAULT:3003/api/health"
    echo "  -- UI --"
    check_service "Command Center"  "http://$VAULT:3001"
    echo ""
fi

if [ "$FILTER" = "all" ] || [ "$FILTER" = "dev" ]; then
    echo "DEV ($DEV) — Operations Center"
    check_service "Node Exporter"   "http://$DEV:9100/metrics"
    echo ""
fi

echo "========================================"
echo "  Done."
echo "========================================"
