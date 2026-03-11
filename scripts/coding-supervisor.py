#!/usr/bin/env python3
"""coding-supervisor.py — Athanor Three-Tier Coding Dispatcher

Routes coding tasks to the optimal tier based on complexity:
  SIMPLE  → Aider single-pass (local Qwen3-Coder, free)
  MEDIUM  → Aider architect/editor (local Qwen3.5 + Qwen3-Coder, free)
  COMPLEX → Escalate to Claude Code (subscription)
  RESEARCH→ Local reasoning model or subscription

Usage:
  python coding-supervisor.py --task "add pagination to API" --repo /path/to/repo
  python coding-supervisor.py --task "fix typo in README" --tier simple
  python coding-supervisor.py --task "how to implement JWT auth" --tier research
  python coding-supervisor.py --task "refactor auth module" --n 3  # Best-of-N
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

# ─── Configuration ────────────────────────────────────────────────────────────

NTFY_URL = "http://192.168.1.203:8880/athanor"
LITELLM_URL = "http://192.168.1.203:4000/v1"
LITELLM_KEY = "sk-athanor-litellm-2026"

# Classification heuristics
SIMPLE_PATTERNS = [
    r"^fix\s+\w+$",                    # "fix typo"
    r"^rename\s+",                      # "rename function"
    r"^add\s+import",                   # "add import"
    r"^remove\s+\w+",                   # "remove unused"
    r"single.?line",
    r"\btypo\b",
    r"\bcomment\b",
    r"\bdocstring\b",
    r"\bformatting?\b",
]

COMPLEX_PATTERNS = [
    r"\barchitecture\b",
    r"\bredesign\b",
    r"\bmigration\b",
    r"\bsystem.?wide\b",
    r"\bcross.?service\b",
    r"\bbreaking.?change\b",
    r"\brefactor.{0,20}entire\b",
    r"\bmulti.?service\b",
]

RESEARCH_PATTERNS = [
    r"^how\s+to\b",
    r"^what\s+is\b",
    r"^find\s+",
    r"^search\s+",
    r"\bbest\s+way\b",
    r"\bwhich\s+library\b",
    r"\bcompare\b",
    r"\bexplain\b",
]


# ─── Types ────────────────────────────────────────────────────────────────────

class Tier(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"
    RESEARCH = "research"


@dataclass
class TaskResult:
    task_id: str
    tier: Tier
    task: str
    repo: Optional[Path]
    worktree: Optional[Path]
    branch: Optional[str]
    success: bool
    output: str
    duration_s: float
    error: Optional[str] = None
    files_changed: list[str] = field(default_factory=list)


# ─── Classification ───────────────────────────────────────────────────────────

def classify_task(task: str) -> Tier:
    """Classify task complexity using keyword heuristics."""
    task_lower = task.lower().strip()

    # Research first (questions)
    for pattern in RESEARCH_PATTERNS:
        if re.search(pattern, task_lower):
            return Tier.RESEARCH

    # Complex patterns
    for pattern in COMPLEX_PATTERNS:
        if re.search(pattern, task_lower):
            return Tier.COMPLEX

    # Simple patterns
    for pattern in SIMPLE_PATTERNS:
        if re.search(pattern, task_lower):
            return Tier.SIMPLE

    # Heuristic: short task description → likely simple
    word_count = len(task.split())
    if word_count <= 4:
        return Tier.SIMPLE
    if word_count >= 15:
        return Tier.MEDIUM

    # Default: medium
    return Tier.MEDIUM


# ─── Worktree Management ──────────────────────────────────────────────────────

def create_worktree(repo: Path, branch: str) -> Path:
    """Create a git worktree for isolated task execution."""
    worktree_base = repo / ".worktrees"
    worktree_base.mkdir(exist_ok=True)
    worktree_path = worktree_base / branch

    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree_path)],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Try without -b (branch may already exist)
        result = subprocess.run(
            ["git", "worktree", "add", str(worktree_path), branch],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create worktree: {result.stderr}")

    return worktree_path


def remove_worktree(repo: Path, worktree_path: Path) -> None:
    """Remove a git worktree and its branch."""
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=repo,
        capture_output=True,
    )


def get_changed_files(worktree: Path) -> list[str]:
    """Get list of files changed in the worktree."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=worktree,
        capture_output=True,
        text=True,
    )
    files = [f.strip() for f in result.stdout.splitlines() if f.strip()]

    # Also check staged files
    result2 = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=worktree,
        capture_output=True,
        text=True,
    )
    staged = [f.strip() for f in result2.stdout.splitlines() if f.strip()]
    return list(set(files + staged))


