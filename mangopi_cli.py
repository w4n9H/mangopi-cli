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
import base64
import logging
import mimetypes
import argparse
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    import readline  # 解决 Unix-like 系统中 input 无法正常删除中文的问题
except Exception:
    pass

__version__ = "0.1.28"
__author__ = "moofs"
__license__ = "Apache License 2.0"

# --- System Env ---
MANGO_KEY = os.environ.get("MANGO_KEY")
MANGO_API_URL = os.environ.get("MANGO_API_URL", "https://api.deepseek.com")
MANGO_MODEL = os.environ.get("MANGO_MODEL", "deepseek-v4-flash")
MANGO_MAX_CONTEXT = int(os.environ.get("MANGO_MAX_CONTEXT", 1_000_000))
MANGO_MAX_ITER = int(os.environ.get("MANGO_MAX_ITER", 100))
LANGUAGE = os.environ.get("MANGO_LANG", "en").lower()
MANGO_ROUTING = os.environ.get("MANGO_ROUTING", "off").lower()


project_root = os.getcwd()
base_persist_dir = os.path.join(project_root, '.mangocli')
session_dir = os.path.join(base_persist_dir, "session")
memory_dir = os.path.join(base_persist_dir, "memory")
goal_file = os.path.join(base_persist_dir, "goal.json")
providers_file = os.path.join(base_persist_dir, "providers.json")

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
            f"{_c(f'{after_tokens:,}', GREEN)} {_c(f'(-{saved:,})', ORANGE)}")
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
    os.makedirs(memory_dir, exist_ok=True)


def helper():
    console.text(_i18n("cli.welcome"))
    console.text(_i18n("cli.help_intro"))
    for cmd, desc in I18N.get(LANGUAGE, {}).get("cli.help_commands", {}).items():
        console.text(f"  {cmd:<6} {desc}")


# --- Utils function ---
FILTERED_DIRS = [
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", ".turbo", ".idea",
    ".vscode", ".mypy_cache", ".pytest_cache", ".cache", "target", "vendor"]
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


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


def _bocha_search_api(query: str = None, freshness: str = "noLimit",  summary: bool = True,
                      include: str = "",  exclude: str = "",  count: int = 10,
                      bocha_key: str = None, bocha_url: str = "https://api.bocha.cn/v1/web-search"):
    headers = {"Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Bearer {bocha_key}"}
    payload = {"query": query, "freshness": freshness, "summary": summary,
               "include": include, "exclude": exclude, "count": count}
    data = _request(bocha_url, payload, headers).get("data", {})
    pages = data.get("webPages", {}) if isinstance(data, dict) else {}
    return [{"date": m.get("dateLastCrawled", ""), "title": m.get("name", ""),
             "link": m.get("url", ""), "summary": m.get("summary", ""), "content": m.get("content", "")}
            for m in pages.get("value", [])] if isinstance(pages, dict) else []


def _goal_load() -> Optional[Dict[str, Any]]:
    try:
        return json.loads(open(goal_file, encoding="utf-8").read())
    except Exception as err:
        return None


def _goal_save(g: Dict[str, Any]) -> None:
    with open(goal_file, "w", encoding="utf-8") as fp:
        fp.write(json.dumps(g, indent=2, ensure_ascii=False))


def _goal_clear() -> None: os.remove(goal_file) if os.path.exists(goal_file) else None


