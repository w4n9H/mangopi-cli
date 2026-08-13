"""Tests for ClipboardTool (shipped extension: examples/extensions/clipboard.py).

Covers:
    * read: pipes pbpaste/xclip output, returns trimmed text
    * write: feeds text via stdin, reports char count
    * confirm: read skips confirmation, write requires console.prompt_apply
      (denied → run_tool returns "User denied action")
    * validation: bad action, write without text
    * unsupported platform error (simulated)
"""
import importlib.util
import os
import subprocess
import sys
import unittest
from unittest import mock

# Force a fake MANGO_KEY so the module-level create_provider() doesn't choke
os.environ.setdefault("MANGO_KEY", "test-key-not-used")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mangopi_cli as m  # noqa: E402

# ── Load the shipped extension module ────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT_PATH = os.path.join(PROJECT_ROOT, "examples", "extensions", "clipboard.py")
_spec = importlib.util.spec_from_file_location("mango_clipboard_ext", EXT_PATH)
clip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(clip)
ClipboardTool = clip.ClipboardTool


def _proc(stdout="", rc=0):
    return mock.Mock(returncode=rc, stdout=stdout, stderr="err-msg")


class ClipboardTestBase(unittest.TestCase):
    def setUp(self):
        self._orig_apply = m.console.prompt_apply
        self._orig_yolo = m.MANGO_YOLO
        m.MANGO_YOLO = False

    def tearDown(self):
        m.console.prompt_apply = self._orig_apply
        m.MANGO_YOLO = self._orig_yolo

    def _run(self, **kwargs):
        return m.run_tool("clipboard", kwargs)


class TestRead(ClipboardTestBase):
    def test_read_returns_trimmed_text(self):
        with mock.patch.object(subprocess, "run", return_value=_proc("line1\nline2\n\n")):
            r = self._run(action="read")
        self.assertTrue(r["success"])
        self.assertEqual(r["content"], "line1\nline2")

    def test_read_does_not_ask_confirmation(self):
        m.console.prompt_apply = mock.Mock(return_value=True)
        with mock.patch.object(subprocess, "run", return_value=_proc("x")):
            r = self._run()  # 默认 action=read
        self.assertTrue(r["success"])
        m.console.prompt_apply.assert_not_called()

    def test_read_command_failure(self):
        with mock.patch.object(subprocess, "run", return_value=_proc(rc=1)):
            r = self._run(action="read")
        self.assertFalse(r["success"])
        self.assertIn("err-msg", r["content"])


class TestWrite(ClipboardTestBase):
    def test_write_feeds_text_and_reports_count(self):
        m.console.prompt_apply = mock.Mock(return_value=True)
        with mock.patch.object(subprocess, "run", return_value=_proc()) as run:
            r = self._run(action="write", text="hello")
        self.assertTrue(r["success"])
        self.assertIn("5 chars", r["content"])
        args, kwargs = run.call_args
        self.assertEqual(args[0], clip.ClipboardTool._commands()[0])  # write_cmd
        self.assertEqual(kwargs["input"], "hello")

    def test_write_denied_by_confirmation(self):
        m.console.prompt_apply = mock.Mock(return_value=False)
        with mock.patch.object(subprocess, "run") as run:
            r = self._run(action="write", text="secret")
        self.assertFalse(r["success"])
        self.assertIn("User denied action", r["content"])
        run.assert_not_called()  # 拒绝后不触碰剪贴板

    def test_write_without_text_fails(self):
        m.console.prompt_apply = mock.Mock(return_value=True)
        r = self._run(action="write")
        self.assertFalse(r["success"])
        self.assertIn("'text' is required", r["content"])


class TestValidationAndPlatform(ClipboardTestBase):
    def test_bad_action(self):
        r = self._run(action="copy")
        self.assertFalse(r["success"])
        self.assertIn("'action' must be 'read' or 'write'", r["content"])

    def test_unsupported_platform(self):
        with mock.patch.object(sys, "platform", "win32"):
            r = self._run(action="read")
        self.assertFalse(r["success"])
        self.assertIn("unsupported platform", r["content"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
