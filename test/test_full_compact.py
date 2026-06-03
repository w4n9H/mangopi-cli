#!/usr/bin/env python3
"""Test full_compact() —— 验证手动 LLM 摘要压缩流程：构造 prompt → 调用 LLM → 替换为 system + 摘要。

full_compact 流程概述:
  1. 构造 _full_compact_prompt 列表
  2. self.append_user("\n".join(prompt)) 把 prompt 作为 user 消息塞入 messages
  3. provider.parse_response(_request(provider.api_url, provider.build_body(self.messages), headers=provider.headers()))
  4. 若 respon.get("content") 真值 → self.messages = systems + [新 user 摘要]
  5. 若 respon.get("content") 假值 → raise RuntimeError("full compact err: llm respon null")
  6. 任何异常 → raise RuntimeError(f"full compact err: {e}")
"""

import sys
import os
import json
from unittest.mock import patch, MagicMock

# 将项目根目录加到 sys.path，以便 import mangopi_cli 中的 ContextManager
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

def long(n=500):
    return "X" * n

def build_simple_turn(user_text, assistant_text):
    return [make_user(user_text), make_assistant(assistant_text)]


# ── Mock Provider 工厂 ────────────────────────────────────

def make_mock_provider(summary_content="<summary>this is a mock summary</summary>"):
    """构造一个可注入到 mangopi_cli.provider 的 mock 对象。

    默认行为: parse_response 返回 {"content": summary_content}。
    调用方可以修改返回值来模拟不同场景（空 content / 异常 / 特定内容）。
    """
    mock_provider = MagicMock()
    mock_provider.api_url = "https://mock.api/chat/completions"
    mock_provider.build_body = MagicMock(return_value={"model": "mock-model", "messages": []})
    mock_provider.headers = MagicMock(return_value={
        "Content-Type": "application/json", "Authorization": "Bearer mock-key"
    })
    mock_provider.parse_response = MagicMock(return_value={"content": summary_content})
    return mock_provider


# ── 测试运行器 ────────────────────────────────────────────

passed = 0
failed = 0

def t(name, setup_fn, verify_fn, expect_exception=False):
    """运行一个测试用例: setup → full_compact → verify。

    expect_exception=True 时，verify_fn 应当断言 RuntimeError 被抛出。
    """
    global passed, failed
    ctx = ContextManager()
    setup_fn(ctx)
    mock_provider = make_mock_provider()
    raised = None
    try:
        with patch("mangopi_cli.provider", mock_provider), \
             patch("mangopi_cli._request", return_value={"raw": "mock"}):
            ctx.full_compact()
    except Exception as e:
        raised = e
    try:
        verify_fn(ctx, raised, mock_provider)
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
#  1. 正常压缩: 清除所有非 system 消息，替换为 LLM 摘要
# ═══════════════════════════════════════════════════════════

def test_01_normal_compact_clears_and_replaces():
    """LLM 返回有效摘要 → 旧 user/assistant/tool 全部清空, 仅保留 system + 摘要 user"""
    def setup(ctx):
        ctx.messages = [
            {"role": "system", "content": "you are an assistant"},
            make_user("query 1"),
            make_assistant("reply 1"),
            make_tool("c1", "read", "file content"),
            make_user("query 2"),
            make_assistant("reply 2"),
        ]
    def verify(ctx, raised, mp):
        assert raised is None, f"不应抛异常, 实际: {raised}"
        # system 保留
        assert ctx.messages[0]["role"] == "system", "system 应保留在首位"
        assert ctx.messages[0]["content"] == "you are an assistant"
        # 旧消息清除
        assert len(ctx.messages) == 2, f"应只剩 system + 摘要 user, 实际 {len(ctx.messages)} 条"
        assert ctx.messages[1]["role"] == "user", "摘要应为 user 角色"
        # 摘要内容 = mock 返回
        assert ctx.messages[1]["content"] == "<summary>this is a mock summary</summary>"
    t("正常压缩清除并替换", setup, verify)