class MemoryManager:
    def __init__(self):
        self.memory_dir = memory_dir

    def today_path(self): return os.path.join(self.memory_dir, datetime.now().strftime("%Y-%m-%d.md"))

    def append(self, content: str):
        with open(self.today_path(), "a", encoding="utf-8") as f:
            f.write(content.strip() + "\n\n")

    @staticmethod
    def _tokenize(text: str): return [x.strip().lower() for x in text.split() if x.strip()]

    @staticmethod
    def _split_chunks(text: str): return [c.strip() for c in re.split(r"\n\s*\n", text) if c.strip()]

    def search(self, query: str, top_k: int = 10):
        keywords = self._tokenize(query)
        if not keywords:
            return "empty query"

        scored = []
        for path in sorted(globlib.glob(self.memory_dir + "/*.md"), reverse=True):
            try:
                with open(path, encoding="utf-8") as fp:
                    memory_text = fp.read()
                    chunks = self._split_chunks(memory_text)
                    for chunk in chunks:
                        lower = chunk.lower()
                        score = 0
                        for kw in keywords:
                            if kw in lower:
                                score += lower.count(kw) * 10
                        if score <= 0:
                            continue
                        score += min(len(chunk) // 200, 5)
                        mtime_bonus = max(0, 30 - int((time.time() - os.path.getmtime(path)) / 86400))
                        score += mtime_bonus
                        scored.append({"score": score, "file": os.path.basename(path), "content": chunk[:2000]})
            except Exception:
                continue
        if not scored:
            return ("No memory found. Tip: append important user preferences, decisions, "
                    "and non-obvious fixes so future sessions can recall them.")
        scored.sort(key=lambda x: x["score"], reverse=True)
        results = []
        for item in scored[:top_k]:
            results.append(f"# {item['file']} (score={item['score']})\n{item['content']}")
        return "\n\n---\n\n".join(results)


memory_manager = MemoryManager()


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


# --- Flash-ext: Thinking Framework System ---
class FlashThinking:  # 思考引导增强系统——根据 query 关键词和 tool call 模式选择和注入结构化思考框架。
    KEYWORDS = {"debug": ["报错", "bug", "error", "失败", "fail", "慢", "slow", "崩溃", "crash", "排查", "debug"],
                "design": ["设计", "design", "架构", "architect", "方案", "选型", "规划"],
                "explain": ["什么是", "解释", "explain", "区别", "原理", "怎么理解", "what is"],
                "optimize": ["优化", "optimize", "性能", "performance", "加速", "提升"],
                "implement": ["实现", "implement", "写", "create", "build", "开发", "生成"]}

    PHASES = {
        "exploring": lambda tools: tools and all(t in ("read", "grep", "search", "search_memory") for t in tools),
        "executing": lambda tools: tools and any(t in ("edit", "write") for t in tools),
        "verifying": lambda tools: tools and sum(1 for t in tools if t == "bash") >= 2}

    PHASE_MAP = {"exploring": "investigate", "executing": "implement", "verifying": "verify", "stuck": "reevaluate"}

    def __init__(self):
        self.frameworks = {
            "debug": [
                "先复现问题，确认触发条件", "列出所有可能的原因，按概率排序", "对每个原因设计验证方法", "逐一排除，找到根因",
                "给出修复方案和验证步骤"],
            "design": [
                "明确需求和约束条件", "列出 2-3 个可行方案", "对比方案的优缺点", "选择一个方案并说明理由", "给出实现的关键步骤"],
            "explain": [
                "先给一句话总结", "再展开关键细节", "最后给一个实际例子"],
            "optimize": [
                "先测量当前性能基线", "定位瓶颈(用数据说话,不要猜)", "针对瓶颈提出优化方案", "预估优化效果", "给出验证方法"],
            "implement": [
                "理解需求，确认输入输出", "设计数据结构和核心逻辑", "先写主体逻辑，再处理边界", "验证：手跑一遍核心路径",
                "列出可能的失败场景"],
            "investigate": [
                "明确当前已知信息", "列出缺失的关键信息", "规划信息收集顺序", "先收集再决策，不要急于行动"],
            "verify": [
                "逐个检查预期结果", "对每个预期结果：通过记录，失败修复", "列出所有遗留项", "确认没有引入新问题"],
            "reevaluate": [
                "停下，重新审视当前假设", "之前的结论有没有可能是错的", "有没有完全不同的思路", "列出替代方案，逐个评估可行性"]}

    def match(self, query, tool_pattern=None):  # 匹配思考框架：query 关键词 + tool pattern 阶段感知
        q = query.lower()
        if tool_pattern:  # 1. tool pattern 阶段框架（优先，更实时）
            for phase, test in self.PHASES.items():
                if test(tool_pattern):
                    return self.PHASE_MAP[phase]
        for fw, keywords in self.KEYWORDS.items():  # 2. query 关键词匹配
            if any(kw in q for kw in keywords):
                return fw
        return None

    def inject(self, messages, framework_name):  # 将思考框架注入为 system 消息前缀
        steps_list = self.frameworks.get(framework_name)
        if not steps_list:
            return messages
        steps = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps_list))
        return [{"role": "system", "content": f"[Thinking Framework: {framework_name}]\n{steps}\n"}] + messages


flash_thinking = FlashThinking()


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
    def ok(content: Any = "", **extra): return {"success": True, "content": content, **extra}

    @staticmethod
    def fail(content="", **extra): return {"success": False, "content": content, **extra}


class ReadTool(ToolBase):
    name = "read"
    description = "Read a file from the local filesystem (text or image; images are auto-routed to vision)"
    params = {
        "path": {"type": "string", "description": "Path to the file to read (text or image: png/jpg/jpeg/gif/webp)"},
        "offset": {"type": "number?", "description": "Line number to start reading from (0-indexed, default 0)"},
        "limit": {"type": "number?", "description": "Maximum number of lines to read (default: all lines)"}}

    def preview(self, args): return (args.get("path") or "")[:self.preview_width]

    def run(self, args):
        path = args["path"]
        ext = os.path.splitext(path)[1].lower()
        if ext in IMAGE_EXTS and "offset" not in args and "limit" not in args:
            return ViewImageTool().run({"path": path})
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
    preview_lines = 100
    preview_width = 150
    use_spinner = True

    def confirm(self, args):
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


class SearchMemoryTool(ToolBase):
    name = "search_memory"
    description = ("Search YOUR long-term memory — notes YOU have saved in past sessions. CALL THIS WHEN: "
                   "(1) user references past work ('last time', 'as discussed'), "
                   "(2) before recommending architecture/patterns (check for prior decisions), "
                   "(3) user asks about their preferences or project conventions.")
    params = {
        "query": {
            "type": "string",
            "description": "Search query. Supports multiple space-separated keywords in both English and Chinese."}}
    use_spinner = True

    def preview(self, args): return (args.get("query") or "")[:self.preview_width]

    def run(self, args):
        result = memory_manager.search(args["query"])
        return self.ok(result)


class AppendMemoryTool(ToolBase):
    name = "append_memory"
    description = ("Save a note to YOUR long-term memory. Persists across sessions. CALL THIS WHEN: "
                   "(1) user states a preference ('I always use X'), "
                   "(2) an architecture decision is made, (3) a non-obvious bug fix is found, "
                   "(4) a project convention is established. "
                   "DO NOT CALL for ephemeral session context, code already in the repo, or trivial facts.")
    params = {
        "content": {
            "type": "string",
            "description": "Concise 5-10 sentence note. Prefix tag: [PREFERENCE]/[DECISION]/[BUG-FIX]/[CONVENTION]."}}

    def run(self, args):
        memory_manager.append(args["content"])
        return self.ok("memory appended")


