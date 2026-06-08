"""Tests for GrepTool — covers recursive regex content search.

Covers:
    * Metadata / schema correctness (name, params, required fields)
    * Invalid regex returns failure with a clear message
    * Hit format: "{filepath}:{line_num}:{content}" (1-based, rstripped)
    * Regex semantics: anchors, character classes, quantifiers,
      greedy/lazy filtering, grouping, alternation
    * Recursive subdirectory traversal
    * Silent skipping of directories, binary files, and unreadable files
    * "none" sentinel when there are no hits
    * 500-hit truncation cap
    * Default path="." and trailing-slash tolerance
"""
import os
import re
import sys
import tempfile
import unittest

# Add parent dir to sys.path so we can import mangopi_cli.
# This file lives at <project>/test/test_grep_tool.py, so the project
# root is one level up from __file__'s directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangopi_cli import GrepTool  # noqa: E402


# ── Module-level helpers ─────────────────────────────────────────────────────


def _tool():
    """Convenience constructor — keeps test bodies short."""
    return GrepTool()


def _write(path, content):
    """Create parent dirs as needed, then write text content to path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _parse_hits(content):
    """Parse GrepTool output into [(filepath, line_num, text), ...].

    Hit line format: "{filepath}:{line_num}:{line_content}"
    Empty content ("none" sentinel) returns an empty list.
    """
    if content == "none":
        return []
    out = []
    for line in content.split("\n"):
        if not line:
            continue
        m = re.match(r"^(?P<path>.+?):(?P<num>\d+):(?P<text>.*)$", line)
        if not m:
            raise AssertionError(
                f"hit line does not match expected format: {line!r}"
            )
        out.append((m.group("path"), int(m.group("num")), m.group("text")))
    return out


# ── 1. Metadata / schema ─────────────────────────────────────────────────────


class TestGrepToolMetadata(unittest.TestCase):
    """Static checks: name, params, and OpenAI-style schema."""

    def test_01_name_is_grep(self):
        self.assertEqual(_tool().name, "grep")

    def test_02_params_keys(self):
        params = _tool().params
        self.assertIn("pat", params)
        self.assertIn("path", params)
        # `pat` is required (type does NOT end with "?")
        self.assertFalse(params["pat"]["type"].endswith("?"))
        # `path` is optional (type ends with "?")
        self.assertTrue(params["path"]["type"].endswith("?"))

    def test_03_schema_required_only_pat(self):
        sch = _tool().schema()
        self.assertEqual(sch["type"], "function")
        self.assertEqual(sch["function"]["name"], "grep")
        required = sch["function"]["parameters"]["required"]
        self.assertEqual(required, ["pat"])
        props = sch["function"]["parameters"]["properties"]
        self.assertEqual(set(props.keys()), {"pat", "path"})
        self.assertEqual(props["pat"]["type"], "string")
        self.assertEqual(props["path"]["type"], "string")


# ── 2. Invalid regex handling ───────────────────────────────────────────────


class TestGrepToolInvalidRegex(unittest.TestCase):
    """Malformed patterns must return failure (not raise)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        # Best-effort cleanup of the entire tmpdir tree.
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_10_unbalanced_paren_is_fail(self):
        r = _tool().run({"pat": "(unclosed", "path": self.tmpdir})
        self.assertFalse(r["success"])
        self.assertIn("invalid regex", r["content"])

    def test_11_trailing_backslash_is_fail(self):
        # Trailing "\" is an invalid escape (no char to escape).
        r = _tool().run({"pat": "abc\\", "path": self.tmpdir})
        self.assertFalse(r["success"])
        self.assertIn("invalid regex", r["content"])

    def test_12_invalid_quantifier_is_fail(self):
        r = _tool().run({"pat": "*invalid", "path": self.tmpdir})
        self.assertFalse(r["success"])
        self.assertIn("invalid regex", r["content"])


# ── 3. Hit format & basic behavior ──────────────────────────────────────────


