#!/usr/bin/env python3
"""Test micro_compact() —— 不修改主文件，只验证 micro_compact 的行为是否正确。"""

import sys
import os
import time
import json

# 将项目根目录加到 sys.path，以便 import mangopi_cli 中的 ContextManager
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangopi_cli import ContextManager

# ── 辅助函数 ──────────────────────────────────────────────

def make_tool_msg(tool_call_id, tool_name, content, hours_ago=0):
    """构造一条带 ts 的 tool 消息，hours_ago=0 表示刚产生，hours_ago=7 表示 7 小时前。"""
    ts = int(time.time()) - hours_ago * 3600
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "content": content,
        "ts": ts,
    }

def make_user_msg(content, hours_ago=0):
    ts = int(time.time()) - hours_ago * 3600
    return {"role": "user", "content": content, "ts": ts}

def make_assistant_msg(content, hours_ago=0):
    ts = int(time.time()) - hours_ago * 3600
    return {"role": "assistant", "content": content, "ts": ts}

def long_text(n_chars=500):
    """生成长度为 n_chars 的文本（确保 >200 tokens 估算）。"""
    return "x" * n_chars

# ── 测试用例 ──────────────────────────────────────────────

passed = 0
failed = 0

def t(name, setup_fn, verify_fn):
    """运行一个测试用例。"""
    global passed, failed
    ctx = ContextManager()
    setup_fn(ctx)
    ctx.micro_compact()
    try:
        verify_fn(ctx)
        passed += 1
        print(f"  ✓ {name}")
    except AssertionError as e:
        failed += 1
        print(f"  ✗ {name}  FAIL: {e}")
    except Exception as e:
        failed += 1
        print(f"  ✗ {name}  ERROR: {e}")


# ── 1. 旧 tool 消息被压缩 ─────────────────────────────────

def test_01_old_tool_gets_compacted():
    def setup(ctx):
        ctx.messages = [
            make_tool_msg("c1", "read", long_text(2000), hours_ago=7),
        ]

    def verify(ctx):
        m = ctx.messages[0]
        assert m["content"].endswith("<compacted>"), "旧 tool 应该被压缩"
        assert len(m["content"]) < 500, f"压缩后内容应该明显变短，实际: {len(m['content'])}"

    t("旧 tool 被压缩", setup, verify)


# ── 2. 新 tool 消息不被压缩 ────────────────────────────────

def test_02_new_tool_not_compacted():
    def setup(ctx):
        ctx.messages = [
            make_tool_msg("c1", "read", long_text(2000), hours_ago=1),
        ]

    def verify(ctx):
        m = ctx.messages[0]
        assert not m["content"].endswith("<compacted>"), "新 tool 不应该被压缩"
        assert len(m["content"]) == 2000, "新 tool 内容不应该变化"

    t("新 tool 不被压缩", setup, verify)


# ── 3. 边界: 刚好 6 小时的 tool ─────────────────────────────

def test_03_exactly_6_hours():
    def setup(ctx):
        ctx.messages = [
            make_tool_msg("c1", "read", long_text(2000), hours_ago=6),
        ]

    def verify(ctx):
        m = ctx.messages[0]
        # 6 小时 = 21600 秒，条件为 now - ts < max_age_seconds
        # 恰好 6 小时时: now - ts == 21600, 不小于 21600，所以会被压缩
        assert m["content"].endswith("<compacted>"), "恰好 6 小时应该被压缩"

    t("恰好 6 小时被压缩", setup, verify)


# ── 4. 边界: 不足 6 小时 (5.9h) ────────────────────────────

def test_04_just_under_6_hours():
    def setup(ctx):
        # 5.9 小时 —— 还在窗口内
        ctx.messages = [
            make_tool_msg("c1", "read", long_text(2000), hours_ago=5.9),
        ]

    def verify(ctx):
        m = ctx.messages[0]
        assert not m["content"].endswith("<compacted>"), "5.9h 不应该被压缩"

    t("不足 6h 不压缩", setup, verify)


# ── 5. user 消息不被压缩 ──────────────────────────────────

