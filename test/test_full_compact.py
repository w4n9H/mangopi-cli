"""Tests for ContextManager.full_compact() — the manual LLM-summary
compact flow.

Flow under test:
    1. Build `_full_compact_prompt` lines and append as a user message.
    2. Call `provider.parse_response(_request(provider.api_url,
       provider.build_body(self.messages), headers=provider.headers()))`.
    3. If `respon.get("content")` is truthy → replace messages with
       `[<all systems>, <new user summary>]`.
    4. Else → raise `RuntimeError("full compact err: llm respon null")`.
    5. Any exception → wrapped as `RuntimeError(f"full compact err: {e}")`.

All tests mock `mangopi_cli.provider` and `mangopi_cli._request`, so
no real network calls are made.
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add parent dir to sys.path so we can import mangopi_cli.
# This file lives at <project>/test/test_full_compact.py,
# so the project root is one level up from __file__'s directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangopi_cli import ContextManager  # noqa: E402


# ── Message builders (module-level helpers, parallel to other test files) ───


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


# ── Mock provider factory ───────────────────────────────────────────────────


DEFAULT_SUMMARY = "<summary>this is a mock summary</summary>"


def make_mock_provider(summary_content=DEFAULT_SUMMARY):
    """Build a MagicMock provider with the surface area full_compact uses:
    `api_url`, `build_body(messages)`, `headers()`, `parse_response(body)`.
    Tests can override individual attributes (e.g. side_effect) to drive
    error-path branches.
    """
    mock_provider = MagicMock()
    mock_provider.api_url = "https://mock.api/chat/completions"
    mock_provider.build_body = MagicMock(return_value={"model": "mock-model", "messages": []})
    mock_provider.headers = MagicMock(return_value={
        "Content-Type": "application/json",
        "Authorization": "Bearer mock-key",
    })
    mock_provider.parse_response = MagicMock(return_value={"content": summary_content})
    return mock_provider


# ── Shared base: fresh ContextManager + auto-cleaned patches ────────────────


class _FullCompactBase(unittest.TestCase):
    """Each test gets a fresh ContextManager and a fresh mock provider.

    Subclasses use `self._patch_provider(mock)` to activate the patches
    (the patches are removed in `tearDown`). Tests that want to assert
    on mock call counts use the mock returned from this method.
    """

    def setUp(self):
        self.ctx = ContextManager()
        self.mock_provider = make_mock_provider()
        self._patches = []

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()

    def _patch_provider(self, mock=None):
        """Activate patches of `mangopi_cli.provider` and `_request`.
        Returns (mock_provider, mock_request) so the caller can override
        either side effect.
        """
        mock = mock or self.mock_provider
        p_provider = patch("mangopi_cli.provider", mock)
        p_request = patch("mangopi_cli._request", return_value={"raw": "mock"})
        p_provider.start()
        p_request.start()
        self._patches.append(p_provider)
        self._patches.append(p_request)
        return mock

    def _run_full_compact(self, **request_overrides):
        """Run full_compact under the standard patches. Returns the
        `RuntimeError` if one was raised, else None.
        """
        mp = self._patch_provider()
        # Allow per-test override of _request behavior (e.g. side_effect).
        if "request_side_effect" in request_overrides:
            patch.stopall()  # tear down what we just started
            self._patches.clear()
            p_provider = patch("mangopi_cli.provider", mp)
            p_request = patch(
                "mangopi_cli._request",
                side_effect=request_overrides["request_side_effect"],
            )
            p_provider.start()
            p_request.start()
            self._patches.extend([p_provider, p_request])
        raised = None
        try:
            self.ctx.full_compact()
        except Exception as e:
            raised = e
        return raised


# ── 1. Normal compact: clears and replaces ─────────────────────────────────


class TestNormalCompact(_FullCompactBase):
    def test_01_normal_compact_clears_and_replaces(self):
        self.ctx.messages = [
            {"role": "system", "content": "you are an assistant"},
            make_user("query 1"),
            make_assistant("reply 1"),
            make_tool("c1", "read", "file content"),
            make_user("query 2"),
            make_assistant("reply 2"),
        ]
        raised = self._run_full_compact()
        self.assertIsNone(raised)
        # system is preserved at index 0
        self.assertEqual(self.ctx.messages[0]["role"], "system")
        self.assertEqual(self.ctx.messages[0]["content"], "you are an assistant")
        # everything else is replaced with a single summary user msg
        self.assertEqual(len(self.ctx.messages), 2)
        self.assertEqual(self.ctx.messages[1]["role"], "user")
        self.assertEqual(self.ctx.messages[1]["content"], DEFAULT_SUMMARY)


# ── 2. Multiple system messages preserved in order ─────────────────────────


class TestMultipleSystemMessages(_FullCompactBase):
    def test_02_multiple_system_messages_preserved(self):
        self.ctx.messages = [
            {"role": "system", "content": "sys A"},
            {"role": "system", "content": "sys B"},
            make_user("q"),
            make_assistant("a"),
        ]
        raised = self._run_full_compact()
        self.assertIsNone(raised)
        self.assertEqual(len(self.ctx.messages), 3)
        self.assertEqual(self.ctx.messages[0], {"role": "system", "content": "sys A"})
        self.assertEqual(self.ctx.messages[1], {"role": "system", "content": "sys B"})
        self.assertEqual(self.ctx.messages[2]["role"], "user")


# ── 3. Empty LLM content → RuntimeError("llm respon null") ─────────────────


class TestEmptyContentRaises(_FullCompactBase):
    def test_03_empty_content_raises_runtime_error(self):
        self.ctx.messages = [
            {"role": "system", "content": "sys"},
            make_user("q"),
            make_assistant("a"),
        ]
        # Custom mock that returns empty content.
        empty_mock = make_mock_provider(summary_content="")
        self.mock_provider = empty_mock
        raised = self._run_full_compact()
        self.assertIsNotNone(raised)
        self.assertIsInstance(raised, RuntimeError)
        self.assertIn("llm respon null", str(raised))


# ── 4. _request exception → wrapped RuntimeError ───────────────────────────


class TestRequestExceptionWrapped(_FullCompactBase):
    def test_04_request_exception_raises_runtime_error(self):
        self.ctx.messages = [
            {"role": "system", "content": "sys"},
            make_user("q"),
            make_assistant("a"),
        ]
        raised = self._run_full_compact(
            request_side_effect=ConnectionError("network down"),
        )
        self.assertIsNotNone(raised)
        self.assertIsInstance(raised, RuntimeError)
        self.assertIn("full compact err", str(raised))


# ── 5. Prompt contains expected keywords ────────────────────────────────────


class TestPromptKeywords(_FullCompactBase):
    def test_05_prompt_contains_expected_keywords(self):
        self.ctx.messages = [
            {"role": "system", "content": "sys"},
            make_user("user query"),
            make_assistant("assistant reply"),
        ]
        mp = self._patch_provider()
        raised = self._run_full_compact()
        self.assertIsNone(raised)
        # build_body must have been invoked with the messages list.
        self.assertTrue(mp.build_body.called)
        sent_messages = mp.build_body.call_args[0][0]
        # The summary-prompt content must include these structural keywords.
        all_content = " ".join(
            json.dumps(m, ensure_ascii=False) for m in sent_messages
        )
        for keyword in ["Primary Request", "summary", "Current Work", "Pending Tasks"]:
            self.assertIn(keyword, all_content)


# ── 6. provider.api_url and headers() are used ─────────────────────────────


class TestProviderUrlAndHeaders(_FullCompactBase):
    def test_06_provider_url_and_headers_used(self):
        self.ctx.messages = [
            {"role": "system", "content": "sys"},
            make_user("q"),
        ]
        mp = self._patch_provider()
        raised = self._run_full_compact()
        self.assertIsNone(raised)
        self.assertTrue(mp.headers.called)
        self.assertEqual(mp.api_url, "https://mock.api/chat/completions")


# ── 7. Empty messages list ─────────────────────────────────────────────────


class TestEmptyMessagesList(_FullCompactBase):
    def test_07_empty_messages_list(self):
        # ctx.messages starts empty.
        raised = self._run_full_compact()
        self.assertIsNone(raised)
        self.assertEqual(len(self.ctx.messages), 1)
        self.assertEqual(self.ctx.messages[0]["role"], "user")
        self.assertEqual(self.ctx.messages[0]["content"], DEFAULT_SUMMARY)


# ── 8. No system messages ─────────────────────────────────────────────────


class TestNoSystemMessages(_FullCompactBase):
    def test_08_no_system_messages(self):
        self.ctx.messages = [
            make_user("q1"),
            make_assistant("a1"),
            make_tool("c1", "bash", "output"),
            make_user("q2"),
            make_assistant("a2"),
        ]
        raised = self._run_full_compact()
        self.assertIsNone(raised)
        self.assertEqual(len(self.ctx.messages), 1)
        self.assertEqual(self.ctx.messages[0]["role"], "user")
        # Every remaining message must be system or user (no leakage).
        for m in self.ctx.messages:
            self.assertIn(m["role"], ("system", "user"))


# ── 9. Summary with XML tags preserved as-is ───────────────────────────────


class TestSummaryWithXmlTags(_FullCompactBase):
    def test_09_summary_with_xml_tags_preserved(self):
        analysis = "<analysis>thought process here</analysis>"
        summary = "<summary>1. Primary Request and Intent:\n  do something</summary>"
        full = analysis + "\n" + summary
        self.ctx.messages = [
            {"role": "system", "content": "sys"},
            make_user("q"),
            make_assistant("a"),
        ]
        xml_mock = make_mock_provider(summary_content=full)
        self.mock_provider = xml_mock
        raised = self._run_full_compact()
        self.assertIsNone(raised)
        self.assertEqual(len(self.ctx.messages), 2)
        self.assertEqual(self.ctx.messages[1]["role"], "user")
        self.assertEqual(self.ctx.messages[1]["content"], full)
        self.assertIn("<analysis>", self.ctx.messages[1]["content"])
        self.assertIn("<summary>", self.ctx.messages[1]["content"])


# ── 10. parse_response / build_body / headers all called ───────────────────


class TestInvokeChain(_FullCompactBase):
    def test_10_invoke_chain_all_called(self):
        self.ctx.messages = [
            {"role": "system", "content": "sys"},
            make_user("q"),
            make_assistant("a"),
        ]
        mp = self._patch_provider()
        raised = self._run_full_compact()
        self.assertIsNone(raised)
        self.assertTrue(mp.parse_response.called)
        self.assertTrue(mp.build_body.called)
        self.assertTrue(mp.headers.called)


# ── 11. parse_response exception → wrapped RuntimeError ────────────────────


class TestParseResponseException(_FullCompactBase):
    def test_11_parse_response_exception_raises_runtime_error(self):
        self.ctx.messages = [
            {"role": "system", "content": "sys"},
            make_user("q"),
        ]
        # Override parse_response to raise.
        boom = make_mock_provider()
        boom.parse_response = MagicMock(side_effect=ValueError("parse boom"))
        self.mock_provider = boom
        raised = self._run_full_compact()
        self.assertIsNotNone(raised)
        self.assertIsInstance(raised, RuntimeError)
        self.assertIn("full compact err", str(raised))


# ── 12. Realistic 10-turn coding-session scenario ───────────────────────────


class TestRealScenario(_FullCompactBase):
    def test_12_real_scenario_with_output(self):
        # Construct the 10-turn session.
        self.ctx.messages = [
            {"role": "system", "content": "You are a senior Python engineer. Be precise."},
        ]
        for i in range(1, 6):
            self.ctx.messages.extend([
                make_user(f"读取并分析 module_{i}.py 的实现"),
                make_assistant(
                    "",
                    tool_calls=[make_tc(f"c{i}", "read", f'{{"path": "module_{i}.py"}}')],
                    reasoning=f"分析 module_{i}.py 的依赖关系..." + long(200),
                ),
                make_tool(f"c{i}", "read", "# module_" + str(i) + ".py\n" + long(800)),
                make_assistant(
                    f"module_{i}.py 已读取, 包含 {i*100} 行核心代码。" + long(150)
                ),
            ])

        summary_text = (
            "<analysis>User asked to analyze 5 Python modules with tool calls and reasoning.</analysis>\n"
            "<summary>"
            "1. Primary Request and Intent:\n  analyze 5 modules\n"
            "2. Files and Code Sections:\n  - module_1.py ~ module_5.py\n"
            "3. Current Work:\n  All 5 modules analyzed.\n"
            "</summary>"
        )

        before_total = self.ctx.total_tokens()
        before_msgs = len(self.ctx.messages)

        real_mock = make_mock_provider(summary_content=summary_text)
        self.mock_provider = real_mock
        raised = self._run_full_compact()
        self.assertIsNone(raised)

        after_total = self.ctx.total_tokens()
        after_msgs = len(self.ctx.messages)

        # Brief diagnostic line so the test still doubles as a useful
        # signal when run with -v.
        print(
            f"\n  full_compact: {before_msgs} → {after_msgs} msgs; "
            f"{before_total} → {after_total} tokens"
        )

        # Invariants:
        self.assertEqual(self.ctx.messages[0]["role"], "system")
        self.assertEqual(
            self.ctx.messages[0]["content"],
            "You are a senior Python engineer. Be precise.",
        )
        self.assertEqual(len(self.ctx.messages), 2)
        self.assertEqual(self.ctx.messages[1]["role"], "user")
        self.assertEqual(self.ctx.messages[1]["content"], summary_text)
        # No tool / assistant residue.
        roles = {m["role"] for m in self.ctx.messages}
        self.assertNotIn("tool", roles)
        self.assertNotIn("assistant", roles)
        # Token reduction.
        self.assertLess(after_total, before_total)


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)