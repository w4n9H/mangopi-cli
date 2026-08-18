"""Shipped preset — minimal: 极简基准模式 (对齐 DeepSeek Harness minimal).
Shipped preset — minimal: benchmark mode (mirrors DeepSeek Harness minimal).

只保留 bash + edit 两个工具, System Prompt 压缩为一句话. 剥离所有外围增强
(安全规则/编码规则/工具指引/技能/记忆/环境), 纯粹测量模型自主规划、代码修改
和终端操作能力.
Only bash + edit, one-line system prompt. Strips all peripheral enhancements
(safety/rules/tool guidance/skills/memory/environment) to purely measure the
model's autonomous planning, code editing and terminal capability.

目录结构 / Layout:
  ~/.mangocli/presets/minimal/
  ├── conf.py              # 本文件: 总配置 (keep_tools 白名单 + prompt_overrides)
  └── extensions/          # 该 preset 的扩展 (tools/prompt_sections/entry_points/on 订阅)

启用 / Enable: 将本目录复制到 ~/.mangocli/presets/ 后, 以 `MANGO_PRESET=minimal` 启动
mangopi-cli.
Copy this directory into ~/.mangocli/presets/ and start with `MANGO_PRESET=minimal`.

字段 / Fields:
  * keep_tools  — 白名单: TOOLS 只剩名单内工具 (内置 + 扩展统一过滤), 逆操作登记
                  __preset__ 槽位, unload_source("__preset__") 可恢复;
                  whitelist: TOOLS keeps only listed tools (built-in + extensions),
                  inverse registered under __preset__, unload_source("__preset__") restores.
  * prompt_overrides — prompt 覆盖: base 替换 base_intro 段, clear_sections 删除段;
                  prompt overrides: base replaces the base_intro section,
                  clear_sections removes sections.
"""
preset = {
    "name": "minimal",
    "description": "Benchmark mode: bash + edit only, one-line system prompt",
    "keep_tools": [
        "bash",
        "edit",
    ],
    "prompt_overrides": {
        "base": "You are a helpful software engineer assistant.",
        "clear_sections": [
            "safety",
            "builtin_rules",
            "tool_guidance",
            "skills_guidance",
            "memory",
            "environment",
        ],
    },
}
