"""Shipped extension — audit: tool 调用审计 (JSONL 落盘).

按需启用:
  * 复制/软链本文件到 preset 扩展目录: ~/.mangocli/presets/<name>/extensions/ (需设 MANGO_PRESET=<name>)

订阅事件总线的 tool:before / tool:after / tool:error, 追加写入
~/.mangocli/tool_audit.jsonl (每行一个 JSON 事件), 供事后统计成功率/频率.

契约: 顶层仅 `from mangopi_cli import on` (事件总线定义早于扫描点), 其余符号一律延迟导入或不用.
"""
from mangopi_cli import on

import json
import os
import time

_AUDIT = os.path.expanduser("~/.mangocli/tool_audit.jsonl")


def _log(ev, name, *a):
    with open(_AUDIT, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "event": ev, "name": name}) + "\n")


on("tool:before", lambda n, a: _log("before", n))
on("tool:after", lambda n, r: _log("after", n, r.get("success")))
on("tool:error", lambda n, e: _log("error", n, str(e)))
