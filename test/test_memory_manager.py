"""Tests for MemoryManager — focus on `search()` scoring & sort.

Score formula (per matching chunk):
    score = (count(keyword) × 10) × num_keywords  + length_bonus + mtime_bonus
    length_bonus = min(len(chunk) // 200, 5)             # 0..5
    mtime_bonus  = max(0, 30 - days_since_mtime)         # 0..30, linear decay

Covers:
    * `_tokenize` static method
    * `_split_chunks` static method
    * `search()` boundary cases (empty query, no .md files, no hits,
      non-.md ignored)
    * Hit format & substring/case behavior
    * Content truncation to 2000 chars
    * Scoring components: keyword frequency, length bonus, mtime bonus
    * Multi-keyword additive scoring
    * Combined ranking (keyword-count vs mtime)
    * `top_k` truncation
    * Multi-file aggregation & chunk-split behavior
"""
import os
import re
import shutil
import sys
import tempfile
import time
import unittest

# Add parent dir to sys.path so we can import mangopi_cli.
# This file lives at <project>/test/test_memory_manager.py,
# so the project root is one level up from __file__'s directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangopi_cli import MemoryManager  # noqa: E402


# ── Module-level helpers ─────────────────────────────────────────────────────


NO_HIT_PREFIX = "No memory found."


def _make_manager(memory_dir):
    """Build a MemoryManager pointed at an isolated tempdir (so we don't
    touch the real ~/.mangocli/memory)."""
    mm = MemoryManager()
    mm.memory_dir = memory_dir
    return mm