# ═══════════════════════════════════════════════════════════
#  2. 多个 system 消息顺序保留
# ═══════════════════════════════════════════════════════════

def test_02_multiple_system_messages_preserved():
    """多个 system 消息按原顺序全部保留"""
    def setup(ctx):
        ctx.messages = [
            {"role": "system", "content": "sys A"},
            {"role": "system", "content": "sys B"},
            make_user("q"),
            make_assistant("a"),
        ]
    def verify(ctx, raised, mp):
        assert raised is None
        assert len(ctx.messages) == 3, f"应 2 system + 1 摘要, 实际 {len(ctx.messages)}"
        assert ctx.messages[0] == {"role": "system", "content": "sys A"}
        assert ctx.messages[1] == {"role": "system", "content": "sys B"}
        assert ctx.messages[2]["role"] == "user"
    t("多个 system 消息保留顺序", setup, verify)


# ═══════════════════════════════════════════════════════════
#  3. 空 content → RuntimeError
# ═══════════════════════════════════════════════════════════

def test_03_empty_content_raises_runtime_error():
    """LLM 返回 content 为空 → raise RuntimeError('llm respon null')"""
    global passed, failed
    ctx = ContextManager()
    ctx.messages = [
        {"role": "system", "content": "sys"},
        make_user("q"),
        make_assistant("a"),
    ]
    mp = make_mock_provider(summary_content="")  # 显式空 content
    raised = None
    try:
        with patch("mangopi_cli.provider", mp), \
             patch("mangopi_cli._request", return_value={"raw": "mock"}):
            ctx.full_compact()
    except Exception as e:
        raised = e
    try:
        assert raised is not None, "应抛出 RuntimeError"
        assert isinstance(raised, RuntimeError), f"应抛 RuntimeError, 实际 {type(raised)}"
        assert "llm respon null" in str(raised), f"错误信息应包含 'llm respon null', 实际: {raised}"
        passed += 1
        print(f"  ✓ 空 content 抛 RuntimeError")
    except AssertionError as e:
        failed += 1
        print(f"  ✗ 空 content 抛 RuntimeError  FAIL: {e}")


# ═══════════════════════════════════════════════════════════
#  4. _request 抛异常 → RuntimeError 包装
# ═══════════════════════════════════════════════════════════

def test_04_request_exception_raises_runtime_error():
    """_request 抛出异常 → full_compact 包装为 RuntimeError"""
    def setup(ctx):
        ctx.messages = [
            {"role": "system", "content": "sys"},
            make_user("q"),
            make_assistant("a"),
        ]
    def verify(ctx, raised, mp):
        assert raised is not None
        assert isinstance(raised, RuntimeError)
        assert "full compact err" in str(raised), f"错误信息应包含 'full compact err', 实际: {raised}"
    # 在测试运行器中特殊处理: 让 _request 抛异常
    global passed, failed
    ctx = ContextManager()
    setup(ctx)
    mp = make_mock_provider()
    try:
        with patch("mangopi_cli.provider", mp), \
             patch("mangopi_cli._request", side_effect=ConnectionError("network down")):
            ctx.full_compact()
        # 若未抛异常, 视为失败
        failed += 1
        print(f"  ✗ 请求异常抛 RuntimeError  FAIL: 应抛异常但未抛")
    except RuntimeError as e:
        if "full compact err" in str(e):
            passed += 1
            print(f"  ✓ 请求异常抛 RuntimeError")
        else:
            failed += 1
            print(f"  ✗ 请求异常抛 RuntimeError  FAIL: 错误信息不符: {e}")
    except Exception as e:
        failed += 1
        print(f"  ✗ 请求异常抛 RuntimeError  FAIL: 应抛 RuntimeError, 实际 {type(e)}: {e}")


# ═══════════════════════════════════════════════════════════
#  5. Prompt 包含预期关键词
# ═══════════════════════════════════════════════════════════