def test_05_user_not_tool():
    def setup(ctx):
        ctx.messages = [
            make_user_msg(long_text(2000), hours_ago=10),
        ]

    def verify(ctx):
        m = ctx.messages[0]
        assert not m["content"].endswith("<compacted>"), "user 消息不应该被压缩"

    t("user 消息不被压缩", setup, verify)


# ── 6. assistant 消息不被压缩 ──────────────────────────────

def test_06_assistant_not_tool():
    def setup(ctx):
        ctx.messages = [
            make_assistant_msg(long_text(2000), hours_ago=10),
        ]

    def verify(ctx):
        m = ctx.messages[0]
        assert not m["content"].endswith("<compacted>"), "assistant 消息不应该被压缩"

    t("assistant 消息不被压缩", setup, verify)


# ── 7. 白名单工具不被压缩 ──────────────────────────────────

def test_07_whitelist_tool_not_compacted():
    def setup(ctx):
        ctx.messages = [
            make_tool_msg("c1", "attempt_completion", long_text(2000), hours_ago=10),
        ]

    def verify(ctx):
        m = ctx.messages[0]
        assert not m["content"].endswith("<compacted>"), "attempt_completion 不应该被压缩"

    t("白名单 attempt_completion 不压缩", setup, verify)


# ── 8. 已压缩的不重复压缩 ──────────────────────────────────

def test_08_already_compacted_skipped():
    def setup(ctx):
        ctx.messages = [
            make_tool_msg("c1", "read", f"{long_text(200)}<compacted>", hours_ago=10),
            make_tool_msg("c2", "bash", long_text(2000), hours_ago=10),
        ]

    def verify(ctx):
        m0 = ctx.messages[0]
        m1 = ctx.messages[1]
        # 第一条以 <compacted> 结尾，不应再变
        assert m0["content"] == long_text(200) + "<compacted>", "已压缩的不应该变化"
        # 第二条应该被压缩
        assert m1["content"].endswith("<compacted>"), "未压缩的应该被压缩"

    t("已压缩的跳过", setup, verify)


# ── 9. 内容太小不压缩 (min_tokens=200) ────────────────────

def test_09_small_content_not_compacted():
    def setup(ctx):
        # 10 个字符，token 估算远小于 200
        ctx.messages = [
            make_tool_msg("c1", "read", "tiny text", hours_ago=10),
        ]

    def verify(ctx):
        m = ctx.messages[0]
        assert m["content"] == "tiny text", "小内容不应该被压缩"

    t("小内容不压缩", setup, verify)


# ── 10. summary 不比原内容短则不压缩 ───────────────────────

def test_10_summary_not_smaller():
    def setup(ctx):
        # 刚好在 160 字符以内的内容，compact_text 不会裁剪
        text = "A" * 160  # head=80 + tail=80 = 160，不会裁剪
        ctx.messages = [
            make_tool_msg("c1", "read", text, hours_ago=10),
        ]

    def verify(ctx):
        m = ctx.messages[0]
        # summary == 原文 => estimated_tokens 相等，不满足 < 条件，不压缩
        assert not m["content"].endswith("<compacted>"), "summary 不比原文短不应该压缩"

    t("summary 不更短时不压缩", setup, verify)


# ── 11. 混合消息: 新旧 tool + user + assistant ─────────────

def test_11_mixed_messages():
    def setup(ctx):
        ctx.messages = [
            make_tool_msg("c1", "read", long_text(2000), hours_ago=10),   # 旧 tool → 压缩
            make_user_msg("hello user", hours_ago=10),                     # user → 跳过
            make_tool_msg("c2", "bash", long_text(2000), hours_ago=1),    # 新 tool → 不压缩
            make_assistant_msg(long_text(2000), hours_ago=10),             # assistant → 跳过
            make_tool_msg("c3", "read", long_text(2000), hours_ago=12),   # 旧 tool → 压缩
        ]

    def verify(ctx):
        assert ctx.messages[0]["content"].endswith("<compacted>"), "c1 旧tool 应该压缩"
        assert not ctx.messages[1]["content"].endswith("<compacted>"), "user 不压缩"
        assert not ctx.messages[2]["content"].endswith("<compacted>"), "c2 新tool 不压缩"
        assert not ctx.messages[3]["content"].endswith("<compacted>"), "assistant 不压缩"
        assert ctx.messages[4]["content"].endswith("<compacted>"), "c3 旧tool 应该压缩"

    t("混合消息正确筛选", setup, verify)


