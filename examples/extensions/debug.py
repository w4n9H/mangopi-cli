"""Shipped extension — debug: 每次 tool 调用打印参数/结果 (stderr, 不落盘).

按需启用:
  * 复制/软链本文件到 preset 扩展目录: ~/.mangocli/presets/<name>/extensions/ (需设 MANGO_PRESET=<name>)

调试时观察每次 tool 调用的入参 (tool:before) 与结果 (tool:after/error).

契约: 顶层仅 `from mangopi_cli import on` (事件总线定义早于扫描点); print 为 stdlib, 不触碰核心符号.
"""
from mangopi_cli import on


def _before(name, args):
    print(f"[debug] tool:before {name} args={args}", flush=True)


def _after(name, result):
    print(f"[debug] tool:after {name} success={result.get('success')}", flush=True)


def _error(name, err):
    print(f"[debug] tool:error {name} err={err}", flush=True)


on("tool:before", _before)
on("tool:after", _after)
on("tool:error", _error)
