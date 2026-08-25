#!/usr/bin/env python3
import copy
import difflib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import ast
import urllib.error
import urllib.request
import glob as globlib
import platform
import shutil
import argparse
import types
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

try:
    import readline  # 解决 Unix-like 系统中 input 无法正常删除中文的问题
except Exception:
    pass

__version__ = "0.1.52"
__author__ = "moofs"
__license__ = "Apache License 2.0"

# --- System Env ---
MANGO_KEY = os.environ.get("MANGO_KEY")
MANGO_API_URL = os.environ.get("MANGO_API_URL", "https://api.deepseek.com")
MANGO_MODEL = os.environ.get("MANGO_MODEL", "deepseek-v4-flash")
MANGO_MAX_CONTEXT = int(os.environ.get("MANGO_MAX_CONTEXT", 1_000_000))
MANGO_MAX_ITER = int(os.environ.get("MANGO_MAX_ITER", 100))
LANGUAGE = os.environ.get("MANGO_LANG", "en").lower()
MANGO_YOLO = os.environ.get("MANGO_YOLO", "").lower() in ("1", "true", "yes")
MANGO_PRESET = os.environ.get("MANGO_PRESET", "").strip()  # preset 名 (目录名, 大小写敏感)
MANGO_PRESET_DIR = os.path.expanduser("~/.mangocli/presets")


project_root = os.getcwd()
base_persist_dir = os.path.join(project_root, '.mangocli')
session_dir = os.path.join(base_persist_dir, "session")
extensions_dir = os.path.expanduser(f"~/.mangocli/presets/{MANGO_PRESET}/extensions") \
    if MANGO_PRESET else os.path.expanduser(f"~/.mangocli/extensions")
# 直接运行 (python mangopi_cli.py) 时模块名为 __main__, 此处注入别名使扩展文件可 `from mangopi_cli import ...`
sys.modules.setdefault("mangopi_cli", sys.modules[__name__])

# --- Catppuccin Mocha palette (24-bit, active roles only) ---
MOCHA = {  # Ghostty theme: Catppuccin Mocha. https://github.com/catppuccin/catppuccin
    "blue": "#89b4fa", "sky": "#89dceb", "green": "#a6e3a1", "yellow": "#f9e2af",
    "red": "#f38ba8", "subtext0": "#a6adc8", "mauve": "#cba6f7", "text": "#cdd6f4"}


def _fg(hex_color: str) -> str:  # '#rrggbb' -> ANSI 24-bit foreground escape (\033[38;2;r;g;bm).
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"\033[38;2;{r};{g};{b}m"


# ANSI attributes (kept as-is; colors below are role-mapped to Catppuccin Mocha)
RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
BLUE = _fg(MOCHA["blue"])      # interactive input prompt (❯)
CYAN = _fg(MOCHA["sky"])       # tool names, diff @@ headers
GREEN = _fg(MOCHA["green"])    # success / ok / diff additions
YELLOW = _fg(MOCHA["yellow"])  # warnings / mid-thresholds
RED = _fg(MOCHA["red"])        # errors / diff deletions
GREY = _fg(MOCHA["subtext0"])  # secondary & thinking text
ACCENT = _fg(MOCHA["mauve"])   # section titles, spinner, strategy
SOFT = _fg(MOCHA["text"])      # LLM final output text


# --- i18n dict (zh, en)---
I18N = {
    "tool.call":                     {"zh": "工具调用",         "en": "Tool call"},
    "tool.result.ok":                {"zh": "成功应用",         "en": "Applied successfully"},
    "tool.result.fail":              {"zh": "执行失败",         "en": "Execution failed"},
    "llm.thinking":                  {"zh": "思考中",           "en": "Thinking"},
    "llm.output":                    {"zh": "输出",             "en": "Output"},
    "context.compact":               {"zh": "上下文压缩",       "en": "Context compact"},
    "context.compact.strategy":      {"zh": "策略",             "en": "Strategy"},
    "context.round":                 {"zh": "轮次",             "en": "round"},
    "context.tokens_in_out":         {"zh": "tokens 输入/输出", "en": "tokens in/out"},
    "cli.welcome":                   {"zh": "Mangopi CLI — 基于大模型的命令行编程助手",
                                      "en": "Mangopi CLI — Large Model CLI Assistant"},
    "cli.help_intro":                {"zh": "内置命令:",        "en": "Built-in commands:"},
    "safety.warn.dangerous_command": {"zh": "检测到危险命令",   "en": "Dangerous command detected"},
    "safety.danger.rm":              {"zh": "文件删除",         "en": "File deletion"},
    "safety.danger.mkfs":            {"zh": "磁盘格式化或分区", "en": "Disk formatting or partition"},
    "safety.danger.chmod":           {"zh": "危险权限修改",     "en": "Dangerous permission change"},
    "safety.danger.sudo":            {"zh": "提权操作",         "en": "Privilege escalation"},
    "safety.danger.kill":            {"zh": "危险进程操作",     "en": "Dangerous process operation"},
    "safety.danger.env":             {"zh": "环境变量或系统配置修改", "en": "Environment or system config change"},
    "safety.danger.history":         {"zh": "清理历史/日志",    "en": "History/log clearing"}}

HELP_COMMANDS = {
    "/q or /quit":          {"zh": "退出程序", "en": "Quit"},
    "/c or /compact":       {"zh": "手动压缩当前会话（释放上下文空间）", "en": "Manually compact current session"},
    "/n or /new":           {"zh": "结束当前会话并创建一个全新的会话", "en": "End current session and start a new one"},
    "/s or /session":       {"zh": "列出会话; /s <name> 切换或新建会话", "en": "List sessions; /s <name> switch or create"},
    "/h or /help":          {"zh": "显示本帮助信息", "en": "Show this help info"}}


def _c(text, color): return f"{color}{text}{RESET}"


def _i18n(key: str): return I18N[key].get(LANGUAGE, "")


