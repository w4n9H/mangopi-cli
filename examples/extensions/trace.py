"""Shipped extension — trace: 会话级事件流 JSON 落盘 (替代核心 MANGO_TRACE, v0.1.49 插件化).

按需启用:
  * 复制/软链本文件到 preset 扩展目录: ~/.mangocli/presets/<name>/extensions/ (需设 MANGO_PRESET=<name>)

订阅事件总线:
  * agent:user_input  (mode, goal, session_file, length)      -> 会话开始, 初始化事件列表
  * agent:assistant   (round, finish_reason, has_tool_calls, tool_calls_count, has_reasoning,
                       reasoning_len, content_len, model, prompt_tokens, completion_tokens)
  * agent:compact     (tokens_before, tokens_after, saved)
  * tool:before       (name, args)  /  tool:after (name, result)   -> 工具调用/结果
  * agent:end         (total_rounds)                          -> 会话结束, 落盘

输出 ~/.mangocli/traces/run_<mode>_<ts>_<rand>.json (与原 MANGO_TRACE 格式兼容).

契约: 顶层仅 `from mangopi_cli import on` (事件总线定义早于扫描点); 其余符号一律延迟导入或不用.
"""
from mangopi_cli import on

import json
import os
import time
import uuid

_TRACES_DIR = os.path.expanduser("~/.mangocli/traces")
_events = []
_meta = {}


def _start(mode, goal, session_file, length):
    global _events, _meta
    _events = [{"ts": int(time.time() * 1000), "kind": "user_input",
                "mode": mode, "goal": goal, "session_file": session_file, "length": length}]
    _meta = {"mode": mode, "goal": goal, "session_file": session_file}


def _assistant(round_no, finish_reason, has_tool_calls, tool_calls_count, has_reasoning,
               reasoning_len, content_len, model, prompt_tokens, completion_tokens):
    _events.append({"ts": int(time.time() * 1000), "kind": "assistant",
                    "round": round_no, "finish_reason": finish_reason,
                    "has_tool_calls": has_tool_calls, "tool_calls_count": tool_calls_count,
                    "has_reasoning": has_reasoning, "reasoning_len": reasoning_len,
                    "content_len": content_len, "model": model,
                    "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens})


def _compact(tokens_before, tokens_after, saved):
    _events.append({"ts": int(time.time() * 1000), "kind": "compact",
                    "tokens_before": tokens_before, "tokens_after": tokens_after, "saved": saved})


def _tool_call(name, args):
    _events.append({"ts": int(time.time() * 1000), "kind": "tool_call",
                    "name": name, "args_preview": str(args)[:150]})


def _tool_result(name, result):
    _events.append({"ts": int(time.time() * 1000), "kind": "tool_result",
                    "name": name, "success": result.get("success"),
                    "content_size": len(result.get("content") or "")})


def _end(total_rounds):
    _events.append({"ts": int(time.time() * 1000), "kind": "end", "total_rounds": total_rounds})
    os.makedirs(_TRACES_DIR, exist_ok=True)
    fname = f"run_{_meta.get('mode', 'x')}_{int(time.time())}_{uuid.uuid4().hex[:6]}.json"
    with open(os.path.join(_TRACES_DIR, fname), "w", encoding="utf-8") as f:
        f.write(json.dumps(_events, indent=2, ensure_ascii=False))
    _events.clear()
    _meta.clear()


on("agent:user_input", _start)
on("agent:assistant", _assistant)
on("agent:compact", _compact)
on("tool:before", _tool_call)
on("tool:after", _tool_result)
on("agent:end", _end)
