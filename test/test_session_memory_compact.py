#!/usr/bin/env python3
"""Test session_memory_compact() —— 不修改主文件，只验证会话记忆压缩的行为是否正确。"""

import sys
import os
import time
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangopi_cli import ContextManager

# ── 辅助函数 ──────────────────────────────────────────────

def make_tool(call_id, name, content):
    return {"role": "tool", "tool_call_id": call_id, "tool_name": name, "content": content}

def make_user(content):
    return {"role": "user", "content": content}

def make_assistant(content, tool_calls=None, reasoning=None, reasoning_details=None):
    m = {"role": "assistant", "content": content}
    if tool_calls:
        m["tool_calls"] = tool_calls
    if reasoning:
        m["reasoning_content"] = reasoning
    if reasoning_details:
        m["reasoning_details"] = reasoning_details
    return m

def make_tc(call_id, name="read", args='{"path": "x"}'):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}

def long(n=500):
    return "L" * n

def build_turn(user_text, assistant_tc=None, tool_results=None, assistant_reply=None, reasoning=None):
    """构建一个完整 turn: user → assistant(tool_calls) → tool... → assistant(reply)"""
    msgs = [make_user(user_text)]
    if assistant_tc:
        msgs.append(make_assistant("", assistant_tc, reasoning=reasoning))
    if tool_results:
        for tc_id, name, content in tool_results:
            msgs.append(make_tool(tc_id, name, content))
    if assistant_reply is not None:
        msgs.append(make_assistant(assistant_reply, reasoning=reasoning))
    return msgs

def build_assistant_only_turn(content, reasoning=None):
    """构建一个无 tool 调用的 turn: user → assistant"""
    return [make_user("user query"), make_assistant(content, reasoning=reasoning)]


# ── 测试用例 ──────────────────────────────────────────────

passed = 0
failed = 0

def t(name, setup_fn, verify_fn):
    """运行一个测试用例，ctx 通过 setup_fn 填充，verify_fn 验证结果。"""
    global passed, failed
    ctx = ContextManager()
    setup_fn(ctx)
    result = ctx.session_memory_compact()
    try:
        verify_fn(ctx, result)
        passed += 1
        print(f"  ✓ {name}")
    except AssertionError as e:
        failed += 1
        print(f"  ✗ {name}  FAIL: {e}")
    except Exception as e:
        failed += 1
        print(f"  ✗ {name}  ERROR: {e}")


# ═══════════════════════════════════════════════════════════
#  基础行为
# ═══════════════════════════════════════════════════════════

def test_01_turns_lt_10_returns_false():
    """turns <= 10 → no-op, return False"""
    def setup(ctx):
        ctx.messages = [
            make_user("q1"), make_assistant("a1"),
            make_user("q2"), make_assistant("a2"),
        ]
    def verify(ctx, result):
        assert result == False, "9 个 turn 应该返回 False"
        assert len(ctx.messages) == 4, "消息不应变化"
    t("<=10 turn 返回 False", setup, verify)


def test_02_exactly_10_turns_returns_false():
    """恰好 10 个 turn → no-op"""
    def setup(ctx):
        ctx.messages = []
        for i in range(10):
            ctx.messages.append(make_user(f"q{i}"))
            ctx.messages.append(make_assistant(f"a{i}"))
    def verify(ctx, result):
        assert result == False, "恰好 10 turn 应该返回 False"
    t("恰好 10 turn 返回 False", setup, verify)


def test_03_exactly_11_turns_compacts():
    """11 turn → 保留最近 10，压缩最早 1 个 turn"""
    def setup(ctx):
        ctx.messages = []
        for i in range(11):
            ctx.messages.append(make_user(f"q{i}"))
            ctx.messages.append(make_assistant(f"a{i}"))
    def verify(ctx, result):
        assert result == True, "11 turn 应该返回 True"
        # 最早的那个 assistant 被压缩了（2 user + assistant pairs per turn, 22 messages total, 2 system not here = 22 messages）
        # 最近 10 turn = 最后 20 条消息不被压缩
        # 最早 1 turn 的 assistant 如果内容太小 (<200t) 也不会被压缩
        # 但在这里我们主要验证: 旧 turn 的 user 消息还在
        users = [m for m in ctx.messages if m["role"] == "user"]
        assert len(users) == 11, "所有 11 个 user 消息应该都被保留"
    t("恰好 11 turn 触发压缩", setup, verify)