class GoalTool(ToolBase):
    name = "goal"
    description = ("Manage the current goal plan. "
                   "action='plan' creates, 'step' updates a step, 'show' views, 'finish' clears.")
    params = {
        "action": {
            "type": "string",
            "description": "What to do: 'plan'(create new),'step'(update one step),'show'(view current),"
                           "'finish'(mark goal done)"},
        "goal": {
            "type": "string?",
            "description": "The user's goal text in plain language, required for action='plan'."},
        "steps": {
            "type": "string?",
            "description": "JSON array of step descriptions, e.g. '[\"set up project\", \"write tests\"]'"
                           ", required for action='plan'."},
        "step": {
            "type": "number?",
            "description": "Which step to update (1-indexed), required for action='step'."},
        "status": {
            "type": "string?",
            "description": "Step status: 'done' = completed, 'failed' = errored, required for action='step'."},
        "note": {
            "type": "string?",
            "description": "Free-text note about the result,e.g. 'pytest 3/3 passed' or 'compile error: undefined foo',"
                           "Optional but recommended action='step'."}}
    use_spinner = True
    preview_lines = 100
    preview_width = 500

    def run(self, args):
        action = args.get("action", "show")
        method = getattr(self, f"_action_{action}", None)
        if not method:
            return self.fail(f"unknown action '{action}', one of 'plan' | 'step' | 'show' | 'finish'")
        return method(args)

    def _action_plan(self, args):
        if not args.get("goal") or not args.get("steps"):
            return self.fail("action='plan' requires 'goal' and 'steps'")
        try:
            sl = json.loads(args["steps"])
            if not isinstance(sl, list) or not sl:
                return self.fail("steps must be non-empty JSON array")
        except json.JSONDecodeError as e:
            return self.fail(f"invalid steps JSON array: {e}")
        cur = _goal_load()  # 拒绝覆盖未结束的活跃 goal
        if cur and cur.get("current", 0) < len(cur.get("steps", [])):
            return self.fail(
                "action='plan' refused: an active goal is still in progress "
                f"(step {cur['current'] + 1}/{len(cur['steps'])}). "
                "Use action='step' to advance the current goal, or action='finish' to close it first.")
        g = {"goal": args["goal"], "steps": [{"desc": s, "status": "pending"} for s in sl], "current": 0}
        _goal_save(g)
        return self.ok(f"plan: {len(sl)} steps\n{json.dumps(g, ensure_ascii=False)}")

    def _action_step(self, args):
        n, status = args.get("step"), args.get("status", "done")
        if status not in ("done", "failed"):
            return self.fail(f"invalid status '{status}', one of 'done' | 'failed'")
        g = _goal_load()
        if not g or not n or n < 1 or n > len(g["steps"]):
            return self.fail("no active goal or invalid step number, the goal may have already ended,"
                             "call `attempt_completion` tool finish task.")
        g["steps"][n - 1]["status"] = status
        if args.get("note"):
            g["steps"][n - 1]["note"] = args["note"]
        if status == "done" and n == g["current"] + 1:
            g["current"] = n
        _goal_save(g)
        nxt = (f"next: step {n + 1}" if n < len(g["steps"])
               else "ALL STEPS DONE. You MUST now: (1) call goal(action='finish'), "
                    "(2) call attempt_completion. DO NOT call goal(action='plan') again — "
                    "it will be rejected and will reset your progress.")
        return self.ok(f"step {n} {status}. {nxt}")

    def _action_show(self, args):
        g = _goal_load()
        return self.ok(json.dumps(g, ensure_ascii=False, indent=2)) if g else self.fail("no active goal")

    def _action_finish(self, args):
        _goal_clear()
        return self.ok("goal cleared, call `attempt_completion` tool finish task.")


class WebSearchTool(ToolBase):
    name = "web_search"
    description = (
        "Search the live web via the Bocha (博查) AI Search API and return a list of results with "
        "per-page AI summaries. Use this when the user asks for the latest docs, news, blog posts, "
        "or any information that requires looking up something beyond the local filesystem. "
        "Requires the MANGO_SEARCH_API_KEY env var to be set; returns a clear error otherwise.")
    params = {
        "query": {"type": "string", "description": "Natural-language search query, e.g. 'FastAPI vs Flask in 2026'."},
        "top_k": {"type": "number?", "description": "How many results to return (1-50, default 10)."},
        "freshness": {"type": "string?",
                      "description": "Time filter for results: 'noLimit' (default), "
                                     "'oneDay', 'oneWeek', 'oneMonth', 'oneYear'."}}
    preview_lines = 0
    preview_width = 200
    use_spinner = True
    _VALID_FRESHNESS = ("noLimit", "oneDay", "oneWeek", "oneMonth", "oneYear")

    def preview(self, args): return (args.get("query") or "")[:self.preview_width]

    def run(self, args):
        query = (args.get("query") or "").strip()
        if not query:
            return self.fail("web_search error: 'query' is required")
        api_key = os.environ.get("MANGO_SEARCH_API_KEY")
        if not api_key:
            return self.fail("web_search error: MANGO_SEARCH_API_KEY env var is not set")
        raw_k = args.get("top_k")
        try:
            top_k = int(raw_k) if raw_k not in (None, "") else 10
        except (TypeError, ValueError):
            return self.fail(f"web_search error: 'top_k' must be an integer in [1, 50], got {raw_k!r}")
        if not 1 <= top_k <= 50:
            return self.fail(f"web_search error: 'top_k' must be in [1, 50], got {top_k}")
        freshness = (args.get("freshness") or "noLimit").strip()
        if freshness not in self._VALID_FRESHNESS:
            return self.fail(f"web_search error: 'freshness' must be one of "
                             f"{'/'.join(self._VALID_FRESHNESS)}, got {freshness!r}")

        try:
            results = _bocha_search_api(query=query, count=top_k, freshness=freshness, bocha_key=api_key)
        except Exception as err:
            return self.fail(f"web_search error: Bocha API call failed: {err}")
        if not results:
            return self.ok(f"(no results for query: {query})")

        lines = [f"## Answer (Bocha · {len(results)} result(s) for: {query})", ""]
        sources = []
        for i, r in enumerate(results, 1):
            title = (r.get("title") or "(untitled)").strip()
            link = (r.get("link") or "").strip()
            date = (r.get("date") or "").strip()
            summary = (r.get("summary") or "").strip()
            content = (r.get("content") or "").strip()

            header = f"### {i}. [{title}]({link})" if link else f"### {i}. {title}"
            lines.append(header)
            if date:
                lines.append(f"*Date: {date}*")
            lines.append("")
            if summary:
                lines.append(f"> {summary}")
                lines.append("")
            if content and content != summary:
                snippet = content if len(content) <= 500 else content[:500] + "..."
                lines.append(snippet)
                lines.append("")

            sources.append(f"{i}. [{title}]({link})" if link else f"{i}. {title}")

        lines.append("## Sources")
        lines.extend(sources)
        return self.ok("\n".join(lines).rstrip())


