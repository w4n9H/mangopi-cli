"""Tests for ContextManager.session_memory_compact() — selective turn-level
compaction that keeps the last `retain_turns` turns intact and compacts
old turns by:
    * replacing each old tool message with a placeholder
      "<Old tool(<name>:<id>) result force compacted>",
    * compacting large old assistant content via `compact_text`
      (if `estimated_tokens` > `assistant.max_tokens=1500`),
    * compacting large reasoning/reasoning_content/reasoning_details
      via the same machinery (if > `reasoning_content.max_tokens=500`),
    * leaving user and system messages untouched.

Returns True when any compaction happened, False if `len(turns) <=
retain_turns` (default retain_turns=10).

Covers:
    * Basic threshold behavior (False when ≤10 turns, True when >10)
    * Tool message replacement / preservation
    * Assistant with tool_calls → tool_calls field preserved
    * Assistant content / reasoning / reasoning_details compaction
    * System / user messages always preserved
    * Boundary cases (empty, system-only, list-typed content)
    * Custom `retain_turns` parameter
    * Message order invariants
    * Comprehensive mixed-content scenario
    * Realistic 16-turn coding-session scenario
"""
import os
import sys
import time
import unittest

# Add parent dir to sys.path so we can import mangopi_cli.
# This file lives at <project>/test/test_session_memory_compact.py,
# so the project root is one level up from __file__'s directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangopi_cli import ContextManager  # noqa: E402


# ── Module-level message builders ────────────────────────────────────────────
#
# `long()` returns content larger than the current `assistant.max_tokens=1500`
# rule's threshold. The test helper uses the no-arg form for "big enough" content.

def long(n_chars=6000):
    """Default 6000 chars → estimated_tokens ≈ 1507, above the
    `assistant.max_tokens=1500` threshold that triggers content compaction."""
    return "L" * n_chars


def make_user(content):
    return {"role": "user", "content": content}


def make_assistant(content, tool_calls=None, reasoning=None,
                   reasoning_details=None):
    m = {"role": "assistant", "content": content}
    if tool_calls:
        m["tool_calls"] = tool_calls
    if reasoning:
        m["reasoning_content"] = reasoning
    if reasoning_details:
        m["reasoning_details"] = reasoning_details
    return m


def make_tool(call_id, name, content):
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "tool_name": name,
        "content": content,
    }


def make_tc(call_id, name="read", args='{"path": "x"}'):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": args},
    }


def build_turn(user_text, assistant_tc=None, tool_results=None,
               assistant_reply=None, reasoning=None):
    """Construct a full turn: user → assistant(tool_calls) → tool(s) →
    assistant(reply)."""
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
    """Construct a no-tool turn: user → assistant."""
    return [
        make_user("user query"),
        make_assistant(content, reasoning=reasoning),
    ]


# ── Shared base: each test gets a fresh ContextManager ─────────────────────


class _SessionMemoryCompactBase(unittest.TestCase):
    """Base: fresh ContextManager per test, plus helpers."""

    def setUp(self):
        self.ctx = ContextManager()

    def compact(self, **kwargs):
        """Run session_memory_compact and return its bool result."""
        return self.ctx.session_memory_compact(**kwargs)


# ── 1. Basic threshold behavior ────────────────────────────────────────────


class TestBasic(_SessionMemoryCompactBase):
    """When turn count ≤ retain_turns (default 10), session_memory_compact
    is a no-op and returns False.
    """

    def test_01_turns_lt_10_returns_false(self):
        for i in range(2):
            self.ctx.messages.append(make_user(f"q{i}"))
            self.ctx.messages.append(make_assistant(f"a{i}"))
        self.assertEqual(len(self.ctx.messages), 4)
        result = self.compact()
        self.assertFalse(result)
        self.assertEqual(len(self.ctx.messages), 4)

    def test_02_exactly_10_turns_returns_false(self):
        for i in range(10):
            self.ctx.messages.append(make_user(f"q{i}"))
            self.ctx.messages.append(make_assistant(f"a{i}"))
        self.assertEqual(self.compact(), False)

    def test_03_exactly_11_turns_compacts(self):
        for i in range(11):
            self.ctx.messages.append(make_user(f"q{i}"))
            self.ctx.messages.append(make_assistant(f"a{i}"))
        self.assertEqual(self.compact(), True)
        # All 11 user messages should still be present (user is never touched).
        users = [m for m in self.ctx.messages if m["role"] == "user"]
        self.assertEqual(len(users), 11)


