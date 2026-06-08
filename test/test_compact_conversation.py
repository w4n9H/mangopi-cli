"""Tests for ContextManager.compact_conversation() — turn-level token
discard strategy.

Covers:
    * Empty messages / system-only — no-op
    * Under-threshold — nothing discarded
    * Over-threshold with no old turns — discard recent turns to floor of 1
    * Over-threshold with old turns — discard old turns turn-by-turn
    * Old turns fully discarded but still over — discard recent turns
    * System messages are always preserved
    * Message order preserved (system → user → assistant → ...)
    * Messages themselves are deep-copied, not mutated
    * retain_turns parameter
    * Tool-call turns discarded as atomic units
    * Realistic 14-turn coding-session scenario
"""
import copy
import os
import sys
import unittest

# Add parent dir to sys.path so we can import mangopi_cli.
# This file lives at <project>/test/test_compact_conversation.py,
# so the project root is one level up from __file__'s directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangopi_cli import ContextManager  # noqa: E402


# ── Message builders (module-level helpers) ─────────────────────────────────


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
    """Long filler string used to push messages past the token threshold."""
    return "X" * n


def build_turn(user_text, assistant_tc=None, tool_results=None,
               assistant_reply=None, reasoning=None):
    """Build a full turn: user → assistant(tc) → tool... → assistant(reply)."""
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
    """Pure conversation turn: user → assistant (no tools)."""
    return [make_user(user_text), make_assistant(assistant_text)]


# ── Shared base: each test gets a fresh ContextManager ─────────────────────


class _CompactConversationBase(unittest.TestCase):
    """Base: provides a fresh ContextManager per test plus a `compact()`
    convenience wrapper that mirrors the original test body shape.
    """

    def setUp(self):
        self.ctx = ContextManager()

    def compact(self, **kwargs):
        """Run compact_conversation on the shared self.ctx."""
        self.ctx.compact_conversation(**kwargs)


# ── 1. Empty messages / system-only — no-op ────────────────────────────────


class TestEmptyAndSystemOnly(_CompactConversationBase):
    """When there's nothing to compact, messages must be left alone."""

    def test_01_empty_messages(self):
        # ctx.messages starts as []; compact must not crash or change it.
        self.ctx.messages = []
        self.compact()
        self.assertEqual(len(self.ctx.messages), 0)

    def test_02_only_system(self):
        self.ctx.messages = [
            {"role": "system", "content": "sys1"},
            {"role": "system", "content": "sys2"},
        ]
        self.compact()
        self.assertEqual(len(self.ctx.messages), 2)
        self.assertEqual(self.ctx.messages[0]["content"], "sys1")
        self.assertEqual(self.ctx.messages[1]["content"], "sys2")


# ── 2. Under threshold — no turn discarded ─────────────────────────────────


class TestUnderThreshold(_CompactConversationBase):
    """When total tokens are below the threshold, no turns are discarded."""

    def test_03_under_threshold_no_trim(self):
        self.ctx.auto_compact_threshold = 50_000  # well above message total
        self.ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(5):
            self.ctx.messages.extend(build_simple_turn(f"q{i}", f"a{i}"))
        self.compact()
        self.assertEqual(len(self.ctx.messages), 11)
        users = [m for m in self.ctx.messages if m["role"] == "user"]
        self.assertEqual(len(users), 5)

    def test_04_over_threshold_no_old_turns_discard_recent(self):
        """6 turns with an ultra-low threshold → no old turns exist, so
        recent turns must be discarded down to a floor of 1."""
        self.ctx.auto_compact_threshold = 10
        self.ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(6):
            self.ctx.messages.extend(build_simple_turn(f"q{i}", long(500)))
        self.compact()
        users = [m["content"] for m in self.ctx.messages if m["role"] == "user"]
        self.assertEqual(len(users), 1)
        self.assertIn("q5", users)


# ── 3. Discarding old turns one at a time ─────────────────────────────────