class ViewImageTool(ToolBase):
    name = "view_image"
    description = (
        "Load a local image (screenshot, UI mockup, error screen, diagram) into the model's vision context. "
        "Accepts an absolute path to a file on disk; URLs are not supported. "
        "Supported formats: png, jpg, jpeg, gif, webp.")
    params = {"path": {"type": "string",
                       "description": "Absolute path to a local image file (png/jpg/jpeg/gif/webp). "
                                      "URL inputs are rejected."}}
    preview_lines = 0
    preview_width = 200
    use_spinner = True
    MAX_BYTES = 5 * 1024 * 1024  # 5 MB hard cap

    @staticmethod
    def _is_url(s: str) -> bool: return s.startswith("http://") or s.startswith("https://")

    def preview(self, args): return (args.get("path") or "")[:self.preview_width]

    def run(self, args):
        path = (args.get("path") or "").strip()
        if not path:
            return self.fail("view_image error: 'path' is required")
        if self._is_url(path):
            return self.fail("view_image error: URL inputs are not supported. "
                             "Download the image to a local file first, then pass the file path.")
        err = _validate_file_path(path)
        if err:
            return self.fail(f"view_image error: {err}")
        try:
            size = os.path.getsize(path)
        except OSError as e:
            return self.fail(f"view_image error: cannot stat file: {e}")
        if size == 0:
            return self.fail("view_image error: image file is empty")
        if size > self.MAX_BYTES:
            return self.fail(f"view_image error: image too large ({size:,} bytes, max {self.MAX_BYTES})")
        ext = os.path.splitext(path)[1].lower()
        if ext not in IMAGE_EXTS:
            return self.fail(f"view_image error: unsupported image format '{ext}' (supported: png,jpg,jpeg,gif,webp)")
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
        except OSError as e:
            return self.fail(f"view_image error: cannot read file: {e}")
        mime, _ = mimetypes.guess_type(path)
        if not mime:
            mime = "image/png"
        data_uri = f"data:{mime};base64,{b64}"
        return self.ok({"type": "image", "text": f"Image: {path} ({size} bytes,{mime})", "image_url": data_uri})


class AttemptCompletionTool(ToolBase):
    name = "attempt_completion"
    description = "Indicate that the task is complete and provide the final result/answer to the user"
    params = {"result": {"type": "string", "description": "The final result or summary of the completed task"}}
    preview_lines = 500
    preview_width = 500

    def run(self, args):
        return self.ok(args["result"])


