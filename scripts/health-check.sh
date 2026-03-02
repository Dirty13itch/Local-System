#!/usr/bin/env bash
# Local-System — Health check across all nodes
# Usage: ./scripts/health-check.sh [node]

set -euo pipefail

# Load config
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# Defaults
NODE1_HOST="${NODE1_HOST:-10.0.0.11}"
NODE2_HOST="${NODE2_HOST:-10.0.0.12}"
VAULT_HOST="${VAULT_HOST:-10.0.0.13}"
DESK_HOST="${DESK_HOST:-10.0.0.14}"
DEV_HOST="${DEV_HOST:-10.0.0.15}"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

check_service() {
    local name="$1"
    local url="$2"
    local timeout="${3:-5}"

    if response=$(curl -sf --connect-timeout "$timeout" --max-time "$timeout" "$url" 2>/dev/null); then
        status=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "ok")
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

if [ "$FILTER" = "all" ] || [ "$FILTER" = "desk" ]; then
    echo "DESK ($DESK_HOST) — UI + Gateway + Orchestrator"
    check_service "Gateway"      "http://$DESK_HOST:8000/health"
    check_service "Orchestrator"  "http://$DESK_HOST:8002/health"
    check_service "UI"            "http://$DESK_HOST:3000"
    echo ""
fi

if [ "$FILTER" = "all" ] || [ "$FILTER" = "node1" ]; then
    echo "NODE 1 ($NODE1_HOST) — Primary Inference"
    check_service "Inference"     "http://$NODE1_HOST:8001/health"
    check_service "Model Manager" "http://$NODE1_HOST:8005/health"
    check_service "Ollama"        "http://$NODE1_HOST:11434/api/tags"
    echo ""
fi

if [ "$FILTER" = "all" ] || [ "$FILTER" = "node2" ]; then
    echo "NODE 2 ($NODE2_HOST) — Secondary Inference"
    check_service "Inference"     "http://$NODE2_HOST:8001/health"
    check_service "Ollama"        "http://$NODE2_HOST:11434/api/tags"
    echo ""
fi

if [ "$FILTER" = "all" ] || [ "$FILTER" = "vault" ]; then
    echo "VAULT ($VAULT_HOST) — Storage + RAG"
    check_service "Storage"       "http://$VAULT_HOST:8004/health"
    check_service "RAG"           "http://$VAULT_HOST:8003/health"
    check_service "Qdrant"        "http://$VAULT_HOST:6333/collections"
    check_service "PostgreSQL"    "http://$VAULT_HOST:5432" 2
    echo ""
fi

if [ "$FILTER" = "all" ] || [ "$FILTER" = "dev" ]; then
    echo "DEV ($DEV_HOST) — Monitoring"
    check_service "Prometheus"    "http://$DEV_HOST:9090/-/healthy"
    check_service "Grafana"       "http://$DEV_HOST:3001/api/health"
    echo ""
fi

echo "========================================"
echo "  Done."
echo "========================================"