class TestDiscardOldTurns(_CompactConversationBase):
    """When there are old turns and total exceeds the threshold, old turns
    are discarded one at a time until the total is back under threshold.
    """

    def _set_threshold_relative_to(self, n_turns_to_keep):
        """Compute the token threshold so that exactly the most recent
        n_turns_to_keep turns plus the system message will fit, while
        dropping the rest."""
        # system + n_turns_to_keep turns (= n_turns_to_keep*2 messages)
        keep_msg_count = 1 + n_turns_to_keep * 2
        kept = [self.ctx.messages[0]] + self.ctx.messages[-keep_msg_count * 1:]
        # The most recent keep_msg_count messages after the system message:
        kept = [self.ctx.messages[0]] + self.ctx.messages[-(keep_msg_count - 1):]
        total = sum(self.ctx.estimated_tokens(m) for m in kept)
        self.ctx.auto_compact_threshold = total + 5

    def test_05_discard_one_old_turn(self):
        """12 turns, threshold sized to drop the very first turn."""
        self.ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(12):
            self.ctx.messages.extend(build_simple_turn(f"q{i}", f"reply_{i}"))
        all_tokens = self.ctx.total_tokens()
        first_turn_tokens = (
            self.ctx.estimated_tokens(self.ctx.messages[1])
            + self.ctx.estimated_tokens(self.ctx.messages[2])
        )
        self.ctx.auto_compact_threshold = all_tokens - first_turn_tokens
        self.compact()
        users = [m["content"] for m in self.ctx.messages if m["role"] == "user"]
        self.assertNotIn("q0", users)
        self.assertIn("q1", users)
        self.assertIn("q11", users)

    def test_06_discard_multiple_old_turns(self):
        """12 turns, threshold sized to keep only 5 turns."""
        self.ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(12):
            self.ctx.messages.extend(build_simple_turn(f"turn_{i}", f"reply_{i}"))
        keep_5 = sum(self.ctx.estimated_tokens(m) for m in self.ctx.messages[:11])
        self.ctx.auto_compact_threshold = keep_5 + 10
        self.compact()
        users = [m["content"] for m in self.ctx.messages if m["role"] == "user"]
        self.assertEqual(len(users), 5)
        for i in range(7):
            self.assertNotIn(f"turn_{i}", users)
        for i in range(7, 12):
            self.assertIn(f"turn_{i}", users)


# ── 4. Old turns fully discarded but still over — discard recent turns ─────


class TestDiscardRecentTurns(_CompactConversationBase):
    """When even after dropping all old turns the conversation is still
    over the threshold, recent turns must be discarded down to a floor
    of 1 (system is always preserved).
    """

    def test_07_discard_recent_turns(self):
        self.ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(10):
            self.ctx.messages.extend(build_simple_turn(f"q{i}", long(500)))
        # Threshold sized to only hold the system + the LAST turn.
        keep_1 = (
            self.ctx.estimated_tokens(self.ctx.messages[0])
            + self.ctx.estimated_tokens(self.ctx.messages[-2])
            + self.ctx.estimated_tokens(self.ctx.messages[-1])
        )
        self.ctx.auto_compact_threshold = keep_1 + 5
        self.compact()
        users = [m["content"] for m in self.ctx.messages if m["role"] == "user"]
        self.assertEqual(len(users), 1)
        self.assertIn("q9", users)
        self.assertEqual(self.ctx.messages[0]["role"], "system")


# ── 5. System messages always preserved ────────────────────────────────────


class TestSystemAlwaysPreserved(_CompactConversationBase):
    def test_08_system_always_preserved(self):
        self.ctx.messages = [
            {"role": "system", "content": "sys A"},
            {"role": "system", "content": "sys B"},
        ]
        for i in range(12):
            self.ctx.messages.extend(build_simple_turn(f"q{i}", long(500)))
        # Threshold: only system + last turn.
        sys_tokens = sum(self.ctx.estimated_tokens(m) for m in self.ctx.messages[:2])
        one_turn = (
            self.ctx.estimated_tokens(self.ctx.messages[-2])
            + self.ctx.estimated_tokens(self.ctx.messages[-1])
        )
        self.ctx.auto_compact_threshold = sys_tokens + one_turn + 5
        self.compact()
        self.assertEqual(self.ctx.messages[0]["role"], "system")
        self.assertEqual(self.ctx.messages[1]["role"], "system")
        self.assertEqual(self.ctx.messages[0]["content"], "sys A")
        self.assertEqual(self.ctx.messages[1]["content"], "sys B")


