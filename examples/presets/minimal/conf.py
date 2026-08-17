"""Shipped preset — minimal: 只保留核心 8 工具 (无网络/无视觉/无扩展).
Shipped preset — minimal: core 8 tools only (no network, no vision, no extensions).

目录结构 / Layout:
  ~/.mangocli/presets/minimal/
  ├── conf.py              # 本文件: 总配置 (keep_tools 白名单等)
  └── extensions/          # 该 preset 的扩展 (tools/prompt_sections/entry_points/on 订阅)

启用 / Enable: 将本目录复制到 ~/.mangocli/presets/ 后, 以 `MANGO_PRESET=minimal` 启动
mangopi-cli. 无 MANGO_PRESET 时纯内置 8 工具 (无扩展目录).
Copy this directory into ~/.mangocli/presets/ and start with `MANGO_PRESET=minimal`.
Without MANGO_PRESET the CLI runs pure built-in tools (no extensions dir).

字段 / Fields:
  * keep_tools  — 白名单: TOOLS 只剩名单内工具 (内置 + 扩展统一过滤), 逆操作登记
                  __preset__ 槽位, unload_source("__preset__") 可恢复;
                  whitelist: TOOLS keeps only listed tools (built-in + extensions),
                  inverse registered under __preset__, unload_source("__preset__") restores.
  * unload_sources — 可选: 逐个可逆卸载扩展注册 (三通道), 与 keep_tools 组合使用;
                  optional: unload extension registrations (three channels), combinable.
"""
preset = {
    "name": "minimal",
    "description": "Core 8 tools only: no network, no vision, no extensions",
    "keep_tools": [
        "read",
        "write",
        "edit",
        "search",
        "grep",
        "bash",
        "use_skill",
        "attempt_completion",
    ],
}
