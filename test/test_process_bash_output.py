"""Tests for _process_bash_output() and its sub-helpers.

Covers:
    * Empty/falsy output short-circuit
    * Non-directory commands: pass-through (no filter, but still line-limited)
    * Directory-heavy commands: drop lines that reference FILTERED_DIRS
    * 1000-line truncation cap (and its composition with the filter)
    * _is_directory_heavy boundary cases (substring-match regressions)
    * _filter_directory_output path-shape variants
"""
import os
import sys
import unittest

# Add parent dir to sys.path so we can import mangopi_cli.
# This file lives at <project>/test/test_process_bash_output.py,
# so the project root is one level up from __file__'s directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangopi_cli import (  # noqa: E402
    _process_bash_output,
    _is_directory_heavy,
    _filter_directory_output,
    _limit_output_lines,
)


# ── 1. Empty / falsy output short-circuit ───────────────────────────────────


class TestEmptyOutputShortCircuit(unittest.TestCase):
    """When output is empty, _process_bash_output returns it untouched."""

    def test_01_empty_list(self):
        # Empty list must short-circuit; no command branching happens.
        self.assertEqual(_process_bash_output("ls -la", []), [])

    def test_02_empty_list_with_directory_command(self):
        # Even when the command is "directory-heavy", empty output is
        # returned as-is (no filtering, no truncation marker).
        self.assertEqual(_process_bash_output("find . -name '*.py'", []), [])


# ── 2. Non-directory commands: pass-through (with line cap) ─────────────────


class TestNonDirectoryCommandsPassThrough(unittest.TestCase):
    """Commands not classified as directory-heavy must keep their output."""

    def test_10_non_dir_command_unchanged(self):
        self.assertEqual(
            _process_bash_output("echo hello", ["hello"]),
            ["hello"],
        )

    def test_11_non_dir_command_keeps_git_paths(self):
        """Non-dir commands must not invoke the directory filter, so .git
        and node_modules references in arbitrary output are preserved."""
        self.assertEqual(
            _process_bash_output(
                "echo ./node_modules/foo",
                ["./node_modules/foo", "build/output.bin"],
            ),
            ["./node_modules/foo", "build/output.bin"],
        )

    def test_12_non_dir_command_preserves_1000_lines(self):
        # 1000 lines is exactly the cap; nothing should be truncated.
        lines = [f"line-{i}" for i in range(1000)]
        self.assertEqual(_process_bash_output("cat big.txt", lines), lines)


# ── 3. Directory-heavy commands: filter lines referencing FILTERED_DIRS ─────


class TestDirectoryHeavyFiltering(unittest.TestCase):
    """When the command is directory-heavy, lines that reference any
    FILTERED_DIRS path shape must be removed."""

    def test_20_find_filters_node_modules(self):
        self.assertEqual(
            _process_bash_output(
                "find . -type f",
                ["./node_modules/lib/index.js", "./src/main.py"],
            ),
            ["./src/main.py"],
        )

    def test_21_find_filters_git(self):
        self.assertEqual(
            _process_bash_output(
                "find . -type d",
                ["./src", "./.git/objects/abc", "./README.md"],
            ),
            ["./src", "./README.md"],
        )

    def test_22_find_filters_multiple_dirs(self):
        self.assertEqual(
            _process_bash_output(
                "find .",
                [
                    "./__pycache__/x.cpython-311.pyc",
                    "./dist/bundle.js",
                    "./build/output",
                    "./src/a.py",
                    "./.venv/lib/python",
                ],
            ),
            ["./src/a.py"],
        )

    def test_23_tree_command_filters(self):
        self.assertEqual(
            _process_bash_output(
                "tree -L 2",
                ["./node_modules", "./src", "./.git"],
            ),
            ["./src"],
        )

    def test_24_ls_R_command_filters(self):
        self.assertEqual(
            _process_bash_output(
                "ls -R",
                ["./node_modules/foo", "./vendor/bar", "./src/main.py"],
            ),
            ["./src/main.py"],
        )

    def test_25a_du_filters_slash_separated_path(self):
        # A path containing "/__pycache__/" is filtered; tab-separated
        # pure-name rows survive (next test).
        self.assertEqual(
            _process_bash_output(
                "du -sh *",
                ["./__pycache__/x.cpython-311.pyc", "./src\t10K"],
            ),
            ["./src\t10K"],
        )

    def test_25b_du_keeps_tab_separated_pure_name(self):
        # Plain "__pycache__" name (no slashes) is NOT in the path-shape
        # set, so the row must be preserved.
        self.assertEqual(
            _process_bash_output(
                "du -sh *",
                ["__pycache__\t1K", "./src\t10K"],
            ),
            ["__pycache__\t1K", "./src\t10K"],
        )

    def test_26_fd_command_filters(self):
        self.assertEqual(
            _process_bash_output(
                "fd py",
                ["./node_modules/foo.py", "./.cache/data", "./src/main.py"],
            ),
            ["./src/main.py"],
        )

    def test_27_rg_command_filters(self):
        self.assertEqual(
            _process_bash_output(
                "rg pattern",
                ["./.git/config:token=abc", "./src/a.py:pattern"],
            ),
            ["./src/a.py:pattern"],
        )

    def test_28_filter_skips_unrelated_lines(self):
        # When nothing matches a FILTERED_DIRS path shape, the output
        # is unchanged.
        self.assertEqual(
            _process_bash_output(
                "find . -name '*.py'",
                ["./src/main.py", "./tests/test_a.py", "./docs/readme.py"],
            ),
            ["./src/main.py", "./tests/test_a.py", "./docs/readme.py"],
        )


