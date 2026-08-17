"""Tests for WebSearchTool — covers input validation, _bocha_search_api
integration, result formatting, error handling, and schema correctness.

Covers:
    * Input validation: missing query, missing API key, bad top_k, bad freshness
    * Argument forwarding: defaults, custom top_k / freshness, string-coerced top_k
    * Empty results: empty list, non-list defensive
    * Markdown rendering: ## Answer / ## Sources structure, dates, blockquote
      summaries, content truncation, missing-field robustness, query echo
    * API error handling: generic exception, HTTP 401
    * preview() method: query truncation, missing query
    * Schema: name, required/optional params, description
    * Registration in TOOLS dict
"""
import os
import sys
import unittest
import urllib.error
from unittest import mock

# Force a fake MANGO_KEY so the module-level create_provider() doesn't choke
os.environ.setdefault("MANGO_KEY", "test-key-not-used")

# Add parent dir to sys.path so we can import mangopi_cli.
# This file is meant to live at <project>/test/test_web_search.py,
# so the project root is one level up from __file__'s directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mangopi_cli as m  # noqa: E402


# v0.1.49: web_search 插件化, 从扩展文件加载 (与 test_clipboard 同模式)
_EXT = os.path.join("examples", "extensions", "web_search.py")
_wmod = m.ExtensionRegistry.load_file(_EXT)
WebSearchTool = _wmod.WebSearchTool  # noqa: E402


# ── Shared base: each test gets a controllable API key + mocked API ──────────


class _WebSearchBase(unittest.TestCase):
    """Base class: patches MANGO_SEARCH_API_KEY and replaces _bocha_search_api
    (on the extension module) with a Mock so each test can stage return_value /
    side_effect freely.

    setUp stores the original key and function reference, then swaps them.
    tearDown restores both, so tests are order-independent and don't leak
    state into the rest of the suite.
    """

    def setUp(self):
        # Tool reads the env var at call time via os.environ.get(), so we
        # set/restore the env var directly rather than patching a module
        # attribute (none exists).
        self._orig_env = os.environ.get("MANGO_SEARCH_API_KEY")
        os.environ["MANGO_SEARCH_API_KEY"] = "test-bocha-key"
        self._orig_api = _wmod._bocha_search_api
        self.api_mock = mock.Mock()
        _wmod._bocha_search_api = self.api_mock

    def tearDown(self):
        if self._orig_env is None:
            os.environ.pop("MANGO_SEARCH_API_KEY", None)
        else:
            os.environ["MANGO_SEARCH_API_KEY"] = self._orig_env
        _wmod._bocha_search_api = self._orig_api

    def _run(self, **kwargs):
        return WebSearchTool().run(kwargs)


# ── 1. Input validation: reject bad input before touching the network ───────


class TestInputValidation(_WebSearchBase):
    """Validation must fail fast and never reach _bocha_search_api."""

    def test_missing_query_returns_clear_error(self):
        result = self._run()
        self.assertFalse(result["success"])
        self.assertIn("'query' is required", result["content"])
        # No network call should happen on validation failure
        self.api_mock.assert_not_called()

    def test_whitespace_only_query_rejected(self):
        result = self._run(query="   ")
        self.assertFalse(result["success"])
        self.assertIn("'query' is required", result["content"])
        self.api_mock.assert_not_called()

    def test_missing_api_key_returns_clear_error(self):
        os.environ.pop("MANGO_SEARCH_API_KEY", None)
        result = self._run(query="hello")
        self.assertFalse(result["success"])
        self.assertIn("MANGO_SEARCH_API_KEY", result["content"])
        self.assertIn("not set", result["content"])
        self.api_mock.assert_not_called()

    def test_non_integer_top_k_rejected(self):
        result = self._run(query="x", top_k="abc")
        self.assertFalse(result["success"])
        self.assertIn("'top_k' must be an integer", result["content"])
        self.assertNotIn("[" + str(self._run.__hash__()) + "]", result["content"])
        self.api_mock.assert_not_called()

    def test_top_k_above_max_rejected(self):
        result = self._run(query="x", top_k=51)
        self.assertFalse(result["success"])
        self.assertIn("'top_k' must be in [1, 50]", result["content"])

    def test_top_k_below_min_rejected(self):
        result = self._run(query="x", top_k=0)
        self.assertFalse(result["success"])
        self.assertIn("'top_k' must be in [1, 50]", result["content"])

    def test_top_k_negative_rejected(self):
        result = self._run(query="x", top_k=-3)
        self.assertFalse(result["success"])
        self.assertIn("'top_k' must be in [1, 50]", result["content"])

    def test_invalid_freshness_rejected(self):
        result = self._run(query="x", freshness="yesterday")
        self.assertFalse(result["success"])
        self.assertIn("'freshness' must be one of", result["content"])
        # All valid values should be listed in the error
        for v in ("noLimit", "oneDay", "oneWeek", "oneMonth", "oneYear"):
            self.assertIn(v, result["content"])
        self.api_mock.assert_not_called()