def _write(path, text, mtime=None):
    """Write `text` to `path`; optionally set mtime (epoch seconds)."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _parse_results(out):
    """Parse `search()`'s string output into [(file, score, content), ...].

    Format per record: "# {file} (score={score})\\n{content}"
    Multi-record separator: "\\n\\n---\\n\\n".
    Sentinel strings (`'empty query'`, the `'No memory found.'` tip) are
    returned as-is for the caller to assert on.
    """
    assert isinstance(out, str), f"expected str, got {type(out)}"
    if out == "empty query" or out.startswith(NO_HIT_PREFIX):
        return out
    records = out.split("\n\n---\n\n")
    parsed = []
    pat = re.compile(
        r"^# (?P<file>[^ ]+) \(score=(?P<score>-?\d+)\)\n(?P<content>.*)$",
        re.DOTALL,
    )
    for rec in records:
        m = pat.match(rec)
        if not m:
            raise AssertionError(
                f"record does not match expected format: {rec!r}"
            )
        parsed.append(
            (m.group("file"), int(m.group("score")), m.group("content"))
        )
    return parsed


# ── 1. _tokenize static method ─────────────────────────────────────────────


class TestTokenize(unittest.TestCase):
    """`_tokenize` splits on whitespace and lower-cases; it intentionally
    does NOT strip punctuation (matches `search()`'s substring matching).
    """

    def test_01_tokenize_basic(self):
        self.assertEqual(
            MemoryManager._tokenize("Hello World"),
            ["hello", "world"],
        )

    def test_02_tokenize_lowercase_and_strip(self):
        self.assertEqual(
            MemoryManager._tokenize("  Foo   BAR  "),
            ["foo", "bar"],
        )

    def test_03_tokenize_empty_and_whitespace(self):
        self.assertEqual(MemoryManager._tokenize(""), [])
        self.assertEqual(MemoryManager._tokenize("   \t  "), [])

    def test_04_tokenize_keeps_internal_punct(self):
        # Punctuation is preserved as part of the token.
        self.assertEqual(
            MemoryManager._tokenize("foo,bar.baz"),
            ["foo,bar.baz"],
        )


# ── 2. _split_chunks static method ─────────────────────────────────────────


class TestSplitChunks(unittest.TestCase):
    """`_split_chunks` splits on blank lines (`\\n\\s*\\n`) and skips empties."""

    def test_10_split_chunks_on_blank_line(self):
        self.assertEqual(
            MemoryManager._split_chunks("alpha\n\nbeta\n\ngamma"),
            ["alpha", "beta", "gamma"],
        )

    def test_11_split_chunks_skips_empty(self):
        self.assertEqual(
            MemoryManager._split_chunks("\n\nfoo\n\n   \n\nbar\n\n"),
            ["foo", "bar"],
        )

    def test_12_split_chunks_preserves_newlines_inside_block(self):
        self.assertEqual(
            MemoryManager._split_chunks("line1\nline2\nline3\n\nline4"),
            ["line1\nline2\nline3", "line4"],
        )


# ── 3. search() boundary cases (empty query / no match / no files) ─────────


class TestSearchBoundaryCases(unittest.TestCase):
    """`search()` short-circuits or returns the documented 'No memory
    found.' sentinel for the obvious non-match inputs.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_20_empty_query_returns_empty_query(self):
        mm = _make_manager(self.tmpdir)
        self.assertEqual(mm.search(""), "empty query")

    def test_21_whitespace_only_query_returns_empty_query(self):
        mm = _make_manager(self.tmpdir)
        self.assertEqual(mm.search("   \t  "), "empty query")

    def test_22_no_memory_dir_returns_no_match(self):
        """memory_dir exists but has no .md files → 'No memory found.'"""
        mm = _make_manager(self.tmpdir)
        # Place a non-.md file to verify the glob filter excludes it.
        with open(os.path.join(self.tmpdir, "ignore.txt"), "w") as f:
            f.write("apple banana")
        self.assertTrue(mm.search("apple").startswith(NO_HIT_PREFIX))

    def test_23_no_matching_chunks_returns_no_match(self):
        mm = _make_manager(self.tmpdir)
        _write(
            os.path.join(self.tmpdir, "2024-01-01.md"),
            "这是一些完全不相关的笔记\n\n另一段内容",
        )
        self.assertTrue(mm.search("python").startswith(NO_HIT_PREFIX))

    def test_24_non_md_files_are_ignored(self):
        """Only *.md files participate in search."""
        mm = _make_manager(self.tmpdir)
        _write(os.path.join(self.tmpdir, "notes.txt"), "python 是好语言")
        _write(os.path.join(self.tmpdir, "2024-01-01.md"), "无相关内容")
        self.assertTrue(mm.search("python").startswith(NO_HIT_PREFIX))


# ── 4. search() basic hit format & substring behavior ───────────────────────


class TestSearchHitFormat(unittest.TestCase):
    """Single-hit output format, case-insensitivity, substring matching,
    and content truncation to 2000 chars.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_30_single_hit_format(self):
        mm = _make_manager(self.tmpdir)
        _write(
            os.path.join(self.tmpdir, "2024-01-01.md"),
            "我们用 python 写了一个工具",
        )
        results = _parse_results(mm.search("python"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        file, score, content = results[0]
        self.assertEqual(file, "2024-01-01.md")
        # 1×10 (count) + 0 (len<200) + 30 (mtime=now) = 40
        self.assertEqual(score, 40)
        self.assertIn("python", content)

    def test_31_case_insensitive(self):
        mm = _make_manager(self.tmpdir)
        _write(os.path.join(self.tmpdir, "2024-01-01.md"), "Python is GREAT")
        r1 = _parse_results(mm.search("python"))
        r2 = _parse_results(mm.search("PYTHON"))
        self.assertIsInstance(r1, list)
        self.assertIsInstance(r2, list)
        self.assertEqual(len(r1), 1)
        self.assertEqual(len(r2), 1)
        self.assertEqual(r1[0][1], r2[0][1])

    def test_32_substring_match(self):
        """`search` uses substring `in`/`count`, not word-boundary matching."""
        mm = _make_manager(self.tmpdir)
        _write(os.path.join(self.tmpdir, "2024-01-01.md"), "category catalog")
        results = _parse_results(mm.search("cat"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        # "cat" appears 2 times → 20 points.
        _, score, _ = results[0]
        self.assertGreaterEqual(score, 20)

    def test_33_content_truncated_to_2000(self):
        mm = _make_manager(self.tmpdir)
        long_chunk = "python " + ("x" * 3000)
        _write(os.path.join(self.tmpdir, "2024-01-01.md"), long_chunk)
        results = _parse_results(mm.search("python"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        _, _, content = results[0]
        # Content is chunk[:2000].
        self.assertEqual(len(content), 2000)


# ── 5. search() scoring: keyword frequency ─────────────────────────────────


class TestSearchKeywordFrequency(unittest.TestCase):
    """Higher keyword frequency → higher score (everything else equal)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_40_keyword_frequency_score(self):
        mm = _make_manager(self.tmpdir)
        _write(
            os.path.join(self.tmpdir, "2024-01-01.md"),
            "apple apple apple\n\nbanana",
        )
        results = _parse_results(mm.search("apple"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        _, score, _ = results[0]
        # 3 × 10 + 0 (len<200) + 30 (mtime=now) = 60
        self.assertEqual(score, 60)

    def test_41_keyword_frequency_higher_score(self):
        mm = _make_manager(self.tmpdir)
        _write(
            os.path.join(self.tmpdir, "2024-01-01.md"),
            "python\n\npython python\n\npython python python",
        )
        results = _parse_results(mm.search("python"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 3)
        scores = [r[1] for r in results]
        # Strictly decreasing by score.
        self.assertTrue(scores[0] > scores[1] > scores[2])
        # 1×10+0+30=40, 2×10+0+30=50, 3×10+0+30=60.
        self.assertEqual(sorted(scores), [40, 50, 60])


# ── 6. search() scoring: multi-keyword additivity ───────────────────────────


class TestSearchMultiKeyword(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_50_multi_keyword_additive(self):
        mm = _make_manager(self.tmpdir)
        _write(
            os.path.join(self.tmpdir, "2024-01-01.md"),
            "python and java are popular",
        )
        results = _parse_results(mm.search("python java"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        _, score, _ = results[0]
        # 1×10 (python) + 1×10 (java) + 0 (len<200) + 30 (mtime=now) = 50
        self.assertEqual(score, 50)

    def test_51_multi_keyword_partial_match(self):
        """A chunk containing only some keywords still matches (no skip)."""
        mm = _make_manager(self.tmpdir)
        _write(os.path.join(self.tmpdir, "2024-01-01.md"), "we love python")
        results = _parse_results(mm.search("python rust"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        # Only "python" matches → 1×10 + 0 + 30 = 40.
        self.assertEqual(results[0][1], 40)


# ── 7. search() scoring: length bonus (0..5) ───────────────────────────────


class TestSearchLengthBonus(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_60_length_bonus_capped_at_5(self):
        """Three chunks of len 56 / 506 / 2000 → length bonus 0 / 2 / 5."""
        mm = _make_manager(self.tmpdir)
        bodies = [
            "python" + "x" * 50,        # len=56   → length_bonus=0
            "python" + "x" * 500,       # len=506  → length_bonus=2
            "python" + "x" * 2000,      # len=2006 → trunc to 2000 → length_bonus=5
        ]
        text = "\n\n".join(bodies)
        _write(os.path.join(self.tmpdir, "2024-01-01.md"), text)
        results = _parse_results(mm.search("python"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 3)
        scores_by_len = {len(r[2]): r[1] for r in results}
        # mtime 0 days → +30; count=1×10; length_bonus 0/2/5 → totals 40/42/45.
        expected = {56: 40, 506: 42, 2000: 45}
        for trunc_len, exp_score in expected.items():
            self.assertIn(trunc_len, scores_by_len)
            self.assertEqual(
                scores_by_len[trunc_len], exp_score,
                f"content_len={trunc_len} expected {exp_score}, "
                f"got {scores_by_len[trunc_len]}",
            )

    def test_61_length_bonus_just_under_boundary(self):
        """Length 200/400/600/800/1000/2000 → bonus 1/2/3/4/5/5."""
        mm = _make_manager(self.tmpdir)
        chunks = {n: "python" + "x" * (n * 200 - 6) for n in (1, 2, 3, 4, 5, 10)}
        for n, body in chunks.items():
            self.assertEqual(len(body), n * 200)
        text = "\n\n".join(chunks.values())
        _write(os.path.join(self.tmpdir, "2024-01-01.md"), text)
        results = _parse_results(mm.search("python"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), len(chunks))
        scores_by_len = {len(r[2]): r[1] for r in results}
        expected = {200: 41, 400: 42, 600: 43, 800: 44, 1000: 45, 2000: 45}
        for length, exp_score in expected.items():
            self.assertIn(length, scores_by_len)
            self.assertEqual(scores_by_len[length], exp_score)


# ── 8. search() scoring: mtime bonus (0..30, decays linearly) ───────────────


class TestSearchMtimeBonus(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_70_mtime_bonus_fresh_file(self):
        mm = _make_manager(self.tmpdir)
        _write(os.path.join(self.tmpdir, "2024-01-01.md"), "python rocks")
        results = _parse_results(mm.search("python"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        # 1×10 + 0 (len<200) + 30 (mtime=now) = 40
        self.assertEqual(results[0][1], 40)

    def test_71_mtime_bonus_decays_to_zero_at_30_days(self):
        mm = _make_manager(self.tmpdir)
        path = os.path.join(self.tmpdir, "2024-01-01.md")
        _write(path, "python rocks")
        # Set mtime to 30 days ago (rounded).
        mtime_30d_ago = time.time() - 30 * 86400
        os.utime(path, (mtime_30d_ago, mtime_30d_ago))
        results = _parse_results(mm.search("python"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        # 30 days → mtime_bonus = max(0, 30-30) = 0 → score 10.
        self.assertEqual(results[0][1], 10)

    def test_72_mtime_bonus_beyond_30_days_clamps_to_zero(self):
        mm = _make_manager(self.tmpdir)
        path = os.path.join(self.tmpdir, "2024-01-01.md")
        _write(path, "python rocks")
        mtime_old = time.time() - 365 * 86400
        os.utime(path, (mtime_old, mtime_old))
        results = _parse_results(mm.search("python"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        # 365 days → mtime_bonus = max(0, 30-365) = 0 → score 10.
        self.assertEqual(results[0][1], 10)

    def test_73_mtime_bonus_newer_file_ranks_higher(self):
        """Newer mtime wins when keyword frequency is equal."""
        mm = _make_manager(self.tmpdir)
        new_path = os.path.join(self.tmpdir, "2024-02-01.md")  # newer
        old_path = os.path.join(self.tmpdir, "2024-01-01.md")
        _write(new_path, "python")
        _write(old_path, "python")
        # Old file's mtime is 10 days ago.
        os.utime(old_path, (time.time() - 10 * 86400,) * 2)
        results = _parse_results(mm.search("python"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 2)
        # New file bonus=30, old file bonus=20 → newer file should rank first.
        self.assertEqual(results[0][0], "2024-02-01.md")
        self.assertEqual(results[1][0], "2024-01-01.md")
        self.assertEqual(results[0][1] - results[1][1], 10)


# ── 9. search() combined ranking ───────────────────────────────────────────


class TestSearchCombinedRanking(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_80_higher_keyword_count_ranks_above_higher_mtime(self):
        """Higher keyword frequency (×10) should outweigh mtime bonus (<=30)."""
        mm = _make_manager(self.tmpdir)
        # File A: mtime=now, 1×python → 10 + 0 + 30 = 40
        path_a = os.path.join(self.tmpdir, "2024-01-01.md")
        _write(path_a, "python")
        # File B: mtime=10 days ago, 4×python → 40 + 0 + 20 = 60
        path_b = os.path.join(self.tmpdir, "2024-02-01.md")
        _write(path_b, "python python python python")
        os.utime(path_b, (time.time() - 10 * 86400,) * 2)
        results = _parse_results(mm.search("python"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 2)
        # B (60) > A (40) → B ranks first.
        self.assertEqual(results[0][0], "2024-02-01.md")
        self.assertEqual(results[1][0], "2024-01-01.md")
        self.assertEqual(results[0][1], 60)
        self.assertEqual(results[1][1], 40)


# ── 10. search() top_k truncation ──────────────────────────────────────────


class TestSearchTopK(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_90_top_k_limits_results(self):
        mm = _make_manager(self.tmpdir)
        text = "python a\n\npython b\n\npython c"
        _write(os.path.join(self.tmpdir, "2024-01-01.md"), text)
        # top_k=2 returns only the first 2.
        results = _parse_results(mm.search("python", top_k=2))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 2)
        # Default returns all 3.
        results_all = _parse_results(mm.search("python", top_k=10))
        self.assertEqual(len(results_all), 3)

    def test_91_top_k_one_returns_single_best(self):
        mm = _make_manager(self.tmpdir)
        _write(
            os.path.join(self.tmpdir, "2024-01-01.md"),
            "python\n\npython python\n\npython python python",
        )
        results = _parse_results(mm.search("python", top_k=1))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        # The highest-frequency (3×) chunk must be the winner.
        self.assertEqual(results[0][2].count("python"), 3)
        self.assertEqual(results[0][1], 60)


# ── 11. search() multi-file & chunk-split behavior ─────────────────────────


class TestSearchMultiFile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_100_multiple_files_aggregated(self):
        mm = _make_manager(self.tmpdir)
        _write(os.path.join(self.tmpdir, "2024-01-01.md"), "python first")
        _write(os.path.join(self.tmpdir, "2024-02-01.md"), "python second")
        results = _parse_results(mm.search("python"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][1], 40)
        self.assertEqual(results[1][1], 40)

    def test_101_chunks_split_on_blank_line_only(self):
        """Only the chunk that contains the keyword should appear in results."""
        mm = _make_manager(self.tmpdir)
        _write(
            os.path.join(self.tmpdir, "2024-01-01.md"),
            "line1\nline2\nline3\n\nanother chunk",
        )
        results = _parse_results(mm.search("line2"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        # Whole chunk1 returned as content.
        self.assertIn("line1", results[0][2])
        self.assertIn("line2", results[0][2])
        self.assertIn("line3", results[0][2])
        self.assertNotIn("another", results[0][2])

    def test_101b_two_chunks_both_match_independently(self):
        """Two matching chunks are returned as independent results."""
        mm = _make_manager(self.tmpdir)
        _write(
            os.path.join(self.tmpdir, "2024-01-01.md"),
            "python in chunk1\n\npython in chunk2",
        )
        results = _parse_results(mm.search("python"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 2)
        contents = {r[2] for r in results}
        self.assertIn("python in chunk1", contents)
        self.assertIn("python in chunk2", contents)

    def test_102_results_separator_is_dashes(self):
        """Multi-record separator is '\\n\\n---\\n\\n'."""
        mm = _make_manager(self.tmpdir)
        _write(
            os.path.join(self.tmpdir, "2024-01-01.md"),
            "python a\n\npython b",
        )
        out = mm.search("python")
        self.assertIn("\n\n---\n\n", out)


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)