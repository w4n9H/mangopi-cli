"""Shipped extension — run_code: Code Mode / 程序化工具调用 (PTC).
Shipped extension — run_code: Code Mode / Programmatic Tool Calling (PTC).

模型编写一段 Python 脚本, 将多步工具操作编排进一次执行, 减少模型往返与
token 消耗. 中间工具结果不进对话, 只有 print 输出回流. 对齐 DeepSeek
Harness Code Mode, 适配 Mangopi 的同步 exec() 运行时.
The model writes a Python script that orchestrates multiple tool calls in
one execution, reducing round-trips and token usage. Intermediate tool
results stay out of the conversation; only print output flows back. Mirrors
DeepSeek Harness Code Mode, adapted for Mangopi's synchronous exec() runtime.

按需启用 / Enable on demand:
  * 复制/软链本文件到 preset 扩展目录: ~/.mangocli/presets/<name>/extensions/
    (配合 codemode preset: examples/presets/codemode/conf.py, MANGO_PRESET=codemode)
  * Copy/symlink this file into a preset extensions dir and enable the codemode
    preset (examples/presets/codemode/conf.py) with MANGO_PRESET=codemode.

三通道契约 / Three-channel contract:
  - tools: RunCodeTool (6 个工具 API 绑定到脚本作用域: read/write/edit/search/grep/bash)
  - prompt_sections: 无 / none — code-only 指令与 SDK 声明由 codemode preset 的
    conf.py 经 prompt_overrides.append_sections 注入 (examples/presets/codemode/conf.py)
  - entry_points: 无 / none

安全模型 / Security model:
  - 整体确认: run_tool 执行前调用 RunCodeTool.confirm (展示 description + code 摘要,
    MANGO_YOLO 跳过) — 确认的是"运行这段模型生成的程序", 脚本内工具调用不再逐个确认
    (对齐 dsh 程序级审批语义)
  - exec() 于受限作用域: 白名单 builtins (排除 __import__/open/eval/exec/compile/
    globals/locals/vars/dir 等), 仅绑定 6 个工具 API + ToolError
  - 工具调用复用核心安全 (路径沙箱 _validate_file_path; 命令检测由整体确认把关)
  - SIGALRM 超时 (仅主线程; ACP 非主线程降级为无超时) + 输出截断
"""

from mangopi_cli import ToolBase

import contextlib
import io
import signal
import threading


# ─── Tool API exposed to model-generated scripts ────────────────────────────


class ToolError(Exception):
    """Raised when a tool call inside a run_code script fails.

    Bound in the script scope as `ToolError` so scripts can
    `try/except ToolError` to handle and continue.
    """


class CodeModeAPI:
    """The tool API bound into model-generated script scopes.

    Holds its own instances of the six built-in tools (created lazily on
    first use, once per process), fully decoupled from the module-level
    TOOLS dict — preset `keep_tools` filtering (e.g. codemode removes the
    six tools from the tool catalog) does not affect script-side calls.
    Each method delegates to the corresponding ToolBase instance,
    inheriting its safety checks (command safety, path sandbox, etc.).
    A failed call raises ToolError with the tool's error content.
    """

    _instances = None

    def __init__(self):
        if CodeModeAPI._instances is None:
            import mangopi_cli as m  # 延迟导入: 核心符号晚于扩展扫描点
            CodeModeAPI._instances = {
                "read": m.ReadTool(),
                "write": m.WriteTool(),
                "edit": m.EditTool(),
                "search": m.SearchTool(),
                "grep": m.GrepTool(),
                "bash": m.BashTool(),
            }
        self._tools = CodeModeAPI._instances

    def _call(self, name: str, args: dict) -> str:
        result = self._tools[name].run(args)
        if not result.get("success", True):
            raise ToolError(f"{name} failed: {result.get('content', '')}")
        return result.get("content", "")

    def read(self, path: str) -> str:
        """Read a text file and return its content."""
        return self._call("read", {"path": path})

    def write(self, path: str, content: str) -> str:
        """Write content to a file (overwrite or create)."""
        return self._call("write", {"path": path, "content": content})

    def edit(self, path: str, old: str, new: str) -> str:
        """Replace old with new in the file at path."""
        return self._call("edit", {"path": path, "old": old, "new": new})

    def search(self, pat: str) -> str:
        """Search files matching a glob pattern, sorted by modification time."""
        return self._call("search", {"pat": pat})

    def grep(self, pat: str, path: str = ".") -> str:
        """Search for pattern in file contents recursively."""
        return self._call("grep", {"pat": pat, "path": path})

    def bash(self, cmd: str) -> str:
        """Execute a shell command (60s timeout, output filtered)."""
        return self._call("bash", {"cmd": cmd})


