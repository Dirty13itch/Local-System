#!/usr/bin/env bash
# Local-System — Initial setup script
# Run on each node to prepare the environment.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Local-System Setup ==="
echo "Project: $PROJECT_DIR"
echo ""

# Check prerequisites
check_command() {
    if ! command -v "$1" &>/dev/null; then
        echo "ERROR: $1 is not installed."
        return 1
    fi
    echo "  [OK] $1 $(command -v "$1")"
}

echo "Checking prerequisites..."
check_command docker
check_command python3
check_command node
check_command git
echo ""

# Create .env if it doesn't exist
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "Creating .env from .env.example..."
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo "  -> Edit .env with your node-specific settings."
else
    echo ".env already exists."
fi
echo ""

# Install Python shared library
echo "Installing shared Python library..."
cd "$PROJECT_DIR"
pip install -e shared/python 2>/dev/null || pip install -e shared/python[dev]
echo ""

# Install UI dependencies
echo "Installing UI dependencies..."
cd "$PROJECT_DIR/ui"
if [ -f "package.json" ]; then
    npm install
fi
echo ""

echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your node settings (NODE_NAME, network IPs)"
echo "  2. Start services: make up NODE=<your-node>"
echo "  3. Check health: make health"
