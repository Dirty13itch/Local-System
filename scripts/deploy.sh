#!/usr/bin/env bash
# Local-System — Deploy services to nodes via SSH
# Usage: ./scripts/deploy.sh [node|all]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# Node SSH targets — use env vars or defaults matching actual infrastructure
declare -A NODES=(
    [hydra-ai]="${HYDRA_AI_SSH:-root@192.168.1.250}"
    [hydra-compute]="${HYDRA_COMPUTE_SSH:-root@192.168.1.203}"
    [hydra-storage]="${HYDRA_STORAGE_SSH:-root@192.168.1.244}"
)

DEPLOY_DIR="/opt/local-system"
TARGET="${1:-all}"

deploy_node() {
    local node="$1"
    local ssh_target="${NODES[$node]}"

    echo "=== Deploying to $node ($ssh_target) ==="

    # Check if deploy config exists for this node
    if [ ! -d "$PROJECT_DIR/deploy/$node" ]; then
        echo "  No deploy config for $node — skipping"
        return
    fi

    # Sync project files
    rsync -az --delete \
        --exclude='.git' \
        --exclude='node_modules' \
        --exclude='.next' \
        --exclude='__pycache__' \
        --exclude='.venv' \
        --exclude='data' \
        --exclude='models' \
        --exclude='.env' \
        "$PROJECT_DIR/" "$ssh_target:$DEPLOY_DIR/"

    # Build and start services
    ssh "$ssh_target" "cd $DEPLOY_DIR && docker compose -f deploy/$node/docker-compose.yml up -d --build --remove-orphans"

    echo "=== $node deployed ==="
    echo ""
}

if [ "$TARGET" = "all" ]; then
    for node in "${!NODES[@]}"; do
        deploy_node "$node"
    done
else
    if [ -z "${NODES[$TARGET]+x}" ]; then
        echo "Unknown node: $TARGET"
        echo "Available: ${!NODES[*]}"
        exit 1
    fi
    deploy_node "$TARGET"
fi

echo "Deployment complete. Check health with: curl http://192.168.1.244:8700/health/cluster"
