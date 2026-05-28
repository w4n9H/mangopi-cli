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
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    import readline  # 解决 Unix-like 系统中 input 无法正常删除中文的问题
except Exception:
    pass

__version__ = "0.1.17"
__author__ = "moofs"
__license__ = "Apache License 2.0"

# --- System Env ---
MANGO_KEY = os.environ.get("MANGO_KEY")
MANGO_API_URL = os.environ.get("MANGO_API_URL", "https://api.deepseek.com")
MANGO_MODEL = os.environ.get("MANGO_MODEL", "deepseek-v4-flash")
MANGO_MAX_CONTEXT = int(os.environ.get("MANGO_MAX_CONTEXT", 1_000_000))
LANGUAGE = os.environ.get("MANGO_LANG", "en").lower()


project_root = os.getcwd()
base_persist_dir = os.path.join(project_root, '.mangocli')
session_dir = os.path.join(project_root, ".mangocli", "session")

# ANSI colors
RESET, BOLD, SOFT, DIM = "\033[0m", "\033[1m", "\033[37m", "\033[2m"
BLUE, CYAN, GREEN, YELLOW, RED, GREY, ORANGE = (
    "\033[34m", "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[90m", "\033[38;2;245;78;0m")


# --- i18n dict (zh, en)---
I18N = {
    "zh": {
        "tool.call": "工具调用",
        "tool.result.ok": "成功应用",
        "tool.result.fail": "执行失败",
        "llm.thinking": "思考中",
        "llm.output": "输出",
        "context.compact": "上下文压缩",
        "context.compact.strategy": "策略",
        "context.round": "轮次",
        "context.tokens_in_out": "tokens 输入/输出",
        "cli.welcome": "Mangopi CLI — 基于大模型的命令行编程助手",
        "cli.help_intro": "内置命令:",
        "cli.help_commands": {
            "/q or /quit": "退出程序",
            "/c or /compact": "手动压缩当前会话（释放上下文空间）",
            "/n or /new": "结束当前会话并创建一个全新的会话",
            "/g or /goal <query>": "进入 Goal 模式，自主规划、执行并验证直到完成目标",
            "/h or /help": "显示本帮助信息"},
        "safety.warn.dangerous_command": "检测到危险命令",
        "safety.danger.rm": "文件删除",
        "safety.danger.mkfs": "磁盘格式化或分区",
        "safety.danger.chmod": "危险权限修改",
        "safety.danger.sudo": "提权操作",
        "safety.danger.kill": "危险进程操作",
        "safety.danger.env": "环境变量或系统配置修改",
        "safety.danger.history": "清理历史/日志"},
    "en": {
        "tool.call": "Tool call",
        "tool.result.ok": "Applied successfully",
        "tool.result.fail": "Execution failed",
        "llm.thinking": "Thinking",
        "llm.output": "Output",
        "context.compact": "Context compact",
        "context.compact.strategy": "Strategy",
        "context.round": "round",
        "context.tokens_in_out": "tokens in/out",
        "cli.welcome": "Mangopi CLI — Large Model CLI Assistant",
        "cli.help_intro": "Built-in commands:",
        "cli.help_commands": {
            "/q or /quit": "Quit",
            "/c or /compact": "Manually compact current session",
            "/n or /new": "End current session and start a new one",
            "/g or /goal <query>": "Enter Goal mode — autonomously plan, execute and verify until the goal is achieved",
            "/h or /help": "Show this help info"},
        "safety.warn.dangerous_command": "Dangerous command detected",
        "safety.danger.rm": "File deletion",
        "safety.danger.mkfs": "Disk formatting or partition",
        "safety.danger.chmod": "Dangerous permission change",
        "safety.danger.sudo": "Privilege escalation",
        "safety.danger.kill": "Dangerous process operation",
        "safety.danger.env": "Environment or system config change",
        "safety.danger.history": "History/log clearing"}
}


def _c(text, color): return f"{color}{text}{RESET}"


def _i18n(key: str): return I18N[LANGUAGE].get(key, "")