# ── 12. 无消息不应该报错 ──────────────────────────────────

def test_12_empty_messages():
    def setup(ctx):
        ctx.messages = []

    def verify(ctx):
        assert len(ctx.messages) == 0, "空列表不应该报错"

    t("空消息不报错", setup, verify)


# ── 13. 没有 ts 字段的旧消息 ───────────────────────────────

def test_13_no_ts_field():
    def setup(ctx):
        m = {"role": "tool", "tool_call_id": "c1", "tool_name": "read", "content": "some content"}
        ctx.messages = [m]

    def verify(ctx):
        # 没有 ts → m.get("ts", now) 取 now → now - now = 0 < max_age → 不压缩
        m = ctx.messages[0]
        assert not m["content"].endswith("<compacted>"), "无 ts 字段的不应该被压缩（当作新消息）"

    t("无 ts 字段不压缩", setup, verify)


# ── 14. 压缩后的格式正确 ──────────────────────────────────

def test_14_compacted_format():
    def setup(ctx):
        ctx.messages = [
            make_tool_msg("c1", "read", long_text(2000), hours_ago=10),
        ]

    def verify(ctx):
        m = ctx.messages[0]
        assert m["content"].endswith("<compacted>"), "应该以 <compacted> 结尾"
        # compact_text 的格式: head(80) + "\n...\n" + tail(80)
        assert "\n...\n" in m["content"], "应该包含 head...tail 格式"

    t("压缩格式正确", setup, verify)


# ── 15. 空 content 不被压缩 ───────────────────────────────

def test_15_empty_content():
    def setup(ctx):
        ctx.messages = [
            make_tool_msg("c1", "read", "", hours_ago=10),
        ]

    def verify(ctx):
        m = ctx.messages[0]
        assert m["content"] == "", "空内容不应该被压缩"

    t("空 content 不压缩", setup, verify)


# ── 16. 只有空白字符的 content ────────────────────────────

def test_16_whitespace_content():
    def setup(ctx):
        ctx.messages = [
            make_tool_msg("c1", "read", "   \n  \t  ", hours_ago=10),
        ]

    def verify(ctx):
        m = ctx.messages[0]
        # compact_text 对 whitespace-only 做 strip 后为空
        assert not m["content"].endswith("<compacted>"), "纯空白 content 不应该被压缩（summary 为空）"

    t("纯空白 content 不压缩", setup, verify)


# ── 17. 多个不同年龄的 tool 消息 ──────────────────────────

def test_17_multiple_ages():
    def setup(ctx):
        ctx.messages = [
            make_tool_msg("c1", "read", long_text(2000), hours_ago=20),   # 压缩
            make_tool_msg("c2", "bash", long_text(2000), hours_ago=10),   # 压缩
            make_tool_msg("c3", "grep", long_text(2000), hours_ago=3),    # 不压缩
            make_tool_msg("c4", "read", long_text(2000), hours_ago=1),    # 不压缩
            make_tool_msg("c5", "bash", long_text(2000), hours_ago=8),    # 压缩
        ]

    def verify(ctx):
        assert ctx.messages[0]["content"].endswith("<compacted>"), "20h → 压缩"
        assert ctx.messages[1]["content"].endswith("<compacted>"), "10h → 压缩"
        assert not ctx.messages[2]["content"].endswith("<compacted>"), "3h → 不压缩"
        assert not ctx.messages[3]["content"].endswith("<compacted>"), "1h → 不压缩"
        assert ctx.messages[4]["content"].endswith("<compacted>"), "8h → 压缩"

    t("多年龄精确筛选", setup, verify)


# ── 18. 内容刚好等于 min_tokens 阈值 ──────────────────────

def test_18_at_min_token_threshold():
    def setup(ctx):
        # 804 字节 content → estimated_tokens ≈ 804/4+4 = 205 (略超 200)
        text = "A" * 800
        ctx.messages = [
            make_tool_msg("c1", "read", text, hours_ago=10),
        ]

    def verify(ctx):
        m = ctx.messages[0]
        assert m["content"].endswith("<compacted>"), "刚超 200 tokens 应该压缩"

    t("刚好超 min_tokens 阈值压缩", setup, verify)