# --- UI ---
class Printer:
    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self):
        self.mode = "console"            # console | acp (acp: 文本静默, 事件经 emitter 发射)
        self.emitter = None              # ACP 事件发射器 (AcpServer 注册; 接收事件 dict)
        self.permission_handler = None   # ACP 权限裁决回调 (acp 模式下 prompt_apply 调用)
        self._round = 0
        self._spinner_running = False
        self._spinner_thread = None
        self._spinner_message = ""
        self._lock = threading.RLock()

    @staticmethod
    def _clear_spinner_line():
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def _write_line(self, text: str = ""):
        if self.mode == "acp":
            return
        with self._lock:
            was_running = self._spinner_running
            if was_running:
                self._clear_spinner_line()
            print(text)
            if was_running:
                self._render_spinner_frame()

    def _render_spinner_frame(self, frame: str = "⠋"):
        text = f"{_c(frame, ACCENT)} {_c(self._spinner_message, ACCENT)}"
        sys.stdout.write("\r" + text)
        sys.stdout.flush()

    def section(self, title):
        self._write_line()
        self._write_line(_c(f"• {title}", ACCENT))

    def tool_call(self, name: str, desc: str):
        if self.mode == "acp":
            if self.emitter:
                self.emitter({"type": "tool", "name": name, "args_preview": desc, "round": self._round})
            return
        self.section(_i18n("tool.call"))
        self._write_line(f"{_c('› ', GREY)}{_c(name, CYAN)}  {_c(desc, GREY)}")

    def tool_result(self, name: str, ok=True, snippet=""):
        if self.mode == "acp":
            if self.emitter:
                self.emitter({"type": "tool_result", "name": name, "ok": ok,
                              "snippet": snippet[:200], "round": self._round})
            return
        icon = "✓" if ok else "✗"
        color = GREEN if ok else RED
        suffix = _i18n("tool.result.ok") if ok else _i18n("tool.result.fail")
        self._write_line(f"  {_c(icon, color)}{_c(suffix, GREY)}")

    def tool_display(self, text: str): self._write_line(text)

    def success(self, msg: str): self._write_line(f"{_c('✓ ', GREEN)}{_c(msg, GREY)}")

    def error(self, msg: str): self._write_line(f"{_c('✗ ', RED)}{_c(msg, GREY)}")

    def warning(self, msg: str): self._write_line(f"{_c('! ', YELLOW)}{_c(msg, GREY)}")

    def text(self, msg: str): self._write_line(_c(msg, GREY))

    def separator(self):
        self._write_line(f"{DIM}{'─' * min(shutil.get_terminal_size().columns, 80)}{RESET}")

    def thinking(self, content: str):
        if self.mode == "acp":
            if self.emitter:
                self.emitter({"type": "thinking", "content": content})
            return
        self.section(_i18n("llm.thinking"))
        for line in content.splitlines():
            self._write_line("  " + _c(line, GREY))

    def output(self, content: str):
        if self.mode == "acp":
            if self.emitter:
                self.emitter({"type": "output", "content": content})
            return
        self.section(_i18n("llm.output"))
        for line in content.splitlines():
            self._write_line("  " + _c(line, SOFT))

    def token_usage(self, iteration: int, input_tokens: int, output_tokens: int, context_tokens: int, max_context: int):
        if self.mode == "acp":
            if self.emitter:
                self.emitter({"type": "usage", "prompt_tokens": input_tokens,
                              "completion_tokens": output_tokens, "total": input_tokens + output_tokens,
                              "context_tokens": context_tokens, "max_context": max_context})
            return

        def fmt(n): return f"{n / 1000:.1f}k" if n >= 1000 else str(n)
        ratio = context_tokens / max_context if max_context else 0
        percent = int(ratio * 100)
        color = GREEN if percent < 50 else YELLOW if percent < 70 else RED

        self._write_line()
        self._write_line(
            _c(f"{_i18n('context.round')}: {iteration} | "
               f"{_i18n('context.tokens_in_out')}: {fmt(input_tokens)} in / {fmt(output_tokens)} out |  ctx: ", GREY) +
            _c(f"{percent}%", color))

    def compact_status(self, before_tokens: int, after_tokens: int, max_context: int, strategy: str = "auto"):
        saved = before_tokens - after_tokens
        ratio = (after_tokens / max_context) if max_context else 0
        percent = int(ratio * 100)
        color = GREEN if percent < 50 else YELLOW if percent < 70 else RED

        self.section(_i18n("context.compact"))
        self._write_line(f"  {_c(_i18n('context.compact.strategy'), GREY)} {_c(strategy, ACCENT)}")
        self._write_line(
            f"  {_c('tokens', GREY)} {_c(f'{before_tokens:,}', RED)} {_c('→', GREY)} "
            f"{_c(f'{after_tokens:,}', GREEN)} {_c(f'(-{saved:,})', ACCENT)}")
        self._write_line(f"  {_c('context', GREY)} {_c(f'{percent}%', color)}")

    @staticmethod
    def _prompt_apply_input(message: str) -> bool:
        while True:
            resp = input(f"{YELLOW}{message} [y/n]: {RESET}").strip().lower()
            if resp in ("y", "yes"):
                return True
            elif resp in ("n", "no"):
                return False
            else:
                print("input y or n")

    def prompt_apply(self, message: str) -> bool:
        if self.mode == "acp":
            # ACP: 经 session/request_permission 由 client 裁决; handler 缺失时拒绝,
            # 绝不 fall through 到终端 input() (会读 JSON-RPC 流且 print 污染 stdout)
            return self.permission_handler(message) if self.permission_handler else False
        return self._prompt_apply_input(message)

    def diff(self, old: str, new: str, context: int = 3, filename: str = "file.py"):
        self.section("Code Diff")
        old_lines = old.splitlines()
        new_lines = new.splitlines()
        diff_lines = difflib.unified_diff(
            old_lines, new_lines, fromfile=f"a/{filename}", tofile=f"b/{filename}", lineterm="", n=context)
        for dl in diff_lines:
            if dl.startswith("+") and not dl.startswith("+++"):
                self._write_line(_c(dl, GREEN))
            elif dl.startswith("-") and not dl.startswith("---"):
                self._write_line(_c(dl, RED))
            elif dl.startswith("@@"):
                self._write_line(_c(dl, CYAN))
            else:
                self._write_line(_c(dl, GREY))

    def start_spinner(self, message: str = "Running..."):
        if self.mode == "acp":
            return
        if self._spinner_running:
            return
        self._spinner_running = True
        self._spinner_message = message

        def run():
            i = 0
            while self._spinner_running:
                with self._lock:
                    frame = self.SPINNER_FRAMES[i % len(self.SPINNER_FRAMES)]
                    self._render_spinner_frame(frame)
                time.sleep(0.1)
                i += 1

        self._spinner_thread = threading.Thread(target=run, daemon=True)
        self._spinner_thread.start()

    def end_spinner(self):
        if self.mode == "acp":
            return
        if not self._spinner_running:
            return
        self._spinner_running = False
        if self._spinner_thread:
            self._spinner_thread.join()
        with self._lock:
            self._clear_spinner_line()


console = Printer()


# --- Init dir, Base data ---
def initialize_system():
    os.makedirs(session_dir, exist_ok=True)  # auto create .mangocli


def doctor():
    results = [(bool(MANGO_KEY), "MANGO_KEY is set" if MANGO_KEY else "MANGO_KEY: not set (required)")]
    if not os.path.isdir(session_dir):
        results.append((False, "session directory not found"))
    else:
        files = [f for f in os.listdir(session_dir) if f.endswith(".json") and not f.endswith(".backup")]
        results.append((True, f"session directory: {len(files)} JSON file(s)"))
    for ok, msg in results:
        if ok:
            console.success(msg)
        else:
            console.error(msg)
    return sum(1 for ok, _ in results if not ok)


def helper():
    console.text(_i18n("cli.welcome"))
    console.text(_i18n("cli.help_intro"))
    for cmd, desc in HELP_COMMANDS.items():
        console.text(f"  {cmd:<6} -- {desc.get(LANGUAGE, '')}")


# --- Utils function ---
FILTERED_DIRS = [
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", ".turbo", ".idea",
    ".vscode", ".mypy_cache", ".pytest_cache", ".cache", "target", "vendor"]


def _is_directory_heavy(command: str) -> bool:  # 判断是否是目录遍历类命令
    return any(k in command for k in ["find ", "tree", "ls -R", "du ", "fd ", "rg ",])


def _filter_directory_output(lines: List[str]) -> List[str]:  # 过滤大型/无意义目录
    def _matches(line, d):
        return (f"/{d}/" in line or f"/{d}:" in line or line.startswith(f"{d}/") or
                line.startswith(f"./{d}/") or line.startswith(f"./{d}:") or
                line == d or line == f"./{d}" or line.endswith(f"/{d}"))
    return [line for line in lines if not any(_matches(line, d) for d in FILTERED_DIRS)]


def _limit_output_lines(lines: List[str], max_lines: int = 1000) -> List[str]:  # 限制输出行数
    return lines if len(lines) <= max_lines else (
            lines[:max_lines] + ["", f"... truncated {len(lines)-max_lines} lines ..."])


def _process_bash_output(command: str, output: List[str]) -> List[str]:
    """ bash command -> directory filter -> line limit"""
    if not output:
        return output
    if _is_directory_heavy(command):
        output = _filter_directory_output(output)
    output = _limit_output_lines(output)
    return output


def _check_command_safety(command: str):
    dangerous_patterns = [
        (r'\brm\s+.*-[rf]', 1), (r'\brm\s+-[rf]', 1), (r'\bunlink\b', 1), (r'\brm\s+(-[rf]+\s+)?.*', 1),
        (r'\bmkfs\b', 2), (r'\bfdisk\b', 2), (r'\bparted\b', 2), (r'\bdd\s+.*if=.*of=', 2),
        (r'\bchmod\s+(?:-[a-zA-Z]+\s+)*\d*7\d*7\b', 3), (r'\bchmod\s+777\b', 3), (r'\bchmod\s+\d*7\d*7\b', 3),
        (r'\bchown\s+.*root\b', 3),
        (r'\bsudo\s+.*rm\b', 4), (r'\bsu\s+-\b', 4), (r'\bsu\s+root\b', 4),
        (r'\bkill\s+-9\s+1\b', 5), (r'\bkillall\s+-9\b', 5), (r'\bpkill\s+-9\b', 5), (r'\bkill\s+-9\s+-\d+\b', 5),
        (r'\bexport\s+PATH=', 6), (r'\bunset\s+PATH\b', 6), (r'>>?\s*/etc/', 6), (r'\becho\s+.*>\s*/etc/', 6),
        (r'\bhistory\s+-c\b', 7), (r'>\s*/dev/null\s+2>&1', 7),]
    dangerous_i18n = {
        1: "safety.danger.rm", 2: "safety.danger.mkfs", 3: "safety.danger.chmod", 4: "safety.danger.sudo",
        5: "safety.danger.kill", 6: "safety.danger.env", 7: "safety.danger.history"}
    command = command.strip()
    if not command:
        return False, None
    for pattern, reason_id in dangerous_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return True, f"{_i18n(dangerous_i18n[reason_id])}"
    return False, None


def _validate_file_path(path: str) -> Optional[str]:  # 验证给定路径是否在项目根目录内
    abs_path = os.path.abspath(path)
    real_path = os.path.realpath(abs_path)
    real_root = os.path.realpath(project_root)
    if not real_path.startswith(real_root + os.sep) and real_path != real_root:    # 必须位于项目根目录下
        return f"path '{path}' is outside project root"
    if os.path.isdir(real_path):    # 不允许直接操作目录（write/edit 只能操作文件）
        return f"path '{path}' is a directory, not a file"
    return None


