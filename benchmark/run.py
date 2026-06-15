#!/usr/bin/env python3
"""mangopi-cli end-to-end benchmark runner.

Evaluates the AI agent on real tasks with real LLM calls.
Supports baseline save/compare to measure system-prompt changes.

Usage:
    python benchmark/run.py                  # run all tasks
    python benchmark/run.py --level 1,2      # only L1 and L2
    python benchmark/run.py --task L2_read   # single task
    python benchmark/run.py --dry-run        # show tasks without running
    python benchmark/run.py --json           # JSON output

    # Baseline workflow (measure prompt iterations)
    python benchmark/run.py --baseline       # run + save as "main"
    # ... edit mangopi_cli.py system prompt ...
    python benchmark/run.py --compare main   # run + diff against "main"

    python benchmark/run.py --baselines      # list saved baselines
    python benchmark/run.py --delete-baseline old-test

Requires:
    MANGO_KEY        — API key (required)
    MANGO_MODEL      — model name (default: deepseek-v4-flash)
    MANGO_API_URL    — API base URL (default: https://api.deepseek.com)
"""

import argparse
import hashlib
import json
import os
import sys
import time
import tempfile
import shutil
from datetime import datetime
from typing import Dict, List, Optional

# Ensure the project root is on sys.path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.tasks import ALL_TASKS, TASKS_BY_NAME, TASKS_BY_LEVEL
from benchmark.base import AgentRunner, TaskResult, BenchmarkTask


# ═══════════════════════════════════════════════════════════════════════════════
# System prompt fingerprint
# ═══════════════════════════════════════════════════════════════════════════════