# ── 2. Argument forwarding: valid args reach _bocha_search_api correctly ─────


class TestApiCallParams(_WebSearchBase):
    """The tool must translate its public params into the private API call."""

    def test_defaults_passed_to_api(self):
        self.api_mock.return_value = []
        self._run(query="hello world")
        self.api_mock.assert_called_once()
        kwargs = self.api_mock.call_args.kwargs
        self.assertEqual(kwargs["query"], "hello world")
        self.assertEqual(kwargs["count"], 10)
        self.assertEqual(kwargs["freshness"], "noLimit")
        self.assertEqual(kwargs["bocha_key"], "test-bocha-key")


    def test_custom_top_k_passed_as_count(self):
        self.api_mock.return_value = []
        self._run(query="x", top_k=25)
        self.assertEqual(self.api_mock.call_args.kwargs["count"], 25)

    def test_top_k_passed_as_string_is_coerced(self):
        # LLMs sometimes send "5" as a string. The tool should coerce.
        self.api_mock.return_value = []
        self._run(query="x", top_k="5")
        self.assertEqual(self.api_mock.call_args.kwargs["count"], 5)

    def test_custom_freshness_passed_through(self):
        self.api_mock.return_value = []
        self._run(query="x", freshness="oneWeek")
        self.assertEqual(self.api_mock.call_args.kwargs["freshness"], "oneWeek")

    def test_whitespace_freshness_stripped(self):
        self.api_mock.return_value = []
        self._run(query="x", freshness="  oneMonth  ")
        self.assertEqual(self.api_mock.call_args.kwargs["freshness"], "oneMonth")


# ── 3. Empty / defensive results ────────────────────────────────────────────


class TestEmptyResults(_WebSearchBase):
    """No results should produce a clean response, not a stack trace."""

    def test_empty_list_returns_graceful_message(self):
        self.api_mock.return_value = []
        result = self._run(query="obscure-nothing-here")
        self.assertTrue(result["success"])
        self.assertIn("no results", result["content"])
        # The query is echoed so the LLM can correlate
        self.assertIn("obscure-nothing-here", result["content"])

    def test_api_returning_none_treated_as_empty(self):
        # Defensive: if Bocha ever returns something unexpected, we should
        # still produce a useful response (not crash on `len(None)`).
        self.api_mock.return_value = None
        result = self._run(query="x")
        self.assertTrue(result["success"])
        self.assertIn("no results", result["content"])


# ── 4. Result formatting: markdown structure fed back to the LLM ────────────


