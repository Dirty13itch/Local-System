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

# Node SSH targets — uses ~/.ssh/config aliases set up by setup-dev.sh
declare -A NODES=(
    [foundry]="foundry"
    [workshop]="workshop"
    [vault]="vault"
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

    # Copy .env to remote
    scp "$PROJECT_DIR/.env" "$ssh_target:$DEPLOY_DIR/.env"

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

echo "Deployment complete. Check health: bash scripts/health-check.sh"