# ─── Task Executors ──────────────────────────────────────────────────────────

def run_aider_simple(task: str, worktree: Path, timeout: int = 300) -> tuple[bool, str]:
    """Run aider in single-pass mode for simple tasks."""
    cmd = [
        "aider",
        "--message", task,
        "--yes-always",
        "--no-auto-commits",  # We'll commit after review
        "--no-suggest-shell-commands",
    ]

    result = subprocess.run(
        cmd,
        cwd=worktree,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = result.stdout + ("\n" + result.stderr if result.stderr else "")
    return result.returncode == 0, output


def run_aider_medium(task: str, worktree: Path, timeout: int = 600) -> tuple[bool, str]:
    """Run aider in architect/editor mode for medium complexity tasks."""
    cmd = [
        "aider",
        "--architect",
        "--message", task,
        "--yes-always",
        "--no-auto-commits",
        "--no-suggest-shell-commands",
    ]

    result = subprocess.run(
        cmd,
        cwd=worktree,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = result.stdout + ("\n" + result.stderr if result.stderr else "")
    return result.returncode == 0, output


def run_research(task: str, timeout: int = 120) -> tuple[bool, str]:
    """Run a research query via local reasoning model."""
    import urllib.request

    payload = json.dumps({
        "model": "reasoning",
        "messages": [
            {
                "role": "system",
                "content": "You are a technical research assistant. Answer concisely with code examples where relevant.",
            },
            {"role": "user", "content": task},
        ],
        "max_tokens": 4096,
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        f"{LITELLM_URL}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LITELLM_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            content = data["choices"][0]["message"]["content"]
            return True, content
    except Exception as e:
        return False, f"Research query failed: {e}"


# ─── Test Runner (Phase C-5) ─────────────────────────────────────────────────

def detect_test_runner(worktree: Path) -> tuple[list[str], str]:
    """Auto-detect the appropriate test runner for this project."""
    # Python: pytest
    has_pytest_cfg = any(
        worktree.joinpath(f).exists()
        for f in ["pytest.ini", "setup.cfg", ".pytest.ini"]
    )
    has_pyproject = worktree.joinpath("pyproject.toml").exists()
    test_files = list(worktree.rglob("test_*.py"))[:1] + list(worktree.rglob("*_test.py"))[:1]
    if has_pytest_cfg or (has_pyproject and test_files) or test_files:
        return ["python", "-m", "pytest", "-x", "--tb=short", "-q", "--no-header"], "pytest"

    # JavaScript / TypeScript: npm test
    pkg_json = worktree / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text())
            if "test" in pkg.get("scripts", {}):
                return ["npm", "test", "--", "--passWithNoTests"], "npm"
        except Exception:
            pass

    # Go
    if (worktree / "go.mod").exists():
        return ["go", "test", "./...", "-count=1"], "go"

    # Rust
    if (worktree / "Cargo.toml").exists():
        return ["cargo", "test", "--quiet"], "cargo"

    return [], "none"


def run_tests(worktree: Path, test_cmd: list[str], timeout: int = 120) -> tuple[bool, str]:
    """Run the test suite. Returns (passed, output)."""
    if not test_cmd:
        return True, "No tests detected (assuming pass)"

    result = subprocess.run(
        test_cmd,
        cwd=worktree,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = result.stdout + ("\n" + result.stderr if result.stderr else "")
    return result.returncode == 0, output


# ─── Iterative Refinement (Phase C-5) ────────────────────────────────────────

def run_with_refinement(
    task: str,
    worktree: Path,
    tier: Tier,
    max_iterations: int = 5,
    verbose: bool = False,
) -> tuple[bool, str, int]:
    """Iterative generate→test→fix loop. Returns (success, combined_output, iterations_used).

    With free local tokens this costs $0 regardless of iterations.
    Typical stopping conditions:
      - Tests pass (success)
      - Aider fails to make changes (stuck)
      - max_iterations exhausted
    """
    combined_output: list[str] = []
    current_task = task

    for i in range(max_iterations):
        label = f"[iter {i+1}/{max_iterations}]"
        if verbose:
            print(f"[supervisor] {label} Running aider ({tier.value})...")

        # Generate
        if tier == Tier.SIMPLE:
            aider_ok, aider_out = run_aider_simple(current_task, worktree)
        else:
            aider_ok, aider_out = run_aider_medium(current_task, worktree)

        combined_output.append(f"=== Aider {label} ===\n{aider_out[-800:]}")

        if not aider_ok:
            if verbose:
                print(f"[supervisor] {label} Aider failed; stopping refinement")
            return False, "\n".join(combined_output), i + 1

        # Re-detect test runner after each aider run (aider may have created tests)
        test_cmd, runner_name = detect_test_runner(worktree)
        if verbose:
            print(f"[supervisor] {label} Test runner: {runner_name}")

        # Test
        if not test_cmd:
            if verbose:
                print(f"[supervisor] {label} No tests detected; accepting aider output")
            return True, "\n".join(combined_output), i + 1

        if verbose:
            print(f"[supervisor] {label} Running {runner_name} tests...")
        tests_ok, test_out = run_tests(worktree, test_cmd)
        combined_output.append(f"=== Tests {label} ({runner_name}) ===\n{test_out[-1500:]}")

        if tests_ok:
            if verbose:
                print(f"[supervisor] {label} All tests pass!")
            return True, "\n".join(combined_output), i + 1

        # Feed failures back as next task
        if i < max_iterations - 1:
            failures_snip = test_out[-1200:]
            current_task = (
                f"Fix these test failures. Original task: {task}\n\n"
                f"Test output:\n{failures_snip}"
            )
            if verbose:
                print(f"[supervisor] {label} Tests failed — refining...")

    # Exhausted iterations; report partial success
    return False, "\n".join(combined_output), max_iterations


# ─── Memory Integration (Phase C-6) ──────────────────────────────────────────

MEMORY_URL = "http://192.168.1.189:8720"


def query_memory_context(task: str, limit: int = 3) -> str:
    """Query episodic + procedural memory for relevant past experience."""
    import urllib.request

    payload = json.dumps({
        "query": task,
        "limit": limit,
        "tiers": ["episodic", "procedural"],
    }).encode()

    req = urllib.request.Request(
        f"{MEMORY_URL}/v1/memory/search",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            memories = data.get("results", [])
            parts = ["Relevant past experience:"]
            for m in memories:
                content = m.get("content", "")
                score = m.get("score", 0.0)
                if content and score > 0.65:
                    parts.append(f"- {content[:200]}")
            return "\n".join(parts) if len(parts) > 1 else ""
    except Exception:
        return ""  # Best-effort


def store_memory_result(task: str, result: "TaskResult") -> None:
    """Store task outcome in episodic memory for future reference."""
    import urllib.request

    status = "SUCCESS" if result.success else "FAILURE"
    content = (
        f"Coding task ({result.tier.value}): {task}\n"
        f"Result: {status} in {result.duration_s:.1f}s. "
        f"Files: {', '.join(str(f) for f in result.files_changed[:5]) or 'none'}"
    )
    if result.error:
        content += f" Error: {result.error}"

    payload = json.dumps({
        "tier": "episodic",
        "content": content,
        "metadata": {
            "task_id": result.task_id,
            "tier": result.tier.value,
            "success": result.success,
            "source": "coding-supervisor",
        },
    }).encode()

    req = urllib.request.Request(
        f"{MEMORY_URL}/v1/memory/store",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass  # Best-effort


# ─── Best-of-N ────────────────────────────────────────────────────────────────

def run_best_of_n(
    task: str,
    repo: Path,
    branch_prefix: str,
    n: int,
    tier: Tier,
    verbose: bool = False,
) -> tuple[bool, str, Path, str]:
    """Generate N solutions in parallel worktrees, return the best one.

    Returns: (success, output, best_worktree_path, best_branch)
    """
    import concurrent.futures

    if verbose:
        print(f"[supervisor] Generating {n} candidate solutions...")

    def run_candidate(i: int) -> dict:
        branch = f"{branch_prefix}-candidate-{i}"
        worktree = None
        try:
            worktree = create_worktree(repo, branch)
            start = time.time()
            if tier == Tier.SIMPLE:
                success, output = run_aider_simple(task, worktree)
            else:
                success, output = run_aider_medium(task, worktree)
            duration = time.time() - start
            files = get_changed_files(worktree)
            return {
                "i": i,
                "branch": branch,
                "worktree": worktree,
                "success": success,
                "output": output,
                "duration": duration,
                "files_changed": len(files),
                "files": files,
            }
        except Exception as e:
            if worktree and repo:
                try:
                    remove_worktree(repo, worktree)
                except Exception:
                    pass
            return {
                "i": i,
                "branch": branch,
                "worktree": worktree,
                "success": False,
                "output": str(e),
                "duration": 0,
                "files_changed": 0,
                "files": [],
            }

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(n, 5)) as executor:
        futures = [executor.submit(run_candidate, i) for i in range(n)]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    # Rank: prefer successful + more files changed (more complete solution)
    successful = [r for r in results if r["success"]]
    candidates = successful if successful else results

    # Simple scoring: success + files changed
    best = max(candidates, key=lambda r: (r["success"], r["files_changed"]))

    if verbose:
        print(f"[supervisor] Best candidate: {best['branch']} ({best['files_changed']} files changed)")

    # Clean up losing candidates
    for r in results:
        if r["branch"] != best["branch"] and r["worktree"]:
            try:
                remove_worktree(repo, r["worktree"])
                subprocess.run(
                    ["git", "branch", "-D", r["branch"]],
                    cwd=repo,
                    capture_output=True,
                )
            except Exception:
                pass

    return best["success"], best["output"], best["worktree"], best["branch"]


# ─── Notifications ────────────────────────────────────────────────────────────

def send_ntfy(title: str, body: str, tags: list[str] | None = None) -> None:
    """Send ntfy push notification to VAULT."""
    import urllib.request

    payload = json.dumps({
        "topic": "athanor",
        "title": title[:100],  # ASCII-safe truncation
        "message": body[:500],
        "tags": tags or ["computer"],
        "priority": 3,
    }).encode()

    try:
        req = urllib.request.Request(
            NTFY_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass  # Notifications are best-effort


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Athanor Coding Supervisor — Three-Tier Task Dispatcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--task", "-t", required=True, help="Task description")
    parser.add_argument(
        "--repo",
        "-r",
        type=Path,
        default=Path.cwd(),
        help="Target git repository (default: current dir)",
    )
    parser.add_argument(
        "--branch",
        "-b",
        help="Worktree branch name (auto-generated if not provided)",
    )
    parser.add_argument(
        "--tier",
        choices=["auto", "simple", "medium", "complex", "research"],
        default="auto",
        help="Force a specific tier (default: auto-classify)",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=1,
        help="Best-of-N: generate N solutions and pick the best (default: 1)",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Send ntfy push notification when done",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and show plan, but don't execute",
    )
    parser.add_argument(
        "--no-worktree",
        action="store_true",
        help="Skip worktree creation, run directly in repo",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument(
        "--refine",
        action="store_true",
        help="Enable iterative refinement: generate→test→fix loop (Phase C-5)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=5,
        metavar="N",
        help="Max refinement iterations when --refine is set (default: 5)",
    )
    parser.add_argument(
        "--use-memory",
        action="store_true",
        help="Query memory for context before task, store result after (Phase C-6)",
    )

    args = parser.parse_args()
    verbose = args.verbose

    # ── Classify ───────────────────────────────────────────────────────────────
    if args.tier == "auto":
        tier = classify_task(args.task)
    else:
        tier = Tier(args.tier)

    task_id = str(uuid.uuid4())[:8]
    branch = args.branch or f"athanor/{task_id}"

    print(f"[supervisor] Task: {args.task!r}")
    print(f"[supervisor] Tier: {tier.value.upper()}  |  Branch: {branch}  |  N={args.n}"
          + (f"  |  refine={args.max_iterations}x" if args.refine else ""))

    # ── Memory pre-query (Phase C-6) ───────────────────────────────────────────
    memory_context = ""
    if args.use_memory and tier not in (Tier.COMPLEX,):
        if verbose:
            print("[supervisor] Querying memory for relevant context...")
        memory_context = query_memory_context(args.task)
        if memory_context and verbose:
            print(f"[supervisor] Memory context: {memory_context[:200]}")

    # Augment task with memory context if available
    effective_task = args.task
    if memory_context:
        effective_task = f"{args.task}\n\n[Context from memory]\n{memory_context}"

    if args.dry_run:
        print(f"[supervisor] DRY RUN — would dispatch to tier={tier.value}")
        if tier == Tier.COMPLEX:
            print("[supervisor] ESCALATE: This task requires Claude Code orchestration.")
            print("             Run: claude code --task <task> --repo <path>")
        return 0

    # ── Validate repo ──────────────────────────────────────────────────────────
    repo = args.repo.resolve()
    if not (repo / ".git").exists() and tier not in (Tier.RESEARCH,):
        # Check if current dir is inside a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"[supervisor] ERROR: {repo} is not a git repository")
            print("[supervisor] Use --repo /path/to/repo or run from inside a repo")
            return 1
        repo = Path(result.stdout.strip())

    # ── Dispatch ───────────────────────────────────────────────────────────────
    start_time = time.time()
    result = TaskResult(
        task_id=task_id,
        tier=tier,
        task=args.task,
        repo=repo,
        worktree=None,
        branch=branch,
        success=False,
        output="",
        duration_s=0.0,
    )

    try:
        if tier == Tier.RESEARCH:
            print("[supervisor] Running research query via local reasoning model...")
            result.success, result.output = run_research(effective_task)
            if result.success:
                print("\n" + "─" * 60)
                print(result.output)
                print("─" * 60)

        elif tier == Tier.COMPLEX:
            print("[supervisor] COMPLEX task — escalating to Claude Code")
            print()
            print("  This task requires subscription-tier orchestration.")
            print("  Run Claude Code directly:")
            print(f"    claude --task {args.task!r} --repo {repo}")
            print()
            result.success = True
            result.output = "ESCALATED: Use Claude Code for complex orchestration."

        elif args.n > 1:
            # Best-of-N mode
            if args.no_worktree:
                print("[supervisor] ERROR: --no-worktree incompatible with --n > 1")
                return 1
            result.success, result.output, result.worktree, result.branch = run_best_of_n(
                effective_task, repo, branch, args.n, tier, verbose=verbose
            )
            if result.success and result.worktree:
                result.files_changed = get_changed_files(result.worktree)
                print(f"[supervisor] Best solution in worktree: {result.worktree}")
                print(f"[supervisor] Files changed: {result.files_changed}")

        else:
            # Single execution (with optional iterative refinement)
            if args.no_worktree:
                worktree = repo
            else:
                print(f"[supervisor] Creating worktree: {branch}")
                worktree = create_worktree(repo, branch)
                result.worktree = worktree

            if args.refine:
                print(f"[supervisor] Dispatching {tier.value.upper()} task with refinement (max {args.max_iterations} iterations)...")
                result.success, result.output, iterations_used = run_with_refinement(
                    effective_task, worktree, tier,
                    max_iterations=args.max_iterations,
                    verbose=verbose,
                )
                print(f"[supervisor] Refinement finished: {iterations_used} iteration(s)")
            else:
                print(f"[supervisor] Dispatching {tier.value.upper()} task to aider...")
                if tier == Tier.SIMPLE:
                    result.success, result.output = run_aider_simple(effective_task, worktree)
                else:
                    result.success, result.output = run_aider_medium(effective_task, worktree)

            result.files_changed = get_changed_files(worktree)

            if verbose:
                print(result.output)

            if result.success:
                print(f"[supervisor] Done. Files changed: {result.files_changed}")
            else:
                print(f"[supervisor] Aider returned non-zero exit")
                if not verbose:
                    print(result.output[-2000:])  # Show tail of output on failure

    except subprocess.TimeoutExpired:
        result.error = "Timeout"
        print(f"[supervisor] TIMEOUT after task execution")
    except Exception as e:
        result.error = str(e)
        print(f"[supervisor] ERROR: {e}")
        if verbose:
            import traceback
            traceback.print_exc()

    result.duration_s = time.time() - start_time

    # ── Memory post-store (Phase C-6) ──────────────────────────────────────────
    if args.use_memory and tier not in (Tier.COMPLEX,):
        if verbose:
            print("[supervisor] Storing result in episodic memory...")
        store_memory_result(args.task, result)

    # ── Summary ────────────────────────────────────────────────────────────────
    status = "SUCCESS" if result.success else "FAILED"
    summary = (
        f"[{status}] {tier.value.upper()} task completed in {result.duration_s:.1f}s"
    )
    if result.files_changed:
        summary += f" | {len(result.files_changed)} files changed"
    print(f"\n[supervisor] {summary}")

    # ── Notification ───────────────────────────────────────────────────────────
    if args.notify or result.success:
        emoji = "white_check_mark" if result.success else "x"
        ntfy_title = f"[{status}] {tier.value.upper()}: {args.task[:50]}"
        ntfy_body = summary
        if result.files_changed:
            ntfy_body += f"\nFiles: {', '.join(str(f) for f in result.files_changed[:5])}"
        send_ntfy(ntfy_title, ntfy_body, tags=[emoji, "coding"])

    # ── Output summary JSON (for MCP/programmatic consumption) ────────────────
    output_data = {
        "task_id": result.task_id,
        "tier": result.tier.value,
        "success": result.success,
        "duration_s": round(result.duration_s, 2),
        "files_changed": [str(f) for f in result.files_changed],
        "worktree": str(result.worktree) if result.worktree else None,
        "branch": result.branch,
        "error": result.error,
    }
    # Write to stdout as JSON if piped (for Claude Code to parse)
    if not sys.stdout.isatty():
        print(json.dumps(output_data))

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