def _request(url: str, body: dict, headers: dict = None, timeout: int = 300, max_retries: int = 3) -> dict:
    last_exception = None
    headers = headers or {"Content-Type": "application/json"}
    for attempt in range(max_retries + 1):
        try:
            request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw_data = response.read().decode("utf-8")
                return json.loads(raw_data)
        except urllib.error.HTTPError as e:
            if e.code >= 500 or e.code == 429:
                last_exception = e
            else:
                raise
        except (urllib.error.URLError, json.JSONDecodeError, socket.timeout) as e:
            last_exception = e
        except Exception as e:
            raise e

        if attempt < max_retries:
            delay = 1 * (2 ** attempt)
            console.warning(f"Request failed (attempt {attempt + 1}/{max_retries + 1}), retrying in {delay:.1f}s")
            time.sleep(delay)
        else:
            break
    raise last_exception


class _EventBus:
    """run_tool 事件总线: on()/emit(). 事件: tool:before/tool:after/tool:error.只做emit,不做 bail/serial/waterfall."""

    def __init__(self):
        self._listeners = {}                      # event -> List[Callable]

    def on(self, event: str, fn: Callable) -> Callable[[], bool]:
        self._listeners.setdefault(event, []).append(fn)

        def unsub():
            try:
                self._listeners[event].remove(fn)
                return True
            except (ValueError, KeyError):
                return False

        return unsub

    def emit(self, event: str, *args) -> int:
        for fn in list(self._listeners.get(event, [])):  # 复制: listener 可在循环内退订
            try:
                fn(*args)
            except Exception as err:  # noqa: BLE001 单个 listener 失败不影响其余
                console.error(f"event {event}: {err}")
        return len(self._listeners.get(event, []))


_mango_events = _EventBus()


def on(event: str, fn: Callable) -> Callable[[], bool]:
    """扩展订阅事件总线的入口: `from mangopi_cli import on` (顶层可用, 早于扫描点)."""
    return _mango_events.on(event, fn)


class ExtensionRegistry:
    """扩展注册表: 一次扫描, 三通道收获. 契约: 扩展文件顶层只允许 import, 禁止访问 mangopi_cli 属性 (导入期半初始化);
    所需符号在函数体内延迟导入. 单个扩展失败只记录诊断, 不影响其他扩展.
    每条注册按 source (扩展文件名) 记录 inverse, unload_source()/reload_source() 支持可逆卸载/单文件重载."""

    def __init__(self):
        self.tools = []                    # 通道一: List[ToolBase], TOOLS 合并时扩展优先
        self.prompt_sections = []          # 通道二: List[(name, content)], 同名覆盖/异名追加
        self.entry_points = {}             # 通道三: name -> Callable[[], int] (如 {"acp": ...}), 同名首个生效
        self._per_source = {}              # source(扩展文件名) -> List[inverse Callable], 可逆卸载用

    def load(self) -> "ExtensionRegistry":  # 全量重扫 extensions_dir (重载语义: 上次结果清空).
        self.tools, self.prompt_sections, self.entry_points, self._per_source = [], [], {}, {}
        if not os.path.isdir(extensions_dir):
            return self
        off = {f.strip() for f in os.environ.get("MANGO_EXTENSIONS_OFF", "").split(",") if f.strip()}
        for py in sorted(globlib.glob(os.path.join(extensions_dir, "*.py"))):
            source = os.path.basename(py)
            if source in off:
                continue                   # MANGO_EXTENSIONS_OFF: 静态禁用, 不加载不记录
            try:
                mod = self.load_file(py)
            except Exception as err:  # noqa: BLE001 扩展失败不拖垮主程序
                console.error(f"load extension {py} err: {err}")
                continue
            for tool in getattr(mod, "tools", []) or []:
                self._register_tool(tool, source)
            for section in self._iter_prompt_sections(mod):
                self._register_prompt_section(section, source)
            for name, fn in (getattr(mod, "entry_points", {}) or {}).items():
                self._register_entry_point(name, fn, source)
        return self

    def unload_source(self, source: str) -> int:
        """可逆卸载: 卸掉 source 贡献的所有注册并跑 inverse (同步清理 TOOLS). 返回卸载的注册数."""
        inverses = self._per_source.pop(source, [])
        for inverse in inverses:
            try:
                inverse()
            except Exception as err:  # noqa: BLE001 单个 inverse 失败不影响其余
                console.error(f"unload {source} err: {err}")
        return len(inverses)

    def reload_source(self, source: str) -> int:
        """重载单个扩展: 先卸旧贡献再重加载该文件, 其他 source 不受影响. 返回新注册数."""
        self.unload_source(source)
        py = os.path.join(extensions_dir, source)
        if not os.path.isfile(py):
            return 0
        mod = self.load_file(py)          # 加载失败向上抛, 由调用方决定 (旧贡献已卸)
        for tool in getattr(mod, "tools", []) or []:
            self._register_tool(tool, source)
            TOOLS[tool.name] = tool        # 运行时重载: 新实例立即生效 (导入期由模块级 TOOLS 合并负责)
        for section in self._iter_prompt_sections(mod):
            self._register_prompt_section(section, source)
        for name, fn in (getattr(mod, "entry_points", {}) or {}).items():
            self._register_entry_point(name, fn, source)
        return len(self._per_source.get(source, []))

    def _register_tool(self, tool, source):
        self.tools.append(tool)

        def inverse():
            if tool in self.tools:
                self.tools.remove(tool)
            if TOOLS.get(tool.name) is tool:  # 同名覆盖时只删自己, 不误删后来者
                del TOOLS[tool.name]

        self._per_source.setdefault(source, []).append(inverse)

    @staticmethod
    def _iter_prompt_sections(mod):
        """兼容两种契约: 模块级列表 [(name, content)] 或函数 () -> list (动态段).
        函数形式原样注册 callable, 由 SystemPrompt 构建时调用 (plan_mode/task_tracker 等
        依赖运行时状态的扩展)."""
        raw = getattr(mod, "prompt_sections", None)
        if raw is None:
            return []
        return [raw] if callable(raw) else raw

    def _register_prompt_section(self, section, source):
        self.prompt_sections.append(section)

        def inverse():
            if section in self.prompt_sections:
                self.prompt_sections.remove(section)

        self._per_source.setdefault(source, []).append(inverse)

    def _register_entry_point(self, name, fn, source):
        if callable(fn) and name not in self.entry_points:  # 同名首个生效, 确定性
            self.entry_points[name] = fn

            def inverse():
                if self.entry_points.get(name) is fn:
                    del self.entry_points[name]

            self._per_source.setdefault(source, []).append(inverse)

    @staticmethod
    def load_file(py: str) -> Any:
        # 直接 compile+exec 而非 importlib: 绕开 SourceFileLoader 的 __pycache__ 字节码缓存
        mod = types.ModuleType("mango_ext_" + os.path.basename(py))
        mod.__file__ = py
        with open(py, encoding="utf-8") as f:
            code = compile(f.read(), py, "exec")
        exec(code, mod.__dict__)
        return mod

    def get_per_source(self):
        return self._per_source


class SkillManager:
    def __init__(self, base_paths: List[str] = None, load_level: str = "resources"):
        self.base_paths = base_paths or [os.path.expanduser("~/.mangocli/skills"), Path(base_persist_dir) / "skills"]
        self.level = load_level
        try:
            self.skills = self._load_skills()
        except Exception as err:
            self.skills = {}
            console.error(f"load skills err: {err}")

    def _load_skills(self) -> Dict[str, dict]:
        def _load_directory(_skill_path: str, _dirname: str):
            dir_path = os.path.join(_skill_path, _dirname)
            if not os.path.exists(dir_path):
                return {}
            files = {}
            for root, _, filenames in os.walk(dir_path):
                for file in filenames:
                    path = os.path.join(root, file)
                    with open(path, 'r', encoding='utf-8') as f:
                        files[path] = f.read()
            return files

        skills = {}
        for base in self.base_paths:
            for skill_md in globlib.glob(os.path.join(base, "*/SKILL.md")):
                skill_dir = os.path.dirname(skill_md)
                skill_name = os.path.basename(skill_dir)
                with open(skill_md, 'r', encoding='utf-8') as f:
                    content = f.read()

                yaml_end = content.find('---', 3)
                if yaml_end == -1:
                    raise ValueError(f"Invalid SKILL.md: missing YAML frontmatter in {skill_md}")
                yaml_text, body = content[3:yaml_end].strip(), content[yaml_end + 3:].strip()

                meta = {}
                for line in yaml_text.splitlines():
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    key, val = re.split(r':\s*', line, 1)
                    val = val.strip()
                    if val.lower() == 'true':
                        val = True
                    elif val.lower() == 'false':
                        val = False
                    elif val.lower() in ('null', '~'):
                        val = None
                    else:
                        try:
                            val = ast.literal_eval(val)
                        except Exception:
                            pass
                    meta[key.strip()] = val
                meta["body"] = body
                skills[skill_name] = {"meta": meta}
                if self.level == "resources":
                    skills[skill_name].update({
                        "scripts": _load_directory(skill_dir, "scripts"),
                        "references": _load_directory(skill_dir, "references")})
        return skills

    def reload(self):
        try:
            self.skills = self._load_skills()
        except Exception as err:
            self.skills = {}
            console.error(f"reload skills err: {err}")

    def all(self) -> Dict[str, dict]: return self.skills

    def descriptions(self) -> str:
        return "\n".join(f"- {name}: {data['meta'].get('description', '')}" for name, data in self.skills.items())

    def find(self, keyword: str) -> List[Dict]:
        matched = []
        for name, data in self.skills.items():
            meta = data.get("meta", {})
            if keyword.lower() in name.lower() or any(keyword.lower() in t.lower() for t in meta.get("tags", [])):
                matched.append({"name": name, "meta": meta})
        return matched