TOOLS = {
    t.name: t for t in [
        ReadTool(), WriteTool(), EditTool(), SearchTool(), GrepTool(), BashTool(), UseSkillTool(),
        SearchMemoryTool(), AppendMemoryTool(), GoalTool(), WebSearchTool(), ViewImageTool(), AttemptCompletionTool()]}


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
            msg["content"] = content if content is not None else ""
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
            if role == "user":
                if current:
                    turns.append(current)
                current = [m]
                continue
            current.append(m)
        if current:
            turns.append(current)
        return turns

    def tool_fingerprint(self, n_turns: int = 10) -> str:  # Return (user_query, [tool, ...]) pairs from recent turns.
        turns = self.split_turns()
        recent = turns[-n_turns:] if len(turns) > n_turns else turns
        fingerprints = []
        for turn in recent:
            tools = [m.get("tool_name", "") for m in turn if m.get("role") == "tool" and m.get("tool_name")]
            if not tools:
                continue
            user_msg = next((m.get("content", "") for m in turn if m.get("role") == "user"), "")
            fingerprints.append([user_msg, tools])
        return str(fingerprints) if fingerprints else "[]"

    def tool_pattern(self, n=10) -> Optional[List[str]]:  # 提取最近 n 条消息的 tool call 模式
        tools = [m.get("tool_name", "") for m in self.messages[-n:] if m.get("role") == "tool" and m.get("tool_name")]
        return tools if tools else None

    def tool_context(self, n=10, cap=500) -> str:  # 提取最近 tool results 的关键内容，注入为上下文
        ctx = []
        for m in self.messages[-n:]:
            if m.get("role") != "tool":
                continue
            content = str(m.get("content", ""))
            if not content:
                continue
            if len(content) <= cap:
                ctx.append(f"[{m['tool_name']}] {content}")
            else:
                ctx.append(f"[{m['tool_name']}: {len(content)} chars] {content[:200]}...\n{content[-200:]}")
        return "\n\n".join(ctx) if ctx else ""

    def detect_loop(self, threshold=3) -> tuple:  # 检测是否陷入迭代死循环，返回 (is_looping, tool_name)
        recent = [m for m in self.messages[-20:] if m.get("role") == "tool"]
        if len(recent) < 10:
            return False, None
        # 1. 同工具连续失败
        last_tool, fail_streak = None, 0
        for m in recent:
            tool, content = m.get("tool_name", ""), str(m.get("content", "")).lower()
            if tool == last_tool and ("fail" in content or "error" in content):
                fail_streak += 1
            else:
                fail_streak = 0 if tool != last_tool else fail_streak
            last_tool = tool
            if fail_streak >= threshold:
                return True, tool
        # 2. 交替循环：近 12 条 tool 中 ≥2 个不同工具在密集失败
        fail_set, fail_count = set(), 0
        for m in recent[-12:]:
            content = str(m.get("content", "")).lower()
            if "fail" in content or "error" in content:
                fail_set.add(m.get("tool_name", ""))
                fail_count += 1
        if len(fail_set) >= 2 and fail_count >= threshold * 2:
            return True, ",".join(sorted(fail_set))
        return False, None

    def detect_phase(self) -> str:  # 推断当前对话阶段（start/exploring/executing/verifying/stuck）
        is_looping, _ = self.detect_loop()
        if is_looping:
            return "stuck"
        all_tools = [m.get("tool_name", "") for m in self.messages if m.get("role") == "tool"]
        if not all_tools:
            return "start"
        recent = all_tools[-5:]
        if any(t in ("edit", "write") for t in recent):
            return "executing"
        if all(t in ("read", "grep", "search") for t in recent):
            return "exploring"
        if recent.count("bash") >= 2:
            return "verifying"
        return "executing"

    def assess_complexity(self) -> str:  # 判断是否需要深思路径（Flash-ext 自己的 LLM 分析）
        tool_pattern, tool_ctx = self.tool_pattern(), self.tool_context()
        if len(tool_ctx) > 2000:
            return "deep"
        if tool_pattern:
            if len(set(tool_pattern)) >= 3:
                return "deep"
            if len(tool_pattern) >= 5 and len(set(tool_pattern)) == 1:
                return "deep"
        query = self.messages[-1].get("content", "") if self.messages else ""
        if any(k in query.lower() for k in ("设计", "架构", "重构", "design", "architect", "refactor")):
            return "deep"
        return "fast"

    def summarize_recent_turns(self, n_turns=3) -> str:  # 压缩最近 n 轮对话为轻量上下文文本，用于 Flash-ext LLM 调用
        lines = []
        turn_count = 0
        for m in self.messages[-50:]:
            role = m.get("role")
            if role == "user" and turn_count >= n_turns:
                break
            if role == "user":
                turn_count += 1
                lines.append(f"[USER] {str(m.get('content', ''))[:300]}")
            elif role == "tool":
                lines.append(f"[{m.get('tool_name', '?')}] {str(m.get('content', ''))[:300]}")
            elif role == "assistant":
                tc = m.get("tool_calls", [])
                if tc:
                    names = ",".join(t.get("name", "?") for t in tc)
                    lines.append(f"[ASSISTANT → tool_calls: {names}]")
                else:
                    lines.append(f"[ASSISTANT] {str(m.get('content', ''))[:300]}")
        return "\n".join(lines)

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

    def micro_compact(self):
        now = int(time.time())
        for idx, m in enumerate(self.messages):
            _age = now - m.get("ts", now)
            if m.get("role") == "tool":  # not tool pass
                if m.get("tool_name") in self.white_tool_list:  # white tool pass
                    continue
                content = m.get("content", "")
                if isinstance(content, list):  # base64 编码的二进制数据, head/tail 文本截断对它毫无意义
                    continue
                if content and not content.endswith("<compacted>"):  # compacted pass
                    rule = COMPACT_RULES["tool"]
                    if _age >= rule.get("max_age", 0):  # new tool pass
                        if self.estimated_tokens({"content": content}) > rule["max_tokens"]:  # too small pass
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
                            msg["reasoning_details"] = [{"text": reasoning}]
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


# --- Smart Provider Routing ---