# ── 19. 被压缩后再次调用 micro_compact 不变 ──────────────

def test_19_idempotent():
    def setup(ctx):
        ctx.messages = [
            make_tool_msg("c1", "read", long_text(2000), hours_ago=10),
        ]

    def verify(ctx):
        # 第一次压缩
        after_first = ctx.messages[0]["content"]
        # 第二次压缩
        ctx.micro_compact()
        after_second = ctx.messages[0]["content"]
        assert after_first == after_second, "幂等: 第二次压缩不应该再变化"

    t("幂等: 二次压缩不变", setup, verify)


# ── 20. 没有 tool 消息时不报错 ─────────────────────────────

def test_20_no_tool_messages():
    def setup(ctx):
        ctx.messages = [
            make_user_msg("hello", hours_ago=10),
            make_assistant_msg("hi there", hours_ago=10),
            {"role": "system", "content": "you are a bot"},
        ]

    def verify(ctx):
        # 所有消息原封不动
        assert ctx.messages[0]["content"] == "hello"
        assert ctx.messages[1]["content"] == "hi there"
        assert ctx.messages[2]["content"] == "you are a bot"

    t("无 tool 消息不报错", setup, verify)


def test_21_real_scenario_with_output():
    """
    模拟一个真实的编程助手会话 ——
    用户先查代码、再搜关键字、读文件、跑命令。
    部分消息 > 6h，部分 < 6h。
    输出压缩前后的每条 tool 消息对比。
    """
    ctx = ContextManager()

    # ── 构造真实消息 ──

    ts_old = int(time.time()) - 8 * 3600    # 8 小时前
    ts_new = int(time.time()) - 2 * 3600    # 2 小时前

    ctx.messages = [
        # system prompt
        {"role": "system", "content": "You are a helpful coding assistant."},

        # ── Turn 1 (旧) ──
        {"role": "user", "content": "分析项目中的搜索功能", "ts": ts_old},
        {"role": "assistant", "content": "我来搜索相关代码。",
         "reasoning_content": "用户想了解项目中的搜索功能，需要 grep 代码库。",
         "tool_calls": [
             {"id": "call_a1", "type": "function",
              "function": {"name": "grep", "arguments": '{"pat": "def search|def grep|def find"}'}}
         ], "ts": ts_old},
        {"role": "tool", "tool_call_id": "call_a1", "tool_name": "grep",
         "content": (
             "src/search.py:42:def search_files(pattern, path):\n"
             + "src/search.py:58:def grep_content(pat, glob_pat):\n"
             + "src/finder.py:12:def find_matches(query, files):\n"
             + ("extra padding to reach >200 tokens " * 30)
         ), "ts": ts_old},
        {"role": "assistant",
         "content": "找到了 3 个搜索相关函数：search_files、grep_content、find_matches。需要进一步阅读源码。",
         "reasoning_content": "搜索结果清晰，接下来读具体实现。",
         "ts": ts_old},

        # ── Turn 2 (旧) ──
        {"role": "user", "content": "读取 src/search.py 的完整实现", "ts": ts_old},
        {"role": "assistant", "content": "",
         "tool_calls": [
             {"id": "call_a2", "type": "function",
              "function": {"name": "read", "arguments": '{"path": "src/search.py"}'}}
         ], "ts": ts_old},
        {"role": "tool", "tool_call_id": "call_a2", "tool_name": "read",
         "content": (
             '"""Search module for the project.\n\n'
             'Provides file and content search capabilities.\n'
             '"""\n\n'
             'import os\nimport re\nfrom pathlib import Path\n\n\n'
             'def search_files(pattern: str, path: str = ".") -> list:\n'
             '    """Glob-based file search."""\n'
             '    import glob\n'
             '    return glob.glob(f"{path}/**/{pattern}", recursive=True)\n\n\n'
             'def grep_content(pat: str, glob_pat: str = "**/*") -> list:\n'
             '    """Search content across files."""\n'
             '    results = []\n'
             '    for filepath in glob.glob(glob_pat, recursive=True):\n'
             '        if not os.path.isfile(filepath):\n'
             '            continue\n'
             '        with open(filepath) as f:\n'
             '            for lineno, line in enumerate(f, 1):\n'
             '                if re.search(pat, line):\n'
             '                    results.append(f"{filepath}:{lineno}:{line}")\n'
             '    return results\n'
             + ("\n" + "x" * 3000)
         ), "ts": ts_old},
        {"role": "assistant",
         "content": "已读取完整实现。search_files 使用 glob 匹配文件，grep_content 逐行正则搜索。",
         "reasoning_content": "代码结构清晰，两个核心函数职责分离良好。",
         "ts": ts_old},

        # ── Turn 3 (旧, 但 attempt_completion 在白名单) ──
        {"role": "assistant", "content": "完成分析。",
         "tool_calls": [
             {"id": "call_a3", "type": "function",
              "function": {"name": "attempt_completion", "arguments": '{"result": "总结完成"}'}}
         ], "ts": ts_old},
        {"role": "tool", "tool_call_id": "call_a3", "tool_name": "attempt_completion",
         "content": "任务已完成。\n" + ("summary details " * 200),
         "ts": ts_old},

        # ── Turn 4 (新) ──
        {"role": "user", "content": "运行一下测试看看有没有问题", "ts": ts_new},
        {"role": "assistant", "content": "",
         "tool_calls": [
             {"id": "call_a4", "type": "function",
              "function": {"name": "bash", "arguments": '{"cmd": "python -m pytest test/ -v"}'}}
         ], "ts": ts_new},
        {"role": "tool", "tool_call_id": "call_a4", "tool_name": "bash",
         "content": (
             "============================= test session starts ==============================\n"
             "collected 20 items\n\n"
             "test/test_search.py::test_find_files PASSED                           [ 25%]\n"
             "test/test_search.py::test_grep_content PASSED                        [ 50%]\n"
             "test/test_utils.py::test_format_output PASSED                        [ 75%]\n"
             "test/test_utils.py::test_error_handling PASSED                       [100%]\n\n"
             "============================== 20 passed in 0.45s ==============================="
             + ("\n" + "y" * 1000)
         ), "ts": ts_new},
        {"role": "assistant",
         "content": "全部 20 个测试通过 ✅",
         "reasoning_content": "测试结果良好，无需修改。",
         "ts": ts_new},

        # ── Turn 5 (新, 小 tool 结果) ──
        {"role": "user", "content": "当前哪个分支？", "ts": ts_new},
        {"role": "assistant", "content": "",
         "tool_calls": [
             {"id": "call_a5", "type": "function",
              "function": {"name": "bash", "arguments": '{"cmd": "git branch --show-current"}'}}
         ], "ts": ts_new},
        {"role": "tool", "tool_call_id": "call_a5", "tool_name": "bash",
         "content": "main\n", "ts": ts_new},
        {"role": "assistant", "content": "当前在 main 分支。", "ts": ts_new},
    ]

    # ── 压缩前统计 ──
    tool_msgs_before = [m for m in ctx.messages if m.get("role") == "tool"]
    total_tokens_before = ctx.total_tokens()
    total_messages_before = len(ctx.messages)

    # ── 快照每条 tool 压缩前的模样 ──
    before_snapshots = []
    for m in tool_msgs_before:
        before_snapshots.append({
            "tool_name": m.get("tool_name"),
            "tool_call_id": m.get("tool_call_id"),
            "content_len": len(m.get("content", "")),
            "content_tokens": ctx.estimated_tokens({"content": m.get("content", "")}),
            "hours_ago": (int(time.time()) - m.get("ts", int(time.time()))) / 3600,
            "ends_compacted": m.get("content", "").endswith("<compacted>"),
        })

    # ── 执行压缩 ──
    ctx.micro_compact()

    # ── 压缩后统计 ──
    tool_msgs_after = [m for m in ctx.messages if m.get("role") == "tool"]
    total_tokens_after = ctx.total_tokens()
    total_messages_after = len(ctx.messages)

    # ── 快照每条 tool 压缩后的模样 ──
    after_snapshots = []
    for m in tool_msgs_after:
        after_snapshots.append({
            "tool_name": m.get("tool_name"),
            "content_len": len(m.get("content", "")),
            "content_tokens": ctx.estimated_tokens({"content": m.get("content", "")}),
            "ends_compacted": m.get("content", "").endswith("<compacted>"),
            "preview": m.get("content", "")[:120].replace("\n", "\\n"),
        })

    # ── 输出结果 ──
    sep = "=" * 72
    print(f"\n{sep}")
    print("  真实环境模拟 — micro_compact 压缩前后对比")
    print(f"{sep}")

    print(f"\n📊 总体统计:")
    print(f"  消息总数: {total_messages_before} → {total_messages_after} (不变)")
    print(f"  总 tokens: {total_tokens_before} → {total_tokens_after} "
          f"(-{total_tokens_before - total_tokens_after}, "
          f"{(total_tokens_before - total_tokens_after) / max(total_tokens_before, 1) * 100:.0f}%)")

    print(f"\n📋 Tool 消息明细 (共 {len(tool_msgs_before)} 条):")
    print(f"  {'工具名':<20} {'调用ID':<10} {'时龄':>6} {'压缩前token':>10} {'压缩后token':>10} {'变化':>6}")
    print(f"  {'-'*20} {'-'*10} {'-'*6} {'-'*10} {'-'*10} {'-'*6}")

    for b, a in zip(before_snapshots, after_snapshots):
        status = "✓ 已压" if a["ends_compacted"] else "✗ 保留"
        delta = a["content_tokens"] - b["content_tokens"]
        delta_str = f"{delta:+d}" if delta != 0 else "  0"
        print(f"  {b['tool_name']:<20} {b['tool_call_id']:<10} {b['hours_ago']:>5.0f}h   "
              f"{b['content_tokens']:>8}   {a['content_tokens']:>8}   {delta_str:>6}  {status}")

    print(f"\n📝 压缩后的内容预览:")
    for snap in after_snapshots:
        marker = " [压缩]" if snap["ends_compacted"] else " [保留]"
        print(f"  {snap['tool_name']}({snap['content_tokens']}t){marker}: {snap['preview']}...")

    # ── 断言 (消息索引: 0=system, 1=u, 2=a, 3=tool, 4=a, 5=u, 6=a, 7=tool, 8=a, 9=a, 10=tool, 11=u, 12=a, 13=tool, 14=a, 15=u, 16=a, 17=tool, 18=a) ──
    # Turn 1 grep (旧, >200t) → 压缩
    assert ctx.messages[3]["content"].endswith("<compacted>"), "Turn1 grep 应该压缩"
    # Turn 2 read (旧, >200t) → 压缩
    assert ctx.messages[7]["content"].endswith("<compacted>"), "Turn2 read 应该压缩"
    # Turn 3 attempt_completion (白名单) → 不压缩
    assert not ctx.messages[10]["content"].endswith("<compacted>"), "attempt_completion 白名单不压缩"
    # Turn 4 bash (新) → 不压缩
    assert not ctx.messages[13]["content"].endswith("<compacted>"), "Turn4 bash 新消息不压缩"
    # Turn 5 bash (小) → 不压缩
    assert not ctx.messages[17]["content"].endswith("<compacted>"), "Turn5 bash 小内容不压缩"
    # Token 确实减少了
    assert total_tokens_after < total_tokens_before, "压缩后 tokens 应该减少"

    msg = (
        f"  压缩前: {total_tokens_before}t, 压缩后: {total_tokens_after}t, "
        f"减少: {total_tokens_before - total_tokens_after}t"
    )
    global passed
    passed += 1
    print(f'  ✓ 真实环境模拟 — 压缩前后对比测试通过')
    assert True, msg  # 通过

# ── 入口 ──────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== micro_compact 单元测试 ===\n")
    # 执行所有 test_* 函数
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()

    print(f"\n{'='*40}")
    print(f"通过: {passed}  失败: {failed}  总计: {passed+failed}")
    if failed:
        sys.exit(1)

# ── 21. 真实环境模拟: 多轮对话 + 压缩前后对比 ──────────────