skill_manager = SkillManager()


# --- Tool definitions: (description, schema, function) ---
class ToolBase:
    name = ""
    description = ""
    params = {}
    preview_lines = 20
    preview_width = 100
    use_spinner = False
    guidance = ""  # 工具使用指导, 注入 SystemPrompt tool_guidance 段 (随扩展加载动态拼接)

    def schema(self):
        properties = {}
        required = []
        for param_name, param_info in self.params.items():
            param_type = param_info["type"]
            is_optional = param_type.endswith("?")
            base_type = param_type.rstrip("?")
            properties[param_name] = {
                "type": "integer" if base_type == "number" else base_type, "description": param_info["description"]}
            if not is_optional:
                required.append(param_name)
        return {
            "type": "function",
            "function": {
                "name": self.name, "description": self.description,
                "parameters": {"type": "object", "properties": properties, "required": required}
            }
        }

    def run(self, args): raise NotImplementedError

    def preview(self, args): return str(list(args.values())[0])[:self.preview_width] if args else ""

    def before(self, args): pass

    def after(self, result): pass

    def confirm(self, args): return True

    @staticmethod
    def ok(content: Any = "", **extra): return {"success": True, "content": content, **extra}

    @staticmethod
    def fail(content="", **extra): return {"success": False, "content": content, **extra}


class ReadTool(ToolBase):
    name = "read"
    description = "Read a file from the local filesystem (text only; use view_image for images)"
    params = {
        "path": {"type": "string", "description": "Path to the file to read (text)"},
        "offset": {"type": "number?", "description": "Line number to start reading from (0-indexed, default 0)"},
        "limit": {"type": "number?", "description": "Maximum number of lines to read (default: all lines)"}}

    def preview(self, args): return (args.get("path") or "")[:self.preview_width]

    def run(self, args):
        path = args["path"]
        with open(path) as f:
            lines = f.readlines()
        offset, limit = args.get("offset", 0), args.get("limit", len(lines))
        selected = lines[offset: offset + limit]
        return self.ok("".join(f"{offset + idx + 1:4}| {line}" for idx, line in enumerate(selected)))


class WriteTool(ToolBase):
    name = "write"
    description = "Write content to a file, overwriting if it exists"
    params = {
        "path": {"type": "string", "description": "Path to the file to write"},
        "content": {"type": "string", "description": "Content to write to the file"}}

    def preview(self, args): return (args.get("path") or "")[:self.preview_width]

    def run(self, args):
        error = _validate_file_path(args["path"])
        if error:
            return self.fail(f"write {args['path']} error: {error}")
        with open(args["path"], "w") as f:
            f.write(args["content"])
        return self.ok(f"write {len(args['content'])}byte to {args['path']} ok")


class EditTool(ToolBase):
    name = "edit"
    description = "Edit a file by replacing an exact string with a new string"
    params = {
        "path": {"type": "string", "description": "Path to the file to edit"},
        "old": {"type": "string", "description": "Exact string to be replaced"},
        "new": {"type": "string", "description": "String to replace it with"},
        "all": {"type": "boolean?", "description": "Replace all occurrences (default: false)"}}

    def preview(self, args): return (args.get("path") or "")[:self.preview_width]
    guidance = "Use **edit** (not write) for small in-place changes; ensure `old` is unique or pass `all=true`."

    def before(self, args):
        if args.get("old") and args.get("new"):
            console.diff(old=args["old"], new=args["new"], filename=args["path"])

    def confirm(self, args): return MANGO_YOLO or console.prompt_apply(f"Edit {args['path']} (y or n)?")

    def run(self, args):
        error = _validate_file_path(args["path"])
        if error:
            return self.fail(f"edit error: {error}")
        with open(args["path"]) as f:
            text = f.read()
        old, new = args["old"], args["new"]
        if old not in text:
            return self.fail("edit error: old_string not found")
        count = text.count(old)
        if not args.get("all") and count > 1:
            return self.fail(f"error: old_string appears {count} times, must be unique (use all=true)")
        replacement = (text.replace(old, new) if args.get("all") else text.replace(old, new, 1))
        with open(args["path"], "w") as f:
            f.write(replacement)
        return self.ok(f"edit {args['path']} ok")


class SearchTool(ToolBase):
    name = "search"
    description = "Search for files using a glob pattern"
    params = {
        "pat": {"type": "string", "description": "Glob pattern to match file paths (e.g. '**/*.py')"},
        "path": {"type": "string?", "description": "Directory to start search from (default: current directory)"}}
    use_spinner = True

    def run(self, args):
        pattern = (args.get("path", ".") + "/" + args["pat"]).replace("//", "/")
        files = globlib.glob(pattern, recursive=True)
        files = sorted(files, key=lambda f: os.path.getmtime(f) if os.path.isfile(f) else 0, reverse=True, )
        return self.ok("\n".join(files) or "none")


class GrepTool(ToolBase):
    name = "grep"
    description = "Search file contents recursively using a regular expression pattern"
    params = {
        "pat": {
            "type": "string",
            "description": "Regular expression pattern to search for (Python regex syntax)"},
        "path": {
            "type": "string?",
            "description": "Search directory to recursively (defaults to current working directory if omitted)"}}
    use_spinner = True

    def run(self, args):
        try:
            pattern = re.compile(args["pat"])
        except re.error as e:
            return self.fail(f"grep error: invalid regex: {e}")
        hits = []
        for filepath in globlib.glob(args.get("path", ".") + "/**", recursive=True):
            if not os.path.isfile(filepath):
                continue
            try:
                with open(filepath) as f:
                    for line_num, line in enumerate(f, 1):
                        if pattern.search(line):
                            hits.append(f"{filepath}:{line_num}:{line.rstrip()}")
            except Exception:
                continue
        return self.ok("\n".join(hits[:500]) or "none")


class BashTool(ToolBase):
    name = "bash"
    description = "Execute a shell command and return its stdout/stderr output (timeout after 60s)"
    params = {
        "cmd": {"type": "string", "description": "The shell command to execute, e.g., 'ls -la' or 'git status'"}}
    preview_lines = 100
    preview_width = 150
    use_spinner = True
    guidance = "Reach for **bash** only when no dedicated tool fits."

    def confirm(self, args):
        if MANGO_YOLO:
            return True
        is_dangerous, reason = _check_command_safety(args["cmd"])
        return not is_dangerous or console.prompt_apply(f"Execute dangerous cmd ({reason})? {args['cmd']}")

    def run(self, args):
        proc = subprocess.Popen(args["cmd"], shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            stdout, _ = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)  # 回收僵尸进程
            return self.fail(f"exec {args['cmd']} timed out after 60s")

        output_lines = stdout.splitlines(keepends=True)
        output_lines = _process_bash_output(args['cmd'], output_lines)
        return self.ok("".join(output_lines).strip() or "(empty)")


class UseSkillTool(ToolBase):
    name = "use_skill"
    description = "Load an installed skill with guidance, scripts and references"
    params = {"name": {"type": "string", "description": "Skill name"}}

    def run(self, args):
        name = args["name"]
        skills = SkillManager().all()
        if name not in skills:
            return self.fail(f"skill '{name}' not found")
        skill = skills[name]
        result = []
        meta = skill.get("meta", {})
        result.append(f"# Skill: {name}")
        result.append(meta.get("body", ""))
        scripts = skill.get("scripts", {})
        if scripts:
            result.append("\n## Scripts\n")
            for path in scripts:
                result.append(path)
        refs = skill.get("references", {})
        if refs:
            result.append("\n## References\n")
            for path in refs:
                result.append(path)
        return self.ok("\n".join(result))


class AttemptCompletionTool(ToolBase):
    name = "attempt_completion"
    description = "Indicate that the task is complete and provide the final result/answer to the user"
    params = {"result": {"type": "string", "description": "The final result or summary of the completed task"}}
    preview_lines = 500
    preview_width = 500
    guidance = "Always finish with **attempt_completion** to present the final result."

    def preview(self, args): return ''

    def run(self, args):
        return self.ok(args["result"])


