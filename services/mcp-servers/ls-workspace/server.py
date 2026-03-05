"""ls-workspace — Project workspace context MCP server.

Provides project context to any coding tool — CLAUDE.md content, recent git
history, active branch, project structure. When switching between Claude Code,
Kimi Code, and Codex, each tool can call get_project_context() to understand
the current state of the project.

Framework: FastMCP 2.0
Transport: stdio (over SSH from DESK/DEV)
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from fastmcp import FastMCP

# --- Configuration ---

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.expanduser("~/dev/local-system-v4"))
CLAUDE_MD = "CLAUDE.md"
DECISIONS_MD = "docs/DECISIONS.md"

# --- Helpers ---


def _run_git(args: list[str], cwd: str | None = None) -> str:
    """Run a git command and return stdout."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd or PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception as e:
        return f"Error: {e}"


def _read_file(path: str, max_lines: int = 200) -> str | None:
    """Read a file relative to project root, returning None if not found."""
    full_path = Path(PROJECT_ROOT) / path
    if not full_path.exists():
        return None
    try:
        lines = full_path.read_text(encoding="utf-8").splitlines()
        if len(lines) > max_lines:
            return "\n".join(lines[:max_lines]) + f"\n\n... ({len(lines) - max_lines} more lines)"
        return "\n".join(lines)
    except Exception:
        return None


# --- MCP Server ---

mcp = FastMCP(
    "ls-workspace",
    instructions=(
        "Project workspace context. Get CLAUDE.md content, git history, "
        "branch state, and project structure for any coding tool."
    ),
)


@mcp.tool()
async def get_project_context() -> dict:
    """Get comprehensive project context for tool onboarding.

    Returns CLAUDE.md content, current branch, recent git log,
    and key project files. Call this when starting a new session
    or switching from another tool to get up to speed.
    """
    context: dict = {
        "project_root": PROJECT_ROOT,
    }

    # Current branch
    context["branch"] = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])

    # Recent git log (last 20 commits, compact)
    context["recent_commits"] = _run_git([
        "log", "--oneline", "--no-decorate", "-20",
    ])

    # Git status (uncommitted changes)
    context["uncommitted_changes"] = _run_git(["status", "--short"])

    # CLAUDE.md content (the shared constitution)
    claude_md = _read_file(CLAUDE_MD)
    if claude_md:
        context["claude_md"] = claude_md
    else:
        context["claude_md"] = "(No CLAUDE.md found)"

    # DECISIONS.md if it exists
    decisions = _read_file(DECISIONS_MD)
    if decisions:
        context["decisions_md"] = decisions

    # Key project structure (top-level dirs)
    try:
        root = Path(PROJECT_ROOT)
        dirs = sorted([d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")])
        files = sorted([f.name for f in root.iterdir() if f.is_file() and not f.name.startswith(".")])
        context["structure"] = {
            "directories": dirs[:30],
            "root_files": files[:20],
        }
    except Exception:
        context["structure"] = {"error": "Could not read project structure"}

    return context


@mcp.tool()
async def list_recent_changes(since: str = "1 day ago", limit: int = 20) -> dict:
    """Show recent changes across all tools.

    Summarizes git diffs and commits since a given time, showing what
    each tool/developer has done. Useful for catching up after switching tools.

    Args:
        since: Time range (e.g., "1 day ago", "3 hours ago", "2026-03-04")
        limit: Maximum commits to show (default: 20)
    """
    # Commits with diff stats
    log = _run_git([
        "log", f"--since={since}", f"-{limit}",
        "--format=%h %ai %an: %s",
        "--stat",
    ])

    # Overall diff stat
    diff_stat = _run_git(["diff", "--stat", "HEAD~5..HEAD"])

    return {
        "since": since,
        "commits": log,
        "diff_summary": diff_stat,
        "branch": _run_git(["rev-parse", "--abbrev-ref", "HEAD"]),
    }


@mcp.tool()
async def read_project_file(path: str, max_lines: int = 200) -> dict:
    """Read a file from the project directory.

    Useful for reading CLAUDE.md, config files, or any project file
    from a remote MCP connection.

    Args:
        path: Relative path from project root (e.g., "CLAUDE.md", "services/gateway/main.py")
        max_lines: Maximum lines to return (default: 200, prevents huge outputs)
    """
    content = _read_file(path, max_lines=max_lines)
    if content is None:
        return {"error": f"File not found: {path}"}

    return {
        "path": path,
        "content": content,
        "lines": content.count("\n") + 1,
    }


@mcp.tool()
async def get_file_tree(directory: str = ".", depth: int = 2) -> dict:
    """Get a directory tree of the project.

    Shows the project structure to help understand code organization.
    Excludes common noise directories (node_modules, .git, __pycache__, etc.).

    Args:
        directory: Subdirectory to list (relative to project root, default: root)
        depth: How many levels deep to go (default: 2)
    """
    root = Path(PROJECT_ROOT) / directory
    if not root.exists():
        return {"error": f"Directory not found: {directory}"}

    SKIP = {
        "node_modules", ".git", "__pycache__", ".venv", "venv",
        ".next", ".cache", "dist", "build", ".mypy_cache",
        ".pytest_cache", ".ruff_cache", "egg-info",
    }

    tree: list[str] = []

    def _walk(path: Path, prefix: str, current_depth: int):
        if current_depth > depth:
            return

        try:
            entries = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            return

        for entry in entries:
            if entry.name in SKIP or entry.name.endswith(".egg-info"):
                continue

            if entry.is_dir():
                tree.append(f"{prefix}{entry.name}/")
                _walk(entry, prefix + "  ", current_depth + 1)
            else:
                tree.append(f"{prefix}{entry.name}")

    _walk(root, "", 1)

    return {
        "directory": directory,
        "tree": "\n".join(tree[:500]),
        "total_entries": len(tree),
    }


@mcp.tool()
async def search_project(
    pattern: str,
    file_glob: str = "*.py",
    max_results: int = 20,
) -> list[dict]:
    """Search for a pattern across project files using git grep.

    Useful for finding where something is defined or used across the codebase.

    Args:
        pattern: Search pattern (supports regex)
        file_glob: File pattern to search in (default: "*.py")
        max_results: Maximum results to return (default: 20)
    """
    output = _run_git([
        "grep", "-n", "--no-color", "-I",
        pattern, "--", file_glob,
    ])

    results = []
    for line in output.splitlines()[:max_results]:
        parts = line.split(":", 2)
        if len(parts) >= 3:
            results.append({
                "file": parts[0],
                "line": int(parts[1]) if parts[1].isdigit() else 0,
                "match": parts[2].strip(),
            })

    return results


def main():
    """Run the MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
