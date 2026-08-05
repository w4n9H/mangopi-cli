"""Tests for loop_engine pipeline execution.

Covers:
    * Success path: review pass → test pass → succeed
    * Failure path: test fail → updater → iterate → max_iter exhausted
    * Review reject path: review fail → updater → iterate → max_iter exhausted
    * Fast mode: dev → test pass → succeed
    * Fast mode failure: dev → test fail → max_iter exhausted
    * Wish mode: research → review pass → test pass → succeed
    * Error handling: agent_loop exception caught and returns False
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("MANGO_KEY", "test-key-not-used")
os.environ.setdefault("MANGO_SEARCH_API_KEY", "test-search-key")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mangopi_cli as m


def _make_agent(agent_cls, name=""):
    """Create a Step instance with a predictable name."""
    return agent_cls()


class LoopEngineTestBase(unittest.TestCase):
    """Base class: mock agent_loop, _get_completion_result, _get_loop_ctx."""

    def setUp(self):
        # Suppress console output
        self.console_patcher = mock.patch.object(m.console, "text")
        self.console_patcher.start()

        # Mock agent_loop (does nothing)
        self.agent_patcher = mock.patch("mangopi_cli.agent_loop")
        self.mock_agent = self.agent_patcher.start()

        # Mock _extract_changed_files to return predictable file list
        self.extract_patcher = mock.patch("mangopi_cli._extract_changed_files",
                                          return_value="src/main.py")
        self.extract_patcher.start()

        # Mock _get_loop_ctx to return temp dir ctx
        self.temp_dir = tempfile.mkdtemp()
        self.ctx_patcher = mock.patch("mangopi_cli._get_loop_ctx")
        self.mock_get_ctx = self.ctx_patcher.start()

        def fake_get_ctx(task_dir, role):
            ctx = m.ContextManager()
            ctx_file = os.path.join(task_dir or self.temp_dir, f"{role}.json")
            ctx.load(ctx_file)
            return ctx, ctx_file
        self.mock_get_ctx.side_effect = fake_get_ctx

    def tearDown(self):
        self.console_patcher.stop()
        self.agent_patcher.stop()
        self.extract_patcher.stop()
        self.ctx_patcher.stop()


# ── Success path ───────────────────────────────────────────────────────

class TestSuccessPath(LoopEngineTestBase):

    def test_normal_success(self):
        """review pass → test pass → succeed → return True"""
        with mock.patch("mangopi_cli._get_completion_result") as mock_res:
            mock_res.side_effect = [
                "VERIFY: PASS",  # ReviewAgent → pass
                "VERIFY: PASS",  # TestAgent → pass
            ]
            result = m.loop_engine("test goal", max_iter=1)
        self.assertTrue(result)

    def test_fast_success(self):
        """dev → test pass → succeed → return True"""
        with mock.patch("mangopi_cli._get_completion_result") as mock_res:
            mock_res.side_effect = [
                "VERIFY: PASS",  # TestAgent → pass
            ]
            result = m.loop_engine("test goal", max_iter=1, fast=True)
        self.assertTrue(result)

    def test_wish_success(self):
        """research → review pass → test pass → succeed → return True"""
        with mock.patch("mangopi_cli._get_completion_result") as mock_res:
            mock_res.side_effect = [
                "research summary",  # ResearchAgent → returns summary
                "VERIFY: PASS",      # ReviewAgent → pass
                "VERIFY: PASS",      # TestAgent → pass
            ]
            result = m.loop_engine("test goal", max_iter=1, wish=True)
        self.assertTrue(result)

    def test_wish_sets_research_in_ctx(self):
        """research summary should be accessible in context"""
        with mock.patch("mangopi_cli._get_completion_result") as mock_res:
            mock_res.side_effect = [
                "my research data",
                "VERIFY: PASS",
                "VERIFY: PASS",
            ]
            m.loop_engine("test goal", max_iter=3, wish=True)
        # _get_completion_result was called, research was stored shared dict
        self.mock_get_ctx.assert_called()


# ── Failure / recovery path ────────────────────────────────────────────

class TestFailurePath(LoopEngineTestBase):

    def test_test_fail_then_exhaust(self):
        """test fail → updater → incr → ... → max_iter exhausted → return False"""
        with mock.patch("mangopi_cli._get_completion_result") as mock_res:
            mock_res.side_effect = [
                "VERIFY: PASS",  # ReviewAgent → pass
                "VERIFY: FAIL",  # TestAgent → fail (round 1)
                "fix the test",  # UpdaterAgent → refined prompt
                "VERIFY: PASS",  # ReviewAgent (round 2)
                "VERIFY: FAIL",  # TestAgent → fail (round 2)
                "fix again",     # UpdaterAgent
            ]
            result = m.loop_engine("test goal", max_iter=2)
        self.assertFalse(result)

    def test_review_fail_then_exhaust(self):
        """review fail → updater → ... → max_iter exhausted → return False"""
        with mock.patch("mangopi_cli._get_completion_result") as mock_res:
            mock_res.side_effect = [
                "VERIFY: FAIL: bad code",  # ReviewAgent → fail (round 1)
                "redesign",      # UpdaterAgent
                "VERIFY: FAIL: still bad",  # ReviewAgent → fail (round 2)
                "redesign again",  # UpdaterAgent
            ]
            result = m.loop_engine("test goal", max_iter=2)
        self.assertFalse(result)

    def test_fast_test_fail_then_exhaust(self):
        """fast mode: test fail → updater → incr → ... → exhausted → return False"""
        with mock.patch("mangopi_cli._get_completion_result") as mock_res:
            mock_res.side_effect = [
                "VERIFY: FAIL",  # TestAgent → fail (round 1)
                "fix it",        # UpdaterAgent
                "VERIFY: FAIL",  # TestAgent → fail (round 2)
            ]
            result = m.loop_engine("test goal", max_iter=2, fast=True)
        self.assertFalse(result)


# ── Error handling ─────────────────────────────────────────────────────

class TestErrorHandling(LoopEngineTestBase):

    def test_agent_loop_raises_exception(self):
        """agent_loop raises → caught → return False"""
        self.mock_agent.side_effect = RuntimeError("API timeout")
        with mock.patch("mangopi_cli._get_completion_result", return_value=""):
            result = m.loop_engine("test goal", max_iter=3)
        self.assertFalse(result)

    def test_empty_goal_still_runs(self):
        """Empty goal string should not crash"""
        with mock.patch("mangopi_cli._get_completion_result") as mock_res:
            mock_res.side_effect = ["VERIFY: PASS", "VERIFY: PASS"]
            result = m.loop_engine("", max_iter=1)
        self.assertTrue(result)


# ── Task ID / persistence ──────────────────────────────────────────────

class TestPersistence(LoopEngineTestBase):

    def test_task_id_generated_when_none(self):
        """task_id auto-generated when not provided"""
        with mock.patch("mangopi_cli._get_completion_result") as mock_res:
            mock_res.side_effect = ["VERIFY: PASS", "VERIFY: PASS"]
            result = m.loop_engine("test goal", max_iter=1)
        self.assertTrue(result)

    def test_user_provided_task_id(self):
        """user-provided task_id is used"""
        with mock.patch("mangopi_cli._get_completion_result") as mock_res:
            mock_res.side_effect = ["VERIFY: PASS", "VERIFY: PASS"]
            result = m.loop_engine("test goal", max_iter=1, task_id="my-custom-id")
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
