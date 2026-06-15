#!/usr/bin/env python3
"""mangopi-cli end-to-end benchmark framework.

Evaluates the AI agent on real tasks by:
    1. Setting up a workspace with initial files
    2. Running a natural-language prompt through the LLM agent pipeline
    3. Verifying the workspace state matches expectations
    4. Measuring tool-call efficiency, token usage, and wall-clock time

Requires MANGO_KEY (and optionally MANGO_MODEL) env vars set.
"""

import io
import os
import sys
import time
import contextlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Ensure the project root is on sys.path so we can import mangopi_cli.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mangopi_cli  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class TaskResult:
    """Result of running a single benchmark task."""
    task_name: str
    level: int
    passed: bool
    detail: str                               # verification detail / error message
    tool_calls: List[Dict] = field(default_factory=list)
    tool_call_count: int = 0
    unique_tools: List[str] = field(default_factory=list)
    wall_time_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    iterations: int = 0                       # agent loop iterations (LLM round-trips)
    error: Optional[str] = None


class BenchmarkTask:
    """Definition of a single benchmark scenario.

    Subclasses declare attributes as class variables; they are automatically
    bound to the instance.  Iteration order follows MRO in reverse so that
    the most-derived class always wins.
    """

    # ── required (set in subclass body) ─────────────────────────────────────
    name: str = ""
    description: str = ""
    level: int = 0
    prompt: str = ""

    # ── optional (override in subclass body if needed) ───────────────────────
    setup_files: Dict[str, str] = {}
    timeout: int = 120
    max_tool_calls: int = 20
    retries: int = 1

    _BASE_DEFAULTS = {
        "name": "", "description": "", "level": 0, "prompt": "",
        "setup_files": {}, "timeout": 120, "max_tool_calls": 20, "retries": 1,
    }

    def __init__(self, **kwargs):
        # 1. Apply base defaults
        for k, v in self._BASE_DEFAULTS.items():
            setattr(self, k, v)
        # 2. Walk MRO in REVERSE so most-derived class wins
        for cls in reversed(type(self).__mro__):
            for k, v in cls.__dict__.items():
                if k.startswith("_") or k.startswith("__"):
                    continue
                if callable(v):
                    continue
                setattr(self, k, v)
        # 3. Apply keyword overrides
        for k, v in kwargs.items():
            setattr(self, k, v)

    def verify(self, workspace: str) -> Tuple[bool, str]:
        """Check if the task was completed correctly.

        Returns (passed, detail). Override in subclasses.
        """
        return True, ""

    def post_run_verify(self, workspace: str, ctx: "mangopi_cli.ContextManager") -> Tuple[bool, str]:
        """Extended verification with access to the context messages."""
        return self.verify(workspace)


# ═══════════════════════════════════════════════════════════════════════════════
# Agent runner
# ═══════════════════════════════════════════════════════════════════════════════


