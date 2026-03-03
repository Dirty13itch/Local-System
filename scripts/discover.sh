#!/usr/bin/env bash
# ============================================================
# Local-System Phase 0.1: Infrastructure Auto-Discovery
# ============================================================
# Run from DEV node after SSH keys are distributed.
# Discovers hardware, network, services, and storage on all nodes.
# Outputs: docs/infrastructure-report.md
# ============================================================
set -euo pipefail

REPORT_DIR="$(cd "$(dirname "$0")/.." && pwd)/docs"
REPORT="$REPORT_DIR/infrastructure-report.md"
mkdir -p "$REPORT_DIR"

# --- Configuration ---
# Node list: name=ssh_target
# Update these after SSH config is set up on DEV.
# "dev" uses localhost (no SSH needed).
declare -A NODES=(
  [FOUNDRY]="foundry"
  [WORKSHOP]="workshop"
  [VAULT]="vault"
  [DEV]="localhost"
)

# Optional non-server nodes (may not be reachable)
declare -A OPTIONAL_NODES=(
  [DESK]="desk"
  [MOBILE]="mobile"
)

TIMESTAMP=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

# --- Helpers ---
run_on() {
  local target="$1"
  shift
  if [[ "$target" == "localhost" ]]; then
    eval "$@" 2>/dev/null || echo "[not available]"
  else
    ssh -o ConnectTimeout=5 -o BatchMode=yes "$target" "$@" 2>/dev/null || echo "[not available]"
  fi
}

log() { echo "  [+] $*"; }

# --- Start Report ---
cat > "$REPORT" <<HEADER
# Infrastructure Discovery Report

**Generated:** $TIMESTAMP
**Run from:** $(hostname) (DEV node)

---

HEADER

echo "=== Local-System Phase 0.1: Infrastructure Auto-Discovery ==="
echo "Report: $REPORT"
echo ""

# --- Discover Each Node ---
for NODE_NAME in FOUNDRY WORKSHOP VAULT DEV; do
  TARGET="${NODES[$NODE_NAME]}"
  echo "--- Discovering $NODE_NAME ($TARGET) ---"

  cat >> "$REPORT" <<NODE_HEADER
## $NODE_NAME ($TARGET)

NODE_HEADER

  # OS
  log "OS info"
  OS_INFO=$(run_on "$TARGET" "cat /etc/os-release 2>/dev/null | head -5")
  HOSTNAME_INFO=$(run_on "$TARGET" "hostname -f")
  KERNEL=$(run_on "$TARGET" "uname -r")
  cat >> "$REPORT" <<SECTION