# 模块级单例, 导入期扫描一次. 必须置于 ToolBase 定义之后: 扩展顶层 `from mangopi_cli import ToolBase` 依赖此处已初始化.
extension_registry = ExtensionRegistry().load()
TOOLS = {
    t.name: t for t in [ReadTool(), WriteTool(), EditTool(), SearchTool(), GrepTool(), BashTool(), UseSkillTool(),
                        AttemptCompletionTool()] + extension_registry.tools}


def load_preset(name: str) -> Optional[dict]:
    """加载 preset 配置并应用副作用 (~/.mangocli/presets/<name>/conf.py): unload_sources 逐个可逆卸载
    扩展 (PR 1), keep_tools 白名单过滤 TOOLS (逆操作登记 _per_source["__preset__"],
    unload_source("__preset__") 可恢复), 完成后触发 preset:applied 事件 (PR 2).
    返回 preset dict (SystemPrompt 据此应用 prompt_overrides); None = preset 不存在或未导出合法 preset dict."""
    path = os.path.join(MANGO_PRESET_DIR, name, "conf.py")
    if not os.path.isfile(path):
        return None
    mod = ExtensionRegistry.load_file(path)   # 与扩展同加载方式 (compile+exec, 无 pyc 缓存坑)
    preset = getattr(mod, "preset", None)
    if not isinstance(preset, dict):
        return None
    for source in preset.get("unload_sources", []) or []:
        extension_registry.unload_source(source)
    keep = preset.get("keep_tools")
    if keep:
        keep_set = set(keep)
        removed = [(name, tool) for name, tool in list(TOOLS.items()) if name not in keep_set]
        for name, _ in removed:
            del TOOLS[name]

        def inverse():
            for name, tool in removed:
                TOOLS[name] = tool

        extension_registry.get_per_source().setdefault("__preset__", []).append(inverse)
    _mango_events.emit("preset:applied", name, preset)
    return preset


def tool_schema():
    return [tool.schema() for tool in TOOLS.values()]


# --- Context manager: () ---
COMPACT_RULES = {
    "tool": {"max_tokens": 800, "keep_head": 200, "keep_tail": 200, "max_age": 21_600},  # 真实执行状态
    "reasoning_content": {"max_tokens": 500, "keep_head": 125, "keep_tail": 125, "max_age": 7_200},  # 信息密度低
    "assistant": {"max_tokens": 1500, "keep_head": 350, "keep_tail": 350, "max_age": 10_800}}


class ContextManager:
    def __init__(self):
        self.messages: List[Dict] = []
        self.white_tool_list = ["attempt_completion"]
        self.auto_compact_threshold = int(MANGO_MAX_CONTEXT * 0.8)
        self.auto_compact_disabled = False
        self.continuous_failures = 0
        self.max_failures = 3
        self.runtime_injections: List[Dict[str, Any]] = []  # 临时运行时注入，不进入 session / compact / save

    def __len__(self): return len(self.messages)

    def clear(self): self.messages = []

    def append_system(self, content: str): self.messages.append({"role": "system", "content": content})

    def append_user(self, content: str):
        self.messages.append({"role": "user", "content": content, "ts": int(time.time())})

    def inject_user(self, content: str): self.runtime_injections.append({"role": "user", "content": content})

    def clear_runtime_injections(self): self.runtime_injections = []

    def append_assistant(self, content: dict):
        content.update({"ts": int(time.time())})
        self.messages.append(content)

    def append_tool(self, tool_call_id: str, tool_name: str, content: Any):
        msg = {"role": "tool", "tool_call_id": tool_call_id, "tool_name": tool_name, "ts": int(time.time())}
        if isinstance(content, dict) and content.get("type") == "image":
            msg["content"] = [{"type": "text", "text": content.get("text", "image")},
                              {"type": "image_url", "image_url": {"url": content["image_url"]}}]
        else:
            msg["content"] = content or ""
        self.messages.append(msg)

    def load(self, persist_file: str):
        if os.path.exists(persist_file):
            try:
                with open(persist_file, "r", encoding="utf-8") as f:
                    self.messages = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                self.backup(persist_file)    # 备份损坏会话文件
                self.messages = []    # 清空消息列表，使后续流程以全新会话开始
                console.error(f"session.json file is corrupted ({e}). "
                              f"The corrupted file has been backed up and a new session.json has been generated.")

    def save(self, persist_file: str):
        with open(persist_file, "w", encoding="utf-8") as fp:
            fp.write(json.dumps(self.messages, indent=2, ensure_ascii=False))

    @staticmethod
    def backup(persist_file: str):
        backup_path = persist_file + f".{str(int(time.time()))}.backup"    # 备份会话文件
        if os.path.exists(persist_file):
            try:
                os.rename(persist_file, backup_path)
                console.warning(f"Session file backed up to {backup_path}")
            except Exception as e:
                console.warning(f"Failed to backup corrupted session file: {e}")

    def get_messages(self) -> List[Dict[str, Any]]: return self.messages

    def get_latest(self, n: int = 10) -> List[Dict]: return self.messages[-n:]

    @staticmethod
    def compact_text(text: str, head: int, tail: int) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        return text if len(text) <= head + tail else f"{text[:head]}\n...\n{text[-tail:]}\n<compacted>"

    def split_turns(self):  # messages 拆分为 turn, user -> assistant -> tool... -> assistant
        turns, current = [], []
        for m in self.messages:
            role = m.get("role")
            if role == "system":
                continue
            if role == "user" and current:
                turns.append(current)
            current = [m] if role == "user" else current + [m]
        if current:
            turns.append(current)
        return turns

    def _role_msgs(self, role, n=None) -> List[Dict]:  # 提取特定 role 的消息,可选最近 n 条
        return [m for m in (self.messages if n is None else self.messages[-n:]) if m.get("role") == role]

    def _tool_names(self, msgs: Optional[List[Dict]] = None) -> List[str]:  # 从消息列表提取 tool_name(去空)
        return [m.get("tool_name", "") for m in (msgs or self.messages) if m.get("role") == "tool" and m.get("tool_name")]

    def _last_user_content(self, msgs: Optional[List[Dict]] = None) -> str:  # 最近 user message 的 content
        return next((m.get("content", "") for m in reversed(msgs or self.messages) if m.get("role") == "user"), "")

    def _under_threshold(self) -> bool: return self.total_tokens() < self.auto_compact_threshold

    def tool_fingerprint(self, n_turns: int = 10) -> str:  # Return (user_query, [tool, ...]) pairs from recent turns.
        fp = [[self._last_user_content(t), self._tool_names(t)] for t in self.split_turns()[-n_turns:]]
        fp = [f for f in fp if f[1]]  # 只保留有 tool 调用的 turn
        return str(fp) if fp else "[]"

    @staticmethod
    def estimated_tokens(msg: Dict[str, Any]) -> int: return len(json.dumps(msg, ensure_ascii=False)) // 4 + 4

    def total_tokens(self) -> int: return sum(self.estimated_tokens(m) for m in self.messages)

    def auto_compact_if_needed(self):
        if self.auto_compact_disabled or self._under_threshold():
            return
        try:
            self.session_memory_compact()
            if self._under_threshold():
                return
            self.compact_conversation()
            if self._under_threshold():
                return
        except Exception:
            pass
        if self.continuous_failures >= self.max_failures:
            return
        try:
            self.full_compact()
            self.continuous_failures = 0
        except Exception:
            self.continuous_failures += 1

    def micro_compact(self):
        now, rule = int(time.time()), COMPACT_RULES["tool"]
        for m in self.messages:
            if m.get("role") != "tool" or m.get("tool_name") in self.white_tool_list:  # not tool/white tool pass
                continue
            content = m.get("content", "")
            if not isinstance(content, str) or content.endswith("<compacted>"):  # compacted/base64 编码 pass
                continue
            if now - m.get("ts", now) < rule.get("max_age", 0):  # new tool pass
                continue
            if self.estimated_tokens({"content": content}) <= rule["max_tokens"]:  # too small pass
                continue
            m["content"] = self.compact_text(content, rule["keep_head"], rule["keep_tail"])

    def session_memory_compact(self, retain_turns: int = 10, min_tokens: int = 200) -> bool:
        systems = [copy.deepcopy(m) for m in self.messages if m.get("role") == "system"]

        turns = self.split_turns()
        if len(turns) <= retain_turns:
            return False

        old_turns = turns[:-retain_turns]
        recent_turns = turns[-retain_turns:]
        compacted = []
        for turn in old_turns:  # old turns
            for m in turn:
                cm = copy.deepcopy(m)
                if cm.get("role") == "tool":
                    cm["content"] = f"<Old tool({cm['tool_name']}:{cm['tool_call_id']}) result force compacted>"
                elif cm.get("role") == "assistant":
                    content = cm.get("content", "")  # llm output
                    if isinstance(content, str) and content:
                        rule = COMPACT_RULES["assistant"]
                        if (not content.endswith("<compacted>") and
                                self.estimated_tokens({"content": content}) > rule["max_tokens"]):
                            cm["content"] = self.compact_text(content, rule["keep_head"], rule["keep_tail"])
                    reasoning = (cm.get("reasoning_content") or cm.get("reasoning") or cm.get("reasoning_details") or "")
                    if reasoning:
                        rule = COMPACT_RULES["reasoning_content"]
                        if (not reasoning.endswith("<compacted>") and
                                self.estimated_tokens({"content": reasoning}) > rule["max_tokens"]):
                            compacted_text = self.compact_text(reasoning, rule["keep_head"], rule["keep_tail"])
                            if "reasoning_content" in cm:
                                cm["reasoning_content"] = compacted_text
                            if "reasoning" in cm:
                                cm["reasoning"] = compacted_text
                            if "reasoning_details" in cm:
                                cm["reasoning_details"] = compacted_text
                compacted.append(cm)
        for turn in recent_turns:
            compacted.extend(copy.deepcopy(turn))
        self.messages = systems + compacted
        return True

    def compact_conversation(self, retain_turns: int = 8):
        systems = [copy.deepcopy(m) for m in self.messages if m.get("role") == "system"]
        turns = self.split_turns()
        if not turns:
            return
        old_turns = turns[:-retain_turns]
        recent_turns = turns[-retain_turns:]
        rebuilt = systems[:]
        for turn in old_turns + recent_turns:
            rebuilt.extend(copy.deepcopy(turn))

        if sum(self.estimated_tokens(m) for m in rebuilt) <= self.auto_compact_threshold:  # 已低于阈值，直接返回
            self.messages = rebuilt
            return

        trimmed_old_turns = list(old_turns)
        while trimmed_old_turns:
            candidate = systems[:]
            for turn in trimmed_old_turns:
                candidate.extend(copy.deepcopy(turn))
            for turn in recent_turns:
                candidate.extend(copy.deepcopy(turn))
            if sum(self.estimated_tokens(m) for m in candidate) <= self.auto_compact_threshold:
                self.messages = candidate
                return
            trimmed_old_turns.pop(0)

        trimmed_recent_turns = list(recent_turns)  # 极端情况:old turns 全删后仍超限
        while len(trimmed_recent_turns) > 1:
            candidate = systems[:]
            for turn in trimmed_recent_turns:
                candidate.extend(copy.deepcopy(turn))
            if sum(self.estimated_tokens(m) for m in candidate) <= self.auto_compact_threshold:
                self.messages = candidate
                return
            trimmed_recent_turns.pop(0)

        self.messages = systems + [copy.deepcopy(m) for turn in trimmed_recent_turns for m in turn]  # 最终 fallback

    def full_compact(self):    # 手动执行，调用模型进行大规模的摘要生成，后续实现
        _full_compact_prompt = """\
        Create a detailed summary of the conversation so far.
        Focus on: user's original intent, files modified with key code snippets, errors encountered and their fixes, 
        and the current work in progress.
        Use this structure:
        1. Primary Request and Intent
        2. Key Technical Concepts
        3. Files and Code Sections (most recent first)
        4. Errors and fixes
        5. Problem Solving
        6. All user messages
        7. Pending Tasks
        8. Current Work

        Output in <analysis>...</analysis><summary>...</summary> format. Example:

        <analysis>
        [Your thought process, ensuring all points are covered thoroughly and accurately]
        </analysis>

        <summary>
        1. Primary Request and Intent:
          [Detailed description]
        2. Key Technical Concepts:
          - [Concept 1] - [...]
        3. Files and Code Sections:
          - [File Name 1] - [why important] - [changes made] - [Important Code Snippet]
          - [File Name 2] - [Important Code Snippet]
        4. Errors and fixes:
          - [Error 1]: [How fixed] [User feedback if any]
        5. Problem Solving:
          [Description of solved problems and ongoing troubleshooting]
        6. All user messages:
          - [Detailed non tool use user message]
        7. Pending Tasks:
          - [Task 1]
        8. Current Work:
          [Precise description of current work]
        </summary>
        """
        try:
            self.append_user(_full_compact_prompt)
            respon = provider.parse_response(_request(
                provider.api_url, provider.build_body(self.messages), headers=provider.headers()))
            if respon.get("content"):
                systems = [m for m in self.messages if m.get("role") == "system"]
                self.messages = systems
                self.append_user(respon["content"])
            else:
                raise RuntimeError("full compact err: llm respon null")
        except Exception as e:
            raise RuntimeError(f"full compact err: {e}")

    def prepare_for_api(self):
        self.micro_compact()
        before = self.total_tokens()
        self.auto_compact_if_needed()
        after = self.total_tokens()
        if before > after:  # Compatible with Python 3.6+
            console.compact_status(
                before_tokens=before, after_tokens=after, max_context=MANGO_MAX_CONTEXT, strategy="auto")
            _mango_events.emit("agent:compact", before, after, before - after)
        return self.messages + self.runtime_injections