# ── 6. Message order preserved ────────────────────────────────────────────


class TestMessageOrderPreserved(_CompactConversationBase):
    def test_09_message_order_preserved(self):
        self.ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(15):
            self.ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=[make_tc(f"c{i}")],
                tool_results=[(f"c{i}", "read", long(300))],
                assistant_reply=f"reply {i}",
            ))
        # Keep just the last 2 turns (each = 4 messages).
        last_2_turns_tokens = sum(
            self.ctx.estimated_tokens(m) for m in self.ctx.messages[-8:]
        )
        sys_tokens = self.ctx.estimated_tokens(self.ctx.messages[0])
        self.ctx.auto_compact_threshold = sys_tokens + last_2_turns_tokens + 10
        self.compact()
        roles = [m["role"] for m in self.ctx.messages]
        self.assertEqual(roles[0], "system")
        # First non-system role must be 'user'.
        for r in roles[1:]:
            if r != "system":
                self.assertEqual(r, "user")
                break
        users = [m for m in self.ctx.messages if m["role"] == "user"]
        self.assertGreaterEqual(len(users), 1)


# ── 7. Messages themselves not mutated ─────────────────────────────────────


class TestMessagesNotModified(_CompactConversationBase):
    def test_10_messages_not_modified(self):
        self.ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(12):
            self.ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=[make_tc(f"c{i}")],
                tool_results=[(f"c{i}", "read", long(300))],
                assistant_reply=f"reply {i} with extra " + long(200),
                reasoning=long(250) if i < 2 else None,
            ))
        # Threshold: keep system + last 4 turns (= 16 messages).
        self.ctx.auto_compact_threshold = self.ctx.estimated_tokens(self.ctx.messages[0])
        for m in self.ctx.messages[-16:]:
            self.ctx.auto_compact_threshold += self.ctx.estimated_tokens(m)
        self.ctx.auto_compact_threshold += 5
        self.compact()
        tools = [m for m in self.ctx.messages if m["role"] == "tool"]
        for tool in tools:
            self.assertNotIn("force compacted", tool["content"])
            self.assertTrue(tool["content"].startswith(long(300)[:10]))
        assistants_with_tc = [
            m for m in self.ctx.messages
            if m["role"] == "assistant" and "tool_calls" in m
        ]
        for a in assistants_with_tc:
            self.assertIn("tool_calls", a)


# ── 8. retain_turns parameter ─────────────────────────────────────────────


class TestCustomRetainTurns(_CompactConversationBase):
    def test_11_custom_retain_turns(self):
        """retain_turns=3 → only the most recent 3 turns are 'recent'; the
        older turns are eligible to be discarded."""
        self.ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(10):
            self.ctx.messages.extend(build_simple_turn(f"q{i}", f"a{i}"))
        all_tokens = self.ctx.total_tokens()
        first_turn = (
            self.ctx.estimated_tokens(self.ctx.messages[1])
            + self.ctx.estimated_tokens(self.ctx.messages[2])
        )
        self.ctx.auto_compact_threshold = all_tokens - first_turn
        self.compact(retain_turns=3)
        users = [m["content"] for m in self.ctx.messages if m["role"] == "user"]
        self.assertNotIn("q0", users)
        for i in range(1, 10):
            self.assertIn(f"q{i}", users)


# ── 9. Tool-call turns discarded as a unit ────────────────────────────────


class TestToolTurnsDiscardedTogether(_CompactConversationBase):
    def test_12_tool_turns_discarded_together(self):
        """An entire turn (user + assistant(tc) + tool + assistant(reply))
        must be either fully kept or fully discarded.
        """
        self.ctx.messages = [{"role": "system", "content": "sys"}]
        for i in range(12):
            self.ctx.messages.extend(build_turn(
                f"q{i}",
                assistant_tc=[make_tc(f"c{i}")],
                tool_results=[(f"c{i}", "read", long(300))],
                assistant_reply=f"reply {i}",
            ))
        # Threshold: keep system + last 3 turns (12 messages).
        keep = self.ctx.estimated_tokens(self.ctx.messages[0])
        for m in self.ctx.messages[-12:]:
            keep += self.ctx.estimated_tokens(m)
        self.ctx.auto_compact_threshold = keep + 10
        self.compact()
        users = [m["content"] for m in self.ctx.messages if m["role"] == "user"]
        self.assertEqual(len(users), 3)
        for i in range(9, 12):
            self.assertIn(f"q{i}", users)
        tools = [m for m in self.ctx.messages if m["role"] == "tool"]
        self.assertEqual(len(tools), 3)


