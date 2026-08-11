"""Tests for CLI session persistence (.current) and session name helpers.

Covers:
    * _current_session_name: no .current file → default "session"
    * .current with valid name + existing file → restored
    * .current with invalid name (.., /) → fallback to "session"
    * .current pointing to a deleted session file → fallback
    * _save_current_session → round-trip readable by _current_session_name
"""
import os
import sys
import tempfile
import unittest

# Add parent dir to sys.path so we can import mangopi_cli.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MANGO_KEY", "test-key-not-used")

import mangopi_cli as m  # noqa: E402


class TestCurrentSessionName(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.orig_session_dir = m.session_dir
        m.session_dir = self._tmp.name

    def tearDown(self):
        m.session_dir = self.orig_session_dir
        self._tmp.cleanup()

    def _touch(self, name):
        with open(os.path.join(m.session_dir, name + ".json"), "w", encoding="utf-8") as f:
            f.write("[]")

    def _write_current(self, content):
        with open(os.path.join(m.session_dir, ".current"), "w", encoding="utf-8") as f:
            f.write(content)

    def test_no_current_file_falls_back_to_default(self):
        self.assertEqual(m._current_session_name(), "session")

    def test_valid_name_restored(self):
        self._touch("feature-x")
        self._write_current("feature-x")
        self.assertEqual(m._current_session_name(), "feature-x")

    def test_invalid_name_falls_back(self):
        self._write_current("../evil")
        self.assertEqual(m._current_session_name(), "session")
        self._write_current("a/b")
        self.assertEqual(m._current_session_name(), "session")

    def test_deleted_session_file_falls_back(self):
        self._write_current("gone")
        self.assertEqual(m._current_session_name(), "session")

    def test_save_round_trip(self):
        self._touch("review")
        self._touch("session")
        m._save_current_session("review")
        self.assertEqual(m._current_session_name(), "review")
        m._save_current_session("session")
        self.assertEqual(m._current_session_name(), "session")


if __name__ == "__main__":
    unittest.main()
