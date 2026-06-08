"""ls-tools — Tool registry & utility execution MCP server.

Meta-server that provides:
  - Discovery of all available MCP servers and their tools
  - Script execution on the DEV node
  - Quick cluster utility commands
  - Environment variable management

Framework: FastMCP 2.0
Transport: stdio (over SSH from DESK/DEV)
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import httpx
from fastmcp import FastMCP

# --- Configuration ---

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.expanduser("~/dev/local-system-v4"))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")

FOUNDRY_HOST = os.environ.get("FOUNDRY_HOST", "192.168.1.244")
WORKSHOP_HOST = os.environ.get("WORKSHOP_HOST", "192.168.1.225")
VAULT_HOST = os.environ.get("VAULT_HOST", "192.168.1.203")
DEV_HOST = os.environ.get("DEV_HOST", "192.168.1.189")

_health_client: httpx.AsyncClient | None = None


async def _get_health_client() -> httpx.AsyncClient:
    """Get or create the shared health-check client."""
    global _health_client
    if _health_client is None or _health_client.is_closed:
        _health_client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
    return _health_client

# --- Tool Registry ---

TOOL_REGISTRY = {
    "ls-inference": {
        "description": "Local & cloud model access (completions, embeddings, reranking)",
        "tools": ["complete", "embed", "rerank", "list_models", "gpu_status"],
        "primary_use": "Run AI inference on any model in the cluster or cloud",
    },
    "ls-memory": {
        "description": "Shared memory for tool interchangeability",
        "tools": [
            "memory_store", "memory_search", "memory_recall",
            "memory_list_sessions", "memory_delete", "memory_list_tags",
            "memory_export",
        ],
        "primary_use": "Store/recall decisions and context across coding tools",
    },
    "ls-knowledge": {
        "description": "RAG search & knowledge base access",
        "tools": ["search", "search_memory", "ingest", "list_collections", "get_working_memory"],
        "primary_use": "Search documents and memory tiers with hybrid vector+BM25",
    },
    "ls-infra": {
        "description": "Cluster infrastructure monitoring",
        "tools": ["cluster_health", "gpu_status", "litellm_models", "service_logs", "docker_status"],
        "primary_use": "Monitor GPU health, services, containers, and databases",
    },
    "ls-workspace": {
        "description": "Project workspace context",
        "tools": [
            "get_project_context", "list_recent_changes",
            "read_project_file", "get_file_tree", "search_project",
        ],
        "primary_use": "Get project context, git history, and file structure",
    },
    "ls-creative": {
        "description": "ComfyUI image generation",
        "tools": [
            "generate_image", "generate_face", "generate_queen",
            "list_pipelines", "list_queens", "generation_status",
            "list_comfyui_models", "generation_history",
        ],
        "primary_use": "Generate images with FLUX pipelines and face identity",
    },
    "ls-tools": {
        "description": "This server — tool discovery and utilities",
        "tools": [
            "discover_tools", "run_script", "cluster_quick_check",
            "restart_service", "tail_logs",
        ],
        "primary_use": "Find the right tool, run scripts, quick cluster ops",
    },
}

# --- MCP Server ---

mcp = FastMCP(
    "ls-tools",
    instructions=(
        "Tool discovery and cluster utilities. Use discover_tools to find "
        "which MCP server has the tool you need. Run scripts and quick "
        "cluster commands without leaving your coding tool."
    ),
)


@mcp.tool()
async def discover_tools(query: str | None = None) -> list[dict]:
    """Find the right MCP server and tool for your task.

    Returns all available MCP servers with their tools, or filters
    by a search query to find the most relevant tool.

    Args:
        query: Optional search term (e.g., "generate image", "search memory",
               "gpu health"). If omitted, lists all servers and tools.
    """
    results = []
    query_lower = query.lower() if query else None

    for server_name, info in TOOL_REGISTRY.items():
        if query_lower:
            # Check if query matches server description, tools, or primary use
            searchable = (
                f"{server_name} {info['description']} "
                f"{info['primary_use']} {' '.join(info['tools'])}"
            ).lower()
            if query_lower not in searchable:
                continue

        results.append({
            "server": server_name,
            "description": info["description"],
            "primary_use": info["primary_use"],
            "tools": info["tools"],
            "tool_count": len(info["tools"]),
        })

    if not results and query:
        return [{"message": f"No tools match '{query}'. Try a broader search term."}]

    return results


@mcp.tool()
async def run_script(
    script_name: str,
    args: list[str] | None = None,
    timeout: int = 30,
) -> dict:
    """Run a project script from the scripts/ directory.

    Only scripts within the project's scripts/ directory can be executed.
    This prevents arbitrary command execution.

    Args:
        script_name: Script filename (e.g., "vllm-health-restart.sh", "deploy.sh")
        args: Optional arguments to pass to the script
        timeout: Maximum execution time in seconds (default: 30)
    """
    script_path = Path(SCRIPTS_DIR) / script_name
    if not script_path.exists():
        # List available scripts
        available = []
        scripts_dir = Path(SCRIPTS_DIR)
        if scripts_dir.exists():
            available = [f.name for f in scripts_dir.iterdir() if f.is_file()]
        return {
            "error": f"Script not found: {script_name}",
            "available_scripts": available,
        }

    # Security: ensure script is within scripts dir (no path traversal)
    try:
        script_path.resolve().relative_to(Path(SCRIPTS_DIR).resolve())
    except ValueError:
        return {"error": "Path traversal detected — script must be in scripts/ directory"}

    cmd = [str(script_path)] + (args or [])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=PROJECT_ROOT,
        )
        return {
            "script": script_name,
            "exit_code": result.returncode,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-1000:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Script timed out after {timeout}s"}
    except Exception as e:
        return {"error": f"Script execution failed: {e}"}


@mcp.tool()
async def cluster_quick_check() -> dict:
    """Quick health check of all cluster nodes (ping + key port).

    Faster than ls-infra's full cluster_health — just checks reachability.
    """
    nodes = {
        "FOUNDRY": (FOUNDRY_HOST, 8000, "/health"),
        "WORKSHOP": (WORKSHOP_HOST, 8000, "/health"),
        "VAULT": (VAULT_HOST, 4000, "/health"),
        "DEV": (DEV_HOST, 8700, "/health"),
    }

    results = {}
    client = await _get_health_client()
    for name, (host, port, path) in nodes.items():
        try:
            resp = await client.get(f"http://{host}:{port}{path}")
            results[name] = f"up ({resp.status_code})"
        except Exception:
            results[name] = "down"

    return results


@mcp.tool()
async def restart_service(
    service: str,
    node: str = "dev",
) -> dict:
    """Restart a service on the cluster.

    Args:
        service: Service name (e.g., "gateway", "memory", "litellm")
        node: Node to restart on — "dev", "vault", "foundry" (default: "dev")
    """
    host_map = {
        "dev": None,  # local
        "vault": f"root@{VAULT_HOST}",
        "foundry": f"athanor@{FOUNDRY_HOST}",
    }

    ssh_target = host_map.get(node)
    if ssh_target is None and node != "dev":
        return {"error": f"Unknown node: {node}"}

    # DEV services run as uvicorn processes
    if node == "dev":
        try:
            result = subprocess.run(
                ["sudo", "systemctl", "restart", f"local-system-{service}"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                # Fallback: try pkill + restart
                return {
                    "service": service,
                    "action": "systemctl restart attempted",
                    "exit_code": result.returncode,
                    "stderr": result.stderr[:500],
                }
            return {"service": service, "node": node, "status": "restarted"}
        except Exception as e:
            return {"error": f"Restart failed: {e}"}

    # Remote nodes use docker
    try:
        result = subprocess.run(
            ["ssh", ssh_target, f"docker restart {service}"],
            capture_output=True, text=True, timeout=30,
        )
        return {
            "service": service,
            "node": node,
            "status": "restarted" if result.returncode == 0 else "failed",
            "output": result.stdout[:500] or result.stderr[:500],
        }
    except Exception as e:
        return {"error": f"Remote restart failed: {e}"}


@mcp.tool()
async def tail_logs(
    service: str,
    lines: int = 30,
    node: str = "dev",
) -> dict:
    """Get recent log output from a service.

    Args:
        service: Service name (e.g., "gateway", "memory", "litellm")
        lines: Number of lines to return (default: 30)
        node: Node — "dev", "vault", "foundry" (default: "dev")
    """
    host_map = {
        "dev": None,
        "vault": f"root@{VAULT_HOST}",
        "foundry": f"athanor@{FOUNDRY_HOST}",
    }

    ssh_target = host_map.get(node)

    if node == "dev":
        cmd = ["journalctl", "-u", f"local-system-{service}", "-n", str(lines), "--no-pager"]
    elif ssh_target:
        cmd = ["ssh", ssh_target, f"docker logs --tail {lines} {service}"]
    else:
        return {"error": f"Unknown node: {node}"}

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        output = result.stdout or result.stderr
        return {
            "service": service,
            "node": node,
            "lines": lines,
            "logs": output[-3000:] if output else "No output",
        }
    except Exception as e:
        return {"error": f"Failed to get logs: {e}"}


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