# ── 4. Line-limit truncation (1000-line cap) ────────────────────────────────


class TestLineLimitTruncation(unittest.TestCase):
    """Output over 1000 lines must be truncated and a marker appended."""

    def test_30_exactly_1000_lines_not_truncated(self):
        lines = [f"line-{i}" for i in range(1000)]
        self.assertEqual(_process_bash_output("echo loop", lines), lines)

    def test_31_over_1000_lines_truncated(self):
        lines = [f"line-{i}" for i in range(1003)]
        expected = lines[:1000] + ["", "... truncated 3 lines ..."]
        self.assertEqual(
            _process_bash_output("cat huge.txt", lines),
            expected,
        )


# ── 5. Filter + truncate composition ────────────────────────────────────────


class TestFilterThenTruncateComposition(unittest.TestCase):
    """Filter runs first, then the 1000-line cap. These tests pin down
    the ordering: filtered count is what the cap measures."""

    def test_32a_filtered_count_exactly_1000_no_truncate(self):
        # 1000 rows that survive the filter → exactly at the cap, no marker.
        lines = [f"./src/file-{i}.py" for i in range(1000)]
        self.assertEqual(
            _process_bash_output("find . -name '*.py'", lines),
            lines,
        )

    def test_32b_filtered_count_1001_truncated(self):
        # 1001 rows survive the filter → cap triggers, 1 line dropped.
        lines = [f"./src/file-{i}.py" for i in range(1001)]
        expected = lines[:1000] + ["", "... truncated 1 lines ..."]
        self.assertEqual(
            _process_bash_output("find . -name '*.py'", lines),
            expected,
        )

    def test_32c_filtered_count_600_no_truncate(self):
        # 500 filtered + 600 survivors → 600 survivors, no cap triggered.
        lines = (
            [f"./node_modules/f{i}.js" for i in range(500)]
            + [f"./src/file-{i}.py" for i in range(600)]
        )
        expected = [f"./src/file-{i}.py" for i in range(600)]
        self.assertEqual(_process_bash_output("find .", lines), expected)

    def test_33a_filtered_count_800_no_truncate(self):
        # 500 filtered + 800 survivors → 800 survivors, no cap.
        lines = (
            [f"./node_modules/f{i}.js" for i in range(500)]
            + [f"./src/f{i}.py" for i in range(800)]
        )
        expected = [f"./src/f{i}.py" for i in range(800)]
        self.assertEqual(_process_bash_output("find .", lines), expected)

    def test_33b_unfiltered_1200_lines_truncated(self):
        # 1200 lines, none filtered → cap triggers, 200 dropped.
        lines = [f"./src/f{i}.py" for i in range(1200)]
        expected = lines[:1000] + ["", "... truncated 200 lines ..."]
        self.assertEqual(_process_bash_output("find .", lines), expected)


