"""Unit tests for Flash-ext — thinking framework injection & FlashExtServer augmentation.

Covers:
    1. FlashThinking.match()        — keyword + tool-pattern phase detection
    2. FlashThinking.inject()       — framework steps injected as system message
    3. ContextManager.tool_pattern() — recent tool name extraction
    4. ContextManager.detect_loop()  — same-tool & alternating loop detection
    5. ContextManager.detect_phase() — phase inference
    6. ContextManager.assess_complexity() — deep vs fast decision
    7. ContextManager.summarize_recent_turns() — message compression
    8. FlashExtServer._augment()    — deep/fast path routing & framework injection
    9. FlashExtServer._analyze_deep() — JSON parse protection & fallback

No real network calls — _request and provider are mocked.
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, Mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mangopi_cli  # noqa: E402
from mangopi_cli import (  # noqa: E402
    ContextManager, FlashThinking, FlashExtServer,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_ctx(messages=None):
    ctx = ContextManager()
    ctx.clear()
    if messages:
        ctx.messages = list(messages)
    return ctx


def _tool_msg(name, content="ok"):
    return {"role": "tool", "tool_name": name, "content": content}


def _user_msg(content):
    return {"role": "user", "content": content}


def _make_server(provider_obj=None):
    srv = FlashExtServer(host="127.0.0.1", port=9999, provider_obj=provider_obj or MagicMock(),
                         enable_memory=False, enable_search=False)
    srv.logger = MagicMock()
    return srv


# ── FlashThinking ────────────────────────────────────────────────────────────

class FlashThinkingMatchTests(unittest.TestCase):
    def setUp(self):
        self.ft = FlashThinking()

    def test_keyword_debug(self):
        self.assertEqual(self.ft.match("排查 crash 问题"), "debug")
        self.assertEqual(self.ft.match("fix error"), "debug")

    def test_keyword_design(self):
        self.assertEqual(self.ft.match("设计一个架构"), "design")
        self.assertEqual(self.ft.match("architecture review"), "design")

    def test_keyword_explain(self):
        self.assertEqual(self.ft.match("解释一下原理"), "explain")
        self.assertEqual(self.ft.match("what is decorator"), "explain")

    def test_keyword_optimize(self):
        self.assertEqual(self.ft.match("优化性能"), "optimize")
        self.assertEqual(self.ft.match("performance tuning"), "optimize")

    def test_keyword_implement(self):
        self.assertEqual(self.ft.match("实现一个cache"), "implement")
        self.assertEqual(self.ft.match("create a REST API"), "implement")

    def test_tool_pattern_exploring(self):
        self.assertEqual(self.ft.match("anything", ["read", "grep", "search"]), "investigate")

    def test_tool_pattern_executing(self):
        self.assertEqual(self.ft.match("anything", ["read", "edit", "read"]), "implement")

    def test_tool_pattern_verifying(self):
        self.assertEqual(self.ft.match("anything", ["bash", "read", "bash"]), "verify")

    def test_tool_pattern_priority_over_keyword(self):
        # tool pattern (verifying) wins over keyword (debug)
        self.assertEqual(self.ft.match("排查 bug", ["bash", "bash", "read"]), "verify")

    def test_no_match(self):
        self.assertIsNone(self.ft.match("hello world"))


# ── ContextManager new methods ───────────────────────────────────────────────

class ToolPatternTests(unittest.TestCase):
    def test_extracts_recent_tools(self):
        ctx = _make_ctx([_tool_msg("read"), _tool_msg("edit"), _tool_msg("bash")])
        self.assertEqual(ctx.tool_pattern(), ["read", "edit", "bash"])

    def test_returns_none_when_empty(self):
        ctx = _make_ctx()
        self.assertIsNone(ctx.tool_pattern())

    def test_respects_n_limit(self):
        ctx = _make_ctx([_tool_msg("a")] * 20)
        self.assertEqual(len(ctx.tool_pattern(n=5)), 5)


class DetectLoopTests(unittest.TestCase):
    def test_same_tool_consecutive_fail(self):
        ctx = _make_ctx(
            [_tool_msg("edit", "fail")] * 4 +
            [_tool_msg("read", "ok")] * 8
        )
        is_loop, tool = ctx.detect_loop()
        self.assertTrue(is_loop)
        self.assertEqual(tool, "edit")

    def test_alternating_loop(self):
        msgs = []
        for _ in range(6):
            msgs.append(_tool_msg("read", "fail"))
            msgs.append(_tool_msg("edit", "error"))
        ctx = _make_ctx(msgs)
        is_loop, tools = ctx.detect_loop()
        self.assertTrue(is_loop)
        self.assertIn("edit", tools)
        self.assertIn("read", tools)

    def test_no_loop_when_few_tools(self):
        ctx = _make_ctx([_tool_msg("read", "ok")] * 3)
        is_loop, _ = ctx.detect_loop()
        self.assertFalse(is_loop)

    def test_no_loop_when_success(self):
        ctx = _make_ctx([_tool_msg("read", "ok")] * 12)
        is_loop, _ = ctx.detect_loop()
        self.assertFalse(is_loop)


class DetectPhaseTests(unittest.TestCase):
    def test_start(self):
        ctx = _make_ctx()
        self.assertEqual(ctx.detect_phase(), "start")

    def test_exploring(self):
        ctx = _make_ctx([_tool_msg("read"), _tool_msg("grep"), _tool_msg("read")])
        self.assertEqual(ctx.detect_phase(), "exploring")

    def test_executing(self):
        ctx = _make_ctx([_tool_msg("read"), _tool_msg("edit")])
        self.assertEqual(ctx.detect_phase(), "executing")

    def test_verifying(self):
        ctx = _make_ctx([_tool_msg("bash"), _tool_msg("bash"), _tool_msg("read")])
        self.assertEqual(ctx.detect_phase(), "verifying")

    def test_stuck_when_looping(self):
        ctx = _make_ctx([_tool_msg("edit", "fail")] * 10)
        self.assertEqual(ctx.detect_phase(), "stuck")


class AssessComplexityTests(unittest.TestCase):
    def test_returns_fast_for_short_simple(self):
        ctx = _make_ctx([_tool_msg("read"), _user_msg("what is this")])
        self.assertEqual(ctx.assess_complexity(), "fast")

    def test_returns_deep_for_large_context(self):
        # 5 large tool results → total tool_context > 2000
        ctx = _make_ctx([_user_msg("q")] + [_tool_msg("read", "x" * 2100) for _ in range(5)])
        self.assertEqual(ctx.assess_complexity(), "deep")
        self.assertEqual(ctx.assess_complexity(), "deep")

    def test_returns_deep_for_diverse_tools(self):
        ctx = _make_ctx([_tool_msg("read"), _tool_msg("edit"), _tool_msg("bash")])
        self.assertEqual(ctx.assess_complexity(), "deep")

    def test_returns_deep_for_repetitive_tool(self):
        ctx = _make_ctx([_tool_msg("edit")] * 6)
        self.assertEqual(ctx.assess_complexity(), "deep")

    def test_returns_deep_for_design_keywords(self):
        ctx = _make_ctx([_tool_msg("read"), _user_msg("设计一个分布式系统")])
        self.assertEqual(ctx.assess_complexity(), "deep")


class SummarizeRecentTurnsTests(unittest.TestCase):
    def test_compresses_user_and_tool_messages(self):
        ctx = _make_ctx([
            _user_msg("read main.py"),
            _tool_msg("read", "file content here"),
            {"role": "assistant", "content": "found the function"},
        ])
        summary = ctx.summarize_recent_turns(n_turns=1)
        self.assertIn("[USER] read main.py", summary)
        self.assertIn("[read] file content here", summary)

    def test_includes_assistant_tool_calls(self):
        ctx = _make_ctx([
            _user_msg("fix it"),
            {"role": "assistant", "tool_calls": [{"name": "edit"}, {"name": "bash"}]},
        ])
        summary = ctx.summarize_recent_turns(n_turns=1)
        self.assertIn("edit,bash", summary)

    def test_truncates_content(self):
        ctx = _make_ctx([_user_msg("x" * 500)])
        summary = ctx.summarize_recent_turns()
        self.assertLessEqual(len(summary), 350)


# ── FlashExtServer _augment ──────────────────────────────────────────────────

class FlashExtServerAugmentTests(unittest.TestCase):
    def setUp(self):
        self.srv = _make_server()
        # Mock _analyze_deep to return None by default (fast path)
        self.srv._analyze_deep = MagicMock(return_value=None)

    def _last_user_content(self, messages):
        for m in reversed(messages):
            if m.get("role") == "user":
                return m.get("content", "")
        return ""

    def test_fast_path_injects_keyword_framework(self):
        msgs = [{"role": "user", "content": "debug this crash"}]
        result = self.srv._augment(msgs)
        user_content = self._last_user_content(result)
        self.assertIn('<framework name=\"debug\">', user_content)
        self.assertIn("Reproduce", user_content)

    def test_deep_path_injects_analysis_framework(self):
        self.srv._analyze_deep.return_value = {
            "framework": "design", "insight": "consider microservices",
            "anti_loop": "", "tool_summary": "",
        }
        ctx = _make_ctx([
            _user_msg("设计系统"),
            _tool_msg("read"),
            _tool_msg("edit"),
            _tool_msg("bash"),
        ])
        with patch.object(ContextManager, "assess_complexity", return_value="deep"):
            result = self.srv._augment(ctx.messages)
        user_content = self._last_user_content(result)
        self.assertIn('<framework name=\"design\">', user_content)
        self.assertIn("microservices", user_content)

    def test_fast_short_tool_context_injected(self):
        msgs = [
            _user_msg("query"),
            _tool_msg("read", "short result"),
        ]
        result = self.srv._augment(msgs)
        user_content = self._last_user_content(result)
        self.assertIn("<tool_context>", user_content)

    def test_no_framework_for_unmatched_query(self):
        msgs = [{"role": "user", "content": "blah blah blah"}]
        result = self.srv._augment(msgs)
        user_content = self._last_user_content(result)
        self.assertNotIn("<framework", user_content)

    def test_query_takes_last_user_message_not_tail(self):
        # last message is assistant tool_calls, query should come from prior user turn
        msgs = [
            {"role": "user", "content": "排查 crash 原因"},
            {"role": "assistant", "tool_calls": [{"name": "read"}], "content": ""},
        ]
        result = self.srv._augment(msgs)
        # Only the LAST user message should be augmented
        user_content = self._last_user_content(result)
        self.assertIn('<framework name=\"debug\">', user_content)


# ── FlashExtServer _analyze_deep ─────────────────────────────────────────────

class AnalyzeDeepTests(unittest.TestCase):
    def setUp(self):
        self.provider = MagicMock()
        self.provider.api_url = "https://test/api"
        self.provider.headers.return_value = {}
        self.provider.build_body.return_value = {}
        self.srv = FlashExtServer(host="127.0.0.1", port=9999, provider_obj=self.provider)
        self.srv.logger = MagicMock()

    def test_returns_parsed_json(self):
        ctx = _make_ctx([_user_msg("debug"), _tool_msg("read")])
        self.provider.parse_response.return_value = {
            "content": '{"framework": "debug", "insight": "check logs", '
                        '"anti_loop": "", "tool_summary": ""}',
        }
        with patch("mangopi_cli._request", return_value={}):
            result = self.srv._analyze_deep(ctx, "debug", ["read"])
        self.assertEqual(result["framework"], "debug")
        self.assertEqual(result["insight"], "check logs")

    def test_returns_none_on_invalid_json(self):
        ctx = _make_ctx([_user_msg("debug"), _tool_msg("read")])
        self.provider.parse_response.return_value = {
            "content": "not json at all, just some text",
        }
        with patch("mangopi_cli._request", return_value={}):
            result = self.srv._analyze_deep(ctx, "debug", ["read"])
        self.assertIsNone(result)

    def test_looping_info_in_prompt(self):
        ctx = _make_ctx([_tool_msg("edit", "fail")] * 10)
        self.provider.parse_response.return_value = {"content": '{"framework": "reevaluate"}'}
        with patch("mangopi_cli._request", return_value={}):
            self.srv._analyze_deep(ctx, "fix", ["edit"])
        body_content = self.provider.build_body.call_args[0][0][0]["content"]
        self.assertIn("yes (edit)", body_content)


if __name__ == "__main__":
    unittest.main()