# --- UI ---
class Printer:
    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self):
        self._spinner_running = False
        self._spinner_thread = None
        self._spinner_message = ""
        self._lock = threading.RLock()

    @staticmethod
    def _clear_spinner_line():
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def _write_line(self, text: str = ""):
        with self._lock:
            was_running = self._spinner_running
            if was_running:
                self._clear_spinner_line()
            print(text)
            if was_running:
                self._render_spinner_frame()

    def _render_spinner_frame(self, frame: str = "⠋"):
        text = f"{_c(frame, ORANGE)} {_c(self._spinner_message, ORANGE)}"
        sys.stdout.write("\r" + text)
        sys.stdout.flush()

    def section(self, title):
        self._write_line()
        self._write_line(_c(f"• {title}", ORANGE))

    def tool_call(self, name: str, desc: str):
        self.section(_i18n("tool.call"))
        self._write_line(f"{_c('› ', GREY)}{_c(name, CYAN)}  {_c(desc, GREY)}")

    def tool_result(self, ok=True):
        icon = "✓" if ok else "✗"
        color = GREEN if ok else RED
        suffix = _i18n("tool.result.ok") if ok else _i18n("tool.result.fail")
        self._write_line(f"  {_c(icon, color)}{_c(suffix, GREY)}")

    def success(self, msg: str): self._write_line(f"{_c('✓ ', GREEN)}{_c(msg, GREY)}")

    def error(self, msg: str): self._write_line(f"{_c('✗ ', RED)}{_c(msg, GREY)}")

    def warning(self, msg: str): self._write_line(f"{_c('! ', YELLOW)}{_c(msg, GREY)}")

    def text(self, msg: str): self._write_line(_c(msg, GREY))

    def separator(self):
        self._write_line(f"{DIM}{'─' * min(os.get_terminal_size().columns, 80)}{RESET}")

    def thinking(self, content: str):
        self.section(_i18n("llm.thinking"))
        for line in content.splitlines():
            self._write_line("  " + _c(line, GREY))

    def output(self, content: str):
        self.section(_i18n("llm.output"))
        for line in content.splitlines():
            self._write_line("  " + _c(line, SOFT))

    def token_usage(self, iteration: int, input_tokens: int, output_tokens: int, context_tokens: int, max_context: int):
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
        self._write_line(f"  {_c(_i18n('context.compact.strategy'), GREY)} {_c(strategy, ORANGE)}")
        self._write_line(
            f"  {_c('tokens', GREY)} {_c(f'{before_tokens:,}', RED)} {_c('→', GREY)} "
            f"{_c(f'{after_tokens:,}', GREEN)} {_c(f'(-{saved:,})', ORANGE)}"
        )
        self._write_line(f"  {_c('context', GREY)} {_c(f'{percent}%', color)}")

    @staticmethod
    def prompt_apply(message: str) -> bool:
        while True:
            resp = input(f"{YELLOW}{message} [y/n]: {RESET}").strip().lower()
            if resp in ("y", "yes"):
                return True
            elif resp in ("n", "no"):
                return False
            else:
                print("input y or n")

    def diff(self, old: str, new: str, context: int = 3, filename: str = "file.py"):
        self.section("Code Diff")
        old_lines = old.splitlines()
        new_lines = new.splitlines()
        diff_lines = difflib.unified_diff(
            old_lines, new_lines, fromfile=f"a/{filename}", tofile=f"b/{filename}", lineterm="", n=context,
        )
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


def helper():
    console.text(_i18n("cli.welcome"))
    console.text(_i18n("cli.help_intro"))
    for cmd, desc in I18N.get(LANGUAGE, {}).get("cli.help_commands", {}).items():
        console.text(f"  {cmd:<6} {desc}")


# --- Utils function ---
FILTERED_DIRS = [
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", ".turbo", ".idea",
    ".vscode", ".mypy_cache", ".pytest_cache", ".cache", "target", "vendor"
]


def _is_directory_heavy(command: str) -> bool:  # 判断是否是目录遍历类命令
    return any(k in command for k in ["find ", "tree", "ls -R", "du ", "fd ", "rg ",])


