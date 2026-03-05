#!/usr/bin/env bash
# deploy.sh — Safe deployment script for Local-System services
# Usage: ./scripts/deploy.sh [service] [action]
#   service: mind | memory | gateway | all
#   action: validate | deploy | restart | health | full (default: full)

set -euo pipefail

PROJECT_DIR="/home/shaun/dev/local-system-v4"
VENV="$PROJECT_DIR/.venv/bin"
LOG_DIR="/tmp"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SERVICE=${1:-all}
ACTION=${2:-full}

declare -A PORTS=(
    [mind]=8710
    [memory]=8720
    [gateway]=8700
)

declare -A MODULES=(
    [mind]="services.mind.main:app"
    [memory]="services.memory.main:app"
    [gateway]="services.gateway.main:app"
)

log() { echo -e "${GREEN}[deploy]${NC} $1"; }
warn() { echo -e "${YELLOW}[deploy]${NC} $1"; }
err() { echo -e "${RED}[deploy]${NC} $1"; }

# --- Validation ---
validate_service() {
    local svc=$1
    log "Validating $svc..."

    # Syntax check all Python files in the service directory
    local errors=0
    while IFS= read -r -d '' pyfile; do
        if ! "$VENV/python3" -m py_compile "$pyfile" 2>/dev/null; then
            err "Syntax error in: $pyfile"
            "$VENV/python3" -m py_compile "$pyfile" 2>&1 || true
            errors=$((errors + 1))
        fi
    done < <(find "$PROJECT_DIR/services/$svc" -name '*.py' -print0)

    # Also validate shared modules
    while IFS= read -r -d '' pyfile; do
        if ! "$VENV/python3" -m py_compile "$pyfile" 2>/dev/null; then
            err "Syntax error in shared: $pyfile"
            errors=$((errors + 1))
        fi
    done < <(find "$PROJECT_DIR/shared/python/local_system" -name '*.py' -print0)

    if [ $errors -gt 0 ]; then
        err "Validation FAILED: $errors syntax errors"
        return 1
    fi
    log "Validation passed for $svc"
    return 0
}

# --- Health Check ---
health_check() {
    local svc=$1
    local port=${PORTS[$svc]}
    local max_attempts=10
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        attempt=$((attempt + 1))
        if curl -sf "http://localhost:$port/health" > /dev/null 2>&1; then
            log "$svc is healthy (attempt $attempt)"
            return 0
        fi
        sleep 2
    done
    err "$svc health check FAILED after $max_attempts attempts"
    return 1
}

# --- Restart ---
restart_service() {
    local svc=$1
    local port=${PORTS[$svc]}
    local module=${MODULES[$svc]}

    log "Restarting $svc on port $port..."

    # Kill existing process on this port
    local pid=$(lsof -ti :$port 2>/dev/null || true)
    if [ -n "$pid" ]; then
        kill $pid 2>/dev/null || true
        sleep 2
        # Force kill if still running
        if kill -0 $pid 2>/dev/null; then
            kill -9 $pid 2>/dev/null || true
            sleep 1
        fi
    fi

    # Start new process
    cd "$PROJECT_DIR"
    nohup "$VENV/uvicorn" "$module"         --host 0.0.0.0 --port "$port" --reload         > "$LOG_DIR/$svc.log" 2>&1 &

    log "$svc started (PID: $!)"
}

# --- Full Deploy ---
deploy_service() {
    local svc=$1

    log "=== Deploying $svc ==='"
    
    # Step 1: Validate
    if ! validate_service "$svc"; then
        err "ABORTING deploy of $svc — validation failed"
        return 1
    fi

    # Step 2: Restart
    restart_service "$svc"

    # Step 3: Health check
    if ! health_check "$svc"; then
        err "DEPLOY FAILED for $svc — health check failed"
        warn "Check logs: tail -50 $LOG_DIR/$svc.log"
        return 1
    fi

    log "=== $svc deployed successfully ==="
    return 0
}

# --- Main ---
run_action() {
    local svc=$1
    case $ACTION in
        validate)
            validate_service "$svc"
            ;;
        restart)
            restart_service "$svc"
            health_check "$svc"
            ;;
        health)
            health_check "$svc"
            ;;
        deploy|full)
            deploy_service "$svc"
            ;;
        *)
            err "Unknown action: $ACTION"
            exit 1
            ;;
    esac
}

if [ "$SERVICE" = "all" ]; then
    for svc in mind memory gateway; do
        run_action "$svc" || true
    done
else
    if [ -z "${PORTS[$SERVICE]+x}" ]; then
        err "Unknown service: $SERVICE"
        exit 1
    fi
    run_action "$SERVICE"
fi
