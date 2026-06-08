#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# WORKSHOP Fix Script — Run this ON WORKSHOP physically or via KVM
# ═══════════════════════════════════════════════════════════════════════════════
#
# This script fixes two critical issues:
# 1. SSH access from DEV and DESK
# 2. ComfyUI GPU assignment (move from RTX 5060 Ti to RTX 5090)
#
# Prerequisites: Physical keyboard/monitor access to WORKSHOP (192.168.1.225)
# Login as: shaun
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

echo "═══════════════════════════════════════════════════════════"
echo "WORKSHOP Fix Script"
echo "═══════════════════════════════════════════════════════════"

# ─── Step 1: Fix SSH ──────────────────────────────────────────────────────────

echo ""
echo "Step 1: Fixing SSH access..."

mkdir -p ~/.ssh
chmod 700 ~/.ssh

# DEV's SSH key
grep -q "shaun@dev" ~/.ssh/authorized_keys 2>/dev/null || \
    echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJKaee9vWA8yL0sGNPL7RuSukcrrCdqRAqLsh5TTJECs shaun@dev" >> ~/.ssh/authorized_keys

# DESK's SSH key (same key used for both DESK and DEV→WORKSHOP)
grep -q "athanor-dev" ~/.ssh/authorized_keys 2>/dev/null || \
    echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPPhHXNRotfpbt1PRuj6fYtxiGv6XUbsFkeIC/KxPOGY athanor-dev" >> ~/.ssh/authorized_keys

chmod 600 ~/.ssh/authorized_keys

# Ensure sshd allows pubkey auth
sudo sed -i 's/^#\?PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?AuthorizedKeysFile.*/AuthorizedKeysFile .ssh\/authorized_keys/' /etc/ssh/sshd_config
sudo systemctl restart sshd

echo "  ✓ SSH keys added, sshd restarted"
echo "  Test: ssh shaun@192.168.1.225 from DEV or DESK"

# ─── Step 2: Identify GPUs ───────────────────────────────────────────────────

echo ""
echo "Step 2: Current GPU layout..."
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
echo ""

# Get GPU info
GPU0_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader -i 0 2>/dev/null || echo "unknown")
GPU1_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader -i 1 2>/dev/null || echo "unknown")
GPU0_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits -i 0 2>/dev/null || echo "0")
GPU1_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits -i 1 2>/dev/null || echo "0")

echo "  GPU 0: $GPU0_NAME ($GPU0_MEM MB)"
echo "  GPU 1: $GPU1_NAME ($GPU1_MEM MB)"

# Determine which GPU is larger (for ComfyUI) and which is smaller (for vLLM-fast)
if [ "$GPU0_MEM" -gt "$GPU1_MEM" ]; then
    COMFYUI_GPU=0
    VLLM_GPU=1
    echo "  → ComfyUI should use GPU $COMFYUI_GPU ($GPU0_NAME, ${GPU0_MEM}MB)"
    echo "  → vLLM-fast should use GPU $VLLM_GPU ($GPU1_NAME, ${GPU1_MEM}MB)"
else
    COMFYUI_GPU=1
    VLLM_GPU=0
    echo "  → ComfyUI should use GPU $COMFYUI_GPU ($GPU1_NAME, ${GPU1_MEM}MB)"
    echo "  → vLLM-fast should use GPU $VLLM_GPU ($GPU0_NAME, ${GPU0_MEM}MB)"
fi

# ─── Step 3: Fix ComfyUI Docker GPU Assignment ───────────────────────────────

echo ""
echo "Step 3: Checking Docker Compose for ComfyUI..."

# Find docker-compose file
COMPOSE_FILE=""
for path in \
    /home/shaun/docker-compose.yml \
    /home/shaun/docker/docker-compose.yml \
    /home/shaun/comfyui/docker-compose.yml \
    /opt/docker/docker-compose.yml \
    /home/shaun/dev/local-system-v4/deploy/workshop/docker-compose.yml; do
    if [ -f "$path" ]; then
        COMPOSE_FILE="$path"
        break
    fi
done

if [ -z "$COMPOSE_FILE" ]; then
    echo "  ⚠️  Could not find docker-compose.yml automatically."
    echo "  Run: find / -name docker-compose.yml -path '*workshop*' -o -name docker-compose.yml -path '*comfyui*' 2>/dev/null"
    echo "  Then manually set NVIDIA_VISIBLE_DEVICES=$COMFYUI_GPU for ComfyUI"
else
    echo "  Found: $COMPOSE_FILE"
    echo ""
    echo "  Current NVIDIA_VISIBLE_DEVICES settings:"
    grep -n "NVIDIA_VISIBLE_DEVICES" "$COMPOSE_FILE" || echo "  (not found)"
    echo ""
    echo "  To fix, edit $COMPOSE_FILE:"
    echo "    - ComfyUI container: NVIDIA_VISIBLE_DEVICES=$COMFYUI_GPU"
    echo "    - vLLM-fast container (if Docker): NVIDIA_VISIBLE_DEVICES=$VLLM_GPU"
    echo ""
    echo "  Then restart:"
    echo "    cd $(dirname $COMPOSE_FILE)"
    echo "    docker compose down"
    echo "    docker compose up -d"
fi

# ─── Step 4: Check vLLM-fast ─────────────────────────────────────────────────

echo ""
echo "Step 4: Checking vLLM-fast..."

if systemctl is-active --quiet vllm-fast 2>/dev/null; then
    echo "  vLLM-fast is a systemd service (not Docker)"
    echo "  Check: systemctl cat vllm-fast | grep -i cuda"
    echo "  Set CUDA_VISIBLE_DEVICES=$VLLM_GPU in the service file"
    echo "  Then: sudo systemctl daemon-reload && sudo systemctl restart vllm-fast"
elif docker ps --format '{{.Names}}' | grep -qi vllm; then
    echo "  vLLM-fast is a Docker container"
    docker ps --format '{{.Names}} {{.Image}}' | grep -i vllm
else
    echo "  ⚠️  Could not find vLLM-fast. Check manually."
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "After fixing GPU assignments, verify with:"
echo "  nvidia-smi  (should show correct processes on correct GPUs)"
echo "  curl http://localhost:8188/system_stats  (ComfyUI should report larger GPU)"
echo "  curl http://localhost:8000/health  (vLLM-fast should respond)"
echo ""
echo "Then from DEV, re-enable the generation scheduler:"
echo "  curl -X POST http://127.0.0.1:8700/v1/generate/scheduler/start \\"
echo "    -H 'Authorization: Bearer x3noSiKVrorjqzJVch6VSv7iM5QmzULBjKR53LIR_1g'"
echo "═══════════════════════════════════════════════════════════"
