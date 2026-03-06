#!/usr/bin/env bash
# cluster-connectivity.sh — Verify and maintain permanent inter-node SSH connectivity
# Run from any node. Tests all connections and reports status.
# Usage: ./scripts/cluster-connectivity.sh [fix|test|setup]

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Cluster node definitions
declare -A NODES=(
    [dev]="192.168.1.189"
    [foundry]="192.168.1.244"
    [workshop]="192.168.1.225"
    [vault]="192.168.1.203"
)

declare -A USERS=(
    [dev]="shaun"
    [foundry]="athanor"
    [workshop]="athanor"
    [vault]="root"
)

declare -A SERVICES=(
    [dev]="gateway:8700 mind:8710 memory:8720 perception:8730 embedding:8001 reranker:8003"
    [foundry]="vllm-reasoning:8000 vllm-coding:8002 vllm-creative:8004"
    [workshop]="vllm-fast:8000 comfyui:8188"
    [vault]="litellm:4000 qdrant:6333 neo4j:7687 prometheus:9090 grafana:3000"
)

CURRENT_HOST=$(hostname)
ACTION=${1:-test}

ok() { echo -e "${GREEN}  ✓${NC} $1"; }
fail() { echo -e "${RED}  ✗${NC} $1"; }
warn() { echo -e "${YELLOW}  ⚠${NC} $1"; }
header() { echo -e "\n${CYAN}=== $1 ===${NC}"; }

# --- Test SSH Connectivity ---
test_ssh() {
    local name=$1
    local ip=${NODES[$name]}
    local user=${USERS[$name]}

    if ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no \
        "${user}@${ip}" "echo ok" &>/dev/null; then
        ok "SSH → ${name} (${user}@${ip})"
        return 0
    else
        fail "SSH → ${name} (${user}@${ip})"
        return 1
    fi
}

# --- Test Service Connectivity ---
test_services() {
    local name=$1
    local ip=${NODES[$name]}
    local services=${SERVICES[$name]}

    for svc_port in $services; do
        local svc=${svc_port%%:*}
        local port=${svc_port##*:}
        if curl -sf --connect-timeout 3 "http://${ip}:${port}/health" &>/dev/null || \
           curl -sf --connect-timeout 3 "http://${ip}:${port}/v1/models" &>/dev/null || \
           curl -sf --connect-timeout 3 "http://${ip}:${port}/" &>/dev/null; then
            ok "${svc} :${port} on ${name}"
        else
            fail "${svc} :${port} on ${name}"
        fi
    done
}

# --- Test NFS Mounts ---
test_nfs() {
    local name=$1
    local ip=${NODES[$name]}
    local user=${USERS[$name]}

    local result
    result=$(ssh -o BatchMode=yes -o ConnectTimeout=5 "${user}@${ip}" \
        "ls /mnt/vault/data/ &>/dev/null && echo 'mounted' || echo 'not-mounted'" 2>/dev/null) || result="ssh-failed"

    case "$result" in
        mounted) ok "NFS /mnt/vault on ${name}" ;;
        not-mounted) fail "NFS /mnt/vault NOT mounted on ${name}" ;;
        *) warn "Cannot check NFS on ${name} (SSH failed)" ;;
    esac
}

# --- Full Test ---
run_test() {
    header "SSH Connectivity"
    local ssh_failures=0
    for node in dev foundry workshop vault; do
        test_ssh "$node" || ssh_failures=$((ssh_failures + 1))
    done

    header "Service Health"
    for node in dev foundry workshop vault; do
        test_services "$node"
    done

    header "NFS Mounts"
    for node in dev foundry workshop; do
        test_nfs "$node"
    done

    header "Summary"
    if [ $ssh_failures -eq 0 ]; then
        ok "All SSH connections healthy"
    else
        fail "${ssh_failures} SSH connection(s) failed"
    fi
}

# --- Setup SSH Config ---
setup_ssh_config() {
    header "Setting up SSH config"

    local config_file="$HOME/.ssh/config"

    if [ -f "$config_file" ]; then
        warn "SSH config already exists at $config_file"
        echo "  Current contents:"
        cat "$config_file" | sed 's/^/    /'
        return
    fi

    cat > "$config_file" << 'SSHEOF'
# Local-System Cluster SSH Configuration

Host dev
    HostName 192.168.1.189
    User shaun
    StrictHostKeyChecking no
    ServerAliveInterval 60
    ServerAliveCountMax 3

Host foundry
    HostName 192.168.1.244
    User athanor
    StrictHostKeyChecking no
    ServerAliveInterval 60
    ServerAliveCountMax 3

Host workshop
    HostName 192.168.1.225
    User athanor
    StrictHostKeyChecking no
    ServerAliveInterval 60
    ServerAliveCountMax 3

Host vault
    HostName 192.168.1.203
    User root
    StrictHostKeyChecking no
    ServerAliveInterval 60
    ServerAliveCountMax 3
SSHEOF

    chmod 600 "$config_file"
    ok "SSH config written to $config_file"
}

# --- Fix: Deploy SSH Keys ---
fix_ssh() {
    header "Fixing SSH Connectivity"

    # Generate key if needed
    if [ ! -f "$HOME/.ssh/id_ed25519" ]; then
        ssh-keygen -t ed25519 -N "" -f "$HOME/.ssh/id_ed25519" -C "$(whoami)@$(hostname)"
        ok "Generated SSH key"
    fi

    local pubkey
    pubkey=$(cat "$HOME/.ssh/id_ed25519.pub")

    for node in dev foundry workshop vault; do
        local ip=${NODES[$node]}
        local user=${USERS[$node]}

        echo -e "  Deploying key to ${node} (${user}@${ip})..."
        if ssh -o BatchMode=yes -o ConnectTimeout=3 "${user}@${ip}" "echo ok" &>/dev/null; then
            ok "Already connected to ${node}"
        else
            warn "Cannot auto-deploy to ${node} — manual key install needed"
            echo "  Run: ssh-copy-id ${user}@${ip}"
        fi
    done

    # Setup SSH config
    setup_ssh_config
}

# --- Main ---
case "$ACTION" in
    test)   run_test ;;
    fix)    fix_ssh; run_test ;;
    setup)  setup_ssh_config ;;
    *)
        echo "Usage: $0 [test|fix|setup]"
        echo "  test  — Test all SSH and service connectivity"
        echo "  fix   — Deploy SSH keys and config, then test"
        echo "  setup — Create SSH config file"
        exit 1
        ;;
esac
