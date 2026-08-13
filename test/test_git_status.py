"""Tests for GitStatusTool (shipped extension: examples/extensions/git_status.py).

Covers:
    * status: branch line + changed-file count (in a real git repo)
    * log: commit list with limit validation
    * diff: working-tree + staged sections
    * validation: bad action, non-integer limit
    * non-git directory returns a clear error
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest import mock

# Force a fake MANGO_KEY so the module-level create_provider() doesn't choke
os.environ.setdefault("MANGO_KEY", "test-key-not-used")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mangopi_cli as m  # noqa: E402

# ── Load the shipped extension module ────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT_PATH = os.path.join(PROJECT_ROOT, "examples", "extensions", "git_status.py")
_spec = importlib.util.spec_from_file_location("mango_git_status_ext", EXT_PATH)
git = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(git)
GitStatusTool = git.GitStatusTool


class TestGitStatus(unittest.TestCase):
    """当前测试进程 cwd 即 git 仓库 (mangopi-cli), 真实 git 输出可用."""

    def test_status_reports_branch_and_count(self):
        r = m.run_tool("git_status", {"action": "status"})
        self.assertTrue(r["success"], r["content"])
        lines = r["content"].splitlines()
        self.assertTrue(lines[0].startswith("##"), lines[0])          # 分支行
        self.assertRegex(lines[-1], r"^\(\d+ changed file\(s\)\)$")   # 计数行

    def test_log_lists_commits(self):
        r = m.run_tool("git_status", {"action": "log", "limit": 2})
        self.assertTrue(r["success"], r["content"])
        lines = r["content"].splitlines()
        self.assertIn("Last 2 commit(s)", lines[0])
        self.assertGreaterEqual(len(lines), 2)

    def test_diff_has_both_sections(self):
        r = m.run_tool("git_status", {"action": "diff"})
        self.assertTrue(r["success"], r["content"])
        self.assertIn("## Working tree", r["content"])
        self.assertIn("## Staged", r["content"])

    def test_bad_action(self):
        r = m.run_tool("git_status", {"action": "blame"})
        self.assertFalse(r["success"])
        self.assertIn("status/log/diff", r["content"])

    def test_bad_limit(self):
        r = m.run_tool("git_status", {"action": "log", "limit": "many"})
        self.assertFalse(r["success"])
        self.assertIn("'limit' must be an integer", r["content"])

    def test_not_a_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("mangopi_cli.project_root", tmp):
                r = m.run_tool("git_status", {"action": "status"})
        self.assertFalse(r["success"])
        self.assertIn("git_status error", r["content"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
