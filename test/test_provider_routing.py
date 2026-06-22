"""Unit tests for Smart Provider Routing (refactored — RoutedProvider + _new_provider).

Tests cover:
    1. _keyword_score           – keyword matching → score
    2. RoutedProvider.__init__   – providers.json parsing & validation
    3. _extract_tool_fingerprint – tool-call pattern extraction
    4. RoutedProvider.route()    – two-phase scoring → tier selection
    5. _llm_score               – LLM scoring edge cases
    6. _new_provider            – factory: url normalisation & provider-class selection

No real network calls — LLM scoring is mocked.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mangopi_cli  # noqa: E402
from mangopi_cli import ContextManager, RoutedProvider  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_fake_ctx(tool_sequences):
    """Return a real ContextManager with tool messages matching the given sequences.

    Each inner list is one user turn; a user message is inserted before each turn.
    """
    from mangopi_cli import ContextManager
    ctx = ContextManager()
    ctx.clear()
    for seq in tool_sequences:
        ctx.messages.append({"role": "user", "content": "query"})
        for name in seq:
            ctx.messages.append({"role": "tool", "tool_name": name, "content": "ok"})
    return ctx


def _write_providers_json(providers, routing=None):
    """Write a temporary providers.json and return its path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    config = {"providers": providers}
    if routing:
        config["routing"] = routing
    json.dump(config, tmp)
    tmp.close()
    return tmp.name


def _make_routed_provider(providers, routing=None):
    """Build a RoutedProvider from a temp file."""
    p_file = _write_providers_json(providers, routing)
    return RoutedProvider.from_file(p_file), p_file


# ── Tests ────────────────────────────────────────────────────────────────────

class KeywordScoreTests(unittest.TestCase):
    """_keyword_score returns correct tier-indicative scores."""

    def test_high_complexity_keywords(self):
        self.assertEqual(RoutedProvider._keyword_score("design me a distributed system"), 9)
        self.assertEqual(RoutedProvider._keyword_score("架构重构"), 9)
        self.assertEqual(RoutedProvider._keyword_score("系统设计 for microservice"), 9)

    def test_medium_high_keywords(self):
        self.assertEqual(RoutedProvider._keyword_score("refactor the auth module"), 7)
        self.assertEqual(RoutedProvider._keyword_score("migrate to new API"), 7)

    def test_medium_low_keywords(self):
        self.assertEqual(RoutedProvider._keyword_score("implement a new feature"), 5)
        self.assertEqual(RoutedProvider._keyword_score("integrate with external API"), 5)

    def test_low_keywords(self):
        self.assertEqual(RoutedProvider._keyword_score("fix the login bug"), 3)
        self.assertEqual(RoutedProvider._keyword_score("add test for utils"), 3)

    def test_trivial_keywords(self):
        self.assertEqual(RoutedProvider._keyword_score("read main.py"), 1)
        self.assertEqual(RoutedProvider._keyword_score("what does this function do"), 4)

    def test_case_insensitive(self):
        self.assertEqual(RoutedProvider._keyword_score("DESIGN a System"), 9)

    def test_no_match_returns_default(self):
        self.assertEqual(RoutedProvider._keyword_score("blah blah blah"), 4)


class RoutedProviderInitTests(unittest.TestCase):
    """RoutedProvider.__init__ parses and validates config."""

    def test_valid_config(self):
        rp, p_file = _make_routed_provider(
            [
                {"name": "lo", "url": "https://lo.com", "model": "lo", "tier": "low",    "api_key": "k-lo"},
                {"name": "md", "url": "https://md.com", "model": "md", "tier": "medium", "api_key": "k-md"},
                {"name": "hi", "url": "https://hi.com", "model": "hi", "tier": "high",   "api_key": "k-hi"},
            ],
        )
        self.assertEqual(len(rp._tiers["low"]), 1)
        self.assertEqual(len(rp._tiers["medium"]), 1)
        self.assertEqual(len(rp._tiers["high"]), 1)
        self.assertEqual(rp.model, "md")  # default tier = medium
        self.assertEqual(rp._thresholds, {"low_max": 3, "medium_max": 7})
        os.unlink(p_file)

    def test_custom_thresholds(self):
        rp, p_file = _make_routed_provider(
            [{"name": "hi", "url": "https://hi.com", "model": "hi", "tier": "high", "api_key": "k"}],
            routing={"score_thresholds": {"low_max": 2, "medium_max": 5}, "default_tier": "high"},
        )
        self.assertEqual(rp._thresholds, {"low_max": 2, "medium_max": 5})
        os.unlink(p_file)

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            RoutedProvider.from_file("/nonexistent/path.json")

    def test_invalid_tier(self):
        p_file = _write_providers_json([
            {"name": "x", "url": "https://x.com", "model": "x", "tier": "super_fast", "api_key": "k"},
        ])
        with self.assertRaises(ValueError):
            RoutedProvider.from_file(p_file)
        os.unlink(p_file)

    def test_empty_providers(self):
        p_file = _write_providers_json([])
        with self.assertRaises(ValueError):
            RoutedProvider.from_file(p_file)
        os.unlink(p_file)

    def test_delegates_to_default_tier(self):
        rp, p_file = _make_routed_provider(
            [{"name": "hi", "url": "https://hi.com", "model": "hi", "tier": "high", "api_key": "k"}],
        )
        # Only high tier is configured, default should fall back to high
        self.assertEqual(rp.model, "hi")
        os.unlink(p_file)


