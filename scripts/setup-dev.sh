#!/usr/bin/env bash
# ============================================================
# Local-System — DEV Node Setup Script
# ============================================================
# Run this on DEV (192.168.1.189) after fresh Ubuntu Server 24.04 install.
# Execute as: bash setup-dev.sh
# ============================================================
set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

step()  { echo -e "\n${BLUE}===[STEP]=== $*${NC}\n"; }
ok()    { echo -e "  ${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "  ${YELLOW}[!!]${NC} $*"; }
fail()  { echo -e "  ${RED}[FAIL]${NC} $*"; }

# ============================================================
# Pre-flight checks
# ============================================================
step "Pre-flight checks"

if [[ $EUID -eq 0 ]]; then
    fail "Do not run as root. Run as your normal user (shaun)."
    exit 1
fi

if ! grep -q "Ubuntu" /etc/os-release 2>/dev/null; then
    fail "This script is for Ubuntu. Detected: $(cat /etc/os-release | head -1)"
    exit 1
fi

ok "Running as $(whoami) on $(hostname)"
ok "OS: $(grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '"')"

# ============================================================
# Step 4a: Base packages
# ============================================================
step "Installing base packages"

sudo apt update
sudo apt upgrade -y
sudo apt install -y \
    git curl wget htop tmux vim jq unzip net-tools \
    lm-sensors nfs-common python3-pip python3-venv build-essential \
    software-properties-common apt-transport-https ca-certificates gnupg \
    rsync nmap openssh-server

ok "Base packages installed"

# ============================================================
# Step 4b: Remove snapd
# ============================================================
step "Removing snapd (if present)"

if dpkg -l snapd &>/dev/null; then
    sudo apt purge -y snapd
    sudo rm -rf /snap /var/snap /var/lib/snapd ~/snap 2>/dev/null || true
    ok "snapd removed"
else
    ok "snapd not installed, skipping"
fi

# ============================================================
# Step 4c: Install Docker Engine
# ============================================================
step "Installing Docker Engine"

if command -v docker &>/dev/null; then
    ok "Docker already installed: $(docker --version)"
else
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list
    sudo apt update
    sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    sudo usermod -aG docker "$USER"
    ok "Docker installed: $(docker --version)"
    warn "You may need to log out and back in for docker group to take effect"
fi

echo "  Docker Compose: $(docker compose version 2>/dev/null || echo 'not available yet - re-login needed')"

# ============================================================
# Step 4d: Install Node.js 24 LTS
# ============================================================
step "Installing Node.js 24 LTS"

if command -v node &>/dev/null && node --version | grep -q "v24"; then
    ok "Node.js 24 already installed: $(node --version)"
else
    curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash -
    sudo apt install -y nodejs
    ok "Node.js installed: $(node --version)"
    ok "npm: $(npm --version)"
fi

# ============================================================
# Step 4e: Install Python tools + Ansible
# ============================================================
step "Installing Python tools and Ansible"

ok "Python: $(python3 --version)"

pip3 install --user ansible ansible-lint 2>/dev/null || pip3 install --user --break-system-packages ansible ansible-lint

# Ensure ~/.local/bin is on PATH
if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
    export PATH="$HOME/.local/bin:$PATH"
fi

ok "Ansible: $(ansible --version | head -1)"

# ============================================================
# Step 4f: Check for NVIDIA GPU
# ============================================================
step "Checking for NVIDIA GPU"

if lspci | grep -qi nvidia; then
    ok "NVIDIA GPU detected:"
    lspci | grep -i nvidia
    echo ""
    if command -v nvidia-smi &>/dev/null; then
        ok "NVIDIA driver already installed"
        nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
    else
        warn "GPU found but no driver installed."
        warn "Install with: sudo apt install -y nvidia-driver-580 nvidia-utils-580"
        warn "Then reboot and verify with: nvidia-smi"
    fi
else
    ok "No NVIDIA GPU detected — skipping driver install"
fi

# ============================================================
# Step 4g: Set timezone
# ============================================================
step "Setting timezone to America/Chicago"

sudo timedatectl set-timezone America/Chicago
ok "Timezone: $(timedatectl show --property=Timezone --value)"

# ============================================================
# Step 4h: Generate SSH key
# ============================================================
step "Generating SSH key"

if [ -f ~/.ssh/id_ed25519 ]; then
    ok "SSH key already exists: ~/.ssh/id_ed25519"
else
    ssh-keygen -t ed25519 -C "shaun@dev" -N "" -f ~/.ssh/id_ed25519
    ok "SSH key generated"
fi

echo ""
echo "  Public key (you'll need this for other nodes):"
echo "  $(cat ~/.ssh/id_ed25519.pub)"
echo ""

# ============================================================
# Step 4i: Network scan to find other nodes
# ============================================================
step "Scanning local network for other nodes"

SUBNET="192.168.1"
echo "  Scanning ${SUBNET}.0/24 for SSH-accessible hosts..."
echo ""

# Quick nmap scan for hosts with port 22 open
SCAN_RESULTS=$(nmap -sn -T4 "${SUBNET}.0/24" 2>/dev/null | grep "Nmap scan report" | awk '{print $NF}' | tr -d '()' | sort -t. -k4 -n)

echo "  Live hosts found on ${SUBNET}.0/24:"
echo "  ──────────────────────────────────"
for ip in $SCAN_RESULTS; do
    hostname_info=$(ssh -o ConnectTimeout=2 -o BatchMode=yes -o StrictHostKeyChecking=no "$ip" "hostname" 2>/dev/null || echo "?")
    if [ "$hostname_info" != "?" ]; then
        printf "  ${GREEN}%-18s${NC} hostname: %s (SSH OK)\n" "$ip" "$hostname_info"
    else
        printf "  %-18s (no SSH access)\n" "$ip"
    fi
done

echo ""
echo "  ──────────────────────────────────"
echo "  Review the list above and identify which IP is which node."
echo ""

# ============================================================
# Step 4i continued: Create SSH config
# ============================================================
step "Creating SSH config"

echo "  Enter the IP addresses for each node."
echo "  (Press Enter to accept the suggested default)"
echo ""

read -rp "  FOUNDRY IP [192.168.1.225]: " FOUNDRY_IP
FOUNDRY_IP="${FOUNDRY_IP:-192.168.1.225}"

read -rp "  WORKSHOP IP [192.168.1.244]: " WORKSHOP_IP
WORKSHOP_IP="${WORKSHOP_IP:-192.168.1.244}"

read -rp "  VAULT IP [192.168.1.203]: " VAULT_IP
VAULT_IP="${VAULT_IP:-192.168.1.203}"

read -rp "  DESK IP (Windows, optional) []: " DESK_IP
DESK_IP="${DESK_IP:-}"

read -rp "  SSH username on other nodes [shaun]: " SSH_USER
SSH_USER="${SSH_USER:-shaun}"

echo ""
ok "Configuring SSH for:"
echo "    FOUNDRY  = ${SSH_USER}@${FOUNDRY_IP}"
echo "    WORKSHOP = ${SSH_USER}@${WORKSHOP_IP}"
echo "    VAULT    = ${SSH_USER}@${VAULT_IP}"
[ -n "$DESK_IP" ] && echo "    DESK     = ${SSH_USER}@${DESK_IP}"

# Backup existing config
[ -f ~/.ssh/config ] && cp ~/.ssh/config ~/.ssh/config.bak

cat > ~/.ssh/config << SSHEOF
# Local-System SSH Config — Generated by setup-dev.sh
# $(date -u '+%Y-%m-%dT%H:%M:%SZ')

Host foundry
    HostName ${FOUNDRY_IP}
    User ${SSH_USER}

Host workshop
    HostName ${WORKSHOP_IP}
    User ${SSH_USER}

Host vault
    HostName ${VAULT_IP}
    User ${SSH_USER}

$([ -n "$DESK_IP" ] && cat << DESK
Host desk
    HostName ${DESK_IP}
    User ${SSH_USER}

DESK
)
Host foundry workshop vault$([ -n "$DESK_IP" ] && echo " desk")
    IdentityFile ~/.ssh/id_ed25519
    StrictHostKeyChecking accept-new
    ServerAliveInterval 60
SSHEOF

chmod 600 ~/.ssh/config
ok "SSH config written to ~/.ssh/config"

# ============================================================
# Step 4j: Distribute SSH key to other nodes
# ============================================================
step "Distributing SSH key to other nodes"

echo "  You'll be asked for the password on each node (one time only)."
echo ""

for node in foundry workshop vault; do
    echo "  --- $node ---"
    if ssh -o ConnectTimeout=5 -o BatchMode=yes "$node" "echo ok" &>/dev/null; then
        ok "$node: Key already authorized"
    else
        ssh-copy-id "$node" || warn "Could not copy key to $node — you may need to do this manually"
    fi
done

# ============================================================
# Step 4k: Test SSH access
# ============================================================
step "Testing SSH access to all nodes"

for node in foundry workshop vault; do
    result=$(ssh -o ConnectTimeout=5 -o BatchMode=yes "$node" "hostname && uname -r" 2>/dev/null)
    if [ $? -eq 0 ]; then
        ok "$node: $result"
    else
        fail "$node: Could not connect"
    fi
done

# ============================================================
# Step 4l: Clone repo and set up project
# ============================================================
step "Cloning Local-System repo and setting up project"

if [ -d ~/Local-System/.git ]; then
    ok "Repo already cloned at ~/Local-System"
    cd ~/Local-System
    git fetch origin
    git checkout claude/plan-local-ai-system-uzaYn 2>/dev/null || git checkout -b claude/plan-local-ai-system-uzaYn origin/claude/plan-local-ai-system-uzaYn
    git pull origin claude/plan-local-ai-system-uzaYn || true
else
    cd ~
    git clone https://github.com/Dirty13itch/Local-System.git
    cd Local-System
    git checkout claude/plan-local-ai-system-uzaYn 2>/dev/null || git checkout -b claude/plan-local-ai-system-uzaYn origin/claude/plan-local-ai-system-uzaYn
fi

ok "On branch: $(git branch --show-current)"

# Install shared python package
pip3 install -e shared/python 2>/dev/null || pip3 install --break-system-packages -e shared/python
ok "Python shared package installed"

# Install Claude Code
if command -v claude &>/dev/null; then
    ok "Claude Code already installed"
else
    sudo npm install -g @anthropic-ai/claude-code
    ok "Claude Code installed"
fi

# Create .env from template
if [ ! -f .env ]; then
    cp .env.example .env
    # Fill in known IPs
    sed -i "s|FOUNDRY_HOST=changeme|FOUNDRY_HOST=${FOUNDRY_IP}|g" .env
    sed -i "s|WORKSHOP_HOST=changeme|WORKSHOP_HOST=${WORKSHOP_IP}|g" .env
    sed -i "s|VAULT_HOST=changeme|VAULT_HOST=${VAULT_IP}|g" .env
    sed -i "s|DEV_HOST=127.0.0.1|DEV_HOST=192.168.1.189|g" .env
    ok ".env created with node IPs filled in"
    warn "Edit .env to set passwords: nano ~/Local-System/.env"
else
    ok ".env already exists"
fi

# ============================================================
# Step 4m: Check for NFS mounts from VAULT
# ============================================================
step "Checking for NFS exports from VAULT"

NFS_EXPORTS=$(showmount -e "$VAULT_IP" 2>/dev/null || echo "none")
if [ "$NFS_EXPORTS" != "none" ]; then
    ok "VAULT NFS exports found:"
    echo "$NFS_EXPORTS"
    echo ""
    echo "  To mount (example):"
    echo "    sudo mkdir -p /mnt/vault/models /mnt/vault/data"
    echo "    sudo mount -t nfs ${VAULT_IP}:/mnt/models /mnt/vault/models"
else
    ok "No NFS exports found on VAULT (this is normal if VAULT runs Unraid with different sharing)"
fi

# ============================================================
# Step 5: Run Infrastructure Discovery
# ============================================================
step "Running infrastructure discovery"

cd ~/Local-System
if bash scripts/discover.sh; then
    ok "Discovery complete!"
    ok "Report saved to: docs/infrastructure-report.md"
    echo ""
    echo "  Review: cat ~/Local-System/docs/infrastructure-report.md"
else
    warn "Discovery had errors. Review output above."
    warn "You can re-run: cd ~/Local-System && bash scripts/discover.sh"
fi

# ============================================================
# Summary
# ============================================================
echo ""
echo "========================================"
echo "  DEV Node Setup Complete!"
echo "========================================"
echo ""
echo "  Node:     DEV (192.168.1.189)"
echo "  OS:       $(grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '"')"
echo "  Docker:   $(docker --version 2>/dev/null || echo 'needs re-login')"
echo "  Node.js:  $(node --version 2>/dev/null || echo 'not found')"
echo "  Python:   $(python3 --version 2>/dev/null)"
echo "  Ansible:  $(ansible --version 2>/dev/null | head -1)"
echo "  Claude:   $(claude --version 2>/dev/null || echo 'not found')"
echo ""
echo "  Next steps:"
echo "    1. Review infrastructure report:  cat ~/Local-System/docs/infrastructure-report.md"
echo "    2. Set passwords in .env:         nano ~/Local-System/.env"
echo "    3. Run from DESK via SSH:         ssh shaun@192.168.1.189"
echo "    4. Start Claude Code:             cd ~/Local-System && claude"
echo ""
echo "========================================"