class RoutedProvider:  # A provider that scores task complexity and delegates to low/medium/high sub-providers.
    @classmethod
    def from_file(cls, path: str) -> "RoutedProvider":
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    def __init__(self, config: dict):
        self._tiers: Dict[str, List[BaseProvider]] = {"low": [], "medium": [], "high": []}
        for p in config.get("providers", []):
            tier = p.get("tier", "")
            if tier not in self._tiers:
                raise ValueError(f"Invalid provider tier '{tier}'. Must be low/medium/high.")
            self._tiers[tier].append(_new_provider(p["model"], p["url"], p["api_key"]))
        if not any(self._tiers.values()):
            raise ValueError("No providers defined in config")

        routing = config.get("routing", {})
        _defaults_score_thresholds = {"low_max": 3, "medium_max": 7}
        self._thresholds = {**_defaults_score_thresholds, **routing.get("score_thresholds", {})}
        default_tier = routing.get("default_tier", "medium")
        self._default_tier_value = default_tier if self._tiers.get(default_tier) else \
            next((t for t in ("medium", "low", "high") if self._tiers.get(t)), "medium")
        default = self._tiers.get(default_tier) or next((v for v in self._tiers.values() if v), [])
        self._current = default[0]

    # ── delegation to _current ──
    @property
    def api_url(self): return self._current.api_url

    @property
    def api_key(self): return self._current.api_key

    @property
    def model(self): return self._current.model

    @property
    def total_providers(self) -> int: return sum(len(v) for v in self._tiers.values())

    def headers(self) -> dict: return self._current.headers()

    def build_body(self, messages: List[Dict[str, Any]]) -> dict: return self._current.build_body(messages)

    def parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]: return self._current.parse_response(response)

    _KEYWORD_RULES: List[tuple] = [
        (["架构", "设计", "系统", "design", "architect", "distribut", "microservic", "scalab", "infrastructur",
          "platform", "framework", "整体", "overall", "可扩展", "高可用", "容灾", "分布式"], 9),
        (["重构", "refactor", "migrat", "死锁", "deadlock", "并发", "concurren", "性能优化", "perform", "tun", "rewrit",
          "async", "multithread", "异步", "迁移", "升级", "upgrad", "重写"], 7),
        (["实现", "integrat", "优化", "multi", "feature", "implement", "api", "interfac", "modul", "component",
          "databas", "config", "开发", "集成", "接口", "模块", "组件", "数据库", "存储", "stor"], 5),
        (["修复", "fix", "debug", "test", "修改", "modif", "update", "chang", "error", "bug", "issue", "adjust",
          "patch", "correct", "错误", "问题", "调整", "更正", "改动", "alter"], 3),
        (["read", "查看", "show", "find", "search", "解释", "explain", "搜索", "查询", "query", "简单",
          "display", "获取", "了解", "描述", "describe"], 1),
    ]

    _ANGER_KEYWORDS: List[str] = [
        "fuck", "fuxx", "f**k", "shit", "damn", "asshole", "bastard", "傻子", "笨蛋", "蠢货", "白痴", "脑残", "sb", "废物",
        "垃圾", "特么", "卧槽", "我操", "cnm", "tmd", "废物", "傻x"]

    _SCORING_PROMPT = """\
Rate this coding task complexity from 1-10 (1=trivial, 10=architectural/system design).
Consider: scope of changes, reasoning depth, debugging difficulty, components involved.

Tool call history (each segment = one user turn):
{tool_patterns}

Current request:
{user_query}

Rubric: 1-3=read/search, 4-6=multi-file/edit/debug, 7-10=design/refactor/complex

Respond with ONLY a single integer."""

    @staticmethod
    def _keyword_score(query: str) -> int:
        q = query.lower()
        for kw in RoutedProvider._ANGER_KEYWORDS:  # 愤怒检测优先：直接返回最高分 10
            if kw in q:
                return 10
        for keywords, score in RoutedProvider._KEYWORD_RULES:
            for kw in keywords:
                if kw in q:
                    return score
        return 4

    @staticmethod
    def _llm_score(user_query: str, fingerprint: str, high_provider) -> int:
        prompt = RoutedProvider._SCORING_PROMPT.format(
            tool_patterns=fingerprint, user_query=user_query)
        body = high_provider.build_body([{"role": "user", "content": prompt}])
        try:
            console.start_spinner("Smart Routing...")
            resp = _request(high_provider.api_url, body,
                            headers=high_provider.headers(), timeout=15)
            parsed = high_provider.parse_response(resp)
            content = parsed.get("content", "").strip()
            match = re.search(r'\d+', content)
            console.end_spinner()
            if match:
                val = int(match.group())
                return max(1, min(10, val))
        except Exception:
            console.end_spinner()
        return 5

    def route(self, ctx, user_query: str):  # Score task complexity and switch to the appropriate tier provider.
        kw = self._keyword_score(user_query)
        if kw <= self._thresholds["low_max"]:
            tier = "low"
        elif kw > self._thresholds["medium_max"]:
            tier = "high"
        else:
            high = self._tiers.get("high", [])
            if high:
                fp = ctx.tool_fingerprint()
                llm = self._llm_score(user_query, fp, high[0])
                final = round(kw * 0.3 + llm * 0.7)
                if final <= self._thresholds["low_max"]:
                    tier = "low"
                elif final <= self._thresholds["medium_max"]:
                    tier = "medium"
                else:
                    tier = "high"
            else:
                tier = self._default_tier
        providers = self._tiers.get(tier)
        if not providers:
            providers = self._tiers[self._default_tier]
        self._current = providers[0]
        print(f"{DIM}→ {tier}: {self._current.model}{RESET}")

    @property
    def _default_tier(self) -> str: return self._default_tier_value


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
            print(f"  {DIM}⎿  (no output){RESET}")
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
        self.sections.append(("tool_guidance", self._build_tool_guidance()))
        self.sections.append(("skills_guidance", self._build_skills_guidance()))
        self.sections.append(("memory", self._build_user_rules()))
        self.sections.append(("environment", self._build_environment()))

    @staticmethod
    def _build_base_intro() -> str:
        return ("You are an interactive agent that helps users with software engineering tasks. "
                "Use the instructions below and the tools available to you to assist the user.\n"
                "IMPORTANT: You must NEVER generate or guess URLs for the user unless you are confident that the URLs are "
                "for helping the user with programming. For file paths, always prefer absolute paths when possible. If "
                "you need to read a directory, use the bash tool (ls) because the read tool cannot read directories.\n")

    @staticmethod
    def _build_tool_guidance() -> str:
        return ("## Tool Selection\n\n"
                "Use the dedicated tool when one exists (read/write/edit/search/grep/search_memory/"
                "append_memory/attempt_completion). Reach for **bash** only when no dedicated tool fits.\n"
                "Use **edit** (not write) for small in-place changes; ensure `old` is unique or pass `all=true`.\n"
                "Use **search_memory** for long-term knowledge, **append_memory** only for "
                "architecture decisions / persistent preferences (not ephemeral context).\n"
                "Use **view_image** for screenshots, UI mockups, error screens, and diagrams. "
                "The `read` tool auto-routes image files (.png/.jpg/.jpeg/.gif/.webp) to vision, "
                "but call `view_image` directly when the path is computed or generated.\n"
                "Use **web_search** for the latest docs, news, or anything that requires the live web "
                "beyond the local filesystem. Requires the `MANGO_SEARCH_API_KEY` env var. "
                "Use sparingly — at most 3 times per user query to avoid excessive API calls.\n"
                "Always finish with **attempt_completion** to present the final result.\n\n")

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
    def _build_user_rules() -> str:
        memory_path = os.path.join(project_root, ".mangocli", "MANGO.md")
        if not os.path.exists(memory_path) or os.path.getsize(memory_path) == 0:
            return "## User Rules\n\nNo user-defined rules.\n"
        return "## User Rules\n\n" + open(memory_path, "r", encoding="utf-8").read()

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
        if iteration == MANGO_MAX_ITER:
            break
    ctx.save(ctx_file_path)