class ExtractToolFingerprintTests(unittest.TestCase):
    """ContextManager.tool_fingerprint() builds compact tool-call patterns."""

    def test_single_turn(self):
        ctx = _make_fake_ctx([["read", "grep", "read"]])
        fp = ctx.tool_fingerprint()
        self.assertIn("read", fp)
        self.assertIn("grep", fp)
        self.assertIn("query", fp)  # user message content

    def test_multiple_turns(self):
        ctx = _make_fake_ctx([["read", "edit"], ["bash", "read"], ["edit", "edit"]])
        fp = ctx.tool_fingerprint()
        self.assertIn("['read', 'edit']", fp)
        self.assertEqual(fp.count("query"), 3)  # three user messages

    def test_truncates_to_n_turns(self):
        ctx = _make_fake_ctx([["a"], ["b"], ["c"], ["d"], ["e"]])
        fp = ctx.tool_fingerprint(n_turns=2)
        self.assertNotIn("'a'", fp)
        self.assertIn("'d'", fp)
        self.assertIn("'e'", fp)

    def test_empty_context(self):
        ctx = _make_fake_ctx([])
        self.assertEqual(ctx.tool_fingerprint(), "[]")

    def test_skips_turns_without_tools(self):
        ctx = ContextManager()
        ctx.clear()
        ctx.messages.append({"role": "user", "content": "hello"})
        self.assertEqual(ctx.tool_fingerprint(), "[]")


class LLMScoreTests(unittest.TestCase):
    """_llm_score calls high-tier model and extracts integer score."""

    def test_returns_integer(self):
        hp = MagicMock()
        hp.api_url = "https://test/api"
        hp.headers.return_value = {}
        hp.build_body.return_value = {}
        hp.parse_response.return_value = {"content": "7", "tool_calls": [], "has_tool_calls": False}
        with patch("mangopi_cli._request", return_value={}):
            self.assertEqual(RoutedProvider._llm_score("q", "[]", hp), 7)

    def test_clamps_to_1_10(self):
        hp = MagicMock()
        hp.api_url = "https://test/api"
        hp.headers.return_value = {}
        hp.build_body.return_value = {}
        hp.parse_response.return_value = {"content": "15", "tool_calls": [], "has_tool_calls": False}
        with patch("mangopi_cli._request", return_value={}):
            self.assertEqual(RoutedProvider._llm_score("q", "[]", hp), 10)
        hp.parse_response.return_value = {"content": "0", "tool_calls": [], "has_tool_calls": False}
        with patch("mangopi_cli._request", return_value={}):
            self.assertEqual(RoutedProvider._llm_score("q", "[]", hp), 1)

    def test_extracts_from_text(self):
        hp = MagicMock()
        hp.api_url = "https://test/api"
        hp.headers.return_value = {}
        hp.build_body.return_value = {}
        hp.parse_response.return_value = {"content": "complexity is 8 out of 10", "tool_calls": [], "has_tool_calls": False}
        with patch("mangopi_cli._request", return_value={}):
            self.assertEqual(RoutedProvider._llm_score("q", "[]", hp), 8)

    def test_fallback_on_error(self):
        hp = MagicMock()
        hp.api_url = "https://test/api"
        hp.headers.return_value = {}
        hp.build_body.return_value = {}
        hp.parse_response.side_effect = Exception("boom")
        with patch("mangopi_cli._request", side_effect=Exception("network down")):
            self.assertEqual(RoutedProvider._llm_score("q", "[]", hp), 5)