def test_05_prompt_contains_expected_keywords():
    """发送给 LLM 的 messages 中应包含摘要 prompt 关键词"""
    def setup(ctx):
        ctx.messages = [
            {"role": "system", "content": "sys"},
            make_user("user query"),
            make_assistant("assistant reply"),
        ]
    def verify(ctx, raised, mp):
        assert raised is None
        # build_body 被调用, 传入的 messages 应包含 prompt 内容
        assert mp.build_body.called, "build_body 应被调用"
        sent_messages = mp.build_body.call_args[0][0]
        # 在 sent_messages 中应能找到 prompt 的特征关键词
        all_content = " ".join(
            json.dumps(m, ensure_ascii=False) for m in sent_messages
        )
        for keyword in ["Primary Request", "summary", "Current Work", "Pending Tasks"]:
            assert keyword in all_content, f"prompt 应包含关键词 '{keyword}'"
    t("prompt 包含预期关键词", setup, verify)


# ═══════════════════════════════════════════════════════════
#  6. provider.api_url 和 headers 被使用
# ═══════════════════════════════════════════════════════════

def test_06_provider_url_and_headers_used():
    """_request 应使用 provider.api_url 和 provider.headers() 的返回值"""
    def setup(ctx):
        ctx.messages = [
            {"role": "system", "content": "sys"},
            make_user("q"),
        ]
    def verify(ctx, raised, mp):
        assert raised is None
        assert mp.headers.called, "provider.headers() 应被调用"
        assert mp.api_url == "https://mock.api/chat/completions"
    t("provider.api_url 和 headers 被使用", setup, verify)


# ═══════════════════════════════════════════════════════════
#  7. 空 messages 列表
# ═══════════════════════════════════════════════════════════

def test_07_empty_messages_list():
    """messages=[] 时 → 压缩后只剩摘要 user 消息"""
    def setup(ctx):
        ctx.messages = []
    def verify(ctx, raised, mp):
        assert raised is None
        assert len(ctx.messages) == 1, f"应只有 1 条摘要 user, 实际 {len(ctx.messages)}"
        assert ctx.messages[0]["role"] == "user"
        assert ctx.messages[0]["content"] == "<summary>this is a mock summary</summary>"
    t("空 messages 列表", setup, verify)


# ═══════════════════════════════════════════════════════════
#  8. 没有 system 消息
# ═══════════════════════════════════════════════════════════

def test_08_no_system_messages():
    """messages 中无 system → 压缩后仅剩摘要 user"""
    def setup(ctx):
        ctx.messages = [
            make_user("q1"),
            make_assistant("a1"),
            make_tool("c1", "bash", "output"),
            make_user("q2"),
            make_assistant("a2"),
        ]
    def verify(ctx, raised, mp):
        assert raised is None
        assert len(ctx.messages) == 1, f"应只有 1 条摘要 user, 实际 {len(ctx.messages)}"
        assert ctx.messages[0]["role"] == "user"
        # 旧消息全部清除
        for m in ctx.messages:
            assert m["role"] in ("system", "user"), f"残留旧消息: {m}"
    t("无 system 消息", setup, verify)


# ═══════════════════════════════════════════════════════════
#  9. 摘要内容含 <analysis>/<summary> 标签时原样保留
# ═══════════════════════════════════════════════════════════

def test_09_summary_with_xml_tags_preserved():
    """LLM 返回的 <analysis>...</analysis><summary>...</summary> 完整保留在 user 消息中"""
    analysis = "<analysis>thought process here</analysis>"
    summary = "<summary>1. Primary Request and Intent:\n  do something</summary>"
    full = analysis + "\n" + summary

    def setup(ctx):
        ctx.messages = [
            {"role": "system", "content": "sys"},
            make_user("q"),
            make_assistant("a"),
        ]
    def verify(ctx, raised, mp):
        assert raised is None
        assert len(ctx.messages) == 2
        assert ctx.messages[1]["role"] == "user"
        assert ctx.messages[1]["content"] == full
        assert "<analysis>" in ctx.messages[1]["content"]
        assert "<summary>" in ctx.messages[1]["content"]
    # 自定义 summary 内容
    ctx = ContextManager()
    setup(ctx)
    mp = make_mock_provider(summary_content=full)
    try:
        with patch("mangopi_cli.provider", mp), \
             patch("mangopi_cli._request", return_value={"raw": "mock"}):
            ctx.full_compact()
        verify(ctx, None, mp)
        global passed
        passed += 1
        print(f"  ✓ 摘要 XML 标签原样保留")
    except AssertionError as e:
        global failed
        failed += 1
        print(f"  ✗ 摘要 XML 标签原样保留  FAIL: {e}")
    except Exception as e:
        failed += 1
        import traceback
        print(f"  ✗ 摘要 XML 标签原样保留  ERROR: {e}")
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════
#  10. 调用链验证: parse_response/_request/build_body/headers 都被调用
# ═══════════════════════════════════════════════════════════