class FlashExtServer:
    """ OpenAI-compatible model enhancement server with thinking-guidance.
    Wraps a backend model API, injects structured thinking frameworks before
    each request, and optionally augments with memory/search.
    Exposes a standard OpenAI /v1/chat/completions endpoint."""

    def __init__(self, host="0.0.0.0", port=8080, token=None, provider_obj=None, enable_memory=True, enable_search=True):
        self.host = host
        self.port = port
        self.token = token
        self.provider: BaseProvider = provider_obj or provider
        self.enable_memory = enable_memory
        self.enable_search = enable_search and bool(os.environ.get("MANGO_SEARCH_API_KEY"))
        self.thinker: FlashThinking = flash_thinking
        self.logger = logging.getLogger("flash-ext")
        self._key = None
        self._server = None

    def _augment(self, messages):  # 用临时 ContextManager 包装 messages，复用其分析方法
        ctx = ContextManager()
        ctx.messages = list(messages)
        query = messages[-1].get("content", "") if messages else ""
        tool_pattern, tool_ctx = ctx.tool_pattern(), ctx.tool_context()

        # 1. 决策路径
        complexity = ctx.assess_complexity()
        self.logger.debug("complexity=%s query=%.80s", complexity, query)
        if complexity == "deep":
            try:
                analysis = self._analyze_deep(ctx, query, tool_pattern)
                if analysis:
                    fw = analysis.get("framework")
                    self.logger.debug("deep framework=%s insight=%.60s", fw, str(analysis.get("insight", ""))[:60])
                    fw = analysis.get("framework")
                    if fw and fw in self.thinker.frameworks:
                        messages = self.thinker.inject(messages, fw)
                    ins = analysis.get("insight")
                    if ins:
                        messages = [{"role": "system", "content": f"[INSIGHT] {ins}"}] + messages
                    al = analysis.get("anti_loop")
                    if al:
                        messages = [{"role": "system", "content": al}] + messages
                    ts = analysis.get("tool_summary")
                    if ts and len(tool_ctx) > 2000:
                        messages = [{"role": "system", "content": f"[Tool Context]\n{ts}"}] + messages
                    elif tool_ctx:
                        messages = [{"role": "system", "content": f"[Tool Context]\n{tool_ctx}"}] + messages
            except Exception:
                pass
        # 2. 快速路径 fallback（deep 成功时跳过）
        if complexity != "deep":
            fw = self.thinker.match(query, tool_pattern)
            self.logger.debug("fast framework=%s", fw)
            if fw and fw in self.thinker.frameworks:
                messages = self.thinker.inject(messages, fw)
            if tool_ctx and len(tool_ctx) < 2000:
                messages = [{"role": "system", "content": f"[Tool Context]\n{tool_ctx}"}] + messages
            elif tool_ctx:
                messages = [{"role": "system", "content": f"[Tool Context]\n{tool_ctx[:2000]}...(truncated)"}] + messages
        # 3. 辅助：记忆 + 搜索
        if self.enable_memory:
            try:
                mem = memory_manager.search(query)
                if mem and "No memory" not in mem:
                    messages = [{"role": "system", "content": f"[Memory]\n{mem}"}] + messages
            except Exception:
                pass
        if self.enable_search:
            try:
                sr = _bocha_search_api(query=query, count=3, bocha_key=os.environ["MANGO_SEARCH_API_KEY"])
                if sr:
                    sc = "\n".join(f"- {r['title']}: {r['summary']}" for r in sr[:3])
                    messages = [{"role": "system", "content": f"[Web Search]\n{sc}"}] + messages
            except Exception:
                pass
        return messages

    def _analyze_deep(self, ctx, query, tool_pattern):  # 深思路径：用 Flash-ext 自己的 LLM 分析对话状态
        is_looping, loop_tool = ctx.detect_loop()
        phase = ctx.detect_phase()
        recent = ctx.summarize_recent_turns(n_turns=3)

        prompt = ("Analyze this coding session and respond ONLY as JSON.\n"
                  f"Tool pattern: {tool_pattern or 'none'}\nPhase: {phase}\n"
                  f"Looping: {'yes (' + loop_tool + ')' if is_looping else 'no'}\n\n"
                  f"{recent}\n\n"
                  f'{{"framework": "<one of: debug/design/explain/optimize/implement/investigate/verify/reevaluate>", '
                  f'"insight": "<optional key insight agent is missing>", '
                  f'"anti_loop": "<optional>", '
                  f'"tool_summary": "<optional>"}}')
        body = self.provider.build_body([{"role": "user", "content": prompt}])
        raw = _request(self.provider.api_url, body, headers=self.provider.headers(), timeout=15)
        parsed = self.provider.parse_response(raw)
        try:
            return json.loads(parsed.get("content", "{}"))
        except (json.JSONDecodeError, ValueError):
            return None

    def _handle(self, body):
        augmented = self._augment(body.get("messages", []))
        try:
            raw = _request(self.provider.api_url, self.provider.build_body(augmented), headers=self.provider.headers())
            parsed = self.provider.parse_response(raw)
        except Exception as e:
            self.logger.warning("upstream error: %s", e)
            return {"error": {"message": f"Upstream model error: {e}", "type": "flash_ext_error", "code": 502}}
        # 记忆写入（不阻塞）
        if self.enable_memory:
            try:
                content = parsed.get("content", "")
                if content and len(content) > 50:
                    triggers = ["建议", "推荐", "配置", "因为", "原因", "recommend", "because", "config"]
                    if any(t in content for t in triggers):
                        q = body["messages"][-1].get("content", "")[:200] if body.get("messages") else ""
                        memory_manager.append(f"[auto] Q: {q}\nA: {content[:500]}")
            except Exception:
                pass
        return self._fmt_response(parsed, body.get("model", f"{self.provider.model}-ext"))

    @staticmethod
    def _fmt_response(parsed, model_name):
        return {
            "id": f"chatcmpl-flash-ext-{int(time.time())}",
            "object": "chat.completion", "created": int(time.time()), "model": model_name,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": parsed.get("content", "")},
                         "finish_reason": parsed.get("finish_reason") or "stop"}],
            "usage": parsed.get("usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})}

    def _models(self): return {"object": "list", "data": [{"id": f"{self.provider.model}-ext", "object": "model"}]}

    def _make_handler(self):
        from http.server import BaseHTTPRequestHandler
        s = self

        class _H(BaseHTTPRequestHandler):
            def _ok(self, data):
                b = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b)

            def _err(self, code, msg): self._ok({"error": {"message": msg, "type": "flash_ext_error", "code": code}})

            def _auth(self):
                if s.token:
                    auth = self.headers.get("Authorization", "")
                    if auth != f"Bearer {s.token}":
                        self.send_response(401)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": {"message": "Invalid token", "code": 401}}).encode())
                        return False
                return True

            def do_POST(self):
                if not self._auth():
                    return
                if self.path == "/v1/chat/completions":
                    t0 = time.time()
                    try:
                        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                        self._ok(s._handle(body))
                        s.logger.info("POST %s 200 %.0fms", self.path, (time.time() - t0) * 1000)
                    except json.JSONDecodeError:
                        self._err(400, "Invalid JSON")
                        s.logger.warning("POST %s 400 invalid json", self.path)
                    except Exception as e:
                        self._err(500, str(e))
                        s.logger.error("POST %s 500 %s", self.path, e)
                else:
                    self._err(404, "Not found")

            def do_GET(self):
                if self.path in ("/v1/models", "/health"):
                    self._ok(s._models() if self.path == "/v1/models" else {"status": "ok"})
                else:
                    self._err(404, "Not found")

            def log_message(self, fmt, *args): pass  # suppress http.server default

        return _H

    def start(self, debug=False):
        level = logging.DEBUG if debug else logging.INFO
        logging.basicConfig(format="%(asctime)s [%(name)s] %(levelname)s %(message)s", level=level)
        from http.server import ThreadingHTTPServer
        self._server = ThreadingHTTPServer((self.host, self.port), self._make_handler())
        self.logger.info("serving on %s:%s (frameworks=%d memory=%s search=%s auth=%s)",
                         self.host, self.port, len(self.thinker.frameworks),
                         self.enable_memory, self.enable_search, bool(self.token))
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down...")
            self._server.shutdown()