class AgentRunner:
    """Runs a single prompt through the mangopi-cli agent pipeline in an
    isolated workspace, capturing all metrics."""

    def __init__(self, workspace: str):
        self.workspace = os.path.abspath(workspace)
        self._saved_globals: Dict[str, object] = {}
        self._stdout_buf = io.StringIO()
        self._stderr_buf = io.StringIO()

    # ── context management ──────────────────────────────────────────────────

    def _enter(self) -> None:
        """Patch mangopi_cli globals to run in the isolated workspace."""
        mod = mangopi_cli
        keys = ["project_root", "base_persist_dir", "session_dir",
                "memory_dir", "goal_file"]
        for k in keys:
            self._saved_globals[k] = getattr(mod, k)

        mod.project_root = self.workspace
        mod.base_persist_dir = os.path.join(self.workspace, ".mangocli")
        mod.session_dir = os.path.join(mod.base_persist_dir, "session")
        mod.memory_dir = os.path.join(mod.base_persist_dir, "memory")
        mod.goal_file = os.path.join(mod.base_persist_dir, "goal.json")

        mod.initialize_system()

        # Silence console output
        self._patch_console_silent(mod)

        # Auto-confirm dangerous commands and edits
        self._orig_prompt_apply = mod.console.prompt_apply
        mod.console.prompt_apply = lambda message: True

        # Redirect stdout/stderr
        self._redirect_out = contextlib.redirect_stdout(self._stdout_buf)
        self._redirect_err = contextlib.redirect_stderr(self._stderr_buf)
        self._redirect_out.__enter__()
        self._redirect_err.__enter__()

        os.chdir(self.workspace)

    def _exit(self) -> None:
        """Restore mangopi_cli globals."""
        mod = mangopi_cli
        for k, v in self._saved_globals.items():
            setattr(mod, k, v)

        mod.console.prompt_apply = self._orig_prompt_apply
        self._redirect_out.__exit__(None, None, None)
        self._redirect_err.__exit__(None, None, None)
        os.chdir(self._saved_globals.get("project_root", os.getcwd()))

    @staticmethod
    def _patch_console_silent(mod) -> None:
        """Replace console output methods with no-ops."""
        c = mod.console
        for method in ["section", "tool_call", "tool_result", "success",
                        "error", "warning", "text", "separator",
                        "thinking", "output", "token_usage",
                        "compact_status", "diff", "start_spinner",
                        "end_spinner", "_write_line", "_clear_spinner_line"]:
            if hasattr(c, method):
                setattr(c, f"_saved_{method}", getattr(c, method))
                setattr(c, method, lambda *a, **kw: None)

    def _restore_console(self) -> None:
        """Restore console methods."""
        c = mangopi_cli.console
        for method in ["section", "tool_call", "tool_result", "success",
                        "error", "warning", "text", "separator",
                        "thinking", "output", "token_usage",
                        "compact_status", "diff", "start_spinner",
                        "end_spinner", "_write_line", "_clear_spinner_line"]:
            saved = getattr(c, f"_saved_{method}", None)
            if saved is not None:
                setattr(c, method, saved)

    # ── run ─────────────────────────────────────────────────────────────────

    def run(self, task: BenchmarkTask) -> TaskResult:
        self._enter()
        try:
            return self._do_run(task)
        except Exception as exc:
            return TaskResult(
                task_name=task.name, level=task.level, passed=False,
                detail="", error=f"{type(exc).__name__}: {exc}")
        finally:
            self._exit()

    def _do_run(self, task: BenchmarkTask) -> TaskResult:
        # Create initial files
        for path, content in task.setup_files.items():
            full = os.path.join(self.workspace, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(content)

        # Build context with system prompt
        ctx = mangopi_cli.ContextManager()
        ctx_file = os.path.join(mangopi_cli.session_dir, "session.json")

        prompt_runtime = mangopi_cli.SystemPrompt()
        ctx.append_system(prompt_runtime.assemble())

        # Run agent
        user_msg = f"{task.prompt}\n\nCurrent date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        t0 = time.perf_counter()

        try:
            mangopi_cli.agent_loop(ctx, ctx_file, user_msg)
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            return TaskResult(
                task_name=task.name, level=task.level, passed=False,
                detail=f"Agent error: {exc}",
                wall_time_s=round(elapsed, 2),
                error=f"{type(exc).__name__}: {exc}")

        elapsed = time.perf_counter() - t0

        # Extract metrics from context messages
        tool_calls, total_prompt, total_completion, iterations = self._extract_metrics(ctx)

        unique = sorted(set(tc["name"] for tc in tool_calls))
        tc_count = len(tool_calls)

        # Verify
        passed, detail = task.post_run_verify(self.workspace, ctx)

        if not passed:
            detail = f"Verification failed: {detail}"

        # Efficiency warning
        if tc_count > task.max_tool_calls:
            efficiency_note = (f" (inefficient: {tc_count} tool calls, "
                               f"expected ≤{task.max_tool_calls})")
            detail = (detail + efficiency_note) if detail else efficiency_note.strip()

        # If passed but detail is empty, provide a default
        if passed and not detail:
            detail = f"OK · {tc_count} tools, {round(elapsed, 1)}s"

        return TaskResult(
            task_name=task.name, level=task.level, passed=passed, detail=detail,
            tool_calls=tool_calls, tool_call_count=tc_count,
            unique_tools=unique, wall_time_s=round(elapsed, 2),
            prompt_tokens=total_prompt, completion_tokens=total_completion,
            total_tokens=total_prompt + total_completion,
            iterations=iterations)

    @staticmethod
    def _extract_metrics(ctx: "mangopi_cli.ContextManager") -> Tuple[List[Dict], int, int, int]:
        """Extract tool calls, token usage, and iterations from context messages."""
        tool_calls = []
        total_prompt = 0
        total_completion = 0
        iterations = 0

        for m in ctx.messages:
            role = m.get("role")
            if role == "tool":
                tool_calls.append({
                    "name": m.get("tool_name", "?"),
                    "call_id": m.get("tool_call_id", ""),
                    "content_preview": str(m.get("content", ""))[:120],
                })
            elif role == "assistant":
                iterations += 1
            # Token usage is embedded in raw_message by provider; we estimate
            # from context since usage is not aggregated across turns.
            total_prompt += mangopi_cli.ContextManager.estimated_tokens(m)

        total_completion = sum(
            len(str(m.get("content", ""))) // 4
            for m in ctx.messages if m.get("role") == "assistant")
        total_completion += sum(
            len(str(m.get("reasoning_content", ""))) // 4
            for m in ctx.messages if m.get("role") == "assistant")

        return tool_calls, total_prompt, total_completion, iterations
