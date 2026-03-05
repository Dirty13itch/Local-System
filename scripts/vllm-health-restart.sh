#!/usr/bin/env bash
# vllm-health-restart.sh — Restart vLLM containers to mitigate VRAM leak (vLLM Issue #28230)
# Run via cron: 0 4 * * * /path/to/vllm-health-restart.sh >> /var/log/vllm-restart.log 2>&1
#
# This restarts all vLLM containers on the local node at 4am daily.
# The ~0.28s sleep-mode wake time means near-zero downtime.

set -euo pipefail

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TIMESTAMP] Starting vLLM health restart..."

# Find all vLLM containers
CONTAINERS=$(docker ps --filter "name=vllm-" --format "{{.Names}}" 2>/dev/null || true)

if [ -z "$CONTAINERS" ]; then
    echo "[$TIMESTAMP] No vLLM containers found, skipping."
    exit 0
fi

for CONTAINER in $CONTAINERS; do
    echo "[$TIMESTAMP] Restarting $CONTAINER..."
    docker restart "$CONTAINER" 2>&1 || echo "[$TIMESTAMP] WARNING: Failed to restart $CONTAINER"
    # Brief pause between restarts to avoid thundering herd
    sleep 5
done

echo "[$TIMESTAMP] vLLM health restart complete. Restarted: $CONTAINERS"

# Optional: Log GPU memory after restart
if command -v nvidia-smi &>/dev/null; then
    echo "[$TIMESTAMP] GPU memory after restart:"
    nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv,noheader 2>/dev/null || true
fi
