"""Shipped preset — standard: 完整 Mangopi 体验 (默认行为的显式化).
Shipped preset — standard: full Mangopi experience (default behavior, made explicit).

目录结构 / Layout:
  ~/.mangocli/presets/standard/
  ├── conf.py              # 本文件: 总配置 (keep_tools 白名单等)
  └── extensions/          # 该 preset 的扩展 (tools/prompt_sections/entry_points/on 订阅)

启用 / Enable: 将本目录复制到 ~/.mangocli/presets/ 后, 以 `MANGO_PRESET=standard` 启动
mangopi-cli. 无 MANGO_PRESET 时行为与此 preset 等价 (纯内置 7 工具 + 完整分层 prompt);
use_skill 需以 skill 扩展启用.
Copy this directory into ~/.mangocli/presets/ and start with `MANGO_PRESET=standard`.
Without MANGO_PRESET the CLI behaves the same (pure built-in 7 tools + full
layered system prompt).

字段 / Fields:
  * keep_tools  — 白名单: TOOLS 只剩名单内工具 (内置 + 扩展统一过滤);
                  whitelist: TOOLS keeps only listed tools (built-in + extensions).
  * 无 prompt_overrides — 使用 SystemPrompt 默认分层组装;
                  no prompt_overrides — SystemPrompt default layered assembly.
"""
preset = {
    "name": "standard",
    "description": "Full Mangopi experience: 7 core tools + use_skill extension, complete system prompt",
    "keep_tools": [
        "read",
        "write",
        "edit",
        "search",
        "grep",
        "bash",
        "use_skill",  # 由 skill 扩展提供; 未安装时白名单忽略该名字 (安全)
        "attempt_completion",
    ],
}
