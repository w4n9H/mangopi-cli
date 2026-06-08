"""Tests for ContextManager.micro_compact() — selective per-tool-message
content compaction.

micro_compact walks every message in `self.messages` and, for each tool
message that is:
    * not on the white-list (`attempt_completion`),
    * old enough (`now - ts >= tool rule max_age = 21_600s = 6h`),
    * large enough (`estimated_tokens({"content": content}) > rule max_tokens = 800`),
    * not already compacted (content does not end with `<compacted>`),
    * not binary (content is not a list),
replaces `m["content"]` with `compact_text(content, head=200, tail=200)`,
i.e. keeps the first 200 and last 200 chars with a `\\n...\\n` middle.

Covers:
    * old tool → compacted
    * new tool → untouched
    * boundary at exactly 6h
    * sub-6h messages (5.9h) untouched
    * user / assistant messages skipped (only `role == "tool"` eligible)
    * white-list tool (`attempt_completion`) skipped
    * already-compacted (`<compacted>` suffix) skipped on second pass
    * small content / min-tokens threshold
    * summary that is no smaller than the original → no compaction
    * mixed message stream (multiple ages, multiple roles)
    * empty / whitespace-only content
    * messages without `ts` field treated as fresh
    * compaction format (`\\n...\\n<compacted>`)
    * idempotency
    * no-tool-messages no-op
    * realistic multi-turn scenario
"""
import os
import sys
import time
import unittest

# Add parent dir to sys.path so we can import mangopi_cli.
# This file lives at <project>/test/test_micro_compact.py,
# so the project root is one level up from __file__'s directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangopi_cli import ContextManager  # noqa: E402


# ── Module-level message builders ────────────────────────────────────────────
#
# `long_text()` returns content larger than the tool-rule `max_tokens=800`
# threshold (i.e. ≈ 4 KB of plain text). Most "should compact" tests below
# use the no-arg form to get a reliably-eligible size.

def _now_ts():
    return int(time.time())


def long_text(n_chars=4000):
    """Default size: 4000 chars, which exceeds `tool.max_tokens=800` for
    the current `estimated_tokens` rule (≈ N/4 + 7)."""
    return "x" * n_chars


def make_tool_msg(tool_call_id, tool_name, content, hours_ago=0):
    """Build a tool message with `ts` set to `hours_ago` ago."""
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "content": content,
        "ts": _now_ts() - hours_ago * 3600,
    }


def make_user_msg(content, hours_ago=0):
    return {"role": "user", "content": content, "ts": _now_ts() - hours_ago * 3600}


def make_assistant_msg(content, hours_ago=0):
    return {
        "role": "assistant", "content": content, "ts": _now_ts() - hours_ago * 3600,
    }


# ── Shared base: each test gets a fresh ContextManager ─────────────────────


class _MicroCompactBase(unittest.TestCase):
    """Base: provides a fresh ContextManager per test plus a `compact()`
    convenience wrapper that mirrors the original test body shape.
    """

    def setUp(self):
        self.ctx = ContextManager()

    def compact(self):
        """Run micro_compact on the shared self.ctx."""
        self.ctx.micro_compact()

    def _content(self, idx):
        return self.ctx.messages[idx]["content"]


# ── 1. Old tool gets compacted ──────────────────────────────────────────────


class TestOldToolGetsCompacted(_MicroCompactBase):
    def test_01_old_tool_gets_compacted(self):
        self.ctx.messages = [
            make_tool_msg("c1", "read", long_text(), hours_ago=7),
        ]
        self.compact()
        content = self._content(0)
        self.assertTrue(
            content.endswith("<compacted>"),
            f"old tool should be compacted; got tail: {content[-40:]!r}",
        )
        self.assertLess(len(content), 500)


# ── 2. New tool not compacted ───────────────────────────────────────────────


class TestNewToolNotCompacted(_MicroCompactBase):
    def test_02_new_tool_not_compacted(self):
        self.ctx.messages = [
            make_tool_msg("c1", "read", long_text(), hours_ago=1),
        ]
        self.compact()
        content = self._content(0)
        self.assertFalse(content.endswith("<compacted>"))
        self.assertEqual(len(content), len(long_text()))


# ── 3 & 4. Boundary at exactly 6h and just under 6h ─────────────────────────


