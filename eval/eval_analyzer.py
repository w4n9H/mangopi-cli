#!/usr/bin/env python3
"""Mangopi Eval Analyzer — 读取 trace 文件，输出 per-run 指标和聚合报告。

用法:
    python eval/eval_analyzer.py
    python eval/eval_analyzer.py --format json
"""

import json, os, sys
from collections import Counter
from datetime import datetime

TRACES_DIR = os.path.join(os.path.dirname(__file__), "..", ".mangocli", "traces")


# ── 解析 ──────────────────────────────────────────────

def load_traces(traces_dir=TRACES_DIR):
    """加载所有 trace 文件，返回解析后的 run 列表。"""
    if not os.path.isdir(traces_dir):
        print(f"[error] traces dir not found: {traces_dir}", file=sys.stderr)
        return []

    runs = []
    for fname in sorted(os.listdir(traces_dir)):
        if not fname.endswith((".json", ".jsonl")):
            continue
        filepath = os.path.join(traces_dir, fname)
        try:
            with open(filepath) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[warn] skip {fname}: {e}", file=sys.stderr)
            continue

        if not data or not isinstance(data, list):
            continue
        if data[0].get("kind") != "user_input":
            continue

        runs.append(_parse_one(data, fname))

    return runs


def _parse_one(events, fname):
    meta = events[0]
    assistants = [e for e in events if e["kind"] == "assistant"]
    tool_calls = [e for e in events if e["kind"] == "tool_call"]
    tool_results = [e for e in events if e["kind"] == "tool_result"]
    compacts = [e for e in events if e["kind"] == "compact"]
    end = next((e for e in reversed(events) if e["kind"] == "end"), None)

    total_in = sum(e.get("prompt_tokens", 0) or 0 for e in assistants)
    total_out = sum(e.get("completion_tokens", 0) or 0 for e in assistants)
    tool_types = Counter(e["name"] for e in tool_calls)
    finish_reasons = Counter(e.get("finish_reason", "") for e in assistants)
    errors = [e for e in tool_results if not e.get("success")]
    last = next((e for e in reversed(tool_results) if e.get("name") == "attempt_completion"), None)

    return {
        "file": fname,
        "mode": meta.get("mode", ""),
        "goal": meta.get("goal", "")[:100],
        "total_rounds": assistants[-1]["round"] if assistants else 0,
        "total_tokens_in": total_in,
        "total_tokens_out": total_out,
        "total_tokens": total_in + total_out,
        "tool_count": len(tool_calls),
        "tool_types": dict(tool_types.most_common()),
        "tool_errors": len(errors),
        "compact_count": len(compacts),
        "compact_saved": sum(e.get("saved", 0) or 0 for e in compacts),
        "finish_reasons": dict(finish_reasons),
        "has_reasoning": any(e.get("has_reasoning") for e in assistants),
        "completed": last is not None and last.get("success", False),
        "final_ctx_pct": round(max((e.get("prompt_tokens") or 0) for e in assistants) / 1_000_000 * 100, 1),
        "rounds_detail": [
            {
                "round": e["round"],
                "tokens_in": e.get("prompt_tokens", 0),
                "tokens_out": e.get("completion_tokens", 0),
                "reasoning_len": e.get("reasoning_len", 0),
                "has_reasoning": e.get("has_reasoning", False),
                "tool_calls": e.get("tool_calls_count", 0),
                "finish_reason": e.get("finish_reason", ""),
                "content_len": e.get("content_len", 0),
            }
            for e in assistants
        ],
    }


# ── 报告 ──────────────────────────────────────────────

def print_report(runs):
    if not runs:
        print("No traces found.")
        return

    n = len(runs)
    chats = [r for r in runs if r["mode"] == "chat"]
    loops = [r for r in runs if r["mode"] == "loop"]

    print()
    print("=" * 58)
    print(f"  Mangopi Eval Report  —  {datetime.now():%Y-%m-%d %H:%M}")
    print(f"  {n} run{'s' if n>1 else ''}")
    print("=" * 58)

    # ── 聚合 ──
    print(f"""
  Aggregate
    Runs:              {n}
      chat:            {len(chats)}
      loop:            {len(loops)}
    Completed:         {sum(1 for r in runs if r['completed'])}/{n}
    Total tokens:      {sum(r['total_tokens'] for r in runs):>10,}
      in:              {sum(r['total_tokens_in'] for r in runs):>10,}
      out:             {sum(r['total_tokens_out'] for r in runs):>10,}
    Avg tokens/run:    {sum(r['total_tokens'] for r in runs)/n:>10,.0f}
    Avg rounds/run:    {sum(r['total_rounds'] for r in runs)/n:>8.1f}
    Tool calls:        {sum(r['tool_count'] for r in runs):>10,}
    Tool errors:       {sum(r['tool_errors'] for r in runs):>10}
    Compactions:       {sum(r['compact_count'] for r in runs):>10}
""".lstrip("\n"))

    # ── 工具分布 ──
    all_tools = Counter()
    for r in runs:
        all_tools.update(r["tool_types"])
    total_tc = sum(all_tools.values()) or 1
    print(f"  Tool Distribution")
    print(f"    {'Tool':<18} {'Calls':>6}  {'%':>7}")
    print(f"    {'-'*18} {'-'*6}  {'-'*7}")
    for tool, cnt in all_tools.most_common():
        print(f"    {tool:<18} {cnt:>6}  {cnt/total_tc*100:>6.1f}%")

    # ── 每 run 明细 ──
    print(f"\n  Per-Run Detail")
    print(f"    {'-'*50}")
    for i, r in enumerate(runs, 1):
        goal_short = r["goal"][:70] + "..." if len(r["goal"]) > 70 else r["goal"]
        st = "✅" if r["completed"] else ("❌" if r["tool_errors"] else "✓")
        extra = ""
        if r["tool_errors"]:
            extra += f"  ❌ errors:{r['tool_errors']}"
        if r["compact_count"]:
            extra += f"  📦 compact:{r['compact_count']}x (saved {r['compact_saved']:,})"
        print(f"    [{i}] {r['file']:<45} {st}")
        print(f"         Goal: {goal_short}")
        print(f"         Rounds: {r['total_rounds']}  Tokens: {r['total_tokens']:>8,}  "
              f"Tools: {_fmt_tools(r['tool_types'])}{extra}")

    # ── 趋势 ──
    print(f"""
  Token Trend (last round ctx% ≈ context utilization)
""")
    print(f"    {'Run':<5} {'R':<3}  {'tokens-in':>10} {'tokens-out':>10}  finish")
    print(f"    {'-'*5} {'-'*3}  {'-'*10} {'-'*10}  {'-'*10}")
    for i, r in enumerate(runs, 1):
        rd = r["rounds_detail"]
        for j, a in enumerate(rd):
            run_label = f"R{i}" if j == 0 else ""
            print(f"    {run_label:<5} {a['round']:<3}  "
                  f"{a['tokens_in']:>10,} {a['tokens_out']:>10,}  "
                  f"{a['finish_reason']:<10}")
    print()


def _fmt_tools(tool_dict):
    return ", ".join(f"{t}({c})" for t, c in tool_dict.items())


# ── JSON 输出 ─────────────────────────────────────────

def json_report(runs):
    print(json.dumps(runs, indent=2, ensure_ascii=False))


# ── CLI ───────────────────────────────────────────────

def main():
    fmt = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("--format", "-f") else "table"
    if fmt in ("json", "--format", "-f"):
        fmt = "json"
    runs = load_traces()
    if fmt == "json":
        json_report(runs)
    else:
        print_report(runs)


if __name__ == "__main__":
    main()
