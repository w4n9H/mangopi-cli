#!/usr/bin/env python3
"""Test MemoryManager —— 重点覆盖 search() 的评分公式与排序：

  score = Σ(关键词出现次数 × 10)
        + min(len(chunk) // 200, 5)              # 长度 bonus (0..5)
        + max(0, 30 - int(Δdays))                # mtime bonus (0..30, 30天内线性衰减)

同时覆盖 _tokenize / _split_chunks 静态方法与 search 边界 (空 query / 无文件 /
无命中 / top_k / 大小写 / 子串匹配 / content 截断到 2000 字符)。
"""

import os
import re
import sys
import tempfile
import time

# 将项目根目录加到 sys.path，以便 import mangopi_cli 中的 MemoryManager
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangopi_cli import MemoryManager

# ── 计数器与辅助函数 ─────────────────────────────────────────

passed = 0
failed = 0
skipped = 0


def _run(name, fn):
    """运行一个零参测试函数，捕获断言与异常。"""
    global passed, failed
    try:
        fn()
        passed += 1
        print(f"  ✓ {name}")
    except AssertionError as e:
        failed += 1
        print(f"  ✗ {name}  FAIL: {e}")
    except Exception as e:
        failed += 1
        print(f"  ✗ {name}  ERROR: {type(e).__name__}: {e}")


def _make_manager(tmpdir):
    """构造一个指向临时目录的 MemoryManager，隔离 .mangocli/memory。"""
    mm = MemoryManager()
    mm.memory_dir = tmpdir
    return mm