class TestSixHourBoundary(_MicroCompactBase):
    def test_03_exactly_6_hours(self):
        # max_age check uses `_age >= rule["max_age"]`, so 21600s triggers.
        self.ctx.messages = [
            make_tool_msg("c1", "read", long_text(), hours_ago=6),
        ]
        self.compact()
        self.assertTrue(self._content(0).endswith("<compacted>"))

    def test_04_just_under_6_hours(self):
        self.ctx.messages = [
            make_tool_msg("c1", "read", long_text(), hours_ago=5.9),
        ]
        self.compact()
        self.assertFalse(self._content(0).endswith("<compacted>"))


# ── 5 & 6. Only `tool` messages are eligible ────────────────────────────────


class TestNonToolRolesSkipped(_MicroCompactBase):
    def test_05_user_message_not_compacted(self):
        self.ctx.messages = [
            make_user_msg(long_text(), hours_ago=10),
        ]
        self.compact()
        self.assertFalse(self._content(0).endswith("<compacted>"))

    def test_06_assistant_message_not_compacted(self):
        self.ctx.messages = [
            make_assistant_msg(long_text(), hours_ago=10),
        ]
        self.compact()
        self.assertFalse(self._content(0).endswith("<compacted>"))


# ── 7. White-list tool skipped ─────────────────────────────────────────────


class TestWhitelistToolSkipped(_MicroCompactBase):
    def test_07_whitelist_tool_not_compacted(self):
        self.ctx.messages = [
            make_tool_msg(
                "c1", "attempt_completion", long_text(), hours_ago=10,
            ),
        ]
        self.compact()
        self.assertFalse(self._content(0).endswith("<compacted>"))


# ── 8. Already-compacted skipped on second pass ─────────────────────────────


class TestAlreadyCompactedSkipped(_MicroCompactBase):
    def test_08_already_compacted_skipped(self):
        original_compacted = long_text(200) + "<compacted>"
        self.ctx.messages = [
            # Pre-compacted (suffix marker) → must not change.
            make_tool_msg("c1", "read", original_compacted, hours_ago=10),
            # Old + big → must be compacted.
            make_tool_msg("c2", "bash", long_text(), hours_ago=10),
        ]
        self.compact()
        # First message: unchanged.
        self.assertEqual(self._content(0), original_compacted)
        # Second message: now has the marker.
        self.assertTrue(self._content(1).endswith("<compacted>"))


# ── 9 & 10. Small content / non-shrinking summary ───────────────────────────


class TestSmallContentAndSummary(_MicroCompactBase):
    def test_09_small_content_not_compacted(self):
        # 9 chars; estimated_tokens is tiny (< 800 threshold).
        self.ctx.messages = [
            make_tool_msg("c1", "read", "tiny text", hours_ago=10),
        ]
        self.compact()
        self.assertEqual(self._content(0), "tiny text")

    def test_10_summary_not_smaller(self):
        """160-char content: head(80)+tail(80)=160 == len, so compact_text
        returns the original unchanged (no `<compacted>` marker)."""
        text = "A" * 160
        self.ctx.messages = [make_tool_msg("c1", "read", text, hours_ago=10)]
        self.compact()
        self.assertFalse(self._content(0).endswith("<compacted>"))


# ── 11. Mixed message stream ───────────────────────────────────────────────


class TestMixedMessages(_MicroCompactBase):
    def test_11_mixed_messages(self):
        self.ctx.messages = [
            make_tool_msg("c1", "read", long_text(), hours_ago=10),   # old tool → compact
            make_user_msg("hello user", hours_ago=10),                  # user → skip
            make_tool_msg("c2", "bash", long_text(), hours_ago=1),     # new tool → skip
            make_assistant_msg(long_text(), hours_ago=10),              # assistant → skip
            make_tool_msg("c3", "read", long_text(), hours_ago=12),    # old tool → compact
        ]
        self.compact()
        self.assertTrue(self._content(0).endswith("<compacted>"))
        self.assertFalse(self._content(1).endswith("<compacted>"))
        self.assertFalse(self._content(2).endswith("<compacted>"))
        self.assertFalse(self._content(3).endswith("<compacted>"))
        self.assertTrue(self._content(4).endswith("<compacted>"))


# ── 12. Empty messages list ────────────────────────────────────────────────


class TestEmptyMessages(_MicroCompactBase):
    def test_12_empty_messages(self):
        self.ctx.messages = []
        self.compact()
        self.assertEqual(len(self.ctx.messages), 0)


# ── 13. Missing `ts` field treated as fresh ────────────────────────────────