# ── 6. _is_directory_heavy boundary cases ───────────────────────────────────


class TestIsDirectoryHeavyEdgeCases(unittest.TestCase):
    """Direct unit tests of _is_directory_heavy() for substring matches.

    The implementation does `k in command` against literal substrings
    like "find " (with trailing space), "tree", "ls -R", "du ", "fd ", "rg ".
    These tests pin down which substrings trigger the classifier and
    protect against regressions on the boundary.
    """

    def test_40_non_heavy_commands_not_filtered(self):
        # Each command below is NOT directory-heavy and must keep all
        # rows including ones that look like filtered paths.
        commands = [
            "ls -la",
            "ls",
            "grep -r pattern",
            "cat file.txt",
            "echo hi",
            "git status",
            "npm install",
            "python script.py",
        ]
        for cmd in commands:
            with self.subTest(cmd=cmd):
                result = _process_bash_output(
                    cmd, ["./.git/HEAD", "./node_modules/x"]
                )
                self.assertEqual(
                    result,
                    ["./.git/HEAD", "./node_modules/x"],
                    f"误过滤: command={cmd!r} result={result!r}",
                )

    def test_41_substring_match_does_not_misclassify(self):
        # Tuple: (command, expected classification)
        cases = [
            ("find . -name '*.py'", True),
            ("findings.txt", False),       # 'find' as a word fragment
            ("defined()", False),          # 'find' substring inside word
            ("ls", False),
            ("ls -l", False),
            ("ls -R", True),
            ("tree", True),
            ("du -sh", True),
            ("du", False),
            ("fd pattern", True),
            ("rg foo", True),
        ]
        for cmd, expected in cases:
            with self.subTest(cmd=cmd):
                actual = _is_directory_heavy(cmd)
                self.assertEqual(
                    actual,
                    expected,
                    f"_is_directory_heavy({cmd!r}) expected {expected}, "
                    f"got {actual}",
                )


# ── 7. _filter_directory_output path-shape variants ─────────────────────────


class TestFilterDirectoryOutputPathShapes(unittest.TestCase):
    """Direct unit tests of _filter_directory_output() for the various
    path shapes that should be recognized as 'inside a filtered dir'.
    """

    def test_50_filter_patterns_variants(self):
        """Many path shapes of the same filtered dir must all be filtered.

        Row-by-row intent:
            "./node_modules/a"        # ./d/
            "src/node_modules/b"      # /d/
            "node_modules/c"          # starting d/
            "./dist:bundle.js"        # ./d:
            "vendor/lib:0.0.1"        # /d:
            "target/classes/X"        # /d/
            "./.cache/data"           # ./d/
            "endswith/__pycache__"    # trailing /d
            "./.idea"                 # starting ./
            ".venv"                   # exact match
            "./build"                 # starting ./
            "./src/keep_this.py"      # KEEP
        """
        cmd = "find ."
        raw = [
            "./node_modules/a",
            "src/node_modules/b",
            "node_modules/c",
            "./dist:bundle.js",
            "vendor/lib:0.0.1",
            "target/classes/X",
            "./.cache/data",
            "endswith/__pycache__",
            "./.idea",
            ".venv",
            "./build",
            "./src/keep_this.py",
        ]
        expected = ["./src/keep_this.py"]
        self.assertEqual(_process_bash_output(cmd, raw), expected)

    def test_50_direct_filter_call_matches(self):
        # Calling the helper directly must produce the same result as
        # routing through _process_bash_output().
        raw = [
            "./node_modules/a",
            "src/node_modules/b",
            "./src/keep_this.py",
        ]
        self.assertEqual(
            _filter_directory_output(raw),
            ["./src/keep_this.py"],
        )

    def test_50_limit_output_lines_under_cap(self):
        # The bare line-limiter is a no-op below the cap.
        lines = [f"line-{i}" for i in range(1000)]
        self.assertEqual(_limit_output_lines(lines), lines)

    def test_50_limit_output_lines_over_cap(self):
        # Over the cap → first 1000 + sentinel.
        lines = [f"line-{i}" for i in range(1005)]
        self.assertEqual(
            _limit_output_lines(lines),
            lines[:1000] + ["", "... truncated 5 lines ..."],
        )


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)