# ── 10. Realistic 14-turn coding-session scenario ──────────────────────────


class TestRealScenario(_CompactConversationBase):
    """End-to-end simulation: build a 14-turn coding session with mixed
    simple/tool turns and verify compact_conversation drops old turns
    while preserving recent ones.
    """

    @staticmethod
    def _build_full_session():
        """Construct the 14-turn session exactly as the original test did."""
        msgs = [{"role": "system", "content": "You are a coding assistant. Be thorough and precise."}]
        # Turns 1-4: early exploration with large tool results.
        for i in range(1, 5):
            msgs.extend(build_turn(
                f"读取项目中的 core_{i}.py",
                assistant_tc=[make_tc(f"c{i}", "read", f'{{"path": "core_{i}.py"}}')],
                tool_results=[(f"c{i}", "read", f"# core_{i}.py\n" + long(1200))],
                assistant_reply=f"core_{i}.py 包含核心逻辑 {i}。" + long(300),
                reasoning=f"分析 core_{i}.py 的架构..." + long(400),
            ))
        # Turn 5: a pure dialogue turn.
        msgs.extend(build_simple_turn(
            "这些核心模块之间的依赖关系是什么？",
            "模块之间存在循环依赖，core_1 依赖 core_2，core_2 依赖 core_3..." + long(500),
        ))
        # Turns 6-9: mid-stream debugging (grep + bash).
        for i in range(6, 10):
            msgs.extend(build_turn(
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
        # Turns 10-14: latest work (compact).
        for i in range(10, 15):
            msgs.extend(build_turn(
                f"最终优化 pass_{i}",
                assistant_tc=[make_tc(f"c{i}", "write", f'{{"path": "opt_{i}.py"}}')],
                tool_results=[(f"c{i}", "write", f"Written opt_{i}.py ({i*10} lines)")],
                assistant_reply=f"opt_{i}.py 已创建。",
            ))
        return msgs

    def _build_14_turn_session(self):
        """Same as _build_full_session() but as an instance method (needed
        because we want to use self.ctx.estimated_tokens)."""
        return self._build_full_session()

    def test_13_real_scenario_with_output(self):
        """Build the 14-turn session, capture before/after stats, and
        verify the documented invariants:
            * turns_after < turns_before
            * total_after < total_before
            * system message is still first
            * no tool message has been mutated to contain 'force compacted'
        """
        # Save the constructed messages BEFORE compact, so we can compute
        # 'before' stats (ctx.messages is mutated by compact).
        before_messages = self._build_full_session()
        self.ctx.messages = copy.deepcopy(before_messages)

        total_before = self.ctx.total_tokens()
        turns_before = self.ctx.split_turns()

        # Threshold sized to retain system + last 6 turns (4 msgs each).
        sys_tokens = self.ctx.estimated_tokens(self.ctx.messages[0])
        recent_msg_count = 6 * 4
        keep_tokens = sys_tokens + sum(
            self.ctx.estimated_tokens(m)
            for m in self.ctx.messages[-recent_msg_count:]
        )
        self.ctx.auto_compact_threshold = keep_tokens + 15

        self.compact()

        total_after = self.ctx.total_tokens()
        turns_after = self.ctx.split_turns()

        # Print a brief before/after summary so the test still doubles as
        # a useful diagnostic when run with `-v`.
        print(
            f"\n  turns: {len(turns_before)} → {len(turns_after)}; "
            f"tokens: {total_before} → {total_after}; "
            f"msgs: {len(before_messages)} → {len(self.ctx.messages)}"
        )

        # Invariants:
        self.assertLess(len(turns_after), len(turns_before))
        self.assertLess(total_after, total_before)
        self.assertEqual(self.ctx.messages[0]["role"], "system")
        for m in self.ctx.messages:
            if m["role"] == "tool":
                self.assertNotIn("force compacted", m.get("content", ""))


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)