class TestMissingTsField(_MicroCompactBase):
    def test_13_no_ts_field(self):
        self.ctx.messages = [{
            "role": "tool",
            "tool_call_id": "c1",
            "tool_name": "read",
            "content": "some content",
        }]
        self.compact()
        # No ts → m.get("ts", now) returns now → now - now = 0 < max_age.
        self.assertFalse(self._content(0).endswith("<compacted>"))


# ── 14. Compaction format includes the `\n...\n` separator ──────────────────


class TestCompactedFormat(_MicroCompactBase):
    def test_14_compacted_format(self):
        self.ctx.messages = [
            make_tool_msg("c1", "read", long_text(), hours_ago=10),
        ]
        self.compact()
        content = self._content(0)
        self.assertTrue(content.endswith("<compacted>"))
        self.assertIn("\n...\n", content)


# ── 15 & 16. Empty / whitespace-only content ────────────────────────────────


class TestEmptyAndWhitespaceContent(_MicroCompactBase):
    def test_15_empty_content(self):
        self.ctx.messages = [
            make_tool_msg("c1", "read", "", hours_ago=10),
        ]
        self.compact()
        self.assertEqual(self._content(0), "")

    def test_16_whitespace_content(self):
        # compact_text strips first, then returns "" for empty.
        self.ctx.messages = [
            make_tool_msg("c1", "read", "   \n  \t  ", hours_ago=10),
        ]
        self.compact()
        self.assertFalse(self._content(0).endswith("<compacted>"))


# ── 17. Multiple ages in one stream ─────────────────────────────────────────


class TestMultipleAges(_MicroCompactBase):
    def test_17_multiple_ages(self):
        self.ctx.messages = [
            make_tool_msg("c1", "read", long_text(), hours_ago=20),  # compact
            make_tool_msg("c2", "bash", long_text(), hours_ago=10),  # compact
            make_tool_msg("c3", "grep", long_text(), hours_ago=3),   # skip
            make_tool_msg("c4", "read", long_text(), hours_ago=1),   # skip
            make_tool_msg("c5", "bash", long_text(), hours_ago=8),   # compact
        ]
        self.compact()
        self.assertTrue(self._content(0).endswith("<compacted>"))
        self.assertTrue(self._content(1).endswith("<compacted>"))
        self.assertFalse(self._content(2).endswith("<compacted>"))
        self.assertFalse(self._content(3).endswith("<compacted>"))
        self.assertTrue(self._content(4).endswith("<compacted>"))


# ── 18. At-min-tokens threshold (just above max_tokens=800) ─────────────────


class TestMinTokensThreshold(_MicroCompactBase):
    def test_18_at_min_token_threshold(self):
        # 4000 chars → estimated_tokens ≈ 1007 > 800 → compact.
        text = "A" * 4000
        self.ctx.messages = [make_tool_msg("c1", "read", text, hours_ago=10)]
        self.compact()
        self.assertTrue(self._content(0).endswith("<compacted>"))


# ── 19. Idempotency ────────────────────────────────────────────────────────


class TestIdempotent(_MicroCompactBase):
    def test_19_idempotent(self):
        self.ctx.messages = [
            make_tool_msg("c1", "read", long_text(), hours_ago=10),
        ]
        self.compact()
        first = self._content(0)
        # Second pass on already-compacted content is a no-op.
        self.compact()
        second = self._content(0)
        self.assertEqual(first, second)


# ── 20. No tool messages ───────────────────────────────────────────────────


class TestNoToolMessages(_MicroCompactBase):
    def test_20_no_tool_messages(self):
        self.ctx.messages = [
            make_user_msg("hello", hours_ago=10),
            make_assistant_msg("hi there", hours_ago=10),
            {"role": "system", "content": "you are a bot"},
        ]
        self.compact()
        self.assertEqual(self._content(0), "hello")
        self.assertEqual(self._content(1), "hi there")
        self.assertEqual(self._content(2), "you are a bot")


# ── 21. Realistic multi-turn scenario ───────────────────────────────────────