def _parse_serve_args(args=None):
    parser = argparse.ArgumentParser(description="Mangopi Flash-ext server")
    parser.add_argument("--flash-ext", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--token", default=None)
    parser.add_argument("--no-memory", action="store_true")
    parser.add_argument("--no-web-search", action="store_true")
    parser.add_argument("--debug", action="store_true")
    return parser.parse_known_args(args)[0] if args else parser.parse_args()


def main():
    initialize_system()
    args = _parse_serve_args()
    if args.flash_ext:
        if not MANGO_KEY:
            console.error("MANGO_KEY env var is required for Flash-ext mode")
            sys.exit(1)
        server = FlashExtServer(
            host=args.host, port=args.port, token=args.token, provider_obj=create_provider(),
            enable_memory=not args.no_memory, enable_search=not args.no_web_search)
        server.start(debug=args.debug)
        return

    global provider
    if MANGO_ROUTING == "on":
        try:
            provider = RoutedProvider.from_file(providers_file)
        except Exception:
            console.warning(f"Failed to load {providers_file}, forcing high-tier fallback")
            provider = RoutedProvider({
                "providers": [{"name": MANGO_MODEL, "url": MANGO_API_URL, "model": MANGO_MODEL,
                               "tier": "high", "api_key": MANGO_KEY or ""}]})

    mode = f"smart-routing[{provider.total_providers}]" if MANGO_ROUTING == "on" else provider.model
    print(f"{BOLD}Mango Cli v{__version__}{RESET} | {DIM}{mode} | {project_root}{RESET}\n")

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
                g = _goal_load()
                if g and (g.get("goal") == goal_text or goal_text.lower() in ("继续", "go on", "continue")):
                    ctx.inject_user(
                        f"[GOAL RESUMED] step {g['current']}/{len(g['steps'])} done\n"
                        f"Plan: {json.dumps(g, ensure_ascii=False)}\n\n"
                        "Continue with next pending step. Call goal(action='show') to refresh.")
                else:
                    if g:
                        _goal_clear()  # 换 goal 时清掉旧的
                    ctx.inject_user(
                        f"[GOAL MODE] {goal_text}\n\n"
                        "Call goal(action='plan', goal='<verbatim>', steps=[\"...\"]) ONCE with 3-8 steps. "
                        "Then for each step: execute, call goal(action='step', step=N, status='done', note='...'). "
                        "After all steps done, call goal(action='finish') then attempt_completion. "
                        "Do NOT call goal(action='plan') again — it will be rejected.\n\n"
                        f"Current date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                console.success(f"🎯 Goal: {goal_text}")
                if MANGO_ROUTING == "on":
                    try:
                        provider.route(ctx, goal_text)
                    except Exception as e:
                        console.warning(f"Routing failed ({e})")
                agent_loop(ctx, ctx_file_path, "[CONTINUE GOAL EXECUTION]")
                continue
            normal_message = f"{user_input}, Current date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            if MANGO_ROUTING == "on":
                try:
                    provider.route(ctx, user_input)
                except Exception as e:
                    console.warning(f"Routing failed ({e})")
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
