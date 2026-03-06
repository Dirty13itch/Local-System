#!/bin/bash
# Daily maintenance cron — run at 3am via: 0 3 * * * /path/to/daily-maintenance.sh
# Runs consolidation, generates brief, checks disk, restarts vLLM (VRAM leak mitigation)

set -euo pipefail

MIND_URL="http://192.168.1.189:8710"
LOG="/tmp/daily-maintenance.log"

echo "=== Daily Maintenance $(date -Iseconds) ===" >> "$LOG"

# 1. Memory consolidation
echo "Running consolidation..." >> "$LOG"
curl -s -X POST "$MIND_URL/v1/consolidate" >> "$LOG" 2>&1
echo "" >> "$LOG"

# 2. Generate daily brief
echo "Generating brief..." >> "$LOG"
curl -s "$MIND_URL/v1/brief" >> "$LOG" 2>&1
echo "" >> "$LOG"

# 3. Disk usage monitoring
echo "Checking disk usage..." >> "$LOG"
# DEV
DEV_USAGE=$(df / | tail -1 | awk '{gsub(/%/,""); print $5}')
echo "DEV disk: ${DEV_USAGE}%" >> "$LOG"
if [ "$DEV_USAGE" -gt 85 ]; then
    echo "WARNING: DEV disk at ${DEV_USAGE}% (>85% threshold)" >> "$LOG"
fi
# VAULT (via SSH)
VAULT_USAGE=$(ssh root@192.168.1.203 'df /mnt/user | tail -1 | awk '"'"'{gsub(/%/,""); print $5}'"'"'' 2>/dev/null || echo "0")
if [ -n "$VAULT_USAGE" ] && [ "$VAULT_USAGE" -gt 0 ]; then
    echo "VAULT disk: ${VAULT_USAGE}%" >> "$LOG"
    if [ "$VAULT_USAGE" -gt 92 ]; then
        echo "CRITICAL: VAULT disk at ${VAULT_USAGE}% (>92% threshold) — investigate immediately!" >> "$LOG"
    elif [ "$VAULT_USAGE" -gt 88 ]; then
        echo "WARNING: VAULT disk at ${VAULT_USAGE}% (>88% threshold) — plan cleanup" >> "$LOG"
    fi
else
    echo "WARNING: Could not check VAULT disk usage" >> "$LOG"
fi

# 4. Service health quick-check
echo "Checking service health..." >> "$LOG"
for svc in local-system-gateway local-system-mind local-system-memory local-system-perception local-system-ui; do
    STATUS=$(systemctl is-active "$svc" 2>/dev/null || echo "unknown")
    if [ "$STATUS" != "active" ]; then
        echo "WARNING: $svc is $STATUS — attempting restart" >> "$LOG"
        sudo systemctl restart "$svc" >> "$LOG" 2>&1
    fi
done
echo "All services checked." >> "$LOG"

# 5. vLLM health restart (VRAM leak mitigation — Issue #28230)
# Uncomment when vLLM containers are deployed:
# echo "Restarting vLLM containers..." >> "$LOG"
# ssh athanor@192.168.1.244 "docker restart vllm-reasoning vllm-coding" >> "$LOG" 2>&1
# ssh shaun@192.168.1.225 "docker restart vllm-fast" >> "$LOG" 2>&1

echo "=== Done $(date -Iseconds) ===" >> "$LOG"