class TestGrepToolHitFormat(unittest.TestCase):
    """Hit line format and the 'none' sentinel for zero matches."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_20_single_hit_format(self):
        _write(os.path.join(self.tmpdir, "a.txt"), "hello world\nsecond line\n")
        r = _tool().run({"pat": "hello", "path": self.tmpdir})
        self.assertTrue(r["success"])
        hits = _parse_hits(r["content"])
        self.assertEqual(len(hits), 1)
        path, num, text = hits[0]
        self.assertEqual(num, 1)  # 1-based line numbers
        self.assertEqual(text, "hello world")
        self.assertTrue(
            path.endswith("a.txt"),
            f"path should end with a.txt, got {path!r}",
        )

    def test_21_multiple_lines_in_one_file(self):
        _write(
            os.path.join(self.tmpdir, "a.txt"),
            "alpha\nbeta alpha\n\ngamma\nALPHA\n",
        )
        r = _tool().run({"pat": "alpha", "path": self.tmpdir})
        self.assertTrue(r["success"])
        hits = _parse_hits(r["content"])
        # ALPHA (capital) must not match — case-sensitive by default.
        nums = [h[1] for h in hits]
        self.assertEqual(nums, [1, 2])

    def test_22_no_match_returns_none_string(self):
        _write(os.path.join(self.tmpdir, "a.txt"), "no match here\n")
        r = _tool().run({"pat": "zzz", "path": self.tmpdir})
        self.assertTrue(r["success"])
        self.assertEqual(r["content"], "none")

    def test_23_empty_directory_returns_none(self):
        r = _tool().run({"pat": "anything", "path": self.tmpdir})
        self.assertTrue(r["success"])
        self.assertEqual(r["content"], "none")

    def test_24_line_is_rstripped(self):
        _write(os.path.join(self.tmpdir, "a.txt"), "matched   \n")
        r = _tool().run({"pat": "matched", "path": self.tmpdir})
        hits = _parse_hits(r["content"])
        self.assertEqual(len(hits), 1)
        # Trailing whitespace stripped.
        self.assertEqual(hits[0][2], "matched")

    def test_25_case_sensitive_by_default(self):
        _write(os.path.join(self.tmpdir, "a.txt"), "Foo foo FOO\n")
        r = _tool().run({"pat": "foo", "path": self.tmpdir})
        hits = _parse_hits(r["content"])
        # Only the lowercase "foo" on line 1 matches.
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0][2], "Foo foo FOO")


# ── 4. Regex semantics ──────────────────────────────────────────────────────


class TestGrepToolRegexSemantics(unittest.TestCase):
    """Verify regex constructs: anchors, classes, quantifiers, groups."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_30_anchors(self):
        _write(os.path.join(self.tmpdir, "a.txt"), "abc\nxabc\nabcx\n")
        r = _tool().run({"pat": "^abc$", "path": self.tmpdir})
        hits = _parse_hits(r["content"])
        nums = [h[1] for h in hits]
        self.assertEqual(nums, [1])

    def test_31_character_class(self):
        _write(os.path.join(self.tmpdir, "a.txt"), "a1\nb2\nc3\n")
        r = _tool().run({"pat": "[ac]\\d", "path": self.tmpdir})
        hits = _parse_hits(r["content"])
        nums = [h[1] for h in hits]
        self.assertEqual(nums, [1, 3])

    def test_32_quantifier(self):
        # abc?d? = "ab" + optional "c" + optional "d"
        _write(os.path.join(self.tmpdir, "a.txt"), "ab\nabc\nabcd\n")
        r = _tool().run({"pat": "abc?d?", "path": self.tmpdir})
        hits = _parse_hits(r["content"])
        nums = [h[1] for h in hits]
        self.assertEqual(nums, [1, 2, 3])

    def test_33_greedy_vs_lazy_filter_behavior(self):
        """GrepTool uses re.search() to decide which lines to include, and
        outputs the full line (rstripped) — not the matched slice. So
        greedy vs lazy doesn't change the visible text, only which lines
        match.

        Part A: two patterns hit the same line; both return the full line.
        """
        _write(os.path.join(self.tmpdir, "a.txt"), "<a><b>\n")
        r_a = _tool().run({"pat": "<a>", "path": self.tmpdir})
        r_b = _tool().run({"pat": "<b>", "path": self.tmpdir})
        hits_a = _parse_hits(r_a["content"])
        hits_b = _parse_hits(r_b["content"])
        self.assertEqual(len(hits_a), 1)
        self.assertEqual(len(hits_b), 1)
        self.assertEqual(hits_a[0][2], "<a><b>")
        self.assertEqual(hits_b[0][2], "<a><b>")

        # Part B: an anchored pattern must NOT match lines that don't
        # fully satisfy the anchor.
        _write(os.path.join(self.tmpdir, "a.txt"), "abc\nxyz\n")
        r_anchor = _tool().run({"pat": "^abc$", "path": self.tmpdir})
        hits_anchor = _parse_hits(r_anchor["content"])
        self.assertEqual(len(hits_anchor), 1)
        self.assertEqual(hits_anchor[0][1], 1)

    def test_34_group_and_alternation(self):
        _write(os.path.join(self.tmpdir, "a.txt"), "cat\ndog\ncow\n")
        r = _tool().run({"pat": "(cat|dog)", "path": self.tmpdir})
        hits = _parse_hits(r["content"])
        nums = [h[1] for h in hits]
        self.assertEqual(nums, [1, 2])