# ── 2. Tool message replacement / preservation ─────────────────────────────


class TestToolCompaction(_SessionMemoryCompactBase):
    def test_04_old_tool_content_replaced(self):
        """Old-turn tool messages get replaced with the placeholder."""
        for i in range(11):
            self.ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=[make_tc(f"c{i}")],
                tool_results=[(f"c{i}", "grep", long())],
                assistant_reply=f"reply {i}",
            ))
        self.assertEqual(self.compact(), True)
        tools = [m for m in self.ctx.messages if m["role"] == "tool"]
        replaced = [m for m in tools if "force compacted" in m.get("content", "")]
        self.assertGreaterEqual(len(replaced), 1)
        placeholder = replaced[0]["content"]
        self.assertIn("force compacted", placeholder)
        self.assertIn(replaced[0].get("tool_name", ""), placeholder)

    def test_05_recent_tool_not_replaced(self):
        """Recent (last 10) turn tool messages keep their original content."""
        for i in range(15):
            self.ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=[make_tc(f"c{i}")],
                tool_results=[(f"c{i}", "read", long())],
                assistant_reply=f"reply {i}",
            ))
        self.assertEqual(self.compact(), True)
        tools = [m for m in self.ctx.messages if m["role"] == "tool"]
        replaced = [m for m in tools if "force compacted" in m.get("content", "")]
        kept = [m for m in tools if "force compacted" not in m.get("content", "")]
        self.assertGreaterEqual(len(kept), 10)
        self.assertGreaterEqual(len(replaced), 5)


# ── 3. Assistant messages with tool_calls ──────────────────────────────────


class TestAssistantWithToolCallsPreserved(_SessionMemoryCompactBase):
    def test_06_assistant_with_tool_calls_preserved(self):
        """Old-turn assistant with tool_calls must keep its `tool_calls`
        field intact (only the `content` may be compacted, but here
        content is empty so nothing happens)."""
        for i in range(12):
            self.ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=[make_tc(f"c{i}")],
                tool_results=[(f"c{i}", "read", long(2000))],
                assistant_reply=f"reply {i}",
            ))
        self.assertEqual(self.compact(), True)
        assistants_with_tc = [
            m for m in self.ctx.messages
            if m["role"] == "assistant" and "tool_calls" in m
        ]
        self.assertEqual(len(assistants_with_tc), 12)
        first = assistants_with_tc[0]
        self.assertIn("tool_calls", first)
        self.assertEqual(len(first["tool_calls"]), 1)


# ── 4. Assistant content / reasoning compaction ───────────────────────────


class TestAssistantContentCompaction(_SessionMemoryCompactBase):
    def test_07_assistant_large_content_compacted(self):
        """Old-turn assistant with no tool_calls and big content → compacted."""
        for i in range(11):
            self.ctx.messages.extend(build_assistant_only_turn(long()))
        self.assertEqual(self.compact(), True)
        assistants = [m for m in self.ctx.messages if m["role"] == "assistant"]
        first = assistants[0]
        last = assistants[-1]
        self.assertIn("\n...\n", first["content"])
        self.assertNotIn("\n...\n", last["content"])

    def test_08_assistant_small_content_not_compacted(self):
        """Old-turn assistant with small content → not compacted."""
        for i in range(11):
            self.ctx.messages.extend(build_assistant_only_turn("short reply"))
        self.assertEqual(self.compact(), True)
        assistants = [m for m in self.ctx.messages if m["role"] == "assistant"]
        first = assistants[0]
        self.assertNotIn("\n...\n", first["content"])

    def test_09_assistant_reasoning_compacted(self):
        """Old-turn assistant's `reasoning_content` (>500 tokens) is compacted."""
        for i in range(11):
            self.ctx.messages.extend(
                build_assistant_only_turn("ok", reasoning=long())
            )
        self.assertEqual(self.compact(), True)
        assistants = [m for m in self.ctx.messages if m["role"] == "assistant"]
        first = assistants[0]
        last = assistants[-1]
        self.assertIn("\n...\n", first.get("reasoning_content", ""))
        self.assertNotIn("\n...\n", last.get("reasoning_content", ""))

    def test_10_assistant_reasoning_details_compacted(self):
        """Old-turn assistant's `reasoning_details` (>500 tokens) is compacted."""
        for i in range(11):
            self.ctx.messages.append(make_user(f"q{i}"))
            self.ctx.messages.append(
                make_assistant("ok", reasoning_details=long())
            )
        self.assertEqual(self.compact(), True)
        assistants = [m for m in self.ctx.messages if m["role"] == "assistant"]
        first = assistants[0]
        last = assistants[-1]
        self.assertIn("\n...\n", first.get("reasoning_details", ""))
        self.assertNotIn("\n...\n", last.get("reasoning_details", ""))