def _write(path, text, mtime=None):
    """写文件并可选地设置 mtime (epoch seconds)。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _parse_results(out):
    """把 search() 返回的字符串解析为 [(filename, score_int, content), ...]。

    每条记录的格式: "# {file} (score={score})\\n{content}"
    多条记录之间用 "\\n\\n---\\n\\n" 分隔。
    """
    assert isinstance(out, str), f"expected str, got {type(out)}"
    if out in ("empty query", "No memory found."):
        return out
    records = out.split("\n\n---\n\n")
    parsed = []
    pat = re.compile(r"^# (?P<file>[^ ]+) \(score=(?P<score>-?\d+)\)\n(?P<content>.*)$", re.DOTALL)
    for rec in records:
        m = pat.match(rec)
        assert m, f"record does not match expected format: {rec!r}"
        parsed.append((m.group("file"), int(m.group("score")), m.group("content")))
    return parsed


# ── 1. _tokenize 静态方法 ───────────────────────────────────

def test_01_tokenize_basic():
    assert MemoryManager._tokenize("Hello World") == ["hello", "world"]


def test_02_tokenize_lowercase_and_strip():
    assert MemoryManager._tokenize("  Foo   BAR  ") == ["foo", "bar"]


def test_03_tokenize_empty_and_whitespace():
    assert MemoryManager._tokenize("") == []
    assert MemoryManager._tokenize("   \t  ") == []


def test_04_tokenize_keeps_internal_punct():
    """_tokenize 仅按空白切分 + 小写化，不剔除标点 (与 search 的子串匹配一致)。"""
    assert MemoryManager._tokenize("foo,bar.baz") == ["foo,bar.baz"]


# ── 2. _split_chunks 静态方法 ──────────────────────────────

def test_10_split_chunks_on_blank_line():
    text = "alpha\n\nbeta\n\ngamma"
    assert MemoryManager._split_chunks(text) == ["alpha", "beta", "gamma"]


def test_11_split_chunks_skips_empty():
    text = "\n\nfoo\n\n   \n\nbar\n\n"
    assert MemoryManager._split_chunks(text) == ["foo", "bar"]


def test_12_split_chunks_preserves_newlines_inside_block():
    text = "line1\nline2\nline3\n\nline4"
    assert MemoryManager._split_chunks(text) == ["line1\nline2\nline3", "line4"]


# ── 3. search —— 边界 / 短路 ───────────────────────────────

def test_20_empty_query_returns_empty_query():
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        assert mm.search("") == "empty query"


def test_21_whitespace_only_query_returns_empty_query():
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        assert mm.search("   \t  ") == "empty query"


def test_22_no_memory_dir_returns_no_match():
    """内存目录存在但无 .md 文件时，应返回 'No memory found.'。"""
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        # 放一个非 .md 文件，确保过滤生效
        with open(os.path.join(tmp, "ignore.txt"), "w") as f:
            f.write("apple banana")
        assert mm.search("apple") == "No memory found."


def test_23_no_matching_chunks_returns_no_match():
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        _write(os.path.join(tmp, "2024-01-01.md"),
               "这是一些完全不相关的笔记\n\n另一段内容")
        assert mm.search("python") == "No memory found."


def test_24_non_md_files_are_ignored():
    """只有 *.md 文件参与搜索。"""
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        _write(os.path.join(tmp, "notes.txt"), "python 是好语言")
        _write(os.path.join(tmp, "2024-01-01.md"), "无相关内容")
        assert mm.search("python") == "No memory found."


# ── 4. search —— 基础命中与输出格式 ────────────────────────

def test_30_single_hit_format():
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        # chunk 较短 (<200 字符) → length_bonus=0
        _write(os.path.join(tmp, "2024-01-01.md"), "我们用 python 写了一个工具")
        out = mm.search("python")
        results = _parse_results(out)
        assert isinstance(results, list)
        assert len(results) == 1
        file, score, content = results[0]
        assert file == "2024-01-01.md"
        # 1*10 (count) + 0 (len<200) + 30 (mtime 0 天) = 40
        assert score == 40, f"expected 40, got {score}"
        assert "python" in content


def test_31_case_insensitive():
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        _write(os.path.join(tmp, "2024-01-01.md"), "Python is GREAT")
        # 大写关键词也能命中 (子串匹配，大小写不敏感)
        out = mm.search("python")
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 1
        out2 = mm.search("PYTHON")
        results2 = _parse_results(out2)
        assert isinstance(results2, list) and len(results2) == 1
        assert results[0][1] == results2[0][1], "大小写不同得分应一致"


def test_32_substring_match():
    """search 用的是子串 in/count, 不是词边界匹配。"""
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        _write(os.path.join(tmp, "2024-01-01.md"), "category catalog")
        out = mm.search("cat")
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 1
        # "cat" 出现 2 次 → 20 分
        file, score, _ = results[0]
        assert score >= 20, f"expected score>=20 (2次*10), got {score}"


def test_33_content_truncated_to_2000():
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        long_chunk = "python " + ("x" * 3000)  # 远超 2000 字符
        _write(os.path.join(tmp, "2024-01-01.md"), long_chunk)
        out = mm.search("python")
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 1
        file, score, content = results[0]
        # content 是 chunk[:2000]，加上 'python ' + 'x'*1993 = 2000
        assert len(content) == 2000, f"expected content length 2000, got {len(content)}"


# ── 5. search —— 评分核心：关键词频次 ───────────────────────

def test_40_keyword_frequency_score():
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        # chunk 长度 < 200 → length_bonus=0; mtime≈now → mtime_bonus=30
        _write(os.path.join(tmp, "2024-01-01.md"),
               "apple apple apple\n\nbanana")  # 第一段 3 个 apple, 第二段无 apple
        out = mm.search("apple")
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 1
        file, score, _ = results[0]
        # 3 次出现 × 10 + 0 (len 17 < 200) + 30 (mtime 0 天) = 60
        assert score == 60, f"expected 60, got {score}"


def test_41_keyword_frequency_higher_score():
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        _write(os.path.join(tmp, "2024-01-01.md"),
               "python\n\npython python\n\npython python python")
        out = mm.search("python")
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 3
        scores = [r[1] for r in results]
        # 频次越高 score 越大 (length_bonus 和 mtime_bonus 三段相同, 都被 len<200, mtime≈now)
        assert scores[0] > scores[1] > scores[2], (
            f"scores should be strictly decreasing, got {scores}")
        # 验证 1/2/3 次对应的精确分数: 1*10 + 0 + 30 = 40, 2*10+0+30=50, 3*10+0+30=60
        assert sorted(scores) == [40, 50, 60], f"expected [40, 50, 60], got {sorted(scores)}"


# ── 6. search —— 评分核心：多关键词累加 ─────────────────────

def test_50_multi_keyword_additive():
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        _write(os.path.join(tmp, "2024-01-01.md"),
               "python and java are popular")
        out = mm.search("python java")
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 1
        file, score, _ = results[0]
        # python 1 次 + java 1 次 → 20; + length_bonus(0) + mtime_bonus(30) = 50
        assert score == 50, f"expected 50, got {score}"


def test_51_multi_keyword_partial_match():
    """chunk 包含 keywords 子集时, 缺失的关键词不影响分数, 不导致 skip。"""
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        _write(os.path.join(tmp, "2024-01-01.md"), "we love python")
        out = mm.search("python rust")  # 第二个 keyword 缺失
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 1
        # 仅 python 命中 → 1*10 + 0 + 30 = 40
        assert results[0][1] == 40, f"expected 40, got {results[0][1]}"


# ── 7. search —— 评分核心：长度 bonus ──────────────────────

def test_60_length_bonus_capped_at_5():
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        # 三个不同长度的 chunk, 都含 1 次 python, mtime 同为现在
        # content 会被截断到 2000 字符, 用截断后的实际长度作 key
        bodies = [
            "python" + "x" * 50,       # 原 len=56   → 截断后 56   → length_bonus=0
            "python" + "x" * 500,      # 原 len=506  → 截断后 506  → length_bonus=2
            "python" + "x" * 2000,     # 原 len=2006 → 截断后 2000 → length_bonus=5 (cap)
        ]
        text = "\n\n".join(bodies)
        _write(os.path.join(tmp, "2024-01-01.md"), text)
        out = mm.search("python")
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 3
        scores_by_len = {len(r[2]): r[1] for r in results}
        # mtime 0 天 → +30; count*10=10; length_bonus=0/2/5 → 总分 40/42/45
        expected = {56: 40, 506: 42, 2000: 45}
        for trunc_len, exp_score in expected.items():
            assert trunc_len in scores_by_len, (
                f"missing result with content_len={trunc_len}, got {sorted(scores_by_len)}")
            assert scores_by_len[trunc_len] == exp_score, (
                f"content_len={trunc_len} expected score {exp_score}, "
                f"got {scores_by_len[trunc_len]}")


def test_61_length_bonus_just_under_boundary():
    """长度 = 200, 400, 600, 800, 1000, 2000 时 length_bonus=1, 2, 3, 4, 5, 5。"""
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        chunks = {n: "python" + "x" * (n * 200 - 6) for n in (1, 2, 3, 4, 5, 10)}
        for n, body in chunks.items():
            assert len(body) == n * 200
        text = "\n\n".join(chunks.values())
        _write(os.path.join(tmp, "2024-01-01.md"), text)
        out = mm.search("python")
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == len(chunks)
        scores_by_len = {len(r[2]): r[1] for r in results}
        # 1*10 (count) + (n//200) (length_bonus) + 30 (mtime 0 天)
        # n=1 → 41, n=2 → 42, n=3 → 43, n=4 → 44, n=5/10 → 45 (cap at 5)
        expected = {200: 41, 400: 42, 600: 43, 800: 44, 1000: 45, 2000: 45}
        for length, exp_score in expected.items():
            assert length in scores_by_len, (
                f"missing chunk with content_len={length}, got {sorted(scores_by_len)}")
            assert scores_by_len[length] == exp_score, (
                f"content_len={length} expected score {exp_score}, "
                f"got {scores_by_len[length]}")


# ── 8. search —— 评分核心：mtime bonus ─────────────────────

def test_70_mtime_bonus_fresh_file():
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        _write(os.path.join(tmp, "2024-01-01.md"), "python rocks")
        out = mm.search("python")
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 1
        # 刚写入 → Δdays = 0 → mtime_bonus = 30
        # 1*10 + 0 (len<200) + 30 = 40
        assert results[0][1] == 40, f"expected 40, got {results[0][1]}"


def test_71_mtime_bonus_decays_to_zero_at_30_days():
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        path = os.path.join(tmp, "2024-01-01.md")
        _write(path, "python rocks")
        # 把 mtime 设为 30 天前 (取整)
        mtime_30d_ago = time.time() - 30 * 86400
        os.utime(path, (mtime_30d_ago, mtime_30d_ago))
        out = mm.search("python")
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 1
        # 30 天 → mtime_bonus = max(0, 30-30) = 0
        # 1*10 + 0 + 0 = 10
        assert results[0][1] == 10, f"expected 10, got {results[0][1]}"


def test_72_mtime_bonus_beyond_30_days_clamps_to_zero():
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        path = os.path.join(tmp, "2024-01-01.md")
        _write(path, "python rocks")
        # 设为 365 天前
        mtime_old = time.time() - 365 * 86400
        os.utime(path, (mtime_old, mtime_old))
        out = mm.search("python")
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 1
        # 365 天 → mtime_bonus = max(0, 30-365) = 0
        assert results[0][1] == 10, f"expected 10, got {results[0][1]}"


def test_73_mtime_bonus_newer_file_ranks_higher():
    """mtime 较新的文件在相同关键词频次下得分更高。"""
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        new_path = os.path.join(tmp, "2024-02-01.md")  # 更新
        old_path = os.path.join(tmp, "2024-01-01.md")
        _write(new_path, "python")
        _write(old_path, "python")
        # 旧文件 mtime 设为 10 天前
        os.utime(old_path, (time.time() - 10 * 86400,) * 2)
        out = mm.search("python")
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 2
        # 新文件 mtime_bonus=30, 旧文件 mtime_bonus=20
        # 排序: 新文件 (40) 在前
        assert results[0][0] == "2024-02-01.md", f"newest file should rank first, got {results[0]}"
        assert results[1][0] == "2024-01-01.md"
        assert results[0][1] - results[1][1] == 10, (
            f"score diff should equal mtime bonus diff (10), got {results[0][1] - results[1][1]}")


# ── 9. search —— 综合排序 ─────────────────────────────────

def test_80_higher_keyword_count_ranks_above_higher_mtime():
    """词频对总分的贡献 (×10) 应能压过 mtime 差异 (<=30)。"""
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        # 文件 A: 新 (mtime=now), 1 次 python → 10 + 0 + 30 = 40
        path_a = os.path.join(tmp, "2024-01-01.md")
        _write(path_a, "python")
        # 文件 B: 旧 10 天 (mtime_bonus=20), 4 次 python → 40 + 0 + 20 = 60
        path_b = os.path.join(tmp, "2024-02-01.md")
        _write(path_b, "python python python python")
        os.utime(path_b, (time.time() - 10 * 86400,) * 2)
        out = mm.search("python")
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 2
        # B (60) > A (40) → B 在前
        assert results[0][0] == "2024-02-01.md"
        assert results[1][0] == "2024-01-01.md"
        assert results[0][1] == 60
        assert results[1][1] == 40


# ── 10. search —— top_k 截断 ─────────────────────────────

def test_90_top_k_limits_results():
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        # 3 个 chunk 都命中, top_k=2 只返回前 2
        text = "python a\n\npython b\n\npython c"
        _write(os.path.join(tmp, "2024-01-01.md"), text)
        out = mm.search("python", top_k=2)
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 2
        # 默认情况下, 3 个 chunk 全返回
        out_all = mm.search("python", top_k=10)
        results_all = _parse_results(out_all)
        assert len(results_all) == 3


def test_91_top_k_one_returns_single_best():
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        _write(os.path.join(tmp, "2024-01-01.md"),
               "python\n\npython python\n\npython python python")
        out = mm.search("python", top_k=1)
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 1
        # 频次最高 (3次) 的 chunk 应胜出
        assert results[0][2].count("python") == 3
        assert results[0][1] == 60


# ── 11. search —— 多文件 / 跨 chunk 行为 ─────────────────

def test_100_multiple_files_aggregated():
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        _write(os.path.join(tmp, "2024-01-01.md"), "python first")
        _write(os.path.join(tmp, "2024-02-01.md"), "python second")
        out = mm.search("python")
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 2
        # mtime 同为 now, 频次相同 → 分数相同
        assert results[0][1] == results[1][1] == 40


def test_101_chunks_split_on_blank_line_only():
    """_split_chunks 用 \\n\\s*\\n 切, 单换行不切分; 只有真正匹配的 chunk 才会出现在结果中。"""
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        # 切分后应得 2 个 chunk:
        #   chunk1 = "line1\nline2\nline3" (含 line2)
        #   chunk2 = "another chunk"      (不含 line2, 应被过滤)
        _write(os.path.join(tmp, "2024-01-01.md"),
               "line1\nline2\nline3\n\nanother chunk")
        out = mm.search("line2")
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 1, (
            f"只有 chunk1 命中, 应只返回 1 条; got {len(results)}")
        # chunk1 整体作为 content 返回, 其中含 line1/line2/line3
        assert "line1" in results[0][2]
        assert "line2" in results[0][2]
        assert "line3" in results[0][2]
        # chunk2 不应出现
        assert "another" not in results[0][2]


def test_101b_two_chunks_both_match_independently():
    """两个 chunk 各自命中时, 都会被独立计分并返回。"""
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        _write(os.path.join(tmp, "2024-01-01.md"),
               "python in chunk1\n\npython in chunk2")
        out = mm.search("python")
        results = _parse_results(out)
        assert isinstance(results, list) and len(results) == 2
        contents = {r[2] for r in results}
        assert "python in chunk1" in contents
        assert "python in chunk2" in contents


def test_102_results_separator_is_dashes():
    """多条记录之间用 '\\n\\n---\\n\\n' 分隔。"""
    with tempfile.TemporaryDirectory() as tmp:
        mm = _make_manager(tmp)
        _write(os.path.join(tmp, "2024-01-01.md"),
               "python a\n\npython b")
        out = mm.search("python")
        assert "\n\n---\n\n" in out, f"expected '---' separator in output: {out!r}"


# ── 入口 ───────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== MemoryManager 单元测试 ===\n")
    for name, fn in sorted(globals().items()):
        if not (name.startswith("test_") and callable(fn)):
            continue
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {name}  FAIL: {e}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {name}  ERROR: {type(e).__name__}: {e}")
        else:
            passed += 1
            print(f"  ✓ {name}")

    print(f"\n{'='*40}")
    print(f"通过: {passed}  失败: {failed}  总计: {passed + failed}")
    if failed:
        sys.exit(1)