# ── 5. Recursive traversal ──────────────────────────────────────────────────


class TestGrepToolRecursion(unittest.TestCase):
    """Subdirectories must be walked transparently."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_40_matches_in_subdirectory(self):
        _write(os.path.join(self.tmpdir, "sub", "deep", "a.txt"), "needle\n")
        r = _tool().run({"pat": "needle", "path": self.tmpdir})
        hits = _parse_hits(r["content"])
        self.assertEqual(len(hits), 1)
        path = hits[0][0]
        # Reported path must include both the subdir and the file.
        self.assertIn("sub", path)
        self.assertIn("a.txt", path)

    def test_41_matches_in_deeply_nested(self):
        _write(
            os.path.join(self.tmpdir, "a", "b", "c", "d", "e", "leaf.txt"),
            "deep\n",
        )
        r = _tool().run({"pat": "deep", "path": self.tmpdir})
        hits = _parse_hits(r["content"])
        self.assertEqual(len(hits), 1)
        self.assertIn("leaf.txt", hits[0][0])

    def test_42_search_path_is_dir_not_root(self):
        """Explicit `path` must NOT bleed into other cwd directories."""
        # In self.tmpdir, we have a real hit.
        _write(os.path.join(self.tmpdir, "inside.txt"), "token\n")
        # In a separate dir, we have a hit that should be ignored.
        with tempfile.TemporaryDirectory() as other:
            _write(os.path.join(other, "outside.txt"), "token\n")
            r = _tool().run({"pat": "token", "path": self.tmpdir})
            hits = _parse_hits(r["content"])
            self.assertEqual(len(hits), 1)
            self.assertIn("inside.txt", hits[0][0])
            self.assertNotIn("outside.txt", hits[0][0])


# ── 6. Skips: directories / binary / nonexistent ─────────────────────────────


class TestGrepToolSkips(unittest.TestCase):
    """Tool must silently skip files it can't read instead of failing."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_50_directories_are_skipped(self):
        """glob() yields directory entries; they must not be opened as files."""
        _write(os.path.join(self.tmpdir, "sub", "a.txt"), "matched\n")
        r = _tool().run({"pat": "matched", "path": self.tmpdir})
        self.assertTrue(r["success"])
        hits = _parse_hits(r["content"])
        self.assertEqual(len(hits), 1)
        self.assertIn("a.txt", hits[0][0])

    def test_51_binary_file_silently_skipped(self):
        """Files with invalid UTF-8 bytes must be silently skipped (open()
        raises → the `except: continue` path)."""
        bin_path = os.path.join(self.tmpdir, "blob.bin")
        with open(bin_path, "wb") as f:
            f.write(b"\xff\xfe\xfd\x00\x01invalid seq")
        # Plus a real text file with a hit.
        _write(os.path.join(self.tmpdir, "a.txt"), "findme\n")
        r = _tool().run({"pat": "findme", "path": self.tmpdir})
        self.assertTrue(r["success"])
        hits = _parse_hits(r["content"])
        self.assertEqual(len(hits), 1)
        self.assertIn("a.txt", hits[0][0])
        self.assertNotIn("blob.bin", r["content"])

    def test_52_empty_file_is_fine(self):
        """Zero-byte file must not blow up the iterator."""
        # 0-byte file
        open(os.path.join(self.tmpdir, "empty.txt"), "w", encoding="utf-8").close()
        _write(os.path.join(self.tmpdir, "a.txt"), "found\n")
        r = _tool().run({"pat": "found", "path": self.tmpdir})
        hits = _parse_hits(r["content"])
        self.assertEqual(len(hits), 1)

    def test_53_directory_heavy_path_works(self):
        """A tree with multiple subdirectories and files must walk cleanly."""
        for i in range(3):
            _write(os.path.join(self.tmpdir, f"d{i}", "x.txt"), f"hit{i}\n")
        r = _tool().run({"pat": "hit", "path": self.tmpdir})
        hits = _parse_hits(r["content"])
        self.assertEqual(len(hits), 3)


# ── 7. Hit cap of 500 ───────────────────────────────────────────────────────