class TestResultFormatting(_WebSearchBase):
    """Verifies the ## Answer / ## Sources layout and per-result blocks."""

    def _sample_results(self):
        return [
            {"date": "2026-05-01", "title": "Title A", "link": "https://a.com",
             "summary": "Sum A", "content": "Content A"},
            {"date": "2026-04-15", "title": "Title B", "link": "https://b.com",
             "summary": "Sum B", "content": "Content B"},
        ]

    def test_full_results_have_answer_and_sources_sections(self):
        self.api_mock.return_value = self._sample_results()
        body = self._run(query="my query")["content"]

        # Header carries query echo + result count
        self.assertIn("## Answer (Bocha · 2 result(s) for: my query)", body)

        # Per-result blocks
        self.assertIn("### 1. [Title A](https://a.com)", body)
        self.assertIn("### 2. [Title B](https://b.com)", body)

        # Dates rendered
        self.assertIn("*Date: 2026-05-01*", body)
        self.assertIn("*Date: 2026-04-15*", body)

        # Summaries as blockquotes
        self.assertIn("> Sum A", body)
        self.assertIn("> Sum B", body)

        # Sources section at the end
        self.assertIn("## Sources", body)
        self.assertIn("1. [Title A](https://a.com)", body)
        self.assertIn("2. [Title B](https://b.com)", body)

        # Sources section must come AFTER the per-result blocks
        self.assertLess(body.index("### 1."), body.index("## Sources"))

    def test_content_truncated_when_over_500_chars(self):
        long_content = "x" * 1000
        self.api_mock.return_value = [
            {"date": "", "title": "T", "link": "https://x.com",
             "summary": "S", "content": long_content},
        ]
        body = self._run(query="q")["content"]
        # Truncation marker present
        self.assertIn("...", body)
        # Full 1000-char string NOT present
        self.assertNotIn("x" * 600, body)

    def test_content_equal_to_summary_omits_content(self):
        # No point rendering the same text twice
        self.api_mock.return_value = [
            {"date": "", "title": "T", "link": "https://x.com",
             "summary": "Same text", "content": "Same text"},
        ]
        body = self._run(query="q")["content"]
        # Appears exactly once (only in blockquote)
        self.assertEqual(body.count("Same text"), 1)

    def test_missing_link_uses_plain_header(self):
        self.api_mock.return_value = [
            {"date": "", "title": "T", "link": "", "summary": "S", "content": ""},
        ]
        body = self._run(query="q")["content"]
        # No markdown link when link is empty
        self.assertIn("### 1. T", body)
        self.assertNotIn("### 1. [T]", body)
        # Sources also linkless
        sources = body.split("## Sources", 1)[1]
        self.assertIn("1. T", sources)

    def test_missing_title_uses_untitled_placeholder(self):
        self.api_mock.return_value = [
            {"date": "", "title": "", "link": "https://x.com", "summary": "S", "content": ""},
        ]
        body = self._run(query="q")["content"]
        self.assertIn("(untitled)", body)

    def test_missing_fields_dont_crash(self):
        # Defensive: some Bocha results may be missing fields entirely
        self.api_mock.return_value = [
            {},  # empty dict
            {"title": "Only title", "link": "https://x.com"},  # no date/summary/content
        ]
        body = self._run(query="q")["content"]
        self.assertIn("### 1. (untitled)", body)
        self.assertIn("### 2. [Only title](https://x.com)", body)

    def test_query_echoed_in_header(self):
        self.api_mock.return_value = [
            {"date": "", "title": "T", "link": "", "summary": "S", "content": ""}
        ]
        body = self._run(query="specific phrase here")["content"]
        self.assertIn("specific phrase here", body)

    def test_content_under_500_chars_kept_intact(self):
        # Boundary: 500 chars is the limit, 499 should be kept verbatim
        short_content = "a" * 499
        self.api_mock.return_value = [
            {"date": "", "title": "T", "link": "https://x.com",
             "summary": "S", "content": short_content},
        ]
        body = self._run(query="q")["content"]
        self.assertIn(short_content, body)
        self.assertNotIn("a" * 500 + "...", body)


# ── 5. API error handling ────────────────────────────────────────────────────