class RouteMethodTests(unittest.TestCase):
    """RoutedProvider.route() selects tier and switches _current."""

    def _make_rp(self, providers=None):
        if providers is None:
            providers = [
                {"name": "lo", "url": "https://lo.com", "model": "lo-model", "tier": "low",    "api_key": "k-lo"},
                {"name": "md", "url": "https://md.com", "model": "md-model", "tier": "medium", "api_key": "k-md"},
                {"name": "hi", "url": "https://hi.com", "model": "hi-model", "tier": "high",   "api_key": "k-hi"},
            ]
        p_file = _write_providers_json(providers)
        rp = RoutedProvider.from_file(p_file)
        self._cleanup_files = getattr(self, '_cleanup_files', [])
        self._cleanup_files.append(p_file)
        return rp

    def tearDown(self):
        for f in getattr(self, '_cleanup_files', []):
            try:
                os.unlink(f)
            except OSError:
                pass
        self._cleanup_files = []

    def test_keyword_low_routes_to_low(self):
        rp = self._make_rp()
        rp.route(_make_fake_ctx([]), "read the file")
        self.assertEqual(rp.model, "lo-model")

    def test_keyword_high_routes_to_high(self):
        rp = self._make_rp()
        rp.route(_make_fake_ctx([]), "design a distributed system")
        self.assertEqual(rp.model, "hi-model")

    def test_ambiguous_with_llm_low(self):
        rp = self._make_rp()
        with patch.object(RoutedProvider, "_llm_score", return_value=2):
            rp.route(_make_fake_ctx([]), "some ambiguous task")
        self.assertEqual(rp.model, "lo-model")

    def test_ambiguous_with_llm_medium(self):
        rp = self._make_rp()
        with patch.object(RoutedProvider, "_llm_score", return_value=5):
            rp.route(_make_fake_ctx([]), "some ambiguous task")
        self.assertEqual(rp.model, "md-model")

    def test_ambiguous_with_llm_high(self):
        rp = self._make_rp()
        # kw=4 * 0.3 + llm=10 * 0.7 = int(8.2) = 8 > 7 → high
        with patch.object(RoutedProvider, "_llm_score", return_value=10):
            rp.route(_make_fake_ctx([]), "some ambiguous task")
        self.assertEqual(rp.model, "hi-model")

    def test_no_high_provider_falls_back(self):
        rp = self._make_rp(providers=[
            {"name": "lo", "url": "https://lo.com", "model": "lo", "tier": "low", "api_key": "k-lo"},
        ])
        rp.route(_make_fake_ctx([]), "some ambiguous task")
        # No high-tier → skips LLM scoring, defaults to low (only tier available)
        self.assertEqual(rp.model, "lo")

    def test_properties_delegate_after_route(self):
        rp = self._make_rp()
        rp.route(_make_fake_ctx([]), "design a distributed system")
        self.assertEqual(rp.model, "hi-model")
        self.assertIn("hi.com", rp.api_url)
        self.assertIsNotNone(rp.headers())


class NewProviderTests(unittest.TestCase):
    """_new_provider returns correct Provider subclass and normalizes URL."""

    def test_deepseek_model(self):
        p = mangopi_cli._new_provider("deepseek-v4-flash", "https://api.deepseek.com", "k")
        self.assertIsInstance(p, mangopi_cli.DeepSeekProvider)
        self.assertEqual(p.model, "deepseek-v4-flash")
        self.assertEqual(p.api_url, "https://api.deepseek.com/chat/completions")

    def test_minimax_model(self):
        p = mangopi_cli._new_provider("minimax-m1", "https://api.minimax.com/v1", "k")
        self.assertIsInstance(p, mangopi_cli.MiniMaxProvider)

    def test_openai_model(self):
        p = mangopi_cli._new_provider("gpt-4o", "https://api.openai.com/v1", "k")
        self.assertIsInstance(p, mangopi_cli.OpenAIProvider)

    def test_url_already_has_chat_completions(self):
        p = mangopi_cli._new_provider("gpt-4o", "https://api.openai.com/v1/chat/completions", "k")
        self.assertEqual(p.api_url, "https://api.openai.com/v1/chat/completions")

    def test_url_with_trailing_slash(self):
        p = mangopi_cli._new_provider("gpt-4o", "https://api.openai.com/v1/", "k")
        self.assertEqual(p.api_url, "https://api.openai.com/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