def _filter_directory_output(lines: List[str]) -> List[str]:  # 过滤大型/无意义目录
    filtered = []
    for line in lines:
        skip = False
        for d in FILTERED_DIRS:
            if (f"/{d}/" in line or f"/{d}:"
                    in line or line.startswith(f"{d}/") or line.startswith(f"./{d}/") or line.startswith(f"./{d}:") or
                    line == d or line == f"./{d}" or line.endswith(f"/{d}")):
                skip = True
                break
        if skip:
            continue
        filtered.append(line)
    return filtered


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
        (r'\bhistory\s+-c\b', 7), (r'>\s*/dev/null\s+2>&1', 7),
    ]
    dangerous_i18n = {
        1: "safety.danger.rm", 2: "safety.danger.mkfs", 3: "safety.danger.chmod", 4: "safety.danger.sudo",
        5: "safety.danger.kill", 6: "safety.danger.env", 7: "safety.danger.history"
    }
    command = command.strip()
    if not command:
        return False, None
    for pattern, reason_id in dangerous_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return True, f"{_i18n(dangerous_i18n[reason_id])}"
    return False, None


def _validate_file_path(path: str) -> Optional[str]:
    """ 验证给定路径是否在项目根目录内, 返回 None 表示合法，否则返回错误描述字符串。"""
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
            console.warning(
                f"Request failed (attempt {attempt + 1}/{max_retries + 1}), retrying in {delay:.1f}s: {last_exception}")
            time.sleep(delay)
        else:
            break
    raise last_exception


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
            return {os.path.join(root, file): open(os.path.join(root, file), 'r', encoding='utf-8').read()
                    for root, _, files in os.walk(dir_path) for file in files}

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
                        "references": _load_directory(skill_dir, "references")
                    })
        return skills

    def reload(self):
        try:
            self.skills = self._load_skills()
        except Exception as err:
            self.skills = {}
            console.error(f"reload skills err: {err}")

    def all(self) -> Dict[str, dict]:
        return self.skills

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
    def ok(content="", **extra): return {"success": True, "content": content, **extra}

    @staticmethod
    def fail(content="", **extra): return {"success": False, "content": content, **extra}


class ReadTool(ToolBase):
    name = "read"
    description = "Read a file from the local filesystem"
    params = {
        "path": {"type": "string", "description": "Path to the file to read"},
        "offset": {"type": "number?", "description": "Line number to start reading from (0-indexed, default 0)"},
        "limit": {"type": "number?", "description": "Maximum number of lines to read (default: all lines)"}}

    def run(self, args):
        lines = open(args["path"]).readlines()
        offset, limit = args.get("offset", 0), args.get("limit", len(lines))
        selected = lines[offset: offset + limit]
        return self.ok("".join(f"{offset + idx + 1:4}| {line}" for idx, line in enumerate(selected)))


class WriteTool(ToolBase):
    name = "write"
    description = "Write content to a file, overwriting if it exists"
    params = {
        "path": {"type": "string", "description": "Path to the file to write"},
        "content": {"type": "string", "description": "Content to write to the file"}}

    def run(self, args):
        error = _validate_file_path(args["path"])
        if error:
            return self.fail(f"write error: {error}")
        with open(args["path"], "w") as f:
            f.write(args["content"])
        return self.ok(f"write {len(args['content'])}byte to {len(args['path'])} ok")


