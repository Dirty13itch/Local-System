#!/bin/bash
# vLLM Health Restart — mitigates VRAM leak (vLLM Issue #28230)
# Runs via cron at 4am daily on FOUNDRY
# Restarts all vLLM containers sequentially with health checks

LOG="/var/log/vllm-health-restart.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

declare -A PORTS
PORTS[vllm-reasoning]=8000
PORTS[vllm-coding]=8002
PORTS[vllm-creative]=8004

echo "[$TIMESTAMP] Starting vLLM health restart cycle" >> $LOG

for container in vllm-reasoning vllm-coding vllm-creative; do
    PORT=${PORTS[$container]}
    echo "[$TIMESTAMP] Restarting $container (port $PORT)..." >> $LOG
    docker restart $container >> $LOG 2>&1

    # Wait for model to load (up to 180s — reasoning TP=2 takes ~90s)
    HEALTHY=false
    for i in $(seq 1 36); do
        sleep 5
        if curl -s --connect-timeout 2 http://localhost:$PORT/v1/models | grep -q data; then
            echo "[$TIMESTAMP] $container healthy after $((i * 5))s" >> $LOG
            HEALTHY=true
            break
        fi
    done
    if [ "$HEALTHY" = false ]; then
        echo "[$TIMESTAMP] WARNING: $container not healthy after 180s" >> $LOG
    fi
done

echo "[$TIMESTAMP] vLLM health restart cycle complete" >> $LOG