def test_10_invoke_chain_all_called():
    """parse_response, _request, build_body, headers 均应被调用一次"""
    def setup(ctx):
        ctx.messages = [
            {"role": "system", "content": "sys"},
            make_user("q"),
            make_assistant("a"),
        ]
    def verify(ctx, raised, mp):
        assert raised is None
        assert mp.parse_response.called, "parse_response 应被调用"
        assert mp.build_body.called, "build_body 应被调用"
        assert mp.headers.called, "headers 应被调用"
    t("调用链完整", setup, verify)


# ═══════════════════════════════════════════════════════════
#  11. parse_response 异常 → RuntimeError 包装
# ═══════════════════════════════════════════════════════════

def test_11_parse_response_exception_raises_runtime_error():
    """parse_response 抛异常 → full_compact 包装为 RuntimeError"""
    def setup(ctx):
        ctx.messages = [
            {"role": "system", "content": "sys"},
            make_user("q"),
        ]
    global passed, failed
    ctx = ContextManager()
    setup(ctx)
    mp = make_mock_provider()
    mp.parse_response = MagicMock(side_effect=ValueError("parse boom"))
    try:
        with patch("mangopi_cli.provider", mp), \
             patch("mangopi_cli._request", return_value={"raw": "mock"}):
            ctx.full_compact()
        failed += 1
        print(f"  ✗ parse_response 异常抛 RuntimeError  FAIL: 应抛异常但未抛")
    except RuntimeError as e:
        if "full compact err" in str(e):
            passed += 1
            print(f"  ✓ parse_response 异常抛 RuntimeError")
        else:
            failed += 1
            print(f"  ✗ parse_response 异常抛 RuntimeError  FAIL: 错误信息不符: {e}")
    except Exception as e:
        failed += 1
        print(f"  ✗ parse_response 异常抛 RuntimeError  FAIL: 应抛 RuntimeError, 实际 {type(e)}: {e}")


# ═══════════════════════════════════════════════════════════
#  12. 真实环境模拟: 多轮编程会话 + 压缩前后对比
# ═══════════════════════════════════════════════════════════