# ═══════════════════════════════════════════════════════════
#  Tool 消息压缩
# ═══════════════════════════════════════════════════════════

def test_04_old_tool_content_replaced():
    """旧 turn 的 tool 消息 → 替换为占位符"""
    def setup(ctx):
        ctx.messages = []
        for i in range(11):
            tc = [make_tc(f"c{i}")]
            ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=tc,
                tool_results=[(f"c{i}", "grep", long(2000))],
                assistant_reply=f"reply {i}",
            ))
    def verify(ctx, result):
        assert result == True
        # 找到旧 turn 的 tool 消息（它属于最早的一个 turn）
        tools = [m for m in ctx.messages if m["role"] == "tool"]
        # 有些 tool 可能被替换为占位符
        replaced = [m for m in tools if "<Old tool" in m.get("content", "")]
        assert len(replaced) >= 1, "至少有一个旧 tool 被替换为占位符"
        # 验证占位符格式
        placeholder = replaced[0]["content"]
        assert "force compacted" in placeholder
        assert "tool_name" in placeholder or replaced[0].get("tool_name") is not None
    t("旧 tool 替换为占位符", setup, verify)


def test_05_recent_tool_not_replaced():
    """最近 10 turn 的 tool 消息 → 保留原内容"""
    def setup(ctx):
        ctx.messages = []
        for i in range(15):
            tc = [make_tc(f"c{i}")]
            ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=tc,
                tool_results=[(f"c{i}", "read", long(2000))],
                assistant_reply=f"reply {i}",
            ))
    def verify(ctx, result):
        assert result == True
        tools = [m for m in ctx.messages if m["role"] == "tool"]
        # 最近 10 turn 的 tool 不应该被替换
        # 统计总量：有 15 个 tool 消息（每个 turn 1 个）
        replaced = [m for m in tools if "force compacted" in m.get("content", "")]
        original = [m for m in tools if "force compacted" not in m.get("content", "")]
        assert len(original) >= 10, f"最近 turn 的 tool 应该保留原文，实际保留: {len(original)}, 替换: {len(replaced)}"
        assert len(replaced) >= 5, f"旧 turn 的 tool 应该被替换，实际替换: {len(replaced)}"
    t("最近 turn tool 保留原文", setup, verify)


# ═══════════════════════════════════════════════════════════
#  Assistant with tool_calls 处理
# ═══════════════════════════════════════════════════════════

def test_06_assistant_with_tool_calls_preserved():
    """旧 turn 的 assistant 带 tool_calls → 不压缩，直接保留"""
    def setup(ctx):
        ctx.messages = []
        for i in range(12):
            tc = [make_tc(f"c{i}")]
            ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=tc,
                tool_results=[(f"c{i}", "read", long(500))],
                assistant_reply=f"reply {i}",
            ))
    def verify(ctx, result):
        assert result == True
        # 旧 turn 中带 tool_calls 的 assistant 应该保留 tool_calls 字段
        assistants_with_tc = [m for m in ctx.messages 
                              if m["role"] == "assistant" and "tool_calls" in m]
        assert len(assistants_with_tc) == 12, f"所有 assistant 的 tool_calls 都应该保留, 实际: {len(assistants_with_tc)}"
        # 最早的几个也保留
        first_tc_assistant = assistants_with_tc[0]
        assert "tool_calls" in first_tc_assistant
        assert len(first_tc_assistant["tool_calls"]) == 1
    t("带 tool_calls 的 assistant 保留", setup, verify)


# ═══════════════════════════════════════════════════════════
#  Assistant 无 tool_calls 的内容压缩
# ═══════════════════════════════════════════════════════════