# ── 5. System & user messages ─────────────────────────────────────────────


class TestSystemAndUser(_SessionMemoryCompactBase):
    def test_11_system_messages_preserved(self):
        self.ctx.messages = [
            {"role": "system", "content": "You are a bot"},
            {"role": "system", "content": "Safety rules here"},
        ]
        for i in range(11):
            self.ctx.messages.extend(build_assistant_only_turn(long()))
        self.assertEqual(self.compact(), True)
        self.assertEqual(self.ctx.messages[0]["role"], "system")
        self.assertEqual(self.ctx.messages[1]["role"], "system")
        self.assertEqual(self.ctx.messages[0]["content"], "You are a bot")
        self.assertEqual(self.ctx.messages[1]["content"], "Safety rules here")

    def test_12_user_messages_in_old_turns_preserved(self):
        """All 15 user messages (including the oldest) must be preserved
        verbatim."""
        for i in range(15):
            self.ctx.messages.extend(build_assistant_only_turn(f"reply {i}"))
        self.assertEqual(self.compact(), True)
        users = [m for m in self.ctx.messages if m["role"] == "user"]
        self.assertEqual(len(users), 15)
        self.assertEqual(users[0]["content"], "user query")


# ── 6. Boundary cases ──────────────────────────────────────────────────────


class TestBoundaryCases(_SessionMemoryCompactBase):
    def test_13_empty_messages(self):
        # No messages at all → split_turns returns [] → compact returns False.
        self.assertEqual(self.compact(), False)
        self.assertEqual(len(self.ctx.messages), 0)

    def test_14_only_system(self):
        self.ctx.messages = [
            {"role": "system", "content": "sys1"},
            {"role": "system", "content": "sys2"},
        ]
        self.assertEqual(self.compact(), False)
        self.assertEqual(len(self.ctx.messages), 2)

    def test_15_one_turn_with_many_tools(self):
        """A single turn with many tools is still 1 turn, but if there
        are >10 turns total, old turns' tools still get replaced."""
        for i in range(12):
            self.ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=[
                    make_tc(f"c{i}_1"), make_tc(f"c{i}_2"), make_tc(f"c{i}_3"),
                ],
                tool_results=[
                    (f"c{i}_1", "read", long()),
                    (f"c{i}_2", "grep", long()),
                    (f"c{i}_3", "bash", long()),
                ],
                assistant_reply=f"done {i}",
            ))
        self.assertEqual(self.compact(), True)
        tools = [m for m in self.ctx.messages if m["role"] == "tool"]
        replaced = [m for m in tools if "force compacted" in m.get("content", "")]
        # 2 old turns × 3 tools each = 6 replaced tools.
        self.assertGreaterEqual(len(replaced), 6)

    def test_16_single_long_turn(self):
        """A single turn, even with many tools, is 1 turn → not triggered."""
        msgs = [
            make_user("complex task"),
            make_assistant("", [make_tc("c0")]),
        ]
        for i in range(30):
            msgs.append(make_tool(f"c{i}", "read", long(800)))
        msgs.append(make_assistant("done"))
        self.ctx.messages = msgs
        self.assertEqual(self.compact(), False)

    def test_17_assistant_content_is_list(self):
        """An assistant with list-typed content (Claude-style) is skipped
        (compactor only handles str content)."""
        for i in range(11):
            self.ctx.messages.append(make_user(f"q{i}"))
            self.ctx.messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": long()}],
            })
        self.assertEqual(self.compact(), True)
        assistants = [m for m in self.ctx.messages if m["role"] == "assistant"]
        # First assistant's content must still be a list (untouched).
        self.assertIsInstance(assistants[0]["content"], list)


# ── 7. retain_turns parameter ──────────────────────────────────────────────