# ─── Restricted builtins whitelist ──────────────────────────────────────────
# 非强沙箱: 对模型生成脚本的常规防线; 工具级安全 (路径沙箱/命令检测) 兜底.

_SAFE_BUILTINS = {
    # Types / constants
    "str": str, "int": int, "float": float, "bool": bool,
    "list": list, "dict": dict, "tuple": tuple, "set": set,
    "frozenset": frozenset, "bytes": bytes, "type": type,
    "None": None, "True": True, "False": False,
    # Iteration / sequence helpers
    "print": print, "len": len, "range": range, "enumerate": enumerate,
    "zip": zip, "map": map, "filter": filter, "iter": iter, "next": next,
    "sorted": sorted, "reversed": reversed,
    "min": min, "max": max, "sum": sum, "abs": abs, "round": round,
    "any": any, "all": all, "pow": pow, "divmod": divmod, "callable": callable,
    "isinstance": isinstance, "issubclass": issubclass,
    "hasattr": hasattr, "getattr": getattr, "setattr": setattr, "delattr": delattr,
    "repr": repr, "format": format, "ascii": ascii,
    "ord": ord, "chr": chr, "hex": hex, "id": id, "hash": hash,
    # Common exceptions
    "Exception": Exception, "ValueError": ValueError,
    "TypeError": TypeError, "KeyError": KeyError,
    "IndexError": IndexError, "AttributeError": AttributeError,
    "FileNotFoundError": FileNotFoundError,
    "RuntimeError": RuntimeError, "StopIteration": StopIteration,
    "ZeroDivisionError": ZeroDivisionError,
}

# 明确排除 (不在白名单即 NameError): __import__ / open / eval / exec /
# compile / globals / locals / vars / dir / input / breakpoint / exit / quit


# ─── Timeout handling ───────────────────────────────────────────────────────

class _ScriptTimeout(Exception):
    """Raised when a run_code script exceeds the time budget."""


def _timeout_handler(signum, frame):
    raise _ScriptTimeout("Script exceeded time budget")


# ─── run_code tool ──────────────────────────────────────────────────────────

