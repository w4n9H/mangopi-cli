#!/usr/bin/env python3
"""Test compact_conversation() —— 验证 turn 级逐轮丢弃降 token 的行为。"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangopi_cli import ContextManager

# ── 辅助函数 ──────────────────────────────────────────────

def make_user(content):
    return {"role": "user", "content": content}

def make_assistant(content, tool_calls=None, reasoning=None):
    m = {"role": "assistant", "content": content}
    if tool_calls:
        m["tool_calls"] = tool_calls
    if reasoning:
        m["reasoning_content"] = reasoning
    return m

def make_tool(call_id, name, content):
    return {"role": "tool", "tool_call_id": call_id, "tool_name": name, "content": content}

def make_tc(call_id, name="read", args='{"path": "x"}'):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}

def long(n=1000):
    return "X" * n

def build_turn(user_text, assistant_tc=None, tool_results=None, assistant_reply=None, reasoning=None):
    """构建一个完整 turn: user → assistant(tc) → tool... → assistant(reply)"""
    msgs = [make_user(user_text)]
    if assistant_tc:
        msgs.append(make_assistant("", assistant_tc, reasoning=reasoning))
    if tool_results:
        for tc_id, name, content in tool_results:
            msgs.append(make_tool(tc_id, name, content))
    if assistant_reply is not None:
        msgs.append(make_assistant(assistant_reply, reasoning=reasoning))
    return msgs

def build_simple_turn(user_text, assistant_text):
    """纯对话 turn: user → assistant"""
    return [make_user(user_text), make_assistant(assistant_text)]


# ── 测试用例 ──────────────────────────────────────────────

passed = 0
failed = 0

def t(name, setup_fn, verify_fn):
    global passed, failed
    ctx = ContextManager()
    setup_fn(ctx)
    ctx.compact_conversation()
    try:
        verify_fn(ctx)
        passed += 1
        print(f"  ✓ {name}")
    except AssertionError as e:
        failed += 1
        print(f"  ✗ {name}  FAIL: {e}")
    except Exception as e:
        failed += 1
        import traceback
        print(f"  ✗ {name}  ERROR: {e}")
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════
#  1. 空消息 / 仅 system — 不操作
# ═══════════════════════════════════════════════════════════

def test_01_empty_messages():
    def setup(ctx):
        ctx.messages = []
    def verify(ctx):
        assert len(ctx.messages) == 0
    t("空消息不操作", setup, verify)


def test_02_only_system():
    def setup(ctx):
        ctx.messages = [
            {"role": "system", "content": "sys1"},
            {"role": "system", "content": "sys2"},
        ]
    def verify(ctx):
        assert ctx.messages[0]["content"] == "sys1"
        assert ctx.messages[1]["content"] == "sys2"
        assert len(ctx.messages) == 2
    t("仅 system 不操作", setup, verify)


# ═══════════════════════════════════════════════════════════
#  2. 低于阈值 — 不丢任何 turn
# ═══════════════════════════════════════════════════════════

def test_03_under_threshold_no_trim():
    """turns <= retain_turns=8, 且总 tokens 低于阈值 → 不变化"""
    def setup(ctx):
        ctx.auto_compact_threshold = 50_000  # 远大于消息量
        ctx.messages = [
            {"role": "system", "content": "sys"},
        ]
        for i in range(5):
            ctx.messages.extend(build_simple_turn(f"q{i}", f"a{i}"))
    def verify(ctx):
        assert len(ctx.messages) == 11, f"应保留全部 11 条消息, 实际: {len(ctx.messages)}"
        users = [m for m in ctx.messages if m["role"] == "user"]
        assert len(users) == 5, "所有 user 消息应保留"
    t("低于阈值不丢 turn", setup, verify)


def test_04_over_threshold_no_old_turns_discard_recent():
    """只有 6 turn (无 old turn), 但超阈值 → 仍会丢弃 recent turns 直到低于阈值 (保底≥1)"""
    def setup(ctx):
        ctx.auto_compact_threshold = 10  # 极低阈值, 只够容纳 system + 1 turn
        ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(6):
            ctx.messages.extend(build_simple_turn(f"q{i}", long(500)))
    def verify(ctx):
        # 无 old turn 但超阈值 → 从头丢 recent turns, 最后只剩 1 turn
        users = [m["content"] for m in ctx.messages if m["role"] == "user"]
        assert len(users) == 1, f"超阈值应丢弃至只剩 1 turn, 实际: {len(users)}"
        assert "q5" in users, "应保留最后一个 turn"
    t("超阈值无 old turn → 丢 recent 至剩 1", setup, verify)


# ═══════════════════════════════════════════════════════════
#  3. 逐轮丢弃 old turns
# ═══════════════════════════════════════════════════════════

def test_05_discard_one_old_turn():
    """12 turn, 阈值刚好只能容纳 11 turn → 丢弃最早 1 个 turn"""
    def setup(ctx):
        ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(12):
            ctx.messages.extend(build_simple_turn(f"q{i}", f"reply_{i}"))
        # 计算如果把所有 turn 都保留需要多少 token, 然后设置阈值刚好少 1 个 turn
        all_tokens = ctx.total_tokens()
        # 第一个 turn 的 token 数 = user + assistant
        first_turn_tokens = ctx.estimated_tokens(ctx.messages[1]) + ctx.estimated_tokens(ctx.messages[2])
        # 设置阈值: 全部 - 第一个 turn 的 token, 这样去掉最早 turn 就刚好低于阈值
        ctx.auto_compact_threshold = all_tokens - first_turn_tokens
    def verify(ctx):
        users = [m["content"] for m in ctx.messages if m["role"] == "user"]
        assert "q0" not in users, "最早的 turn q0 应该被丢弃"
        assert "q1" in users, "q1 应该保留"
        assert "q11" in users, "q11 应该保留"
    t("丢弃 1 个旧 turn", setup, verify)


def test_06_discard_multiple_old_turns():
    """12 turn, 阈值只能容纳 5 turn → 丢弃最早 7 个 turn"""
    def setup(ctx):
        ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(12):
            ctx.messages.extend(build_simple_turn(f"turn_{i}", f"reply_{i}"))
        # 保留 5 turn → 系 + 5*2 = 11 条消息
        all_tokens = ctx.total_tokens()
        keep_5_tokens = sum(ctx.estimated_tokens(m) for m in ctx.messages[:11])  # sys + 5 turns
        ctx.auto_compact_threshold = keep_5_tokens + 10  # 略大于 5 turn
    def verify(ctx):
        users = [m["content"] for m in ctx.messages if m["role"] == "user"]
        # 保留的应该是最近的 5 turn (turn_7 ~ turn_11)
        assert len(users) == 5, f"应保留 5 turn, 实际: {len(users)}"
        for i in range(7):
            assert f"turn_{i}" not in users, f"turn_{i} 应该被丢弃"
        for i in range(7, 12):
            assert f"turn_{i}" in users, f"turn_{i} 应该保留"
    t("丢弃多个旧 turn", setup, verify)


# ═══════════════════════════════════════════════════════════
#  4. old turns 全部丢弃后仍超阈值 → 丢弃 recent turns
# ═══════════════════════════════════════════════════════════

def test_07_discard_recent_turns():
    """阈值极低，old turns 全丢后仍超 → 逐步丢弃 recent turns (至少保留 1)"""
    def setup(ctx):
        ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(10):
            ctx.messages.extend(build_simple_turn(f"q{i}", long(500)))
        # 阈值只能容纳 system + 1 turn
        keep_1_turn_tokens = ctx.estimated_tokens(ctx.messages[0])  # sys
        keep_1_turn_tokens += ctx.estimated_tokens(ctx.messages[-2])  # last user
        keep_1_turn_tokens += ctx.estimated_tokens(ctx.messages[-1])  # last assistant
        ctx.auto_compact_threshold = keep_1_turn_tokens + 5
    def verify(ctx):
        users = [m["content"] for m in ctx.messages if m["role"] == "user"]
        assert len(users) == 1, f"应只保留 1 turn, 实际: {len(users)}"
        assert "q9" in users, "应保留最后一个 turn"
        assert ctx.messages[0]["role"] == "system", "system 应保留"
    t("丢弃 recent turns 至剩 1", setup, verify)


# ═══════════════════════════════════════════════════════════
#  5. System 消息永远保留
# ═══════════════════════════════════════════════════════════

def test_08_system_always_preserved():
    """无论丢弃多少 turn, system 消息始终在最前面"""
    def setup(ctx):
        ctx.messages = [
            {"role": "system", "content": "sys A"},
            {"role": "system", "content": "sys B"},
        ]
        for i in range(12):
            ctx.messages.extend(build_simple_turn(f"q{i}", long(500)))
        # 极低阈值, 只保留 1 turn
        sys_tokens = sum(ctx.estimated_tokens(m) for m in ctx.messages[:2])
        one_turn_tokens = ctx.estimated_tokens(ctx.messages[-2]) + ctx.estimated_tokens(ctx.messages[-1])
        ctx.auto_compact_threshold = sys_tokens + one_turn_tokens + 5
    def verify(ctx):
        assert ctx.messages[0]["role"] == "system"
        assert ctx.messages[1]["role"] == "system"
        assert ctx.messages[0]["content"] == "sys A"
        assert ctx.messages[1]["content"] == "sys B"
    t("system 始终保留", setup, verify)


# ═══════════════════════════════════════════════════════════
#  6. 消息顺序完整性
# ═══════════════════════════════════════════════════════════

def test_09_message_order_preserved():
    """丢弃 turn 后, 剩余消息顺序正确: system → user → assistant → user → ..."""
    def setup(ctx):
        ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(15):
            ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=[make_tc(f"c{i}")],
                tool_results=[(f"c{i}", "read", long(300))],
                assistant_reply=f"reply {i}",
            ))
        # 只保留最近 2 turn
        keep = 0
        for m in ctx.messages:
            keep += ctx.estimated_tokens(m)
        # 实际上需要更精确。直接用最后几个 turn 的 token 和。
        # 最后 2 turn: 每个 turn 4 条消息
        last_turns_tokens = sum(ctx.estimated_tokens(m) for m in ctx.messages[-8:])
        sys_tokens = ctx.estimated_tokens(ctx.messages[0])
        ctx.auto_compact_threshold = sys_tokens + last_turns_tokens + 10
    def verify(ctx):
        roles = [m["role"] for m in ctx.messages]
        assert roles[0] == "system"
        # system 之后第一个非 system 应该是 user
        for r in roles[1:]:
            if r != "system":
                assert r == "user", f"system 后第一条应为 user, 实际: {r}"
                break
        # 检查 user 数量
        users = [m for m in ctx.messages if m["role"] == "user"]
        assert len(users) >= 1, "至少保留 1 个 turn"
    t("消息顺序保持", setup, verify)


# ═══════════════════════════════════════════════════════════
#  7. 保留 message 内容不被修改
# ═══════════════════════════════════════════════════════════

def test_10_messages_not_modified():
    """留存的消息只是 deep-copy，内容不被修改"""
    def setup(ctx):
        ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(12):
            ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=[make_tc(f"c{i}")],
                tool_results=[(f"c{i}", "read", long(300))],
                assistant_reply=f"reply {i} with extra " + long(200),
                reasoning=long(250) if i < 2 else None,
            ))
        # 保留最近 4 turn
        ctx.auto_compact_threshold = ctx.estimated_tokens(ctx.messages[0])  # sys
        for m in ctx.messages[-16:]:  # last 4 turns = 16 messages
            ctx.auto_compact_threshold += ctx.estimated_tokens(m)
        ctx.auto_compact_threshold += 5
    def verify(ctx):
        tools = [m for m in ctx.messages if m["role"] == "tool"]
        # 所有保留的 tool 内容不变
        for tool in tools:
            assert "force compacted" not in tool["content"], "compact_conversation 不应修改 tool 内容"
            assert tool["content"].startswith(long(300)[:10]), "tool 内容应保持原样"
        # assistant with tool_calls 保留完整
        assistants_with_tc = [m for m in ctx.messages if m["role"] == "assistant" and "tool_calls" in m]
        for a in assistants_with_tc:
            assert "tool_calls" in a
    t("保留消息内容不被修改", setup, verify)


# ═══════════════════════════════════════════════════════════
#  8. retain_turns 参数
# ═══════════════════════════════════════════════════════════

def test_11_custom_retain_turns():
    """retain_turns=3 → 最近 3 turn 为 recent, 其余为 old"""
    ctx = ContextManager()
    ctx.messages = [{"role": "system", "content": "sys"}]
    for i in range(10):
        ctx.messages.extend(build_simple_turn(f"q{i}", f"a{i}"))
    # 计算全部 token, 减去最早 1 个 old turn
    all_tokens = ctx.total_tokens()
    first_turn_tokens = ctx.estimated_tokens(ctx.messages[1]) + ctx.estimated_tokens(ctx.messages[2])
    ctx.auto_compact_threshold = all_tokens - first_turn_tokens
    ctx.compact_conversation(retain_turns=3)

    users = [m["content"] for m in ctx.messages if m["role"] == "user"]
    # retain_turns=3 → 7 old turns → 只丢最早 1 个
    assert "q0" not in users, f"最早 turn 应丢弃, 实际保留: {users}"
    for i in range(1, 10):
        assert f"q{i}" in users, f"q{i} 应该保留"

    global passed
    passed += 1
    print(f"  ✓ 自定义 retain_turns=3 正确")


# ═══════════════════════════════════════════════════════════
#  9. 综合: 工具调用 turn
# ═══════════════════════════════════════════════════════════

def test_12_tool_turns_discarded_together():
    """一个 turn 内的 user + assistant(tc) + tool + assistant(reply) 作为一个整体丢弃"""
    def setup(ctx):
        ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(12):
            ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=[make_tc(f"c{i}")],
                tool_results=[(f"c{i}", "read", long(300))],
                assistant_reply=f"reply {i}",
            ))
        # 保留最近 3 turn (12 messages) + system
        keep = ctx.estimated_tokens(ctx.messages[0])
        for m in ctx.messages[-12:]:
            keep += ctx.estimated_tokens(m)
        ctx.auto_compact_threshold = keep + 10
    def verify(ctx):
        users = [m["content"] for m in ctx.messages if m["role"] == "user"]
        assert len(users) == 3, f"应保留 3 turn, 实际: {len(users)}"
        for i in range(9, 12):
            assert f"q{i}" in users, f"q{i} 应该保留"
        # tool 消息也对应保留
        tools = [m for m in ctx.messages if m["role"] == "tool"]
        assert len(tools) == 3, f"应保留 3 条 tool, 实际: {len(tools)}"
    t("工具 turn 整体丢弃", setup, verify)


# ═══════════════════════════════════════════════════════════
#  10. 真实环境模拟: 多轮编程会话 + 压缩前后对比
# ═══════════════════════════════════════════════════════════

def test_13_real_scenario_with_output():
    """
    模拟一个 14 轮的真实编程助手会话，其中部分 turn 携带大 tool 结果。
    设置阈值触发 compact_conversation 逐步丢弃旧 turn。
    输出压缩前后的每条消息/每个 turn 的对比。
    """
    ctx = ContextManager()

    # ── 构造 14 轮会话 ──

    ctx.messages = [
        {"role": "system", "content": "You are a coding assistant. Be thorough and precise."},
    ]

    # Turn 1-4: 早期探索 (每个带大 tool 结果, 模拟 read 源码)
    for i in range(1, 5):
        ctx.messages.extend(build_turn(
            f"读取项目中的 core_{i}.py",
            assistant_tc=[make_tc(f"c{i}", "read", f'{{"path": "core_{i}.py"}}')],
            tool_results=[(f"c{i}", "read", f"# core_{i}.py\n" + long(1200))],
            assistant_reply=f"core_{i}.py 包含核心逻辑 {i}。" + long(300),
            reasoning=f"分析 core_{i}.py 的架构..." + long(400),
        ))

    # Turn 5: 对话
    ctx.messages.extend(build_simple_turn(
        "这些核心模块之间的依赖关系是什么？",
        "模块之间存在循环依赖，core_1 依赖 core_2，core_2 依赖 core_3..." + long(500),
    ))

    # Turn 6-9: 中期调试 (每个带 grep + bash 工具)
    for i in range(6, 10):
        ctx.messages.extend(build_turn(
            f"搜索 bug_{i} 并运行测试",
            assistant_tc=[
                make_tc(f"c{i}a", "grep", f'{{"pat": "bug_{i}"}}'),
                make_tc(f"c{i}b", "bash", f'{{"cmd": "pytest test_bug_{i}.py -v"}}'),
            ],
            tool_results=[
                (f"c{i}a", "grep", f"src/bug_{i}.py:10: bug_{i} found\n" + (" match " * 150)),
                (f"c{i}b", "bash", f"test_bug_{i}.py::test_fix PASSED\n" + (" ok " * 150)),
            ],
            assistant_reply=f"bug_{i} 已修复并测试通过。" + long(250),
            reasoning=f"定位 bug_{i} 并验证修复..." + long(350),
        ))

    # Turn 10-14: 最新工作 (精简)
    for i in range(10, 15):
        ctx.messages.extend(build_turn(
            f"最终优化 pass_{i}",
            assistant_tc=[make_tc(f"c{i}", "write", f'{{"path": "opt_{i}.py"}}')],
            tool_results=[(f"c{i}", "write", f"Written opt_{i}.py ({i*10} lines)")],
            assistant_reply=f"opt_{i}.py 已创建。",
        ))

    # ── 压缩前统计 ──

    total_before = ctx.total_tokens()
    msg_count_before = len(ctx.messages)
    turns_before = ctx.split_turns()

    def show_turn(idx, turn):
        """返回 turn 的摘要"""
        roles = " → ".join(m["role"][:4] for m in turn)
        user_msg = next((m["content"][:50] for m in turn if m["role"] == "user"), "?")
        tokens = sum(ctx.estimated_tokens(m) for m in turn)
        tool_count = sum(1 for m in turn if m["role"] == "tool")
        return f"Turn {idx}: {tokens:>5}t  [{tool_count}tools]  {user_msg}..."

    # ── 设置阈值: 只保留最近 6 turn (丢弃 8 个旧 turn) ──
    sys_tokens = ctx.estimated_tokens(ctx.messages[0])
    # 最后 6 turn 的消息: 消息数 = 5 * 4 = 20 条 (每个 turn 4 条)
    recent_msg_count = 6 * 4  # 最后 6 turn 各有 4 条消息 (user, assistant+tc, tool, assistant)
    keep_tokens = sys_tokens
    for m in ctx.messages[-recent_msg_count:]:
        keep_tokens += ctx.estimated_tokens(m)
    ctx.auto_compact_threshold = keep_tokens + 15

    # ── 执行压缩 ──
    ctx.compact_conversation()

    # ── 压缩后统计 ──

    total_after = ctx.total_tokens()
    msg_count_after = len(ctx.messages)
    turns_after = ctx.split_turns()

    # ── 输出 ──

    sep = "=" * 76
    print(f"\n{sep}")
    print("  真实环境模拟 — compact_conversation 压缩前后对比")
    print(f"{sep}")

    print(f"\n📊 总体统计:")
    print(f"  消息总数: {msg_count_before} → {msg_count_after} (-{msg_count_before - msg_count_after})")
    print(f"  Turn 数:  {len(turns_before)} → {len(turns_after)} (-{len(turns_before) - len(turns_after)})")
    print(f"  总 tokens: {total_before:>6} → {total_after:>6}  "
          f"(-{total_before - total_after}, {(total_before - total_after) / max(total_before, 1) * 100:.0f}%)")
    print(f"  阈值: {ctx.auto_compact_threshold}t")

    print(f"\n📋 Turn 丢弃明细:")
    print(f"  {'':-<55}")
    kept_users = {m["content"][:50] for m in ctx.messages if m["role"] == "user"}
    for idx, turn in enumerate(turns_before, 1):
        user_msg = next((m["content"][:50] for m in turn if m["role"] == "user"), "?")
        tokens = sum(ctx.estimated_tokens(m) for m in turn)
        kept = user_msg in kept_users
        marker = "✓ 保留" if kept else "✗ 丢弃"
        print(f"  {marker}  {show_turn(idx, turn)}")
    print(f"  {'':-<55}")

    # 角色 token 变化
    def role_tokens(msgs):
        d = {}
        for m in msgs:
            r = m["role"]
            d[r] = d.get(r, 0) + ctx.estimated_tokens(m)
        return d

    before_by_role = role_tokens(ctx.messages)  # 注意: ctx.messages 已经是压缩后的
    # 重建压缩前的消息来计算角色 token
    # (不方便重建，用近似的: 记录压缩前的所有消息)
    ctx_before = ContextManager()
    ctx_before.messages = [
        {"role": "system", "content": "You are a coding assistant. Be thorough and precise."},
    ]
    for i in range(1, 5):
        ctx_before.messages.extend(build_turn(
            f"读取项目中的 core_{i}.py",
            assistant_tc=[make_tc(f"c{i}", "read", f'{{"path": "core_{i}.py"}}')],
            tool_results=[(f"c{i}", "read", f"# core_{i}.py\n" + long(1200))],
            assistant_reply=f"core_{i}.py 包含核心逻辑 {i}。" + long(300),
            reasoning=f"分析 core_{i}.py 的架构..." + long(400),
        ))
    ctx_before.messages.extend(build_simple_turn(
        "这些核心模块之间的依赖关系是什么？",
        "模块之间存在循环依赖..." + long(500),
    ))
    for i in range(6, 10):
        ctx_before.messages.extend(build_turn(
            f"搜索 bug_{i} 并运行测试",
            assistant_tc=[
                make_tc(f"c{i}a", "grep", f'{{"pat": "bug_{i}"}}'),
                make_tc(f"c{i}b", "bash", f'{{"cmd": "pytest test_bug_{i}.py -v"}}'),
            ],
            tool_results=[
                (f"c{i}a", "grep", f"src/bug_{i}.py:10: bug_{i} found\n" + (" match " * 150)),
                (f"c{i}b", "bash", f"test_bug_{i}.py::test_fix PASSED\n" + (" ok " * 150)),
            ],
            assistant_reply=f"bug_{i} 已修复。" + long(250),
            reasoning=f"定位 bug_{i}..." + long(350),
        ))
    for i in range(10, 15):
        ctx_before.messages.extend(build_turn(
            f"最终优化 pass_{i}",
            assistant_tc=[make_tc(f"c{i}", "write", f'{{"path": "opt_{i}.py"}}')],
            tool_results=[(f"c{i}", "write", f"Written opt_{i}.py")],
            assistant_reply=f"opt_{i}.py 已创建。",
        ))
    before_by_role = role_tokens(ctx_before.messages)

    print(f"\n📊 各角色 token 变化:")
    after_by_role = role_tokens(ctx.messages)
    for role in ["system", "user", "assistant", "tool"]:
        b = before_by_role.get(role, 0)
        a = after_by_role.get(role, 0)
        delta = a - b
        sign = "+" if delta > 0 else ""
        bar = "▓" * min(abs(delta) // 30, 40)
        print(f"  {role:<10}: {b:>6}t → {a:>6}t  ({sign}{delta}t) {bar}")

    # ── 断言 ──
    assert len(turns_after) < len(turns_before), "压缩后 turn 数应减少"
    assert total_after < total_before, "压缩后 tokens 应减少"
    assert ctx.messages[0]["role"] == "system", "system 应在最前"
    # 保留的 turn 内容应原样
    for m in ctx.messages:
        if m["role"] == "tool":
            assert "force compacted" not in m.get("content", ""), "compact_conversation 不修改 tool 内容"

    global passed
    passed += 1
    print(f"\n  ✓ 真实环境模拟 — 压缩前后对比测试通过")


# ── 入口 ──────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== compact_conversation 单元测试 ===\n")
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn) and name != "test_11_custom_retain_turns":
            fn()
    # test_11 显式调用
    test_11_custom_retain_turns()
    print(f"\n{'='*40}")
    print(f"通过: {passed}  失败: {failed}  总计: {passed+failed}")
    if failed:
        sys.exit(1)