class TestGrepToolHitCap(unittest.TestCase):
    """GrepTool must truncate output to 500 hits."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_60_exactly_500_hits_all_returned(self):
        _write(
            os.path.join(self.tmpdir, "a.txt"),
            "\n".join(f"line {i}" for i in range(500)) + "\n",
        )
        r = _tool().run({"pat": "line", "path": self.tmpdir})
        self.assertTrue(r["success"])
        hits = _parse_hits(r["content"])
        self.assertEqual(len(hits), 500)

    def test_61_more_than_500_hits_truncated(self):
        _write(
            os.path.join(self.tmpdir, "a.txt"),
            "\n".join(f"line {i}" for i in range(501)) + "\n",
        )
        r = _tool().run({"pat": "line", "path": self.tmpdir})
        self.assertTrue(r["success"])
        hits = _parse_hits(r["content"])
        self.assertEqual(len(hits), 500)

    def test_62_1000_hits_truncated_to_500(self):
        _write(
            os.path.join(self.tmpdir, "a.txt"),
            "\n".join(f"hit {i}" for i in range(1000)) + "\n",
        )
        r = _tool().run({"pat": "hit", "path": self.tmpdir})
        hits = _parse_hits(r["content"])
        self.assertEqual(len(hits), 500)


# ── 8. Multi-file aggregation ───────────────────────────────────────────────


class TestGrepToolMultiFile(unittest.TestCase):
    """Hits from several files must be aggregated into one response."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_70_hits_across_multiple_files(self):
        _write(os.path.join(self.tmpdir, "a.txt"), "shared\n")
        _write(os.path.join(self.tmpdir, "b.txt"), "shared\n")
        _write(os.path.join(self.tmpdir, "sub", "c.txt"), "shared\n")
        r = _tool().run({"pat": "shared", "path": self.tmpdir})
        hits = _parse_hits(r["content"])
        self.assertEqual(len(hits), 3)
        files = sorted(h[0] for h in hits)
        self.assertTrue(any("a.txt" in f for f in files))
        self.assertTrue(any("b.txt" in f for f in files))
        self.assertTrue(any("c.txt" in f for f in files))

    def test_71_file_path_includes_subdir(self):
        _write(os.path.join(self.tmpdir, "sub", "x.txt"), "tag\n")
        r = _tool().run({"pat": "tag", "path": self.tmpdir})
        hits = _parse_hits(r["content"])
        self.assertEqual(len(hits), 1)
        path = hits[0][0]
        # Reported path should reference the subdir/file structure.
        expected = os.sep + "sub" + os.sep + "x.txt"
        self.assertTrue(
            expected in path or "sub/x.txt" in path,
            f"path should contain sub/x.txt, got {path!r}",
        )


# ── 9. Line numbering & empty lines ─────────────────────────────────────────


class TestGrepToolLineNumbers(unittest.TestCase):
    """Line numbers must be 1-based; empty lines must not match '.'."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_80_line_numbers_are_1_based(self):
        #     1: empty
        #     2: x
        #     3: empty
        #     4: y
        _write(
            os.path.join(self.tmpdir, "a.txt"),
            "\n" + "x\n" + "\n" + "y\n",
        )
        r = _tool().run({"pat": "x|y", "path": self.tmpdir})
        hits = _parse_hits(r["content"])
        nums = sorted(h[1] for h in hits)
        self.assertEqual(nums, [2, 4])

    def test_81_empty_line_does_not_match_anything(self):
        _write(os.path.join(self.tmpdir, "a.txt"), "\n\n\n")
        # No characters → '.' cannot match.
        r = _tool().run({"pat": ".", "path": self.tmpdir})
        self.assertEqual(r["content"], "none")


# ── 10. Default path behavior ───────────────────────────────────────────────


class TestGrepToolPathDefault(unittest.TestCase):
    """`path` is optional; omitting it must search cwd."""

    def setUp(self):
        # A fresh tmpdir we chdir into for the cwd-dependent test, plus
        # a private tmpdir for the trailing-slash test.
        self.tmpdir = tempfile.mkdtemp()
        self.altdir = tempfile.mkdtemp()

    def tearDown(self):
        # Make sure we restore cwd before tearing down.
        try:
            os.chdir(self._restore_cwd)
        except (AttributeError, OSError):
            pass
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.altdir, ignore_errors=True)

    def test_90_omitted_path_uses_cwd(self):
        """Omitting `path` should search cwd (defaults to '.' in glob)."""
        _write(os.path.join(self.tmpdir, "marker.txt"), "in-cwd\n")
        old_cwd = os.getcwd()
        self._restore_cwd = old_cwd
        try:
            os.chdir(self.tmpdir)
            r = _tool().run({"pat": "in-cwd"})  # no `path` arg
            self.assertTrue(r["success"])
            self.assertIn("marker.txt", r["content"])
        finally:
            os.chdir(old_cwd)

    def test_91_path_with_trailing_slash_works(self):
        """Trailing separator must not break the glob."""
        _write(os.path.join(self.altdir, "a.txt"), "x\n")
        r = _tool().run({"pat": "x", "path": self.altdir + os.sep})
        self.assertTrue(r["success"])
        self.assertIn("a.txt", r["content"])


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)