class BaseProvider:
    _reasoning_field: str = "reasoning_content"  # 子类覆盖：MiniMax 用 reasoning_details

    def __init__(self, api_url: str, api_key: str, model: str):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model

    def headers(self) -> dict: return {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}

    def build_body(self, messages: List[Dict[str, Any]]) -> dict: raise NotImplementedError

    def parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]: raise NotImplementedError

    @staticmethod
    def normalize_tool_calls(message: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw_tool_calls = message.get("tool_calls") or []
        if not raw_tool_calls and message.get("function_call"):  # OpenAI old function_call fallback
            raw_tool_calls = [{"id": "call_0", "type": "function", "function": message["function_call"]}]
        if not raw_tool_calls:
            return []

        tool_calls = []
        for tc in raw_tool_calls:
            function = tc.get("function", {})
            args_str = function.get("arguments", "{}")
            try:
                arguments = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append({
                "id": tc.get("id", ""),
                "type": tc.get("type", "function"),
                "name": function.get("name", ""),
                "arguments": arguments,
            })
        return tool_calls

    @staticmethod
    def extract_reasoning(message: Dict[str, Any]) -> str:
        if message.get("reasoning_content"):  # DeepSeek
            return message["reasoning_content"]
        if message.get("reasoning"):  # Qwen / Some OpenAI-compatible providers
            return message["reasoning"]
        if message.get("reasoning_details"):  # Minimax providers
            return message["reasoning_details"]
        return ""

    def _extract_reasoning_text(self, message: Dict[str, Any]) -> str:  # 从任意已知 reasoning 字段提取纯文本
        val = self.extract_reasoning(message)
        if isinstance(val, list):
            return "\n".join(d.get("text", "") for d in val if isinstance(d, dict) and d.get("text"))
        return val or ""

    def _sanitize_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:  # Strip non-standard fields
        def _text(_content):
            if isinstance(_content, list):
                return next((b.get("text", "") for b in _content if b.get("type") == "text"), "[image content omitted]")
            return _content

        def _wrap_reasoning_detail(text):  # minimax
            return [{"type": "reasoning.text", "id": "reasoning-text-1", "format": "MiniMax-response-v1",
                     "index": 0, "text": text}]

        clean = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                clean.append({"role": "system", "content": m.get("content", "")})
            elif role == "user":
                clean.append({"role": "user", "content": _text(m.get("content", ""))})
            elif role == "assistant":
                msg = {"role": "assistant", "content": m.get("content") or ""}
                if m.get("tool_calls"):
                    msg["tool_calls"] = m["tool_calls"]
                if self._reasoning_field and m.get(self._reasoning_field):
                    msg[self._reasoning_field] = m[self._reasoning_field]
                else:
                    reasoning = self._extract_reasoning_text(m)
                    if reasoning:
                        if self._reasoning_field == "reasoning_details":
                            msg["reasoning_details"] = _wrap_reasoning_detail(reasoning)
                        else:
                            msg["reasoning_content"] = reasoning
                clean.append(msg)
            elif role == "tool":
                clean.append({"role": "tool", "tool_call_id": m.get("tool_call_id", ""),
                              "content": _text(m.get("content", ""))})
        return clean


class OpenAIProvider(BaseProvider):
    def build_body(self, messages: List[Dict[str, Any]]) -> dict:
        return {"model": self.model, "messages": self._sanitize_messages(messages), "tools": tool_schema(), "stream": False}

    def parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message", {})
        tool_calls = self.normalize_tool_calls(message)
        return {
            "finish_reason": choice.get("finish_reason"),
            "raw_message": message,
            "content": message.get("content") or "",
            "reasoning_content": self.extract_reasoning(message),
            "tool_calls": tool_calls,
            "has_tool_calls": bool(tool_calls),
            "model": response.get("model", ""),
            "usage": response.get("usage", {})
        }


class DeepSeekProvider(OpenAIProvider):
    def build_body(self, messages: List[Dict[str, Any]], thinking: str = "enabled", effort: str = "max") -> dict:
        body = super().build_body(messages)
        body.update({"thinking": {"type": thinking}, "reasoning_effort": effort})
        return body


class MiniMaxProvider(OpenAIProvider):
    _reasoning_field = "reasoning_details"

    def build_body(self, messages: List[Dict[str, Any]], reasoning_split: bool = True) -> dict:
        body = super().build_body(messages)
        body.update({"reasoning_split": True})  # 同时返回 reasoning_content(str) 和 reasoning_details(list)
        return body


def _new_provider(model: str, api_url: str, api_key: str) -> BaseProvider:
    url = api_url
    if not url.endswith("/chat/completions"):
        url = url.rstrip("/") + "/chat/completions"
    if "deepseek" in model.lower():
        return DeepSeekProvider(api_url=url, api_key=api_key, model=model)
    if "minimax" in model.lower():
        return MiniMaxProvider(api_url=url, api_key=api_key, model=model)
    return OpenAIProvider(api_url=url, api_key=api_key, model=model)


def create_provider() -> BaseProvider:
    return _new_provider(MANGO_MODEL, MANGO_API_URL, MANGO_KEY)


provider = create_provider()


def chat_completion(messages: List[Dict[str, str]]):
    return _request(provider.api_url, provider.build_body(messages), headers=provider.headers())


def run_tool(tool_name, tool_args) -> dict:
    tool: ToolBase = TOOLS[tool_name]
    _mango_events.emit("tool:before", tool_name, tool_args)  # 事件总线: 工具执行前 (TOOLS 查找失败不触发)
    try:
        console.tool_call(tool.name, tool.preview(tool_args))
        tool.before(tool_args)
        if not tool.confirm(tool_args):
            # 拒绝路径不 emit. 措辞明确: 用户在确认环节主动拒绝 (可能对修改有疑问),
            # agent 应停下询问用户, 而非重试或绕过确认.
            return {"success": False, "content": "error: action denied by user confirmation — pause and ask the user before retrying"}
        if tool.use_spinner:
            console.start_spinner()
        result = tool.run(tool_args)
        _mango_events.emit("tool:after", tool_name, result)  # 事件总线: 工具执行成功 (result 产生后立即)
        tool_status, tool_content = result["success"], result["content"]
        if tool.use_spinner:
            console.end_spinner()
        tool.after(tool_content)  # 需要注意区分 str 和 dict

        if isinstance(tool_content, dict) and tool_content.get("type") == "image":
            display_str = tool_content.get("text", "[image]")
        elif tool_content is None:
            display_str = ""
        else:
            display_str = str(tool_content)

        if not display_str:
            console.tool_display(f"  {DIM}⎿  (no output){RESET}")
        else:
            result_lines = display_str.split("\n")
            lines_to_show = result_lines[:tool.preview_lines]
            preview_lines = [
                line if len(line) <= tool.preview_width else line[:tool.preview_width - 3] + "..."
                for line in lines_to_show]
            if len(result_lines) > tool.preview_lines:
                more = len(result_lines) - tool.preview_lines
                preview_lines.append(f"... and {more} more line{'s' if more > 1 else ''}")
            prefix = f"  {DIM}⎿  "
            for i, line in enumerate(preview_lines):
                if i == 0:
                    console.tool_display(f"{prefix}{line}{RESET}")
                else:
                    console.tool_display(f"     {DIM}{line}{RESET}")

        console.tool_result(tool.name, ok=tool_status, snippet=display_str[:200])
        return result
    except Exception as err:
        console.end_spinner()
        _mango_events.emit("tool:error", tool_name, err)  # 事件总线: 工具执行异常
        return {"success": False, "content": f"run tool {tool_name} error: {err}"}


class SystemPrompt:
    """ 分层装配的提示词运行时. 可根据会话状态、记忆、环境变量等动态生成完整的 system prompt."""
    def __init__(self):
        self.sections = []    # 有序的 section 列表，每个元素为 (section_name, content)
        self._init_default_sections()    # 默认加载基础 sections

    def _init_default_sections(self):
        self.sections.append(("base_intro", self._build_base_intro()))
        self.sections.append(("safety", self._build_safety()))
        self.sections.append(("builtin_rules", self._build_builtin_rules()))
        self.sections.append(("tool_guidance", self._build_tool_guidance()))
        self.sections.append(("skills_guidance", self._build_skills_guidance()))
        self.sections.append(("memory", self._build_user_rules()))
        self.sections.append(("environment", self._build_environment()))
        # 扩展通道: 同名段覆盖默认内容 (强化), 异名段追加
        defaults = {name for name, _ in self.sections}
        for entry in extension_registry.prompt_sections:
            dynamic = entry() if callable(entry) else [entry]
            for name, content in dynamic:
                if name in defaults:
                    self.sections = [(n, c if n != name else content) for n, c in self.sections]
                else:
                    self.sections.append((name, content))
        # preset 级 prompt 覆盖 (v0.1.50 模式系统): base 覆盖 base_intro 段, clear_sections 删除段,
        # append_sections 追加段. 副作用幂等 (load_preset 已在 main 应用过, 此处仅取配置).
        preset = load_preset(MANGO_PRESET)
        overrides = (preset or {}).get("prompt_overrides") or {}
        if overrides.get("base"):
            self.sections = [("base_intro", overrides["base"]) if n == "base_intro" else (n, c)
                             for n, c in self.sections]
        for section_name in overrides.get("clear_sections", []) or []:
            self.sections = [(n, c) for n, c in self.sections if n != section_name]
        for sec in overrides.get("append_sections", []) or []:
            self.sections.append((sec["name"], sec["content"]))

    @staticmethod
    def _build_base_intro() -> str:
        return ("You are an interactive agent that helps users with software engineering tasks. "
                "Use the instructions below and the tools available to you to assist the user.\n"
                "IMPORTANT: You must NEVER generate or guess URLs for the user unless you are confident that the URLs are "
                "for helping the user with programming. For file paths, always prefer absolute paths when possible. If "
                "you need to read a directory, use the bash tool (ls) because the read tool cannot read directories.\n")

    @staticmethod
    def _build_tool_guidance() -> str:
        parts = [  # 总纲: 工具清单随注册变化, 保留为段引言 (不属于任何单一工具)
            "## Tool Selection\n\n",
            "Use the dedicated tool when one exists (read/write/edit/search/grep/attempt_completion)."]
        # 单一数据源: 各工具自身 guidance 动态拼接 (内置 + 扩展统一机制).
        # 收尾句 (attempt_completion) 稳定排序至最后; 其余保持 TOOLS 注册序, 扩展工具追加于内置之后 (覆盖语义不受影响).
        guidance_tools = sorted((t for t in TOOLS.values() if t.guidance),
                                key=lambda t: t.name == "attempt_completion")
        parts.extend(t.guidance for t in guidance_tools)
        return "\n".join(parts) + "\n\n"

    @staticmethod
    def _build_skills_guidance() -> str:
        desc = skill_manager.descriptions()
        if not desc:
            return "## Skills Selection Guidelines\n\nNo skills available.\n\n"
        return (f"## Skills Selection Guidelines\n\n{desc}\n\n"
                "- If an installed skill is relevant, call use_skill first before proceeding.\n"
                "- Skills may contain: workflows, best practices, reusable scripts, references\n\n")

    @staticmethod
    def _build_environment() -> str:
        os_info = f"{platform.system()} {platform.release()} ({platform.machine()})"
        return (f"## Environment\n"
                f"- Working directory: {project_root}\n"
                f"- Operating system: {os_info}\n"
                f"- Python version: {sys.version.split()[0]}\n"
                f"- Shell: {os.environ.get('SHELL', 'unknown')}\n")

    @staticmethod
    def _build_user_rules() -> str:  # 优先级: .mangocli/AGENT.md (行业通用约定, 为主) > .mangocli/MANGO.md (mangopi 私有);
        parts = []
        for p in (os.path.join(project_root, ".mangocli", "AGENT.md"),
                  os.path.join(project_root, ".mangocli", "MANGO.md")):
            if os.path.exists(p) and os.path.getsize(p) > 0:
                with open(p, "r", encoding="utf-8") as f:
                    parts.append(f.read().strip())
        if not parts:
            return "## User Rules\n\nNo user-defined rules.\n"
        return "## User Rules\n\n" + "\n\n".join(parts)

    @staticmethod
    def _build_safety() -> str:
        return ("## Safety\n\n"
                "Destructive commands and any access outside the project root require explicit user confirmation.\n\n")

    @staticmethod
    def _build_builtin_rules() -> str:
        return ("## Built-in Rules\n\n"
                "**1. Think before coding.** State assumptions. If uncertain, ask rather than guess.\n"
                "**2. Minimum code.** If 200 lines can be 50, rewrite. No features beyond what was asked.\n"
                "**3. Surgical changes.** Touch only what you must. Don't 'improve' adjacent code or "
                "refactor things that aren't broken. Match existing style.\n"
                "**4. Verify before completion.** Transform tasks into verifiable goals: "
                "'Write tests for X, then make them pass.' For multi-step work, state a brief plan first.\n\n")

    def assemble(self) -> str: return "\n\n".join(content for _, content in self.sections)


def agent_loop(ctx: ContextManager, ctx_file_path: str, user_input: str, cancel_event: Optional[threading.Event] = None):
    """主 agent 循环. cancel_event 由 AcpServer 传入 (ACP session/cancel): 置位后不再发起
    新的 LLM 调用/工具执行 (软取消), 当前阻塞调用返回后立即终止."""
    _mango_events.emit("agent:user_input", "chat", user_input, ctx_file_path, len(user_input))

    ctx.append_user(user_input)

    iteration = 0
    while True:
        if cancel_event is not None and cancel_event.is_set():
            break  # ACP: session/cancel 已收到, 不再发起新的 LLM 调用
        console.start_spinner("Request...")
        response = provider.parse_response(chat_completion(ctx.prepare_for_api()))
        console.end_spinner()
        ctx.append_assistant(response["raw_message"])

        iteration += 1
        console.token_usage(
            iteration=iteration, input_tokens=response["usage"]["prompt_tokens"],
            output_tokens=response["usage"]["completion_tokens"], context_tokens=ctx.total_tokens(),
            max_context=MANGO_MAX_CONTEXT)

        _mango_events.emit("agent:assistant", iteration, response.get("finish_reason", ""),
                           response["has_tool_calls"], len(response["tool_calls"]),
                           bool(response["reasoning_content"]), len(response["reasoning_content"]),
                           len(response["content"]), response["model"],
                           (response.get("usage") or {}).get("prompt_tokens"),
                           (response.get("usage") or {}).get("completion_tokens"))

        if response["reasoning_content"]:
            console.thinking(response["reasoning_content"])
        if (response["content"] and
                not any(tc["name"] == "attempt_completion" for tc in response.get("tool_calls", []))):
            console.output(response["content"])

        if response["finish_reason"] == "stop":
            break  # 模型明确表示结束，退出循环
        if response["has_tool_calls"]:
            completed = False
            for tool in response["tool_calls"]:
                if cancel_event is not None and cancel_event.is_set():
                    break  # ACP: 已取消, 不再执行后续工具调用
                tool_name, tool_args = tool["name"], tool["arguments"]
                result = run_tool(tool_name, tool_args)  # tool:before/after 事件由 run_tool 触发
                ctx.append_tool(tool["id"], tool_name, result["content"])
                if tool_name == "attempt_completion":
                    completed = True
                    break  # 遇到完成工具就退出当前轮工具调用
            if completed:
                break
        else:
            break
        if iteration >= MANGO_MAX_ITER:
            break
    ctx.save(ctx_file_path)
    _mango_events.emit("agent:end", iteration)  # 会话级事件: trace 等扩展据此落盘


def _parse_args(args=None):
    parser = argparse.ArgumentParser(prog="mangopi-cli", description="Mangopi CLI — single-file AI coding agent")
    parser.add_argument("--version", action="version", version=f"mangopi-cli v{__version__}")
    parser.add_argument("--doctor", action="store_true", help="Run environment diagnostics and exit")
    parser.add_argument("--yolo", action="store_true", help="Skip edit/bash confirmations (overrides MANGO_YOLO)")
    parser.add_argument("--acp", action="store_true",
                        help="Run as ACP (Agent Client Protocol) v1 agent server over stdio (JSON-RPC)")
    return parser.parse_args(args)


def _current_session_name() -> str:
    """读取上次会话名 (.current); 无效或对应文件缺失时回退默认 "session"."""
    try:
        with open(os.path.join(session_dir, ".current"), "r", encoding="utf-8") as f:
            name = f.read().strip()
    except OSError:
        return "session"
    if not name or ".." in name or "/" in name:
        return "session"  # 防御: 磁盘内容不可信
    if not os.path.isfile(os.path.join(session_dir, name + ".json")):
        return "session"  # 会话文件被删 → 回退
    return name


def _save_current_session(name: str):
    try:
        with open(os.path.join(session_dir, ".current"), "w", encoding="utf-8") as f:
            f.write(name)
    except OSError:
        pass


def main():
    initialize_system()
    args = _parse_args()
    global MANGO_YOLO
    MANGO_YOLO = args.yolo or MANGO_YOLO
    if MANGO_PRESET:
        if load_preset(MANGO_PRESET) is None:
            console.warning(f"preset {MANGO_PRESET!r} not found in {MANGO_PRESET_DIR}/")
    if args.doctor:
        sys.exit(doctor())
    if args.acp:
        acp_entry = extension_registry.entry_points.get("acp")  # 扩展优先 (entry_points 契约通道)
        if acp_entry is not None:
            sys.exit(acp_entry())
        target = extensions_dir or "~/.mangocli/presets/<preset>/extensions/ (set MANGO_PRESET)"
        console.error(f"ACP server not installed: copy examples/extensions/acp.py to {target}")
        sys.exit(1)

    global provider

    mode = provider.model
    yolo_tag = f" | {BOLD}YOLO{RESET}{DIM}" if MANGO_YOLO else ""
    preset_tag = f" | {DIM}{MANGO_PRESET}[{len(TOOLS)} tool]{RESET}" if MANGO_PRESET else ""
    print(f"{BOLD}Mango Cli v{__version__}{RESET} | {DIM}{mode}{yolo_tag} | {project_root}{RESET}{preset_tag}\n")

    session_name = _current_session_name()  # 恢复上次会话; 无记录回退默认 "session" (零迁移)
    ctx_file_path = os.path.join(session_dir, session_name + ".json")
    ctx = ContextManager()
    ctx.load(ctx_file_path)
    console.text(f"Session: {session_name}")

    prompt_runtime = SystemPrompt()
    system_prompt = prompt_runtime.assemble()
    if len(ctx) == 0:  # 刚初始化的ctx才需要system prompt
        ctx.append_system(system_prompt)

    while True:
        try:
            console.separator()
            user_input = input(f"{BOLD}{BLUE}❯{RESET} ").strip()
            if not user_input:
                continue
            if user_input.strip() in ("/q", "/quit"):  # 退出
                break
            if user_input.strip() in ("/c", "/compact"):  # 手动触发 full compact
                ctx.full_compact()
                console.success("Full compact success.")
                continue
            if user_input.strip() in ("/n", "/new"):  # 创建新的session
                ctx.backup(ctx_file_path)
                ctx.clear()
                ctx.append_system(system_prompt)
                console.success("New session created.")
                continue
            if user_input.strip() in ("/s", "/session"):  # 列出所有会话 (mtime 倒序, 当前会话标记 *)
                try:
                    files = os.listdir(session_dir)
                except OSError:
                    files = []
                files = sorted([f for f in files if f.endswith(".json")],
                               key=lambda f: os.path.getmtime(os.path.join(session_dir, f)), reverse=True)
                console.text("Sessions:")
                for f in files:
                    fpath = os.path.join(session_dir, f)
                    try:
                        with open(fpath, "r", encoding="utf-8") as fh:
                            n = len(json.load(fh))
                    except (json.JSONDecodeError, IOError):
                        n = 0
                    mtime = datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%m-%d %H:%M")
                    mark = "*" if f[:-5] == session_name else " "
                    console.text(f" {mark} {f[:-5]:<20} {n:>4} msgs  {mtime}")
                continue
            if user_input.strip().startswith("/s ") or user_input.strip().startswith("/session "):  # 切换会话
                parts = user_input.strip().split(maxsplit=1)
                name = parts[1].strip()
                if not name or ".." in name or "/" in name:
                    console.error("Invalid session name")
                    continue
                ctx.save(ctx_file_path)  # 先保存当前会话
                session_name = name
                ctx_file_path = os.path.join(session_dir, name + ".json")
                ctx.clear()
                ctx.load(ctx_file_path)
                if len(ctx) == 0:  # 新会话才需要 system prompt
                    ctx.append_system(system_prompt)
                ctx.save(ctx_file_path)  # 立即落盘: 保证 .current 指向的文件存在, 重启后可靠恢复
                _save_current_session(name)  # 持久化当前会话, 重启后自动恢复
                console.success(f"Switched to session '{name}'")
                continue
            if user_input.strip() in ("/h", "/help"):
                helper()
                continue

            normal_message = f"{user_input}, Current date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            agent_loop(ctx, ctx_file_path, normal_message)
        except (KeyboardInterrupt, EOFError):
            break
        except Exception as err:
            console.end_spinner()  # 触发异常时, end_spinner 未被触发
            print(f"{RED}⏺ Error: {err}{RESET}")
        finally:
            ctx.clear_runtime_injections()
            ctx.save(ctx_file_path)


if __name__ == '__main__':
    main()
