#!/bin/bash
# Daily maintenance cron — run at 3am via: 0 3 * * * /path/to/daily-maintenance.sh
# Runs consolidation, generates brief, restarts vLLM (VRAM leak mitigation)

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

# 3. vLLM health restart (VRAM leak mitigation — Issue #28230)
# Uncomment when vLLM containers are deployed:
# echo "Restarting vLLM containers..." >> "$LOG"
# ssh athanor@192.168.1.244 "docker restart vllm-reasoning vllm-coding" >> "$LOG" 2>&1
# ssh shaun@192.168.1.225 "docker restart vllm-fast" >> "$LOG" 2>&1

echo "=== Done $(date -Iseconds) ===" >> "$LOG"