def _system_prompt_fingerprint() -> str:
    """SHA256 of the assembled system prompt content, for change tracking."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import mangopi_cli  # noqa: E402
    prompt = mangopi_cli.SystemPrompt().assemble()
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def _tasks_fingerprint() -> str:
    """SHA256 of task definitions, to detect task-set changes."""
    data: List[dict] = []
    for t in ALL_TASKS:
        data.append({
            "name": t.name, "level": t.level, "prompt": t.prompt,
            "setup_files": sorted(t.setup_files.keys()),
        })
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════════════════════
# Baseline storage
# ═══════════════════════════════════════════════════════════════════════════════


def _baseline_path() -> str:
    """Path to the baselines JSON file."""
    # Use the project-root .mangocli directory (same as sessions/memory)
    project_root = os.environ.get(
        "MANGO_PROJECT_ROOT",
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    persist = os.path.join(project_root, ".mangocli")
    os.makedirs(persist, exist_ok=True)
    return os.path.join(persist, "benchmark_baselines.json")


def _load_baselines() -> dict:
    path = _baseline_path()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_baselines(data: dict) -> None:
    with open(_baseline_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"Baselines saved to {_baseline_path()}", file=sys.stderr)


def _results_to_dict(results: List[TaskResult]) -> dict:
    """Convert TaskResult list to a JSON-serializable dict."""
    return {
        r.task_name: {
            "level": r.level, "passed": r.passed, "detail": r.detail,
            "tool_call_count": r.tool_call_count,
            "unique_tools": r.unique_tools,
            "wall_time_s": r.wall_time_s,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "total_tokens": r.total_tokens,
            "iterations": r.iterations,
            "error": r.error,
        }
        for r in results
    }


def _summary_from_results(results: List[TaskResult]) -> dict:
    return {
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "total_time_s": round(sum(r.wall_time_s for r in results), 1),
        "total_tokens": sum(r.total_tokens for r in results),
        "total_tool_calls": sum(r.tool_call_count for r in results),
    }


def save_baseline(name: str, results: List[TaskResult]) -> None:
    baselines = _load_baselines()
    baselines[name] = {
        "created": datetime.now().isoformat(),
        "model": os.environ.get("MANGO_MODEL", "deepseek-v4-flash"),
        "system_prompt_hash": _system_prompt_fingerprint(),
        "tasks_hash": _tasks_fingerprint(),
        "results": _results_to_dict(results),
        "summary": _summary_from_results(results),
    }
    _save_baselines(baselines)


def load_baseline(name: str) -> Optional[dict]:
    baselines = _load_baselines()
    return baselines.get(name)


def list_baselines() -> List[dict]:
    baselines = _load_baselines()
    items = []
    for k, v in baselines.items():
        items.append({
            "name": k,
            "created": v.get("created", "?"),
            "model": v.get("model", "?"),
            "prompt_hash": v.get("system_prompt_hash", "?"),
            "tasks_hash": v.get("tasks_hash", "?"),
            "passed": v.get("summary", {}).get("passed", "?"),
            "total": v.get("summary", {}).get("total", "?"),
        })
    items.sort(key=lambda x: x["created"], reverse=True)
    return items


def delete_baseline(name: str) -> bool:
    baselines = _load_baselines()
    if name not in baselines:
        return False
    del baselines[name]
    _save_baselines(baselines)
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# Comparison report
# ═══════════════════════════════════════════════════════════════════════════════


def _delta_str(old: float, new: float) -> str:
    diff = new - old
    if diff > 0:
        return f"+{diff:.1f}"
    elif diff < 0:
        return f"{diff:.1f}"
    return "0"


def _tool_delta_str(old: int, new: int) -> str:
    diff = new - old
    if diff > 0:
        return f"+{diff}  ⬆"
    elif diff < 0:
        return f"{diff}  ⬇"
    return "0"


def _pass_change(old_passed: bool, new_passed: bool) -> str:
    if old_passed and not new_passed:
        return "REGRESSION  ✓→✗"
    if not old_passed and new_passed:
        return "FIXED       ✗→✓"
    if old_passed and new_passed:
        return ""
    return "still failing"


def print_comparison(results: List[TaskResult], baseline_name: str) -> None:
    """Compare current results against a saved baseline."""
    bl = load_baseline(baseline_name)
    if not bl:
        print(f"Baseline '{baseline_name}' not found.", file=sys.stderr)
        return

    print(f"\n{'=' * 90}")
    print(f"  Baseline comparison:  [{baseline_name}]  vs  [current]")
    print(f"{'=' * 90}")
    print(f"  Baseline created : {bl['created']}")
    print(f"  Baseline model   : {bl['model']}")
    print(f"  Baseline prompt  : {bl.get('system_prompt_hash', '?')}")
    print(f"  Current  prompt  : {_system_prompt_fingerprint()}")
    if bl.get("system_prompt_hash") == _system_prompt_fingerprint():
        print(f"  ⚠  System prompt UNCHANGED — no diff expected")
    else:
        print(f"  ✓  System prompt CHANGED — comparing effectiveness")
    print(f"{'=' * 90}\n")

    old_results = bl["results"]
    current_dict = {r.task_name: r for r in results}

    header = (
        f"{'Task':<32} {'Pass':>13} {'Tools':>12} {'Tokens':>14} {'Time':>12}"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)

    regressions = 0
    fixes = 0
    tool_deltas = []
    token_deltas = []
    time_deltas = []

    for r in results:
        name = r.task_name
        old = old_results.get(name)
        if old is None:
            print(f"{name:<32} {'(new task)':>13} {'—':>12} {'—':>14} {'—':>12}")
            continue

        pass_note = _pass_change(old["passed"], r.passed)
        if "REGRESSION" in pass_note:
            regressions += 1
        elif "FIXED" in pass_note:
            fixes += 1

        old_tc = old["tool_call_count"]
        new_tc = r.tool_call_count
        tc_delta = _tool_delta_str(old_tc, new_tc)
        tool_deltas.append(new_tc - old_tc)

        old_tok = old["total_tokens"]
        new_tok = r.total_tokens
        tok_delta = _delta_str(old_tok, new_tok)
        token_deltas.append(new_tok - old_tok)

        old_time = old["wall_time_s"]
        new_time = r.wall_time_s
        time_delta = _delta_str(old_time, new_time)
        time_deltas.append(new_time - old_time)

        print(
            f"{name:<32} {pass_note:>13} "
            f"{old_tc}→{new_tc} {tc_delta:>6} "
            f"{old_tok:,}→{new_tok:,} {tok_delta:>7} "
            f"{old_time:.1f}s→{new_time:.1f}s {time_delta:>5}s"
        )

    print(sep)

    # Summary
    old_sum = bl.get("summary", {})
    new_sum = _summary_from_results(results)

    print(f"\n  Summary:")
    print(f"    Pass rate:  {old_sum['passed']}/{old_sum['total']}  →  "
          f"{new_sum['passed']}/{new_sum['total']}")
    print(f"    Total time: {old_sum['total_time_s']:.0f}s  →  {new_sum['total_time_s']:.0f}s"
          f"  ({_delta_str(old_sum['total_time_s'], new_sum['total_time_s'])}s)")
    print(f"    Total tokens: {old_sum['total_tokens']:,}  →  {new_sum['total_tokens']:,}"
          f"  ({_delta_str(old_sum['total_tokens'], new_sum['total_tokens'])})")
    print(f"    Total tool calls: {old_sum['total_tool_calls']}  →  "
          f"{new_sum['total_tool_calls']}"
          f"  ({_tool_delta_str(old_sum['total_tool_calls'], new_sum['total_tool_calls'])})")
    if regressions:
        print(f"\n  ⚠  {regressions} regression(s)")
    if fixes:
        print(f"  ✓  {fixes} fixe(s)")

    # Tool count trend
    if tool_deltas:
        avg_tc = sum(tool_deltas) / len(tool_deltas)
        trend = "more tools" if avg_tc > 0.5 else "fewer tools" if avg_tc < -0.5 else "≈ same"
        print(f"  Tool trend: {avg_tc:+.1f} avg per task ({trend})")

    print(f"\n{'=' * 90}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# Report formatting (table)
# ═══════════════════════════════════════════════════════════════════════════════

PASS = "✓"
FAIL = "✗"


def format_result(r: TaskResult, idx: int, total: int) -> str:
    status = PASS if r.passed else FAIL
    name = r.task_name
    detail = f"ERROR: {r.error}" if r.error else (r.detail or "(no detail)")
    return (
        f"  [{idx}/{total}] {status} {name:<32} "
        f"tools={r.tool_call_count:<3} {r.wall_time_s:>5.1f}s  "
        f"tokens={r.total_tokens:>6,}  {detail}"
    )


def print_summary_table(results: List[TaskResult]) -> None:
    print()
    header = f"{'Task':<35} {'Level':>5} {'Pass':>5} {'Tools':>6} {'Time':>7} {'Tokens':>8} {'Iters':>5}"
    sep = "-" * len(header)
    print(header)
    print(sep)
    for r in results:
        status = PASS if r.passed else FAIL
        print(
            f"{r.task_name:<35} {r.level:>5} {status:>5} "
            f"{r.tool_call_count:>6} {r.wall_time_s:>6.1f}s {r.total_tokens:>7,} {r.iterations:>5}"
        )
    print(sep)

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    total_time = sum(r.wall_time_s for r in results)
    total_tokens = sum(r.total_tokens for r in results)
    total_tc = sum(r.tool_call_count for r in results)

    print(f"\nResults: {passed}/{total} passed  |  "
          f"Total time: {total_time:.1f}s  |  Total tokens: {total_tokens:,}")
    for lv in [1, 2, 3, 4]:
        lv_results = [r for r in results if r.level == lv]
        if lv_results:
            lv_passed = sum(1 for r in lv_results if r.passed)
            lv_total = len(lv_results)
            bar = "█" * lv_passed + "░" * (lv_total - lv_passed)
            print(f"  L{lv}: {bar} {lv_passed}/{lv_total}")

    print(f"\nAvg tool calls/task: {total_tc / total:.1f}  |  "
          f"Avg tokens/task: {total_tokens // total:,}  |  "
          f"Avg time/task: {total_time / total:.1f}s")

    # Tool usage distribution
    tool_counts: Dict[str, int] = {}
    for r in results:
        for tc in r.tool_calls:
            name = tc.get("name", "?")
            tool_counts[name] = tool_counts.get(name, 0) + 1
    if tool_counts:
        print("\nTool usage distribution:")
        for name, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
            pct = count / total_tc * 100 if total_tc else 0
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            print(f"  {name:<24} {bar} {count:>4} ({pct:5.1f}%)")
    print()


def print_json_report(results: List[TaskResult]) -> None:
    output = []
    for r in results:
        output.append({
            "task": r.task_name, "level": r.level, "passed": r.passed,
            "detail": r.detail, "tool_call_count": r.tool_call_count,
            "unique_tools": r.unique_tools, "wall_time_s": r.wall_time_s,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "total_tokens": r.total_tokens, "iterations": r.iterations,
            "error": r.error,
            "tool_calls": [tc["name"] for tc in r.tool_calls],
        })
    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "total_time_s": round(sum(r.wall_time_s for r in results), 1),
        "total_tokens": sum(r.total_tokens for r in results),
        "model": os.environ.get("MANGO_MODEL", "deepseek-v4-flash"),
        "system_prompt_hash": _system_prompt_fingerprint(),
        "tasks_hash": _tasks_fingerprint(),
        "timestamp": datetime.now().isoformat(),
    }
    print(json.dumps({"summary": summary, "results": output},
                     indent=2, ensure_ascii=False))


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════


def check_env() -> str:
    if not os.environ.get("MANGO_KEY"):
        return "MANGO_KEY env var is not set. Set it to your API key."
    return ""


def main():
    parser = argparse.ArgumentParser(
        description="mangopi-cli E2E benchmark — evaluates agent correctness and tool efficiency")
    parser.add_argument("--level", type=str, default="",
                        help="Comma-separated levels (e.g. '1,2'). Default: all.")
    parser.add_argument("--task", type=str, default="",
                        help="Run a single task by name (e.g. 'L2_read_and_write').")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show task list without executing.")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON.")
    parser.add_argument("--retries", type=int, default=1,
                        help="Max retries for failed tasks (default: 1).")
    parser.add_argument("--timeout", type=int, default=180,
                        help="Max seconds per task (default: 180).")
    parser.add_argument("--keep-workspace", action="store_true",
                        help="Keep temp workspace after run (for debugging).")

    # Baseline flags
    parser.add_argument("--baseline", type=str, nargs="?", const="main", default=None,
                        metavar="NAME",
                        help="Save results as a named baseline (default name: 'main').")
    parser.add_argument("--compare", type=str, default=None, metavar="NAME",
                        help="Run and compare against a saved baseline.")
    parser.add_argument("--baselines", action="store_true",
                        help="List saved baselines and exit.")
    parser.add_argument("--delete-baseline", type=str, default=None, metavar="NAME",
                        help="Delete a saved baseline and exit.")

    args = parser.parse_args()

    # ── baseline-only actions (no API calls) ─────────────────────────────────

    if args.baselines:
        items = list_baselines()
        if not items:
            print("No baselines saved yet.", file=sys.stderr)
        else:
            print(f"\n{'Name':<20} {'Created':<22} {'Model':<22} {'Pass':>6} {'Prompt':>18} {'Tasks':>18}")
            print("-" * 110)
            for b in items:
                print(
                    f"{b['name']:<20} {b['created']:<22} {b['model']:<22} "
                    f"{b['passed']}/{b['total']:>4}  {b['prompt_hash']:>16}  {b['tasks_hash']:>16}"
                )
            print()
        return

    if args.delete_baseline:
        ok = delete_baseline(args.delete_baseline)
        if ok:
            print(f"Baseline '{args.delete_baseline}' deleted.", file=sys.stderr)
        else:
            print(f"Baseline '{args.delete_baseline}' not found.", file=sys.stderr)
        return

    # ── env check ───────────────────────────────────────────────────────────

    err = check_env()
    if err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    # ── task selection ──────────────────────────────────────────────────────

    if args.task:
        if args.task not in TASKS_BY_NAME:
            print(f"Unknown task: {args.task}", file=sys.stderr)
            print(f"Available: {', '.join(sorted(TASKS_BY_NAME.keys()))}",
                  file=sys.stderr)
            sys.exit(1)
        tasks = [TASKS_BY_NAME[args.task]]
    elif args.level:
        levels = [int(l.strip()) for l in args.level.split(",") if l.strip().isdigit()]
        tasks = []
        for lv in levels:
            tasks.extend(TASKS_BY_LEVEL.get(lv, []))
    else:
        tasks = list(ALL_TASKS)

    if not tasks:
        print("No tasks selected.", file=sys.stderr)
        sys.exit(1)

    # ── dry run ─────────────────────────────────────────────────────────────

    if args.dry_run:
        out = sys.stderr if args.json else sys.stdout
        print(f"\nWould run {len(tasks)} task(s):\n", file=out)
        for t in tasks:
            print(f"  [{t.level}] {t.name}", file=out)
            print(f"        {t.description}", file=out)
            print(f"        prompt: {t.prompt[:100]}...", file=out)
            print(file=out)
        if args.baseline:
            print(f"Results would be saved as baseline '{args.baseline}'.", file=out)
        if args.compare:
            print(f"Results would be compared against baseline '{args.compare}'.", file=out)
        return

    # ── run ─────────────────────────────────────────────────────────────────

    model = os.environ.get("MANGO_MODEL", "deepseek-v4-flash")
    use_json = args.json

    if args.compare:
        bl = load_baseline(args.compare)
        if not bl:
            print(f"Baseline '{args.compare}' not found. Run with --baseline first.",
                  file=sys.stderr)
            sys.exit(1)
        prompt_changed = bl.get("system_prompt_hash") != _system_prompt_fingerprint()
        tasks_changed = bl.get("tasks_hash") != _tasks_fingerprint()
        if not use_json:
            print(f"\n  Baseline: {args.compare}  |  model={model}  |  {len(tasks)} task(s)")
            if tasks_changed:
                print(f"  ⚠  Task definitions have changed since baseline was saved.")
            if prompt_changed:
                print(f"  ✓  System prompt CHANGED — measuring impact")
            else:
                print(f"  ⚠  System prompt UNCHANGED — expect similar results")
            print()
    elif not use_json:
        print(f"\nmangopi-cli benchmark · model={model} · {len(tasks)} task(s)")
        if args.baseline:
            print(f"Results will be saved as baseline '{args.baseline}'")
        print()

    results: List[TaskResult] = []
    workspace_root = tempfile.mkdtemp(prefix="mangopi_bench_")

    try:
        for i, task in enumerate(tasks, 1):
            task.timeout = args.timeout
            task.retries = args.retries

            best_result: Optional[TaskResult] = None
            for attempt in range(task.retries + 1):
                workspace = os.path.join(workspace_root, f"{task.name}_{attempt}")
                os.makedirs(workspace, exist_ok=True)

                runner = AgentRunner(workspace)
                result = runner.run(task)

                if result.passed or attempt == task.retries:
                    best_result = result
                    break
                print(f"    Retry {attempt + 1}/{task.retries} for {task.name}...",
                      file=sys.stderr)

            if best_result is None:
                best_result = result

            best_result._max_tool_calls = task.max_tool_calls
            results.append(best_result)

            print(format_result(best_result, i, len(tasks)), file=sys.stderr)
            sys.stderr.flush()

    except KeyboardInterrupt:
        print("\n\nInterrupted.", file=sys.stderr)
    finally:
        if not args.keep_workspace:
            shutil.rmtree(workspace_root, ignore_errors=True)
        else:
            print(f"\nWorkspace kept at: {workspace_root}", file=sys.stderr)

    # ── save baseline ───────────────────────────────────────────────────────

    if args.baseline:
        save_baseline(args.baseline, results)
        if not use_json:
            print(f"Saved as baseline '{args.baseline}' "
                  f"(prompt={_system_prompt_fingerprint()})", file=sys.stderr)

    # ── compare ─────────────────────────────────────────────────────────────

    if args.compare:
        print_comparison(results, args.compare)

    # ── report ──────────────────────────────────────────────────────────────

    if args.json:
        print_json_report(results)
    else:
        print_summary_table(results)

    # Exit code
    failed = sum(1 for r in results if not r.passed)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