### Operating System
\`\`\`
Hostname: $HOSTNAME_INFO
Kernel: $KERNEL
$OS_INFO
\`\`\`

SECTION

  # CPU
  log "CPU info"
  CPU_MODEL=$(run_on "$TARGET" "grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2 | xargs")
  CPU_CORES=$(run_on "$TARGET" "nproc")
  CPU_THREADS=$(run_on "$TARGET" "grep -c processor /proc/cpuinfo")
  cat >> "$REPORT" <<SECTION
### CPU
- **Model:** $CPU_MODEL
- **Cores:** $CPU_CORES
- **Threads:** $CPU_THREADS

SECTION

  # RAM
  log "RAM info"
  RAM_INFO=$(run_on "$TARGET" "free -h | grep Mem")
  RAM_TOTAL=$(echo "$RAM_INFO" | awk '{print $2}')
  RAM_USED=$(echo "$RAM_INFO" | awk '{print $3}')
  RAM_AVAIL=$(echo "$RAM_INFO" | awk '{print $7}')
  cat >> "$REPORT" <<SECTION
### Memory
- **Total:** $RAM_TOTAL
- **Used:** $RAM_USED
- **Available:** $RAM_AVAIL

SECTION

  # GPUs
  log "GPU info"
  GPU_LIST=$(run_on "$TARGET" "lspci | grep -i 'vga\|3d\|display' | grep -iv 'audio'")
  NVIDIA_SMI=$(run_on "$TARGET" "nvidia-smi --query-gpu=index,name,memory.total,memory.free,driver_version --format=csv,noheader 2>/dev/null")
  cat >> "$REPORT" <<SECTION
### GPUs
**PCI devices:**
\`\`\`
$GPU_LIST
\`\`\`

**NVIDIA SMI (index, name, VRAM total, VRAM free, driver):**
\`\`\`
$NVIDIA_SMI
\`\`\`

SECTION

  # Network
  log "Network info"
  IP_INFO=$(run_on "$TARGET" "ip -4 addr show | grep 'inet ' | grep -v '127.0.0.1' | awk '{print \$2, \$NF}'")
  GATEWAY=$(run_on "$TARGET" "ip route | grep default | awk '{print \$3}'")
  cat >> "$REPORT" <<SECTION
### Network
**Interfaces:**
\`\`\`
$IP_INFO
\`\`\`
**Default gateway:** $GATEWAY

SECTION

  # Storage
  log "Storage info"
  DISK_USAGE=$(run_on "$TARGET" "df -h | grep -E '^/dev|^nfs|^cifs' | head -20")
  BLOCK_DEVICES=$(run_on "$TARGET" "lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT 2>/dev/null | head -30")
  NFS_EXPORTS=$(run_on "$TARGET" "showmount -e localhost 2>/dev/null | head -10")
  cat >> "$REPORT" <<SECTION
### Storage
**Disk usage:**
\`\`\`
$DISK_USAGE
\`\`\`

**Block devices:**
\`\`\`
$BLOCK_DEVICES
\`\`\`

**NFS exports (if any):**
\`\`\`
$NFS_EXPORTS
\`\`\`

SECTION

  # Docker
  log "Docker info"
  DOCKER_VERSION=$(run_on "$TARGET" "docker --version 2>/dev/null")
  DOCKER_PS=$(run_on "$TARGET" "docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null | head -30")
  COMPOSE_PROJECTS=$(run_on "$TARGET" "docker compose ls 2>/dev/null")
  cat >> "$REPORT" <<SECTION
### Docker Services
**Docker version:** $DOCKER_VERSION

**Running containers:**
\`\`\`
$DOCKER_PS
\`\`\`

**Compose projects:**
\`\`\`
$COMPOSE_PROJECTS
\`\`\`

---

SECTION

  echo ""
done

# --- Optional nodes ---
for NODE_NAME in DESK MOBILE; do
  TARGET="${OPTIONAL_NODES[$NODE_NAME]}"
  echo "--- Attempting $NODE_NAME ($TARGET) --- (optional, may not be reachable)"

  # Quick connectivity check
  if ! ssh -o ConnectTimeout=3 -o BatchMode=yes "$TARGET" "echo ok" &>/dev/null; then
    echo "  [!] $NODE_NAME not reachable, skipping"
    cat >> "$REPORT" <<SECTION
## $NODE_NAME ($TARGET)

**Status:** Not reachable at discovery time.

---

SECTION
    continue
  fi

  # If reachable, collect basic info
  OS_INFO=$(run_on "$TARGET" "cat /etc/os-release 2>/dev/null | head -3 || systeminfo 2>/dev/null | head -5")
  CPU_MODEL=$(run_on "$TARGET" "grep 'model name' /proc/cpuinfo 2>/dev/null | head -1 | cut -d: -f2 | xargs")
  RAM_TOTAL=$(run_on "$TARGET" "free -h 2>/dev/null | grep Mem | awk '{print \$2}'")
  NVIDIA_SMI=$(run_on "$TARGET" "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null")

  cat >> "$REPORT" <<SECTION
## $NODE_NAME ($TARGET)

**OS:** $OS_INFO
**CPU:** $CPU_MODEL
**RAM:** $RAM_TOTAL
**GPUs:** $NVIDIA_SMI

---

SECTION
  echo ""
done

# --- Summary Table ---
cat >> "$REPORT" <<SUMMARY
## Summary

| Node | Status | CPU | RAM | GPUs | IP |
|------|--------|-----|-----|------|----|
SUMMARY

for NODE_NAME in FOUNDRY WORKSHOP VAULT DEV; do
  TARGET="${NODES[$NODE_NAME]}"
  CPU=$(run_on "$TARGET" "grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2 | xargs")
  RAM=$(run_on "$TARGET" "free -h | grep Mem | awk '{print \$2}'")
  GPUS=$(run_on "$TARGET" "nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | paste -sd ', ' -")
  IP=$(run_on "$TARGET" "hostname -I 2>/dev/null | awk '{print \$1}'")
  echo "| **$NODE_NAME** | Discovered | $CPU | $RAM | $GPUS | $IP |" >> "$REPORT"
done

cat >> "$REPORT" <<FOOTER

---

*Auto-generated by \`scripts/discover.sh\` — Phase 0.1 Infrastructure Auto-Discovery*
*Re-run anytime hardware changes: \`bash scripts/discover.sh\`*
FOOTER

echo ""
echo "=== Discovery complete ==="
echo "Report saved to: $REPORT"
echo ""
echo "Next steps:"
echo "  1. Review the report: cat $REPORT"
echo "  2. Update Ansible inventory based on discovered IPs"
echo "  3. Proceed to Phase 0.5 scaffold cleanup with real specs"
