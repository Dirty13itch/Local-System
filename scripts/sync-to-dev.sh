#!/usr/bin/env bash
# sync-to-dev.sh — Sync codebase from DESK (Windows) to DEV, then deploy
# Usage: ./scripts/sync-to-dev.sh [service|all]
#
# This is the canonical way to deploy code changes:
#   1. Edit on DESK (Claude Code / IDE)
#   2. Run sync-to-dev.sh to push changes
#   3. Services auto-restart on DEV
#
# Runs from Git Bash on DESK.

set -euo pipefail

DEV_HOST="shaun@192.168.1.189"
DEV_PROJECT="/home/shaun/dev/local-system-v4"
LOCAL_PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE=${1:-none}

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[sync]${NC} $1"; }
warn() { echo -e "${YELLOW}[sync]${NC} $1"; }
err() { echo -e "${RED}[sync]${NC} $1"; }

# Sync only source code (not venv, __pycache__, .git, etc.)
log "Syncing codebase to DEV..."
rsync -avz --delete \
    --exclude='.git/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.venv/' \
    --exclude='node_modules/' \
    --exclude='.next/' \
    --exclude='.claude/' \
    --exclude='.serena/' \
    --exclude='*.egg-info/' \
    --exclude='.env' \
    --exclude='*.log' \
    "${LOCAL_PROJECT}/" "${DEV_HOST}:${DEV_PROJECT}/"

log "Sync complete"

# Deploy specific service if requested
if [ "$SERVICE" != "none" ]; then
    log "Deploying ${SERVICE} on DEV..."
    ssh "$DEV_HOST" "cd ${DEV_PROJECT} && bash scripts/deploy.sh ${SERVICE}"
fi