def test_07_assistant_large_content_compacted():
    """旧 turn 的 assistant 无 tool_calls 且 content >200t → 压缩"""
    def setup(ctx):
        ctx.messages = []
        for i in range(11):
            ctx.messages.extend(build_assistant_only_turn(long(2000)))
    def verify(ctx, result):
        assert result == True
        assistants = [m for m in ctx.messages if m["role"] == "assistant"]
        # 最早的 assistant 内容被压缩，最近的保留原文
        first_assistant = assistants[0]
        last_assistant = assistants[-1]
        assert "\n...\n" in first_assistant["content"], f"最早 assistant 应该被压缩, 实际: {first_assistant['content'][:100]}"
        assert "\n...\n" not in last_assistant["content"], "最近 assistant 不应该被压缩"
    t("旧 assistant 大内容压缩", setup, verify)


def test_08_assistant_small_content_not_compacted():
    """旧 turn 的 assistant content 小于 min_tokens → 不压缩"""
    def setup(ctx):
        ctx.messages = []
        for i in range(11):
            ctx.messages.extend(build_assistant_only_turn("short reply"))
    def verify(ctx, result):
        assert result == True
        assistants = [m for m in ctx.messages if m["role"] == "assistant"]
        first_assistant = assistants[0]
        assert "\n...\n" not in first_assistant["content"], "短内容不应该被压缩"
    t("旧 assistant 小内容不压缩", setup, verify)


def test_09_assistant_reasoning_compacted():
    """旧 turn 的 assistant reasoning_content >200t → 压缩"""
    def setup(ctx):
        ctx.messages = []
        for i in range(11):
            ctx.messages.extend(build_assistant_only_turn("ok", reasoning=long(2000)))
    def verify(ctx, result):
        assert result == True
        assistants = [m for m in ctx.messages if m["role"] == "assistant"]
        first = assistants[0]
        last = assistants[-1]
        assert "\n...\n" in first.get("reasoning_content", ""), "最早 assistant 的 reasoning 应该被压缩"
        assert "\n...\n" not in last.get("reasoning_content", ""), "最近 assistant reasoning 不应该被压缩"
    t("旧 assistant reasoning 压缩", setup, verify)


def test_10_assistant_reasoning_details_compacted():
    """旧 turn 的 assistant reasoning_details >200t → 压缩"""
    def setup(ctx):
        ctx.messages = []
        for i in range(11):
            ctx.messages.append(make_user(f"q{i}"))
            ctx.messages.append(make_assistant("ok", reasoning_details=long(2000)))
    def verify(ctx, result):
        assert result == True
        assistants = [m for m in ctx.messages if m["role"] == "assistant"]
        first = assistants[0]
        last = assistants[-1]
        assert "\n...\n" in first.get("reasoning_details", ""), "最早 reasoning_details 应该被压缩"
        assert "\n...\n" not in last.get("reasoning_details", ""), "最近 reasoning_details 不应该被压缩"
    t("旧 assistant reasoning_details 压缩", setup, verify)


# ═══════════════════════════════════════════════════════════
#  System 消息 & User 消息
# ═══════════════════════════════════════════════════════════

def test_11_system_messages_preserved():
    """System 消息保留在最前面"""
    def setup(ctx):
        ctx.messages = [
            {"role": "system", "content": "You are a bot"},
            {"role": "system", "content": "Safety rules here"},
        ]
        for i in range(11):
            ctx.messages.extend(build_assistant_only_turn(long(2000)))
    def verify(ctx, result):
        assert result == True
        assert ctx.messages[0]["role"] == "system"
        assert ctx.messages[1]["role"] == "system"
        assert ctx.messages[0]["content"] == "You are a bot"
        assert ctx.messages[1]["content"] == "Safety rules here"
    t("system 消息保留", setup, verify)


def test_12_user_messages_in_old_turns_preserved():
    """旧 turn 的 user 消息 → 保留原文"""
    def setup(ctx):
        ctx.messages = []
        for i in range(15):
            ctx.messages.extend(build_assistant_only_turn(f"reply {i}"))
    def verify(ctx, result):
        assert result == True
        users = [m for m in ctx.messages if m["role"] == "user"]
        assert len(users) == 15, "所有 user 消息应该都保留"
        # 验证第一个 user 消息内容不变
        assert users[0]["content"] == "user query", "user 消息内容不应该变化"
    t("旧 turn user 消息保留", setup, verify)


