"""Shipped extension — ratelimit: 工具调用频率告警 (滑动窗口, 软限流).

按需启用:
  * 复制/软链本文件到 preset 扩展目录: ~/.mangocli/presets/<name>/extensions/ (需设 MANGO_PRESET=<name>)

事件总线只 emit 不 bail (listener 无法中断工具执行), 故超频只能告警不能拦截;
窗口 1s, 阈值 MANGO_RATELIMIT_PER_SEC (默认 5), 超频每 5s 告警一次.

契约: 顶层仅 `from mangopi_cli import on` (事件总线定义早于扫描点); 其余符号一律延迟导入或不用.
"""
from mangopi_cli import on

import os
import time

_MAX_PER_SEC = float(os.environ.get("MANGO_RATELIMIT_PER_SEC", "5"))
_WINDOW = 1.0
_stamps = []
_last_warn = 0.0


def _check(name, args):
    global _stamps, _last_warn
    now = time.monotonic()
    _stamps = [t for t in _stamps if now - t < _WINDOW]
    if len(_stamps) >= _MAX_PER_SEC:
        if now - _last_warn > 5:
            print(f"[ratelimit] throttled: >{_MAX_PER_SEC:.0f} tools/sec", flush=True)
            _last_warn = now
        return
    _stamps.append(now)


on("tool:before", _check)