class TestCustomRetainTurns(_SessionMemoryCompactBase):
    def test_18_custom_retain_turns(self):
        """retain_turns=3 → 7 old turns get compacted, last 3 are kept intact."""
        for i in range(10):
            self.ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=[make_tc(f"c{i}")],
                tool_results=[(f"c{i}", "read", long())],
                assistant_reply=f"reply {i}",
            ))
        result = self.compact(retain_turns=3)
        self.assertTrue(result)
        tools = [m for m in self.ctx.messages if m["role"] == "tool"]
        replaced = [m for m in tools if "force compacted" in m.get("content", "")]
        kept = [m for m in tools if "force compacted" not in m.get("content", "")]
        self.assertEqual(len(replaced), 7)
        self.assertEqual(len(kept), 3)


# ── 8. Message order invariants ───────────────────────────────────────────


class TestMessageOrder(_SessionMemoryCompactBase):
    def test_19_message_order_preserved(self):
        """After compaction, message roles must remain in the original
        order; no two consecutive tool messages can appear."""
        self.ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(12):
            self.ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=[make_tc(f"c{i}")],
                tool_results=[(f"c{i}", "read", long(2000))],
                assistant_reply=f"reply {i}",
            ))
        self.assertEqual(self.compact(), True)
        roles = [m["role"] for m in self.ctx.messages]
        self.assertEqual(roles[0], "system")
        self.assertEqual(roles[1], "user")  # first non-system must be user
        for i in range(1, len(roles)):
            self.assertFalse(
                roles[i] == "tool" and roles[i - 1] == "tool",
                "two consecutive tool messages detected",
            )


# ── 9. Comprehensive mixed scenario ────────────────────────────────────────


class TestComprehensiveMixed(_SessionMemoryCompactBase):
    def test_20_comprehensive_mixed(self):
        """15 mixed turns: pure-dialogue, single-tool, multi-tool, with
        varying content sizes. Verifies system intact, some old tools
        replaced, recent tools kept.
        """
        self.ctx.messages = [{"role": "system", "content": "system prompt"}]
        for i in range(15):
            if i % 3 == 0:
                # Pure-dialogue turn.
                self.ctx.messages.extend(build_assistant_only_turn(
                    long() if i < 5 else "short",
                ))
            elif i % 3 == 1:
                # Single-tool turn.
                self.ctx.messages.extend(build_turn(
                    f"with tools {i}",
                    assistant_tc=[make_tc(f"c{i}")],
                    tool_results=[(f"c{i}", "grep", long())],
                    assistant_reply=long() if i < 5 else "ok",
                    reasoning=long() if i < 5 else None,
                ))
            else:
                # Multi-tool turn.
                self.ctx.messages.extend(build_turn(
                    f"multi tools {i}",
                    assistant_tc=[make_tc(f"c{i}_a"), make_tc(f"c{i}_b")],
                    tool_results=[
                        (f"c{i}_a", "read", long()),
                        (f"c{i}_b", "bash", long()),
                    ],
                    assistant_reply=f"all done {i}",
                ))
        self.assertEqual(self.compact(), True)
        # system intact
        self.assertEqual(self.ctx.messages[0]["role"], "system")
        # Some tools replaced, at least 10 tools kept (recent turns).
        tools = [m for m in self.ctx.messages if m["role"] == "tool"]
        replaced = [m for m in tools if "force compacted" in m.get("content", "")]
        kept = [m for m in tools if "force compacted" not in m.get("content", "")]
        self.assertGreater(len(replaced), 0)
        self.assertGreaterEqual(len(kept), 10)
        # system not compacted.
        for m in self.ctx.messages:
            if m["role"] == "system":
                self.assertNotIn("...", m["content"])


# ── 10. Realistic 16-turn scenario ─────────────────────────────────────────