def test_12_real_scenario_with_output():
    """模拟多轮编程会话, 验证 full_compact 压缩前后消息结构与角色分布。"""
    global passed, failed
    ctx = ContextManager()

    # ── 构造 10 轮真实风格会话 ──
    ctx.messages = [
        {"role": "system", "content": "You are a senior Python engineer. Be precise."},
    ]
    for i in range(1, 6):
        ctx.messages.extend([
            make_user(f"读取并分析 module_{i}.py 的实现"),
            make_assistant("",
                tool_calls=[make_tc(f"c{i}", "read", f'{{"path": "module_{i}.py"}}')],
                reasoning=f"分析 module_{i}.py 的依赖关系..." + long(200),
            ),
            make_tool(f"c{i}", "read", "# module_" + str(i) + ".py\n" + long(800)),
            make_assistant(f"module_{i}.py 已读取, 包含 {i*100} 行核心代码。" + long(150)),
        ])

    # ── 压缩前统计 ──
    total_before = ctx.total_tokens()
    msg_count_before = len(ctx.messages)
    users_before = [m for m in ctx.messages if m["role"] == "user"]
    assistants_before = [m for m in ctx.messages if m["role"] == "assistant"]
    tools_before = [m for m in ctx.messages if m["role"] == "tool"]

    summary_text = (
        "<analysis>User asked to analyze 5 Python modules with tool calls and reasoning.</analysis>\n"
        "<summary>"
        "1. Primary Request and Intent:\n  analyze 5 modules\n"
        "2. Files and Code Sections:\n  - module_1.py ~ module_5.py\n"
        "3. Current Work:\n  All 5 modules analyzed.\n"
        "</summary>"
    )

    mp = make_mock_provider(summary_content=summary_text)

    # ── 执行 full_compact ──
    try:
        with patch("mangopi_cli.provider", mp), \
             patch("mangopi_cli._request", return_value={"raw": "mock"}):
            ctx.full_compact()
    except Exception as e:
        failed += 1
        print(f"  ✗ 真实环境模拟  ERROR: {e}")
        return

    # ── 压缩后统计 ──
    total_after = ctx.total_tokens()
    msg_count_after = len(ctx.messages)
    users_after = [m for m in ctx.messages if m["role"] == "user"]
    assistants_after = [m for m in ctx.messages if m["role"] == "assistant"]
    tools_after = [m for m in ctx.messages if m["role"] == "tool"]

    # ── 输出 ──
    sep = "=" * 76
    print(f"\n{sep}")
    print("  真实环境模拟 — full_compact 压缩前后对比")
    print(f"{sep}")
    print(f"\n📊 总体统计:")
    print(f"  消息总数: {msg_count_before} → {msg_count_after} (-{msg_count_before - msg_count_after})")
    print(f"  总 tokens: {total_before:>6} → {total_after:>6}  (-{total_before - total_after})")
    print(f"\n📊 各角色消息数:")
    for role, b, a in [
        ("system", 1, len([m for m in ctx.messages if m["role"] == "system"])),
        ("user", len(users_before), len(users_after)),
        ("assistant", len(assistants_before), len(assistants_after)),
        ("tool", len(tools_before), len(tools_after)),
    ]:
        delta = a - b
        sign = "+" if delta > 0 else ""
        print(f"  {role:<10}: {b:>3} → {a:>3}  ({sign}{delta})")

    # ── 断言 ──
    assert ctx.messages[0]["role"] == "system", "system 应在最前"
    assert ctx.messages[0]["content"] == "You are a senior Python engineer. Be precise."
    assert len(ctx.messages) == 2, f"应只剩 system + 摘要, 实际 {len(ctx.messages)}"
    assert ctx.messages[1]["role"] == "user"
    assert ctx.messages[1]["content"] == summary_text
    # 旧消息全部清除
    assert len(tools_after) == 0, f"tool 消息应全部清除, 残留 {len(tools_after)}"
    assert len(assistants_after) == 0, f"assistant 消息应全部清除, 残留 {len(assistants_after)}"
    # 压缩后 token 应大幅减少
    assert total_after < total_before, "压缩后 tokens 应减少"

    passed += 1
    print(f"\n  ✓ 真实环境模拟 — 压缩前后对比测试通过")


# ── 入口 ──────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== full_compact 单元测试 ===\n")
    tests = [
        test_01_normal_compact_clears_and_replaces,
        test_02_multiple_system_messages_preserved,
        test_03_empty_content_raises_runtime_error,
        test_04_request_exception_raises_runtime_error,
        test_05_prompt_contains_expected_keywords,
        test_06_provider_url_and_headers_used,
        test_07_empty_messages_list,
        test_08_no_system_messages,
        test_09_summary_with_xml_tags_preserved,
        test_10_invoke_chain_all_called,
        test_11_parse_response_exception_raises_runtime_error,
        test_12_real_scenario_with_output,
    ]
    for fn in tests:
        fn()
    print(f"\n{'='*40}")
    print(f"通过: {passed}  失败: {failed}  总计: {passed+failed}")
    if failed:
        sys.exit(1)