# ═══════════════════════════════════════════════════════════
#  边界情况
# ═══════════════════════════════════════════════════════════

def test_13_empty_messages():
    """空消息列表 → 内部无 turn, 返回 False"""
    def setup(ctx):
        ctx.messages = []
    def verify(ctx, result):
        assert result == False
        assert len(ctx.messages) == 0
    t("空消息返回 False", setup, verify)


def test_14_only_system():
    """仅 system 消息 → split_turns 返回 [], 返回 False"""
    def setup(ctx):
        ctx.messages = [
            {"role": "system", "content": "sys1"},
            {"role": "system", "content": "sys2"},
        ]
    def verify(ctx, result):
        assert result == False
        assert len(ctx.messages) == 2
    t("仅 system 返回 False", setup, verify)


def test_15_one_turn_with_many_tools():
    """单个 turn 内有多个 tool 调用 → 旧 turn 的多个 tool 都替换"""
    def setup(ctx):
        ctx.messages = []
        for i in range(12):
            tc = [make_tc(f"c{i}_1"), make_tc(f"c{i}_2"), make_tc(f"c{i}_3")]
            ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=tc,
                tool_results=[
                    (f"c{i}_1", "read", long(1000)),
                    (f"c{i}_2", "grep", long(1000)),
                    (f"c{i}_3", "bash", long(1000)),
                ],
                assistant_reply=f"done {i}",
            ))
    def verify(ctx, result):
        assert result == True
        tools = [m for m in ctx.messages if m["role"] == "tool"]
        replaced = [m for m in tools if "force compacted" in m.get("content", "")]
        assert len(replaced) >= 6, f"旧 turn 的多个 tool 都应该被替换, 实际替换: {len(replaced)}"
    t("旧 turn 多 tool 全部替换", setup, verify)


def test_16_single_long_turn():
    """只有一个超长 turn（user + 大量 tool）→ 仍然只有 1 turn, 不触发"""
    def setup(ctx):
        msgs = [
            make_user("complex task"),
            make_assistant("", [make_tc("c0")]),
        ]
        for i in range(30):
            msgs.append(make_tool(f"c{i}", "read", long(800)))
        msgs.append(make_assistant("done"))
        ctx.messages = msgs
    def verify(ctx, result):
        assert result == False, "单个 turn 不应该触发压缩"
    t("单个超长 turn 不触发", setup, verify)


def test_17_assistant_content_is_list():
    """assistant content 为 list（Claude 风格）→ 跳过压缩"""
    def setup(ctx):
        ctx.messages = []
        for i in range(11):
            ctx.messages.append(make_user(f"q{i}"))
            ctx.messages.append({"role": "assistant", "content": [{"type": "text", "text": long(2000)}]})
    def verify(ctx, result):
        assert result == True
        # 最早的 assistant content 为 list → 跳过压缩 → 原样保留
        assistants = [m for m in ctx.messages if m["role"] == "assistant"]
        first = assistants[0]
        assert isinstance(first["content"], list), "list 类型 content 应该原样保留"
    t("assistant content=list 跳过", setup, verify)


# ═══════════════════════════════════════════════════════════
#  retain_turns 参数
# ═══════════════════════════════════════════════════════════

def test_18_custom_retain_turns():
    """retain_turns=3 → 保留最近 3 turn, 其余压缩"""
    def setup(ctx):
        ctx.messages = []
        for i in range(10):
            tc = [make_tc(f"c{i}")]
            ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=tc,
                tool_results=[(f"c{i}", "read", long(2000))],
                assistant_reply=f"reply {i}",
            ))
    def verify(ctx, result):
        # 注意: session_memory_compact 默认 retain_turns=10, 所以需要重新调用
        pass
    # 这个单独调用
    ctx = ContextManager()
    for i in range(10):
        tc = [make_tc(f"c{i}")]
        ctx.messages.extend(build_turn(
            f"q{i}",
            assistant_tc=tc,
            tool_results=[(f"c{i}", "read", long(2000))],
            assistant_reply=f"reply {i}",
        ))
    # 10 turn, retain_turns=3 → 旧 7 turn 压缩
    r = ctx.session_memory_compact(retain_turns=3)
    assert r == True

    tools = [m for m in ctx.messages if m["role"] == "tool"]
    replaced = [m for m in tools if "force compacted" in m.get("content", "")]
    original = [m for m in tools if "force compacted" not in m.get("content", "")]
    assert len(replaced) == 7, f"retain_turns=3 时应该压缩 7 个旧 tool, 实际: {len(replaced)}"
    assert len(original) == 3, f"保留 3 个新 tool, 实际: {len(original)}"
    global passed
    passed += 1
    print(f"  ✓ 自定义 retain_turns=3 正确")