class TestRealScenario(_MicroCompactBase):
    def test_21_real_scenario_with_output(self):
        """Build a 5-turn coding session; verify which tool messages
        compact and which don't.

        Message layout (idx → role):
            0=system, 1=u, 2=a, 3=tool(grep, old), 4=a,
            5=u, 6=a, 7=tool(read, old),
            8=a, 9=a, 10=tool(attempt_completion, white-list),
            11=u, 12=a, 13=tool(bash, new),
            14=a, 15=u, 16=a, 17=tool(bash, small), 18=a
        """
        ts_old = _now_ts() - 8 * 3600
        ts_new = _now_ts() - 2 * 3600

        self.ctx.messages = [
            {"role": "system", "content": "You are a helpful coding assistant."},

            # Turn 1 (old): grep
            {"role": "user", "content": "分析项目中的搜索功能", "ts": ts_old},
            {"role": "assistant", "content": "我来搜索相关代码。",
             "reasoning_content": "用户想了解搜索功能。",
             "tool_calls": [{"id": "call_a1", "type": "function",
                             "function": {"name": "grep",
                                          "arguments": '{"pat": "def search"}'}}],
             "ts": ts_old},
            {"role": "tool", "tool_call_id": "call_a1", "tool_name": "grep",
             "content": ("src/search.py:42:def search_files\n" * 200),
             "ts": ts_old},
            {"role": "assistant",
             "content": "找到了 3 个搜索函数。",
             "ts": ts_old},

            # Turn 2 (old): read
            {"role": "user", "content": "读取 src/search.py", "ts": ts_old},
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "call_a2", "type": "function",
                             "function": {"name": "read",
                                          "arguments": '{"path": "src/search.py"}'}}],
             "ts": ts_old},
            {"role": "tool", "tool_call_id": "call_a2", "tool_name": "read",
             "content": ('"""Search module."""\n' * 500),
             "ts": ts_old},
            {"role": "assistant",
             "content": "已读取实现。",
             "ts": ts_old},

            # Turn 3 (old): attempt_completion (white-list)
            {"role": "assistant", "content": "完成分析。",
             "tool_calls": [{"id": "call_a3", "type": "function",
                             "function": {"name": "attempt_completion",
                                          "arguments": '{"result": "总结"}'}}],
             "ts": ts_old},
            {"role": "tool", "tool_call_id": "call_a3", "tool_name": "attempt_completion",
             "content": "任务已完成。" + ("summary details " * 200),
             "ts": ts_old},

            # Turn 4 (new): bash (big)
            {"role": "user", "content": "跑一下测试", "ts": ts_new},
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "call_a4", "type": "function",
                             "function": {"name": "bash",
                                          "arguments": '{"cmd": "pytest -v"}'}}],
             "ts": ts_new},
            {"role": "tool", "tool_call_id": "call_a4", "tool_name": "bash",
             "content": ("test_search.py::test_a PASSED\n" * 200),
             "ts": ts_new},
            {"role": "assistant", "content": "全部测试通过。", "ts": ts_new},

            # Turn 5 (new): bash (small)
            {"role": "user", "content": "当前哪个分支?", "ts": ts_new},
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "call_a5", "type": "function",
                             "function": {"name": "bash",
                                          "arguments": '{"cmd": "git branch --show-current"}'}}],
             "ts": ts_new},
            {"role": "tool", "tool_call_id": "call_a5", "tool_name": "bash",
             "content": "main\n", "ts": ts_new},
            {"role": "assistant", "content": "在 main 分支。", "ts": ts_new},
        ]

        total_tokens_before = self.ctx.total_tokens()
        self.compact()
        total_tokens_after = self.ctx.total_tokens()

        # Brief diagnostic.
        print(
            f"\n  micro_compact: tokens {total_tokens_before} → {total_tokens_after} "
            f"(Δ={total_tokens_after - total_tokens_before})"
        )

        # Tool messages at indices 3, 7, 10, 13, 17:
        self.assertTrue(self.ctx.messages[3]["content"].endswith("<compacted>"),
                        "Turn1 grep (old, big) should compact")
        self.assertTrue(self.ctx.messages[7]["content"].endswith("<compacted>"),
                        "Turn2 read (old, big) should compact")
        self.assertFalse(self.ctx.messages[10]["content"].endswith("<compacted>"),
                         "attempt_completion (white-list) must NOT compact")
        self.assertFalse(self.ctx.messages[13]["content"].endswith("<compacted>"),
                         "Turn4 bash (new) must NOT compact")
        self.assertFalse(self.ctx.messages[17]["content"].endswith("<compacted>"),
                         "Turn5 bash (small content) must NOT compact")
        # Tokens should decrease overall.
        self.assertLess(total_tokens_after, total_tokens_before)


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)