class TestRealScenario(_SessionMemoryCompactBase):
    def test_21_real_scenario_with_output(self):
        """Simulate a 16-turn coding session (6 old + 10 recent)."""
        self.ctx.messages = [
            {"role": "system", "content": "You are a helpful coding assistant. Be concise."},
        ]

        # Turn 1: bash (file structure)
        self.ctx.messages.extend(build_turn(
            "帮我看看这个项目的文件结构",
            assistant_tc=[make_tc("c1")],
            tool_results=[("c1", "bash", ".\n├── mangopi_cli.py (1319 lines)\n" + ("x" * 2000))],
            assistant_reply="项目根目录包含主文件 mangopi_cli.py (1319行)。",
            reasoning="用户想看项目结构，先列文件。",
        ))
        # Turn 2: grep (class defs)
        self.ctx.messages.extend(build_turn(
            "搜索所有 class 定义",
            assistant_tc=[make_tc("c2", "grep", '{"pat": "^class "}')],
            tool_results=[("c2", "grep", "mangopi_cli.py:435:class ToolBase:\n" * 200)],
            assistant_reply="找到 6 个 class。",
            reasoning="class 定义集中。",
        ))
        # Turn 3: read (ToolBase)
        self.ctx.messages.extend(build_turn(
            "读取 ToolBase 类的实现",
            assistant_tc=[make_tc("c3", "read", '{"path": "mangopi_cli.py"}')],
            tool_results=[("c3", "read", "class ToolBase:\n" * 200)],
            assistant_reply="ToolBase 定义了 6 个钩子方法。",
            reasoning=("分析 ToolBase 设计..." * 30),
        ))
        # Turn 4: pure dialogue
        self.ctx.messages.extend(build_assistant_only_turn(
            "这些工具的设计模式有什么优缺点？",
            reasoning=("思考中..." * 30),
        ))
        # Turn 5: multi-tool (grep + read)
        self.ctx.messages.extend(build_turn(
            "检查 ContextManager 和 deploy.sh",
            assistant_tc=[
                make_tc("c5a", "grep", '{"pat": "def "}'),
                make_tc("c5b", "read", '{"path": "deploy.sh"}'),
            ],
            tool_results=[
                ("c5a", "grep", "def micro_compact\n" * 200),
                ("c5b", "read", "#!/bin/bash\n" * 200),
            ],
            assistant_reply="ContextManager 有 micro_compact 等方法。",
            reasoning="需要同时查看两个文件。",
        ))
        # Turn 6: bash (tests)
        self.ctx.messages.extend(build_turn(
            "运行项目测试",
            assistant_tc=[make_tc("c6", "bash", '{"cmd": "pytest -v"}')],
            tool_results=[("c6", "bash", "test_tools.py::test_read PASSED\n" * 200)],
            assistant_reply="全部通过。",
            reasoning="测试结果良好。",
        ))

        # Turns 7-16: recent (preserved verbatim).
        for i in range(7, 17):
            if i % 3 == 0:
                self.ctx.messages.extend(build_assistant_only_turn(
                    f"第 {i} 轮纯文本回复。" + (" 填充 " * 30),
                    reasoning=f"第 {i} 轮推理。" + (" reason " * 30),
                ))
            elif i % 3 == 1:
                self.ctx.messages.extend(build_turn(
                    f"q{i}: 搜索 turn_{i}",
                    assistant_tc=[make_tc(f"c{i}", "grep", f'{{"pat": "turn_{i}"}}')],
                    tool_results=[(f"c{i}", "grep", f"file.py:{i}: turn_{i}\n" * 200)],
                    assistant_reply=f"找到 turn_{i}。",
                    reasoning=f"搜索 turn_{i}..." + (" reason " * 30),
                ))
            else:
                self.ctx.messages.extend(build_turn(
                    f"q{i}: 处理 turn_{i}",
                    assistant_tc=[
                        make_tc(f"c{i}a", "read", '{"path": "x.py"}'),
                        make_tc(f"c{i}b", "grep", '{"pat": "y"}'),
                    ],
                    tool_results=[
                        (f"c{i}a", "read", f"read {i}\n" * 200),
                        (f"c{i}b", "grep", f"grep {i}\n" * 200),
                    ],
                    assistant_reply=f"turn_{i} 处理完成。",
                    reasoning=f"处理 turn_{i}..." + (" T " * 30),
                ))

        total_before = self.ctx.total_tokens()
        result = self.compact()
        total_after = self.ctx.total_tokens()
        print(
            f"\n  session_memory_compact: tokens {total_before} → {total_after} "
            f"(Δ={total_after - total_before})"
        )

        self.assertTrue(result)
        self.assertLess(total_after, total_before)
        # At least 1 old tool was replaced.
        tools = [m for m in self.ctx.messages if m.get("role") == "tool"]
        replaced = [m for m in tools if "force compacted" in m.get("content", "")]
        kept = [m for m in tools if "force compacted" not in m.get("content", "")]
        self.assertGreaterEqual(len(replaced), 1)
        self.assertGreaterEqual(len(kept), 1)
        # system and user messages must not have been touched.
        for m in self.ctx.messages:
            if m["role"] in ("system", "user"):
                self.assertNotIn("force compacted", m.get("content", ""))


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)