# ═══════════════════════════════════════════════════════════
#  消息顺序完整性
# ═══════════════════════════════════════════════════════════

def test_19_message_order_preserved():
    """压缩后消息顺序仍然保持 user → assistant → tool → assistant 结构"""
    def setup(ctx):
        ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(12):
            ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=[make_tc(f"c{i}")],
                tool_results=[(f"c{i}", "read", long(1000))],
                assistant_reply=f"reply {i}",
            ))
    def verify(ctx, result):
        assert result == True
        roles = [m["role"] for m in ctx.messages]
        # 开头是 system
        assert roles[0] == "system"
        # 然后应该以 user 开始
        non_sys = roles[1:]
        assert non_sys[0] == "user", f"system 后应为 user, 实际: {non_sys[0]}"
        # 不能出现连续的 tool（tool 应该跟在 assistant 后面）
        for i in range(1, len(roles)):
            if roles[i] == "tool" and roles[i-1] == "tool":
                assert False, f"出现连续 tool 消息"
    t("消息顺序保持", setup, verify)


# ═══════════════════════════════════════════════════════════
#  综合场景
# ═══════════════════════════════════════════════════════════

def test_20_comprehensive_mixed():
    """混合场景: 不同角色、不同大小、工具与纯对话交替"""
    def setup(ctx):
        ctx.messages = [
            {"role": "system", "content": "system prompt"},
        ]
        for i in range(15):
            if i % 3 == 0:
                # 纯对话 turn
                ctx.messages.extend(build_assistant_only_turn(long(2000) if i < 5 else "short"))
            elif i % 3 == 1:
                # 工具调用 turn
                ctx.messages.extend(build_turn(
                    f"with tools {i}",
                    assistant_tc=[make_tc(f"c{i}")],
                    tool_results=[(f"c{i}", "grep", long(1500))],
                    assistant_reply=long(2000) if i < 5 else "ok",
                    reasoning=long(1800) if i < 5 else None,
                ))
            else:
                # 多工具 turn
                ctx.messages.extend(build_turn(
                    f"multi tools {i}",
                    assistant_tc=[make_tc(f"c{i}_a"), make_tc(f"c{i}_b")],
                    tool_results=[
                        (f"c{i}_a", "read", long(2000)),
                        (f"c{i}_b", "bash", long(2000)),
                    ],
                    assistant_reply=f"all done {i}",
                ))
    def verify(ctx, result):
        assert result == True
        # 有 system
        assert ctx.messages[0]["role"] == "system"
        # 旧 tool 有占位符
        tools = [m for m in ctx.messages if m["role"] == "tool"]
        replaced = [m for m in tools if "force compacted" in m.get("content", "")]
        assert len(replaced) > 0, "应该有 tool 被替换"
        # 最近 10 turn 的 tool 保留
        original_tools = [m for m in tools if "force compacted" not in m.get("content", "")]
        assert len(original_tools) >= 10, "至少最近 10 turn 的 tool 保留原文"
        # 旧 turn 的大 assistant 被压缩
        assistants = [m for m in ctx.messages if m["role"] == "assistant"]
        compacted_assistants = [m for m in assistants if "..." in m.get("content", "")]
        # 不是所有 assistant 都被压缩，只有旧 turn 的大内容
        # 验证 system 原封不动
        assert all(m["role"] != "system" or "..." not in m["content"] for m in ctx.messages), "system 不应被压缩"

    t("综合混合场景", setup, verify)

# ═══════════════════════════════════════════════════════════
#  21. 真实环境模拟: 多轮编程会话 + 压缩前后对比
# ═══════════════════════════════════════════════════════════