class EditTool(ToolBase):
    name = "edit"
    description = "Edit a file by replacing an exact string with a new string"
    params = {
        "path": {"type": "string", "description": "Path to the file to edit"},
        "old": {"type": "string", "description": "Exact string to be replaced"},
        "new": {"type": "string", "description": "String to replace it with"},
        "all": {"type": "boolean?", "description": "Replace all occurrences (default: false)"}}

    def before(self, args):
        if args.get("old") and args.get("new"):
            console.diff(old=args["old"], new=args["new"], filename=args["path"])

    def confirm(self, args): return console.prompt_apply(f"Edit {args['path']} (y or n)?")

    def run(self, args):
        error = _validate_file_path(args["path"])
        if error:
            return self.fail(f"edit error: {error}")
        text = open(args["path"]).read()
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
                for line_num, line in enumerate(open(filepath), 1):
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
    use_spinner = True

    def confirm(self, args):
        is_dangerous, reason = _check_command_safety(args["cmd"])
        return not is_dangerous or console.prompt_apply(f"Execute dangerous cmd ({reason})? {args['cmd']}")

    def run(self, args):
        proc = subprocess.Popen(args["cmd"], shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        output_lines = []
        try:
            while True:
                line = proc.stdout.readline()
                if not line and proc.poll() is not None:
                    break
                if line:
                    output_lines.append(line)
            output_lines = _process_bash_output(args['cmd'], output_lines)
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            return self.fail(f"exec {args['cmd']} timed out after 60s")
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
    preview_width = 5000

    def run(self, args):
        return self.ok(args["result"])


TOOLS = {
    t.name: t for t in [
        ReadTool(), WriteTool(), EditTool(), SearchTool(), GrepTool(), BashTool(), UseSkillTool(),
        AttemptCompletionTool()]
}


def tool_schema():
    return [tool.schema() for tool in TOOLS.values()]


# --- Context manager: () ---
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

    def disabled_compact(self): self.auto_compact_disabled = True

    def enabled_compact(self): self.auto_compact_disabled = False

    def set_max_failures(self, n: int = 3): self.max_failures = n

    def clear(self): self.messages = []

    def append_system(self, content: str): self.messages.append({"role": "system", "content": content})

    def append_user(self, content: str):
        self.messages.append({"role": "user", "content": content, "ts": int(time.time())})

    def inject_user(self, content: str): self.runtime_injections.append({"role": "user", "content": content})

    def clear_runtime_injections(self): self.runtime_injections = []

    def append_assistant(self, content: dict):
        content.update({"ts": int(time.time())})
        self.messages.append(content)

    def append_tool(self, tool_call_id: str, tool_name: str, content: str):
        self.messages.append({"role": "tool", "tool_call_id": tool_call_id, "tool_name": tool_name,
                              "content": content, "ts": int(time.time())})

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
    def compact_text(text: str, head: int = 80, tail: int = 80) -> str:
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
            if role == "user":
                if current:
                    turns.append(current)
                current = [m]
                continue
            current.append(m)
        if current:
            turns.append(current)
        return turns

    @staticmethod
    def estimated_tokens(msg: Dict[str, Any]) -> int: return len(json.dumps(msg, ensure_ascii=False)) // 4 + 4

    def total_tokens(self) -> int: return sum(self.estimated_tokens(m) for m in self.messages)

    def auto_compact_if_needed(self):
        if self.auto_compact_disabled:
            return
        if self.total_tokens() < self.auto_compact_threshold:
            return

        try:
            self.session_memory_compact()
            current_tokens = self.total_tokens()
            if current_tokens < self.auto_compact_threshold:
                return

            self.compact_conversation()
            current_tokens = self.total_tokens()
            if current_tokens < self.auto_compact_threshold:
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

    def micro_compact(self, max_age_seconds: int = 21_600, min_tokens: int = 200):
        now = int(time.time())
        for idx, m in enumerate(self.messages):
            if now - m.get("ts", now) < max_age_seconds:  # new tool pass
                continue
            if m.get("role") != "tool":  # not tool pass
                continue
            if m.get("tool_name") in self.white_tool_list:  # white tool pass
                continue
            content = m.get("content", "")
            if content.endswith("<compacted>"):  # compacted pass
                continue
            content_tokens = self.estimated_tokens({"content": content})
            if content_tokens < min_tokens:  # too small pass
                continue
            summary = self.compact_text(content)
            if not summary.strip():
                continue
            if self.estimated_tokens({"content": summary}) >= content_tokens:
                continue
            m["content"] = summary

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
                    if cm.get("tool_calls"):  # tool calls pass
                        compacted.append(cm)
                        continue

                    content = cm.get("content", "")
                    if isinstance(content, list):
                        continue  # claude style pass
                    content_tokens = self.estimated_tokens({"content": content})
                    if content_tokens > min_tokens:  # too small pass
                        cm["content"] = (self.compact_text(content) if content else "")

                    reasoning_content = cm.get("reasoning_content", "")
                    reasoning_content_tokens = self.estimated_tokens({"reasoning_content": reasoning_content})
                    if reasoning_content_tokens > min_tokens:
                        cm["reasoning_content"] = self.compact_text(reasoning_content)

                    reasoning_details = cm.get("reasoning_details", "")
                    reasoning_details_tokens = self.estimated_tokens({"reasoning_details": reasoning_details})
                    if reasoning_details_tokens > min_tokens:
                        cm["reasoning_details"] = self.compact_text(reasoning_details)
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
        _full_compact_prompt = [
            "Your task is to create a detailed summary of the conversation so far, "
            "paying close attention to the user's explicit requests and your previous actions.\n",
            "This summary should be thorough in capturing technical details, code patterns, "
            "and architectural decisions that would be essential for continuing development work without "
            "losing context.\n\n",
            "Your summary should include the following sections:\n\n",
            "1. Primary Request and Intent:Capture all of the user's explicit requests and intents in detail\n",
            "2. Key Technical Concepts:List all important technical concepts, technologies, frameworks discussed.\n",
            "3. Files and Code Sections: Enumerate specific files and code sections examined, modified, or created. "
            "Pay special attention to the most recent messages and include full code snippets where applicable "
            "and include a summary of why this file read or edit is important.\n",
            "4. Errors and fixes: List all errors that you ran into, and how you fixed them. "
            "Pay special attention to specific user feedback that you received, "
            "especially if the user told you to do something differently.\n",
            "5. Problem Solving: Document problems solved and any ongoing troubleshooting efforts.\n",
            "6. All user messages: List ALL user messages that are not tool results. "
            "These are critical for understanding the users' feedback and changing intent.\n",
            "7. Pending Tasks: Outline any pending tasks that you have explicitly been asked to work on.\n",
            "8. Current Work: Describe in detail precisely what was being worked on immediately "
            "before this summary request, paying special attention to the most recent messages from both "
            "user and assistant. Include file names and code snippets where applicable.\n\n",
            "Here's an example of how your output should be structured:\n\n",
            "<example>\n",
            "<analysis>\n",
            "[Your thought process, ensuring all points are covered thoroughly and accurately]\n",
            "</analysis>\n\n",
            "<summary>\n",
            "1. Primary Request and Intent:\n",
            "  [Detailed description]\n\n",
            "2. Key Technical Concepts:\n",
            "  - [Concept 1]\n",
            "  - [Concept 1]\n",
            "  - [...]\n\n",
            "3. Files and Code Sections:\n",
            "  - [File Name 1]\n",
            "    - [Summary of why this file is important]\n",
            "    - [Summary of the changes made to this file, if any]\n",
            "    - [Important Code Snippet]\n",
            "  - [File Name 2]\n",
            "    - [Important Code Snippet]\n",
            "  - [...]\n\n",
            "4. Errors and fixes:\n",
            "  - [Detailed description of error 1]:\n",
            "    - [How you fixed the error]\n",
            "    - [User feedback on the error if any]\n",
            "  - [...]\n\n",
            "5. Problem Solving:\n",
            "[Description of solved problems and ongoing troubleshooting]\n\n",
            "6. All user messages:\n",
            "  - [Detailed non tool use user message]\n",
            "  - [...]\n\n",
            "7. Pending Tasks:\n",
            "  - [Task 1]\n",
            "  - [Task 2]\n",
            "  - [...]\n\n",
            "8. Current Work:\n",
            " [Precise description of current work]\n\n",
            "</summary>\n",
            "</example>\n\n",
            "Please provide your summary based on the conversation so far, "
            "following this structure and ensuring precision and thoroughness in your response. \n\n",
            "There may be additional summarization instructions provided in the included context. If so, remember "
            "to follow these instructions when creating the above summary. Examples of instructions include:\n\n",
            "<example>\n",
            "## Compact Instructions\n",
            "When summarizing the conversation focus on typescript code changes and also remember the mistakes "
            "you made and how you fixed them.\n",
            "</example>\n\n",
            "<example>\n",
            "# Summary instructions\n",
            "When you are using compact - please focus on test output and code changes. Include file reads verbatim.\n",
            "</example>\n\n",
        ]
        try:
            self.append_user("\n".join(_full_compact_prompt))
            respon = provider.parse_response(_request(
                provider.api_url, provider.build_body(self.messages), headers=provider.headers()
            ))
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
        if before > (after := self.total_tokens()):
            console.compact_status(
                before_tokens=before, after_tokens=after, max_context=MANGO_MAX_CONTEXT, strategy="auto")
        return self.messages + self.runtime_injections


class BaseProvider:
    def __init__(self, api_url: str, api_key: str, model: str):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model

    def headers(self) -> dict:
        return {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}

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
        content = message.get("content")  # Claude-style thinking blocks
        if isinstance(content, list):
            thoughts = []
            for block in content:
                if block.get("type") == "thinking":
                    thoughts.append(block.get("thinking", ""))
            return "\n".join(thoughts)
        return ""


class OpenAIProvider(BaseProvider):
    def build_body(self, messages: List[Dict[str, Any]]) -> dict:
        return {"model": self.model, "messages": messages, "tools": tool_schema(), "stream": False}

    def parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        choices = response.get("choices", [])
        if not choices:
            return {
                "finish_reason": None,
                "raw_message": {},
                "content": "",
                "reasoning_content": "",
                "tool_calls": [],
                "has_tool_calls": False,
                "model": response.get("model", ""),
                "usage": response.get("usage", {})
            }
        choice = choices[0]
        message = choice.get("message", {})
        tool_calls = self.normalize_tool_calls(message)
        return {
            "finish_reason": choice.get("finish_reason", "stop"),
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
    def build_body(self, messages: List[Dict[str, Any]], reasoning_split: bool = True) -> dict:
        body = super().build_body(messages)
        body.update({"reasoning_split": True})
        return body


def create_provider() -> BaseProvider:
    _base_url = MANGO_API_URL
    if not _base_url.endswith("/chat/completions"):
        _base_url = _base_url.rstrip("/") + "/chat/completions"
    if "deepseek" in MANGO_MODEL.lower():
        return DeepSeekProvider(api_url=_base_url, api_key=MANGO_KEY, model=MANGO_MODEL)
    if "minimax" in MANGO_MODEL.lower():
        return MiniMaxProvider(api_url=_base_url, api_key=MANGO_KEY, model=MANGO_MODEL)
    return OpenAIProvider(api_url=_base_url, api_key=MANGO_KEY, model=MANGO_MODEL)


provider = create_provider()


def chat_completion(messages: List[Dict[str, str]]):
    return _request(provider.api_url, provider.build_body(messages), headers=provider.headers())


def run_tool(tool_name, tool_args):
    tool: ToolBase = TOOLS[tool_name]
    try:
        console.tool_call(tool.name, tool.preview(tool_args))
        tool.before(tool_args)
        if not tool.confirm(tool_args):
            return "error: User denied action"
        if tool.use_spinner:
            console.start_spinner()
        result = tool.run(tool_args)
        tool_status = result["success"]
        tool_content = result["content"]
        if tool.use_spinner:
            console.end_spinner()
        tool.after(tool_content)

        if not tool_content:
            print(f"  {DIM}⎿  (no output){RESET}")
        else:
            result_lines = tool_content.split("\n")
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
                    print(f"{prefix}{line}{RESET}")
                else:
                    print(f"     {DIM}{line}{RESET}")

        console.tool_result(tool_status)
        return tool_content
    except Exception as err:
        console.end_spinner()
        return f"run tool {tool_name} error: {err}"


class SystemPrompt:
    """ 分层装配的提示词运行时. 可根据会话状态、记忆、环境变量等动态生成完整的 system prompt."""
    def __init__(self):
        self.sections = []    # 有序的 section 列表，每个元素为 (section_name, content)
        self._init_default_sections()    # 默认加载基础 sections

    def _init_default_sections(self):
        self.sections.append(("base_intro", self._build_base_intro()))
        self.sections.append(("safety", self._build_safety()))
        self.sections.append(("builtin_rules", self._build_builtin_rules()))
        # self.sections.append(("language", self._build_language()))
        self.sections.append(("tool_guidance", self._build_tool_guidance()))
        self.sections.append(("skills_guidance", self._build_skills_guidance()))
        self.sections.append(("memory", self._build_memory()))
        self.sections.append(("environment", self._build_environment()))

    @staticmethod
    def _build_base_intro() -> List[str]:  # 基础身份和核心约束
        return [
            "You are an interactive agent that helps users with software engineering tasks. Use the instructions "
            "below and the tools available to you to assist the user.\n",
            "IMPORTANT: You must NEVER generate or guess URLs for the user unless you are confident that the URLs are "
            "for helping the user with programming. For file paths, always prefer absolute paths when possible. If "
            "you need to read a directory, use the bash tool (ls) because the read tool cannot read directories.\n",]

    @staticmethod
    def _build_tool_guidance() -> List[str]:  # 工具使用指导
        return [
            "## Tool Selection Guidelines\n\n",
            "You have access to the following dedicated tools: read/write/edit/search/grep/bash/attempt_completion.\n\n",
            "- For reading files: use **read**.\n",
            "- For writing or overwriting files: use **write**.\n",
            "- For replacing exact strings within a file: use **edit**. Prefer edit when you only need to change a "
            "small portion of a file.\n",
            "- For searching file names/paths: use **search** with a glob pattern.\n",
            "- For searching file content with regex: use **grep**.\n",
            "- Only use **bash** when no dedicated tool can accomplish the task, or for system commands (e.g., "
            "installing packages, running tests, managing directories).\n",
            "- Always use **attempt_completion** to present the final result to the user.\n",
            "- When using edit, ensure the `old` string is unique or set `all` to true.\n\n",]

    @staticmethod
    def _build_skills_guidance() -> List[str]:
        desc = skill_manager.descriptions()
        if desc:
            return [
                "## Skills Selection Guidelines\n\n",
                f"{desc}\n\n",
                "- If an installed skill is relevant, call use_skill first before proceeding.\n",
                "- Skills may contain:\n",
                "  - workflows\n",
                "  - best practices\n",
                "  - reusable scripts\n",
                "  - references\n\n"]
        else:
            return ["## Skills Selection Guidelines\n\n", "No skills available.\n\n"]

    @staticmethod
    def _build_environment() -> List[str]:  # 动态环境信息注入
        os_info = f"{platform.system()} {platform.release()} ({platform.machine()})"
        python_ver = sys.version.split()[0]
        return [
            "## Environment\n",
            f"- Working directory: {project_root}\n",
            f"- Operating system: {os_info}\n",
            f"- Python version: {python_ver}\n",
            f"- Shell: {os.environ.get('SHELL', 'unknown')}\n",]

    @staticmethod
    def _build_language() -> List[str]:
        """语言偏好(可通过环境变量 MANGO_LANG 配置), 若未设置则默认使用 English. """
        lang = os.environ.get("MANGO_LANG", "zh")
        if lang.lower() == "chinese" or lang.lower() == "zh":
            return ["## Language\n", f"You should communicate with the user in Chinese (Simplified)."]
        return ["## Language\n", f"You should communicate with the user in {lang}."]

    @staticmethod
    def _build_memory() -> List[str]:
        """ 记忆加载, .mangocli/MEMORY.md 存在，则将其内容作为记忆注入. """
        memory_path = os.path.join(project_root, ".mangocli", "MANGO.md")
        if not os.path.exists(memory_path):
            return ["## Memory\n", "No persistent memory available.\n"]
        if os.path.getsize(memory_path) == 0:
            return ["## Memory\n", "No persistent memory available.\n"]
        content = open(memory_path, "r", encoding="utf-8").readlines()
        return [f"## Persisted Memory\n"] + content

    @staticmethod
    def _build_safety() -> List[str]:
        """ 安全边界提示. 要求模型在执行前对危险命令进行确认，并遵守工具的安全检查。"""
        return [
            "## Safety\n\n",
            "- Before executing any command that modifies the file system, deletes files, changes permissions, "
            "or performs system administration, you MUST ensure the command is safe and the user has confirmed if "
            "necessary.\n",
            "- Do not attempt to access files outside the project root unless explicitly required and confirmed by "
            "the user.\n\n",]

    @staticmethod
    def _build_builtin_rules() -> List[str]:
        return [
            "## Built-in Rules\n\n",
            "### 1. Think Before Coding\n\n",
            "**Don't assume. Don't hide confusion. Surface tradeoffs.**\n",
            "- **State assumptions explicitly** — If uncertain, ask rather than guess\n",
            "- **Present multiple interpretations** — Don't pick silently when ambiguity exists\n",
            "- **Push back when warranted** — If a simpler approach exists, say so\n",
            "- **Stop when confused** — Name what's unclear and ask for clarification\n\n",
            "### 2. Simplicity First\n\n",
            "**inimum code that solves the problem. Nothing speculative.**\n\n",
            "- No features beyond what was asked\n",
            "- No abstractions for single-use code\n",
            "- No 'flexibility' or 'configurability' that wasn't requested\n",
            "- No error handling for impossible scenarios\n",
            "- If 200 lines could be 50, rewrite it\n\n",
            "### 3. Surgical Changes\n\n",
            "**Touch only what you must. Clean up only your own mess.**\n\n",
            "When editing existing code:\n",
            "- Don't 'improve' adjacent code, comments, or formatting\n",
            "- Don't refactor things that aren't broken\n",
            "- Match existing style, even if you'd do it differently\n",
            "- If you notice unrelated dead code, mention it — don't delete it\n",
            "When your changes create orphans:\n",
            "- Remove imports/variables/functions that YOUR changes made unused\n",
            "- Don't remove pre-existing dead code unless asked\n\n",
            "### 4. Goal-Driven Execution\n\n",
            "**Define success criteria. Loop until verified.**\n\n",
            "Transform imperative tasks into verifiable goals:\n",
            "| Instead of... | Transform to... |\n",
            "|--------------|-----------------|\n",
            "| 'Add validation' | 'Write tests for invalid inputs, then make them pass' |\n",
            "| 'Fix the bug' | 'Write a test that reproduces it, then make it pass' |\n",
            "| 'Refactor X' | 'Ensure tests pass before and after' |\n",
            "For multi-step tasks, state a brief plan:\n",
            "```\n",
            "1. [Step] → verify: [check]\n",
            "2. [Step] → verify: [check]\n",
            "3. [Step] → verify: [check]\n",
            "```\n"]

    def assemble(self) -> str:  # 将所有 section 按顺序拼接成完整的 system prompt。
        _basic = []
        for _, content in self.sections:
            _basic.append("".join(content))
        return "\n\n".join(_basic)


def agent_loop(ctx: ContextManager, ctx_file_path: str, user_input: str):
    ctx.append_user(user_input)

    iteration = 0
    while True:
        console.start_spinner("Request...")
        response = provider.parse_response(chat_completion(ctx.prepare_for_api()))
        console.end_spinner()
        ctx.append_assistant(response["raw_message"])

        iteration += 1
        console.token_usage(
            iteration=iteration, input_tokens=response["usage"]["prompt_tokens"],
            output_tokens=response["usage"]["completion_tokens"], context_tokens=ctx.total_tokens(),
            max_context=MANGO_MAX_CONTEXT)

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
                tool_name, tool_args = tool["name"], tool["arguments"]
                result = run_tool(tool_name, tool_args)
                ctx.append_tool(tool["id"], tool_name, result)
                if tool_name == "attempt_completion":
                    completed = True
                    break  # 遇到完成工具就退出当前轮工具调用
            if completed:
                break
        else:
            break
    ctx.save(ctx_file_path)


def main():
    initialize_system()

    print(f"{BOLD}Mango Cli v{__version__}{RESET} | {DIM}{MANGO_MODEL} | {project_root}{RESET}\n")

    ctx_file_path = os.path.join(session_dir, "session.json")
    ctx = ContextManager()
    ctx.load(ctx_file_path)

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
            if user_input.strip() in ("/h", "/help"):
                helper()
                continue

            if user_input.strip().startswith("/g") or user_input.strip().startswith("/goal"):
                parts = user_input.split(maxsplit=1)
                if len(parts) != 2:
                    console.error("Please input '/g or /goal <query>'")
                    continue
                goal_text = parts[1].strip()
                if not goal_text:
                    console.error("Please input '/g or /goal <query>'")
                    continue
                ctx.inject_user(
                    "[GOAL MODE]\n\n"
                    "The user has provided a long-running autonomous goal.\n\n"
                    "You should:\n"
                    "- plan\n"
                    "- execute\n"
                    "- verify\n"
                    "- iterate autonomously\n"
                    "- continue until fully complete\n"
                    "- only call `attempt_completion` tool when the goal is fully completed\n\n"
                    f"GOAL:\n{goal_text}\n\n"
                    f"Current date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                console.success(f"🎯 Goal: {goal_text}")
                agent_loop(ctx, ctx_file_path, "[CONTINUE GOAL EXECUTION]")
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
