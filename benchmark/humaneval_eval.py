#!/usr/bin/env python3
"""
mangopi_humaneval_eval.py — 用 Mangopi CLI 的全套工具和提示词跑 HumanEval

两种模式:
  --mode per_task    每题一个独立 agent session(测单题能力)
  --mode all_session 所有题在一个 agent session 里(测长 session agent 能力)

Tools 和 system prompt 都直接从 mangopi_cli 拿(13 个 tool + Mangopi system prompt)。

评分:HumanEval 标准 test + check(entry_point),exec() 看是否抛 AssertionError。

零第三方依赖(Python 3.8+ stdlib + mangopi_cli 本地 import)
"""
import argparse
import gzip
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# 引入 Mangopi 的 tools 和 prompt (script 在 benchmark/ 下,父目录是项目根)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mangopi_cli as m  # noqa: E402


# ============================================================
# 常量
# ============================================================

HUMANEVAL_URL = "https://raw.githubusercontent.com/openai/human-eval/master/data/HumanEval.jsonl.gz"
CACHE_DIR = Path.home() / ".cache" / "humaneval"
BASH_TIMEOUT = 30
MAX_TURNS_PER_TASK = 8

DANGEROUS_PATTERNS = [
    r"\brm\s+-rf?\s+/",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r">\s*/dev/sd",
    r":\(\)\s*\{.*\}",
    r"\bchmod\s+777\s+/",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bcurl\s+",
    r"\bwget\s+",
    r"\bnc\s+",
    r"\bssh\s+",
]


# ============================================================
# HumanEval 数据
# ============================================================