class RunCodeTool(ToolBase):
    """Execute a Python script that orchestrates multiple tool calls.

    The model writes a script that calls the bound tool API (read, write,
    edit, search, grep, bash). Only printed output re-enters the
    conversation — intermediate tool results stay in the execution scope.
    """

    name = "run_code"
    description = (
        "Execute a Python program against the available tools. "
        "Takes two required arguments: `code`, a Python script "
        "(top-level statements; top-level `return` is not supported), "
        "and `description`, a short summary of what the program does. "
        "Call tools as read(path), write(path, content), "
        "edit(path, old, new), search(pat), "
        "grep(pat), bash(cmd) per the API in the system prompt. "
        "Answer with print(...) — only that comes back, so curate it."
    )
    params = {
        "code": {
            "type": "string",
            "description": "The program: a Python script (top-level statements).",
        },
        "description": {
            "type": "string",
            "description": (
                "Clear, concise description of what this program does "
                "in active voice, 5-10 words (shown in the UI). "
                'Examples: "Count TODO markers across packages"; '
                '"Read failing test and its fixture"; '
                '"Rename config key in every file".'
            ),
        },
    }
    guidance = (
        "Use run_code when you need to perform 3+ tool operations "
        "that can be expressed as a sequential or conditional script. "
        "This reduces token usage and round-trips. Intermediate tool "
        "results stay in the script scope — only print values "
        "re-enter the conversation."
    )

    # Execution budget
    TIMEOUT_SECONDS = 30
    MAX_OUTPUT_CHARS = 8000
    MAX_OUTPUT_LINES = 200

    def run(self, args):
        import mangopi_cli as m  # 延迟导入: 核心符号晚于扩展扫描点

        script = args.get("code", "")
        description = args.get("description", "")
        if not script.strip():
            return self.fail("Empty script: `code` parameter is required")
        if not description.strip():
            return self.fail("Empty description: `description` parameter is required")

        api = CodeModeAPI()
        globals_dict = {
            "__builtins__": _SAFE_BUILTINS,
            "ToolError": ToolError,
            "read": api.read,
            "write": api.write,
            "edit": api.edit,
            "search": api.search,
            "grep": api.grep,
            "bash": api.bash,
        }
        captured = io.StringIO()
        handle = self._arm_timeout()
        try:
            with contextlib.redirect_stdout(captured):
                # locals 不另传: 顶层赋值落入 globals_dict, 脚本内函数可闭包访问
                exec(script, globals_dict)
        except _ScriptTimeout:
            return self.ok(
                f"Script timed out after {self.TIMEOUT_SECONDS}s.\n"
                f"Output before timeout:\n{self._truncate(captured.getvalue())}")
        except Exception as err:  # noqa: BLE001 脚本错误作为输出回流, 模型可自行修正
            return self.ok(
                f"Script error: {type(err).__name__}: {err}\n"
                f"Output before error:\n{self._truncate(captured.getvalue())}")
        finally:
            self._disarm_timeout(handle)

        output = captured.getvalue()
        if not output.strip():
            output = "(run_code completed with no output)"
        return self.ok(f"Script executed successfully.\nOutput:\n{self._truncate(output)}")

    def preview(self, args):
        desc = args.get("description", "")
        code = args.get("code", "")
        return f"{desc}: {code[:self.preview_width]}"

    def confirm(self, args):
        import mangopi_cli as m  # 延迟导入: 核心符号晚于扩展扫描点
        if m.MANGO_YOLO:
            return True
        return m.console.prompt_apply(f"Run run_code script ({args.get('description', '')})?")

    def _arm_timeout(self):
        """布防 SIGALRM 超时. 返回 disarm 句柄; None = 未布防 (非主线程/平台无 SIGALRM)."""
        if threading.current_thread() is not threading.main_thread():
            return None  # ACP 模式: signal.alarm 仅主线程可用, 降级为无超时
        if not hasattr(signal, "SIGALRM"):
            return None
        old = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(max(1, int(self.TIMEOUT_SECONDS)))
        return old if old is not None else signal.SIG_DFL

    @staticmethod
    def _disarm_timeout(handle):
        if handle is None:
            return
        signal.alarm(0)
        signal.signal(signal.SIGALRM, handle)

    @staticmethod
    def _truncate(text: str) -> str:
        """Truncate output to fit within budget."""
        if len(text) > RunCodeTool.MAX_OUTPUT_CHARS:
            half = RunCodeTool.MAX_OUTPUT_CHARS // 2
            text = (
                text[:half]
                + f"\n\n... [{len(text) - RunCodeTool.MAX_OUTPUT_CHARS} chars truncated] ...\n\n"
                + text[-half:]
            )
        lines = text.split("\n")
        if len(lines) > RunCodeTool.MAX_OUTPUT_LINES:
            head, tail = 50, 50
            text = (
                "\n".join(lines[:head])
                + f"\n... [{len(lines) - RunCodeTool.MAX_OUTPUT_LINES} lines truncated] ...\n"
                + "\n".join(lines[-tail:])
            )
        return text


# ─── Extension registration (three-channel contract) ────────────────────────

tools = [RunCodeTool()]