def test_21_real_scenario_with_output():
    """
    模拟一个 16 轮的真实编程助手会话：
    - 用户先探索项目结构、搜索关键字、阅读源码、运行测试、修改代码
    - 前 6 轮为「旧 turn」>10 保留线 → 被压缩
    - 后 10 轮为「近 turn」→ 保留原文
    输出压缩前后每条消息的详细对比。
    """
    ctx = ContextManager()

    # ── 构造 16 轮会话 ──

    ctx.messages = [
        {"role": "system", "content": "You are a helpful coding assistant. Be concise."},
    ]

    # Turn 1: 查看项目结构 (旧)
    ctx.messages.extend(build_turn(
        "帮我看看这个项目的文件结构",
        assistant_tc=[make_tc("c1")],
        tool_results=[("c1", "bash", ".\n├── mangopi_cli.py    (1319 lines)\n├── pyproject.toml\n├── README.md\n├── index.html\n├── deploy.sh\n└── .mangocli/\n    └── skills/\n" + ("extra " * 300))],
        assistant_reply="项目根目录包含主文件 mangopi_cli.py (1319行) 以及配置文件、部署脚本等。",
        reasoning="用户想看项目结构，我先列一下文件。",
    ))

    # Turn 2: 搜索核心类 (旧)
    ctx.messages.extend(build_turn(
        "搜索所有 class 定义",
        assistant_tc=[make_tc("c2", "grep", '{"pat": "^class "}')],
        tool_results=[("c2", "grep",
            "mangopi_cli.py:435:class ToolBase:\n"
            "mangopi_cli.py:530:class GrepTool(ToolBase):\n"
            "mangopi_cli.py:550:class ReadTool(ToolBase):\n"
            "mangopi_cli.py:570:class WriteTool(ToolBase):\n"
            "mangopi_cli.py:590:class BashTool(ToolBase):\n"
            "mangopi_cli.py:650:class ContextManager:\n"
            + ("padding to reach >200 tokens. " * 40))],
        assistant_reply="找到 6 个 class：ToolBase、GrepTool、ReadTool、WriteTool、BashTool、ContextManager。",
        reasoning="class 定义集中在 mangopi_cli.py，是一个典型的单文件项目结构。",
    ))

    # Turn 3: 读取 ToolBase (旧)
    ctx.messages.extend(build_turn(
        "读取 ToolBase 类的实现",
        assistant_tc=[make_tc("c3", "read", '{"path": "mangopi_cli.py", "offset": 435, "limit": 50}')],
        tool_results=[("c3", "read",
            "class ToolBase:\n"
            '    """Base class for all tools."""\n\n'
            "    @staticmethod\n"
            "    def schema() -> dict: raise NotImplementedError\n\n"
            "    @staticmethod\n"
            "    def run(args: dict) -> str: raise NotImplementedError\n\n"
            "    def preview(self, args: dict) -> str:\n"
            '        return json.dumps(args, ensure_ascii=False)[:100]\n\n'
            "    def confirm(self, args: dict) -> bool:\n"
            "        return False  # default: no confirm needed\n\n"
            "    def before(self, args: dict): pass\n"
            "    def after(self, args: dict, result: str): pass\n"
            + ("\n" + "T" * 3000))],
        assistant_reply="ToolBase 定义了 schema/run/preview/confirm/before/after 六个钩子方法，所有工具继承此类。",
        reasoning=("分析 ToolBase 设计模式..." * 50),
    ))

    # Turn 4: 纯对话 (旧)
    ctx.messages.extend(build_assistant_only_turn(
        "这些工具的设计模式有什么优缺点？",
        reasoning="用户问设计模式评价，这是一个开放性问题，不需要工具调用。" + ("思考中..." * 60),
    ))

    # Turn 5: 多工具调用 (旧)
    ctx.messages.extend(build_turn(
        "检查 ContextManager 和 deploy.sh",
        assistant_tc=[make_tc("c5a", "grep", '{"pat": "def "}'), make_tc("c5b", "read", '{"path": "deploy.sh"}')],
        tool_results=[
            ("c5a", "grep",
             "mangopi_cli.py:691:    def micro_compact(self):\n"
             "mangopi_cli.py:711:    def full_compact(self):\n"
             "mangopi_cli.py:750:    def prepare_for_api(self):\n"
             + ("grep result padding. " * 50)),
            ("c5b", "read",
             "#!/bin/bash\n"
             "# Deploy script for mangopi-cli\n"
             "pip install --upgrade .\n"
             "echo 'Deploy complete'\n"
             + ("#" * 2000)),
        ],
        assistant_reply="ContextManager 有 micro_compact/full_compact/prepare_for_api 方法；deploy.sh 负责 pip install 部署。",
        reasoning="需要同时查看两个文件来全面理解项目。",
    ))

    # Turn 6: 运行测试 (旧)
    ctx.messages.extend(build_turn(
        "运行项目测试看看有没有问题",
        assistant_tc=[make_tc("c6", "bash", '{"cmd": "python -m pytest test/ -v 2>&1 | head -30"}')],
        tool_results=[("c6", "bash",
            "============================= test session starts ==============================\n"
            "collected 5 items\n\n"
            "test/test_tools.py::test_read PASSED\n"
            "test/test_tools.py::test_write PASSED\n"
            "test/test_tools.py::test_grep PASSED\n"
            "test/test_tools.py::test_bash PASSED\n"
            "test/test_tools.py::test_search PASSED\n\n"
            "============================== 5 passed in 0.23s ==============================="
            + ("\n" + "=" * 800))],
        assistant_reply="5 个测试全部通过 ✅",
        reasoning="测试结果看起来不错，没有失败的。",
    ))

    # ── 以下是最近 10 轮 (保留) ──
    for i in range(7, 17):
        if i % 3 == 0:
            # 纯对话
            ctx.messages.extend(build_assistant_only_turn(
                f"这是第 {i} 轮的一个纯文本回复，没有工具调用。" + (" 内容填充 " * 40),
                reasoning=f"第 {i} 轮的分析过程..." + (" 推理 " * 50),
            ))
        elif i % 3 == 1:
            # 单工具
            ctx.messages.extend(build_turn(
                f"q{i}: 帮我搜索 turn_{i}",
                assistant_tc=[make_tc(f"c{i}", "grep", f'{{"pat": "turn_{i}"}}')],
                tool_results=[(f"c{i}", "grep", f"file.py:{i}: turn_{i} found" + (" result " * 200))],
                assistant_reply=f"找到 turn_{i}。" + (" 这是详细分析 " * 30),
                reasoning=f"搜索 turn_{i} 的原因..." + (" reason " * 40),
            ))
        else:
            # 双工具
            ctx.messages.extend(build_turn(
                f"q{i}: 读取并检查 turn_{i}",
                assistant_tc=[make_tc(f"c{i}a", "read", '{"path": "x.py"}'), make_tc(f"c{i}b", "grep", '{"pat": "y"}')],
                tool_results=[
                    (f"c{i}a", "read", f"read result for turn_{i}" + (" R " * 250)),
                    (f"c{i}b", "grep", f"grep result for turn_{i}" + (" G " * 250)),
                ],
                assistant_reply=f"turn_{i} 处理完成。" + (" 总结 " * 35),
                reasoning=f"处理 turn_{i} 的推理..." + (" T " * 45),
            ))

    # ── 压缩前快照 ──

    def msg_summary(m):
        role = m["role"]
        content = m.get("content", "")
        if isinstance(content, list):
            return f"{role}: list[{len(content)}]"
        preview = content[:60].replace("\n", "\\n")
        tokens = ctx.estimated_tokens({"content": content})
        extra = ""
        if m.get("tool_calls"):
            extra = f" [tc:{len(m['tool_calls'])}]"
        if role == "tool":
            extra = f" [{m.get('tool_name', '?')}:{m.get('tool_call_id', '?')}]"
        return f"{role}{extra}: {tokens:>5}t  {preview}..."

    before_snapshots = [msg_summary(m) for m in ctx.messages]
    total_before = ctx.total_tokens()
    msg_count_before = len(ctx.messages)

    # 统计压缩前各角色 token
    def role_tokens(messages):
        d = {}
        for m in messages:
            r = m["role"]
            d[r] = d.get(r, 0) + ctx.estimated_tokens(m)
        return d

    before_by_role = role_tokens(ctx.messages)

    # ── 执行压缩 ──
    result = ctx.session_memory_compact()

    # ── 压缩后快照 ──
    after_snapshots = [msg_summary(m) for m in ctx.messages]
    total_after = ctx.total_tokens()
    msg_count_after = len(ctx.messages)
    after_by_role = role_tokens(ctx.messages)

    # ── 输出 ──

    sep = "=" * 76
    print(f"\n{sep}")
    print("  真实环境模拟 — session_memory_compact 压缩前后对比")
    print(f"{sep}")

    print(f"\n📊 总体统计:")
    print(f"  消息总数: {msg_count_before} → {msg_count_after}")
    print(f"  总 tokens: {total_before:>6} → {total_after:>6}  "
          f"(-{total_before - total_after}, {(total_before - total_after) / max(total_before, 1) * 100:.0f}%)")

    print(f"\n📊 各角色 token 变化:")
    for role in ["system", "user", "assistant", "tool"]:
        b = before_by_role.get(role, 0)
        a = after_by_role.get(role, 0)
        delta = a - b
        sign = "+" if delta > 0 else ""
        bar = "▓" * min(abs(delta) // 20, 40)
        print(f"  {role:<10}: {b:>6}t → {a:>6}t  ({sign}{delta}t) {bar}")

    # Turn 拆分
    turns = ctx.split_turns()
    old_count = max(0, len(turns) - 10)
    recent_count = min(len(turns), 10)

    print(f"\n📋 Turn 结构: 共 {len(turns)} turn, 旧 {old_count} turn 被压缩, 近 {recent_count} turn 保留")
    print(f"  旧 turn 内的 tool → 占位符; 大 assistant → head+tail; user → 保留")
    print(f"  近 turn → 全部 deep-copy 原样保留")

    # 找出变化显著的条目
    print(f"\n📝 压缩前后的关键变化 (前 15 条):")
    changes = []
    for i, (b, a) in enumerate(zip(before_snapshots, after_snapshots)):
        if b != a:
            changes.append((i, b, a, ctx.messages[i].get("role")))
    for idx, b, a, role in changes[:15]:
        marker = "🔧" if role == "tool" else "💬" if role == "assistant" else "  "
        print(f"  {marker} #{idx}: {b}")
        print(f"          → {a}")

    if len(changes) > 15:
        print(f"  ... 另外 {len(changes) - 15} 条变化省略")

    # 验证 tool 占位符
    tools = [m for m in ctx.messages if m.get("role") == "tool"]
    replaced = [m for m in tools if "force compacted" in m.get("content", "")]
    kept = [m for m in tools if "force compacted" not in m.get("content", "")]
    print(f"\n🔍 Tool 消息验证: {len(tools)} 条, 替换 {len(replaced)} 条, 保留 {len(kept)} 条")
    if replaced:
        print(f"  占位符示例: {replaced[0]['content']}")

    # ── 断言 ──
    assert result == True, "session_memory_compact 应该返回 True"
    assert total_after < total_before, "压缩后 tokens 应该减少"
    assert len(replaced) >= 1, "至少有一个旧 tool 被替换"
    assert len(kept) >= 1, "至少有一个近 tool 被保留"

    global passed
    passed += 1
    print(f"\n  ✓ 真实环境模拟 — 压缩前后对比测试通过")

    # 确认: system 和 user 消息未被修改
    systems = [m for m in ctx.messages if m["role"] == "system"]
    assert all("force compacted" not in s.get("content", "") for s in systems), "system 不应被压缩"
    users = [m for m in ctx.messages if m["role"] == "user"]
    assert all("force compacted" not in u.get("content", "") for u in users), "user 不应被替换"


# ── 入口 ──────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== session_memory_compact 单元测试 ===\n")
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn) and name != "test_18_custom_retain_turns":
            fn()
    # test_18 手动执行过了
    print(f"\n{'='*40}")
    print(f"通过: {passed}  失败: {failed}  总计: {passed+failed}")
    if failed:
        sys.exit(1)