def load_humaneval(limit: int = 50) -> List[Dict[str, Any]]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / "HumanEval.jsonl.gz"
    if not cache_path.exists():
        print(f"  ↓ 下载 HumanEval...")
        try:
            urllib.request.urlretrieve(HUMANEVAL_URL, cache_path)
        except Exception as e:
            print(f"  ✗ 下载失败:{e}", file=sys.stderr)
            sys.exit(1)
    tasks = []
    with gzip.open(cache_path, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            tasks.append(json.loads(line))
            if len(tasks) >= limit:
                break
    return tasks


# ============================================================
# HumanEval 评分
# ============================================================

def grade_humaneval(task: Dict[str, Any], code: str) -> Tuple[bool, str]:
    test_code = task["test"]
    entry_point = task["entry_point"]
    check_program = test_code + "\n\n" + f"check({entry_point})\n"
    full_program = code + "\n\n" + check_program
    try:
        exec(full_program, {})
        return True, ""
    except AssertionError as e:
        return False, f"assertion: {str(e)[:200]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"


# ============================================================
# 路径工具
# ============================================================

def safe_task_id(task_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", task_id)


def find_solution_code(workdir: str, task_id: str) -> Optional[str]:
    p = Path(workdir) / f"solution_{safe_task_id(task_id)}.py"
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return None
    return None


# ============================================================
# Bash sandbox
# ============================================================

def is_dangerous(cmd: str) -> bool:
    for pat in DANGEROUS_PATTERNS:
        if re.search(pat, cmd):
            return True
    return False


def run_bash(cmd: str, cwd: str, timeout: int = BASH_TIMEOUT) -> str:
    if is_dangerous(cmd):
        return "[BLOCKED] Dangerous command refused (rm -rf /, mkfs, dd, network, etc.)"
    try:
        r = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True, text=True, timeout=timeout, cwd=cwd,
            env={**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
        )
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        ret = f"[exit={r.returncode}]"
        if out:
            ret += f"\nstdout: {out[:1500]}"
        if err:
            ret += f"\nstderr: {err[:800]}"
        return ret or "[no output]"
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT after {timeout}s]"
    except Exception as e:
        return f"[EXEC ERROR: {e}]"


# ============================================================
# Mangopi 工具实现
# ============================================================

def tool_read(path: str, offset: int = 0, limit: int = None) -> str:
    if not os.path.isabs(path):
        return f"[ERROR] relative paths not allowed: {path}"
    if not os.path.exists(path):
        return f"[ERROR] file not found: {path}"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if offset:
            lines = lines[offset:]
        if limit:
            lines = lines[:limit]
        numbered = [f"{i+1+offset:4d}  {ln}" for i, ln in enumerate(lines)]
        return "".join(numbered)[:5000]
    except Exception as e:
        return f"[ERROR] {type(e).__name__}: {e}"


def tool_write(path: str, content: str) -> str:
    if not os.path.isabs(path):
        return f"[ERROR] relative paths not allowed: {path}"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"[OK] wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"[ERROR] {type(e).__name__}: {e}"


def tool_edit(path: str, old: str, new: str, all_occurrences: bool = False) -> str:
    if not os.path.isabs(path):
        return f"[ERROR] relative paths not allowed: {path}"
    if not os.path.exists(path):
        return f"[ERROR] file not found: {path}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        n = content.count(old)
        if n == 0:
            return f"[ERROR] old text not found in {path}"
        if n > 1 and not all_occurrences:
            return f"[ERROR] old text appears {n} times, pass all=true"
        new_content = content.replace(old, new) if all_occurrences else content.replace(old, new, 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return f"[OK] edited {path}"
    except Exception as e:
        return f"[ERROR] {type(e).__name__}: {e}"


def tool_grep(pattern: str, path: str, glob: str = None) -> str:
    cmd = f"grep -rn '{pattern}' {path} 2>/dev/null"
    if glob:
        cmd += f" --include='{glob}'"
    try:
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=10)
        return (r.stdout or "").strip()[:2000] or "(no matches)"
    except Exception as e:
        return f"[ERROR] {e}"


def tool_search(pattern: str, path: str) -> str:
    try:
        r = subprocess.run(["find", path, "-name", pattern, "-not", "-path", "*/.*"],
                          capture_output=True, text=True, timeout=10)
        return (r.stdout or "").strip()[:1500] or "(no files matched)"
    except Exception as e:
        return f"[ERROR] {e}"


def _skip(name: str, *args, **kwargs) -> str:
    return f"[SKIP] {name} disabled in benchmark mode"


TOOL_HANDLERS = {
    "bash": lambda args: run_bash(args.get("cmd", ""), os.environ.get("AGENT_CWD", "/tmp")),
    "read": lambda args: tool_read(args.get("path", ""), args.get("offset", 0), args.get("limit")),
    "write": lambda args: tool_write(args.get("path", ""), args.get("content", "")),
    "edit": lambda args: tool_edit(args.get("path", ""), args.get("old", ""),
                                    args.get("new", ""), args.get("all", False)),
    "grep": lambda args: tool_grep(args.get("pattern", ""), args.get("path", "/tmp"),
                                    args.get("glob")),
    "search": lambda args: tool_search(args.get("pattern", ""), args.get("path", "/tmp")),
    "view_image": lambda args: _skip("view_image"),
    "use_skill": lambda args: _skip("use_skill"),
    "search_memory": lambda args: _skip("search_memory"),
    "append_memory": lambda args: _skip("append_memory"),
    "goal": lambda args: _skip("goal"),
    "web_search": lambda args: _skip("web_search"),
}


# ============================================================
# Mangopi schema / prompt 加载
# ============================================================

def make_tools_schema() -> List[Dict]:
    return m.tool_schema()


def make_system_prompt() -> str:
    return m.SystemPrompt().assemble()


# ============================================================
# API 调用
# ============================================================

class APIError(Exception):
    pass


def chat_completion(base_url: str, api_key: str, model: str, messages: List[Dict],
                    tools: List[Dict], timeout: int = 90) -> Dict[str, Any]:
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    url += "/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": messages,
        "tools": tools,
        "max_tokens": 2048,
        "temperature": 0.0,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise APIError(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}")
    except Exception as e:
        raise APIError(f"{type(e).__name__}: {e}")


# ============================================================
# 代码提取(从 agent 消息里抽 Python 代码)
# ============================================================

def extract_code_from_message(msg: Dict[str, Any]) -> Optional[str]:
    tool_calls = msg.get("tool_calls") or []
    for tc in tool_calls:
        fn = tc.get("function", {})
        if fn.get("name") != "attempt_completion":
            continue
        try:
            args = json.loads(fn.get("arguments", "{}"))
        except Exception:
            continue
        result = args.get("result", "")
        # 从 result 里抓 python code block
        m = re.search(r"```python\n(.+?)```", result, re.DOTALL)
        if m:
            return m.group(1).strip()
        # 抓 def entry_point(...) 开头
        m = re.search(r"(def\s+\w+\s*\(.+?)(?:\n```|$)", result, re.DOTALL)
        if m:
            return m.group(1).strip()
        if "def " in result:
            return result.strip()
    content = msg.get("content") or ""
    m = re.search(r"```python\n(.+?)```", content, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


# ============================================================
# 模式 1:per_task — 每题独立 session
# ============================================================

def build_per_task_prompt(task: Dict[str, Any], workdir: str) -> str:
    return (
        f"## Coding Task (HumanEval/{task['task_id']})\n\n"
        f"Write a Python function that solves the following problem.\n\n"
        f"### Problem\n```python\n{task['prompt']}\n```\n\n"
        f"### Requirements\n"
        f"- Function name: `{task['entry_point']}`\n"
        f"- Save your solution to: `{workdir}/solution.py`\n"
        f"- Run your own tests with bash before submitting.\n"
        f"- When done, call `attempt_completion(result=\"<summary>\")`.\n\n"
        f"Get started."
    )


def run_one_task(task: Dict[str, Any], base_url: str, api_key: str, model: str,
                 max_turns: int = MAX_TURNS_PER_TASK) -> Dict[str, Any]:
    workdir = tempfile.mkdtemp(prefix=f"he_task_{safe_task_id(task['task_id'])}_")
    sol_path = f"{workdir}/solution.py"
    os.environ["AGENT_CWD"] = workdir

    try:
        messages: List[Dict] = [
            {"role": "system", "content": make_system_prompt()},
            {"role": "user", "content": build_per_task_prompt(task, workdir)},
        ]
        tools_schema = make_tools_schema()

        final_code = None
        turns = 0
        last_error = ""
        finished = False

        for turn in range(max_turns):
            turns += 1
            try:
                resp = chat_completion(base_url, api_key, model, messages, tools_schema)
            except APIError as e:
                last_error = f"api: {e}"
                break

            choice = (resp.get("choices") or [{}])[0]
            msg = choice.get("message", {})
            messages.append(msg)

            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                final_code = extract_code_from_message(msg)
                if final_code:
                    finished = True
                    break
                last_error = "no tool call or code"
                break

            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except Exception:
                    args = {}

                if name == "attempt_completion":
                    final_code = extract_code_from_message(msg)
                    finished = True
                    messages.append({
                        "role": "tool", "tool_call_id": tc.get("id", ""),
                        "name": name, "content": "accepted. evaluating...",
                    })
                    break

                handler = TOOL_HANDLERS.get(name)
                if handler:
                    try:
                        output = handler(args)
                    except Exception as e:
                        output = f"[TOOL ERROR] {type(e).__name__}: {e}"
                else:
                    output = f"[SKIP] tool '{name}' not implemented"
                messages.append({
                    "role": "tool", "tool_call_id": tc.get("id", ""),
                    "name": name, "content": output[:3000],
                })

            if finished:
                break

        if not final_code and os.path.exists(sol_path):
            final_code = open(sol_path).read()

        if not final_code:
            return {"task_id": task["task_id"], "passed": False, "turns": turns,
                    "code": "", "error": last_error or "no code produced"}

        passed, err = grade_humaneval(task, final_code)
        return {"task_id": task["task_id"], "passed": passed, "turns": turns,
                "code": final_code[:300], "error": err}
    finally:
        try:
            subprocess.run(["rm", "-rf", workdir], timeout=5)
        except Exception:
            pass


def run_per_task(tasks: List[Dict[str, Any]], base_url: str, api_key: str,
                 model: str, max_turns: int) -> List[Dict[str, Any]]:
    results = []
    t_start = time.time()
    for i, task in enumerate(tasks, 1):
        t0 = time.time()
        r = run_one_task(task, base_url, api_key, model, max_turns=max_turns)
        elapsed = time.time() - t0
        icon = "✓" if r["passed"] else "✗"
        err_short = f"  err={r['error'][:30]}" if r["error"] else ""
        print(f"  [{i:3d}/{len(tasks)}] {icon} {task['task_id']:14s} "
              f"turns={r['turns']} {elapsed:.1f}s{err_short}")
        results.append(r)
    print(f"\n  per_task 总耗时 {time.time()-t_start:.1f}s")
    return results


# ============================================================
# 模式 2:all_session — 所有题一个 session
# ============================================================

INTRO_PROMPT = """## Multi-Task Coding Session (HumanEval, {total} tasks)

You will solve **{total} HumanEval tasks in one continuous session**.

For each task I will:
1. Send you the problem statement
2. You explore / write code / run tests using your tools
3. Call **attempt_completion(result="<summary>")** when done
4. I evaluate and tell you PASS/FAIL, then give you the next task

### Conventions
- Save each solution to: `{workdir}/solution_<task_id>.py`
  (replace `<task_id>` with the task ID, e.g. `solution_HumanEval_0.py`)
- Function name must match `entry_point` given in each task.
- After attempt_completion, **stop and wait** for my PASS/FAIL feedback.

### Strategy
- Use bash to run your own smoke tests before attempt_completion.
- If first attempt fails, edit and retry.
- Manage your own context — prior tasks will accumulate.
- Don't ask questions; make reasonable assumptions.

First task coming next.
"""


def build_task_user_msg(task: Dict[str, Any], idx: int, total: int, workdir: str) -> str:
    fname = f"solution_{safe_task_id(task['task_id'])}.py"
    return (
        f"## Task {idx}/{total} — {task['task_id']}\n\n"
        f"### Problem\n```python\n{task['prompt']}\n```\n\n"
        f"### Requirements\n"
        f"- Function name: **`{task['entry_point']}`**\n"
        f"- Save to: **`{workdir}/{fname}`**\n"
        f"- When done, call `attempt_completion(result=\"<brief summary>\")`.\n\n"
        f"Begin."
    )


def run_all_in_session(tasks: List[Dict[str, Any]], base_url: str, api_key: str,
                       model: str, max_turns_per_task: int) -> List[Dict[str, Any]]:
    workdir = tempfile.mkdtemp(prefix="he_allsess_")
    os.environ["AGENT_CWD"] = workdir

    try:
        sys_prompt = make_system_prompt()
        tools_schema = make_tools_schema()
        intro = INTRO_PROMPT.format(total=len(tasks), workdir=workdir)

        messages: List[Dict] = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": intro},
        ]

        results = []
        t_start = time.time()
        for idx, task in enumerate(tasks, 1):
            messages.append({
                "role": "user",
                "content": build_task_user_msg(task, idx, len(tasks), workdir),
            })

            submitted_code = None
            turns = 0
            last_error = ""
            for turn in range(max_turns_per_task):
                turns += 1
                try:
                    resp = chat_completion(base_url, api_key, model, messages, tools_schema)
                except APIError as e:
                    last_error = f"api: {e}"
                    break

                choice = (resp.get("choices") or [{}])[0]
                msg = choice.get("message", {})
                messages.append(msg)

                tool_calls = msg.get("tool_calls") or []
                finish_called = False

                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except Exception:
                        args = {}

                    if name == "attempt_completion":
                        submitted_code = extract_code_from_message(msg)
                        if not submitted_code:
                            submitted_code = find_solution_code(workdir, task["task_id"])
                        messages.append({
                            "role": "tool", "tool_call_id": tc.get("id", ""),
                            "name": name, "content": "accepted. evaluating...",
                        })
                        finish_called = True
                        break

                    handler = TOOL_HANDLERS.get(name)
                    if handler:
                        try:
                            output = handler(args)
                        except Exception as e:
                            output = f"[TOOL ERROR] {type(e).__name__}: {e}"
                    else:
                        output = f"[SKIP] tool '{name}' not implemented"
                    messages.append({
                        "role": "tool", "tool_call_id": tc.get("id", ""),
                        "name": name, "content": output[:3000],
                    })

                if finish_called:
                    break

            if not submitted_code:
                submitted_code = find_solution_code(workdir, task["task_id"])
            if not submitted_code:
                results.append({"task_id": task["task_id"], "passed": False,
                                "turns": turns, "code": "", "error": last_error or "no code"})
                feedback = f"Task {idx}/{len(tasks)} **FAIL**: no code submitted.{last_error[:80]}"
            else:
                passed, err = grade_humaneval(task, submitted_code)
                results.append({"task_id": task["task_id"], "passed": passed,
                                "turns": turns, "code": submitted_code[:200],
                                "error": err if not passed else ""})
                feedback = f"Task {idx}/{len(tasks)} {'**PASS**' if passed else '**FAIL**: ' + err[:120]}"

            elapsed = time.time() - t_start
            icon = "✓" if results[-1]["passed"] else "✗"
            print(f"  [{idx:3d}/{len(tasks)}] {icon} {task['task_id']:14s} "
                  f"turns={turns}  elapsed={elapsed:.0f}s")
            sys.stdout.flush()

            if idx < len(tasks):
                messages.append({
                    "role": "user",
                    "content": feedback + f"\n\nProceeding to task {idx+1}/{len(tasks)}...",
                })
            else:
                messages.append({
                    "role": "user",
                    "content": feedback + "\n\nAll tasks done. You may stop.",
                })

        print(f"\n  all_session 总耗时 {time.time()-t_start:.1f}s")
        return results
    finally:
        try:
            subprocess.run(["rm", "-rf", workdir], timeout=5)
        except Exception:
            pass


# ============================================================
# CLI
# ============================================================

def run_eval(args):
    tasks = load_humaneval(args.limit)
    print(f"  HumanEval 题数:  {len(tasks)}")
    print(f"  base_url:        {args.base_url}")
    print(f"  model:           {args.model}")
    print(f"  mode:            {args.mode}")
    if args.mode == "per_task":
        print(f"  max_turns:       {args.max_turns} (每题独立 session)")
    else:
        print(f"  max_turns/task:  {args.max_turns} (所有题一个 session)")
    print(f"  system prompt:   Mangopi SystemPrompt.assemble() ({len(make_system_prompt())} 字符)")
    print(f"  tools:           Mangopi 全套 {len(make_tools_schema())} 个")
    print()

    if args.mode == "per_task":
        results = run_per_task(tasks, args.base_url, args.api_key, args.model, args.max_turns)
    else:
        results = run_all_in_session(tasks, args.base_url, args.api_key, args.model, args.max_turns)

    print_summary(results, label=f"base_url={args.base_url}, mode={args.mode}")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({
                "base_url": args.base_url,
                "model": args.model,
                "mode": args.mode,
                "limit": args.limit,
                "ts": time.time(),
                "results": results,
            }, f, indent=2, ensure_ascii=False)
        print(f"\n  已保存:{args.out}")


def print_summary(results, label=""):
    n = len(results)
    if not n:
        return
    passed = sum(1 for r in results if r["passed"])
    errs = sum(1 for r in results if r["error"])
    avg_turns = sum(r["turns"] for r in results) / n
    print()
    print("=" * 50)
    if label:
        print(f"  {label}")
    print(f"  Pass@1:  {passed}/{n} = {passed/n*100:.1f}%")
    if errs:
        print(f"  错误数:  {errs}/{n}")
    print(f"  平均轮数:{avg_turns:.1f}")
    print("=" * 50)


def cmd_compare(args):
    a = json.load(open(args.file_a, encoding="utf-8"))
    b = json.load(open(args.file_b, encoding="utf-8"))
    n = len(a["results"])
    pa = sum(1 for r in a["results"] if r["passed"])
    pb = sum(1 for r in b["results"] if r["passed"])
    print()
    print("=" * 60)
    print(f"  HumanEval ({n} 题,mode={a.get('mode', '?')})")
    print(f"  A: {a.get('base_url', '?')[:50]}")
    print(f"     Pass@1: {pa}/{n} = {pa/n*100:.1f}%")
    print(f"  B: {b.get('base_url', '?')[:50]}")
    print(f"     Pass@1: {pb}/{n} = {pb/n*100:.1f}%")
    print(f"  Δ: {(pb-pa)/n*100:+.1f} pp")
    print("=" * 60)
    diffs = [(ra, rb) for ra, rb in zip(a["results"], b["results"]) if ra["passed"] != rb["passed"]]
    if diffs:
        print(f"\n  差异题 ({len(diffs)}):")
        for ra, rb in diffs:
            ma = "✓" if ra["passed"] else "✗"
            mb = "✓" if rb["passed"] else "✗"
            print(f"  {ra['task_id']:14s}  A={ma}(t={ra['turns']})  B={mb}(t={rb['turns']})")


def main():
    parser = argparse.ArgumentParser(
        description="用 Mangopi 全套 tools + prompt 跑 HumanEval agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  # 单题独立 session
  python mangopi_humaneval_eval.py eval \\
    --mode per_task \\
    --base-url https://api.deepseek.com/v1 \\
    --api-key $MANGO_KEY --model deepseek-v4-flash \\
    --limit 50 --out he_baseline_per.json

  # 所有题一个 session(测长 session agent)
  python mangopi_humaneval_eval.py eval \\
    --mode all_session \\
    --base-url https://api.deepseek.com/v1 \\
    --api-key $MANGO_KEY --model deepseek-v4-flash \\
    --limit 50 --out he_baseline_all.json

  # 对比
  python mangopi_humaneval_eval.py compare he_baseline_all.json he_flash_all.json
""")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_eval = sub.add_parser("eval", help="跑评估")
    p_eval.add_argument("--mode", choices=["per_task", "all_session"],
                        default="all_session",
                        help="per_task=每题独立 session / all_session=所有题一个 session(默认)")
    p_eval.add_argument("--base-url", required=True)
    p_eval.add_argument("--api-key", required=True)
    p_eval.add_argument("--model", required=True)
    p_eval.add_argument("--limit", type=int, default=50)
    p_eval.add_argument("--max-turns", type=int, default=8,
                        help="per_task 模式=每题轮数 / all_session 模式=每题最大轮数")
    p_eval.add_argument("--out", help="保存结果")
    p_eval.set_defaults(func=run_eval)

    p_cmp = sub.add_parser("compare")
    p_cmp.add_argument("file_a")
    p_cmp.add_argument("file_b")
    p_cmp.set_defaults(func=cmd_compare)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()