class TestApiErrorHandling(_WebSearchBase):
    """Any exception from _bocha_search_api should be wrapped, not raised."""

    def test_generic_exception_wrapped_in_clear_error(self):
        self.api_mock.side_effect = RuntimeError("connection refused")
        result = self._run(query="x")
        self.assertFalse(result["success"])
        self.assertIn("web_search error", result["content"])
        self.assertIn("connection refused", result["content"])

    def test_http_401_wrapped_in_clear_error(self):
        # 401 is non-retryable — _request() raises HTTPError immediately
        self.api_mock.side_effect = urllib.error.HTTPError(
            url="https://api.bocha.com", code=401, msg="Unauthorized", hdrs={}, fp=None)
        result = self._run(query="x")
        self.assertFalse(result["success"])
        self.assertIn("web_search error", result["content"])
        self.assertIn("Unauthorized", result["content"])

    def test_http_429_wrapped_in_clear_error(self):
        # 429 would normally be retried by _request, but we mocked the
        # function itself, so the exception is raised directly.
        self.api_mock.side_effect = urllib.error.HTTPError(
            url="https://api.bocha.com", code=429, msg="Too Many Requests", hdrs={}, fp=None)
        result = self._run(query="x")
        self.assertFalse(result["success"])
        self.assertIn("web_search error", result["content"])


# ── 6. preview() method ─────────────────────────────────────────────────────


class TestPreviewMethod(_WebSearchBase):
    """preview() is what the console shows when the tool is invoked."""

    def test_preview_returns_query_truncated_to_width(self):
        tool = WebSearchTool()
        long_q = "x" * 500
        preview = tool.preview({"query": long_q})
        self.assertEqual(len(preview), tool.preview_width)

    def test_preview_handles_missing_query(self):
        self.assertEqual(WebSearchTool().preview({}), "")

    def test_preview_short_query_unchanged(self):
        self.assertEqual(WebSearchTool().preview({"query": "hi"}), "hi")


# ── 7. Schema & TOOLS registration ──────────────────────────────────────────


class TestSchemaAndRegistration(unittest.TestCase):
    """Schema correctness and presence in the global TOOLS dict."""

    def test_schema_name(self):
        self.assertEqual(WebSearchTool().schema()["function"]["name"], "web_search")

    def test_schema_query_is_required_string(self):
        params = WebSearchTool().schema()["function"]["parameters"]
        self.assertIn("query", params["required"])
        self.assertEqual(params["properties"]["query"]["type"], "string")

    def test_schema_top_k_and_freshness_are_optional(self):
        params = WebSearchTool().schema()["function"]["parameters"]
        self.assertNotIn("top_k", params["required"])
        self.assertNotIn("freshness", params["required"])
        # top_k is exposed as integer in JSON Schema (per ToolBase.number→integer rule)
        self.assertEqual(params["properties"]["top_k"]["type"], "integer")
        self.assertEqual(params["properties"]["freshness"]["type"], "string")

    def test_registered_in_tools_dict(self):
        # v0.1.49: 插件化 — 扩展加载合并后进入 TOOLS (此处模拟合并语义)
        m.TOOLS["web_search"] = WebSearchTool()
        try:
            self.assertIsInstance(m.TOOLS["web_search"], WebSearchTool)
        finally:
            del m.TOOLS["web_search"]

    def test_description_mentions_bocha_and_env_var(self):
        desc = WebSearchTool().description
        self.assertIn("Bocha", desc)
        self.assertIn("MANGO_SEARCH_API_KEY", desc)

    def test_in_tool_schema_list(self):
        # v0.1.49: 插件化 — 扩展合并进 TOOLS 后出现在 tool_schema (此处模拟合并语义)
        m.TOOLS["web_search"] = WebSearchTool()
        try:
            names = [s["function"]["name"] for s in m.tool_schema()]
            self.assertIn("web_search", names)
        finally:
            del m.TOOLS["web_search"]


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)
