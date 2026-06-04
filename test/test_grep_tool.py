#!/usr/bin/env python3
"""Test GrepTool —— 覆盖 grep 工具的正则搜索行为:

  - schema/metadata 正确性
  - 无效正则返回 fail
  - 命中格式: "filepath:line_num:content" (line 1-based, content rstrip)
  - 递归子目录命中
  - 目录 / 二进制 / 不存在文件被静默跳过
  - 无命中时返回 ok("none")
  - 命中上限 500
  - 默认 path="."
  - 正则语义 (锚点、字符类、量词、贪婪/非贪婪、分组)
"""

import os
import re
import sys
import tempfile

# 将项目根目录加到 sys.path，以便 import mangopi_cli 中的 GrepTool
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangopi_cli import GrepTool

# ── 计数器与辅助函数 ─────────────────────────────────────────

passed = 0
failed = 0


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


def _tool():
    return GrepTool()


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _parse_hits(content):
    """把 GrepTool 输出解析为 [(filepath, line_num, text), ...]。

    行格式: "{filepath}:{line_num}:{line_content}"
    """
    if content == "none":
        return []
    out = []
    for line in content.split("\n"):
        if not line:
            continue
        # 从右侧切 ":line_num:" → 末次切分
        m = re.match(r"^(?P<path>.+?):(?P<num>\d+):(?P<text>.*)$", line)
        assert m, f"hit line does not match format: {line!r}"
        out.append((m.group("path"), int(m.group("num")), m.group("text")))
    return out


# ── 1. 元数据 / schema ──────────────────────────────────────

def test_01_name_is_grep():
    assert _tool().name == "grep"


def test_02_params_keys():
    params = _tool().params
    assert "pat" in params and "path" in params
    # pat 必填, path 可选
    assert not params["pat"]["type"].endswith("?")
    assert params["path"]["type"].endswith("?")


def test_03_schema_required_only_pat():
    sch = _tool().schema()
    assert sch["type"] == "function"
    assert sch["function"]["name"] == "grep"
    required = sch["function"]["parameters"]["required"]
    assert required == ["pat"], f"expected required=['pat'], got {required}"
    props = sch["function"]["parameters"]["properties"]
    assert set(props.keys()) == {"pat", "path"}
    assert props["pat"]["type"] == "string"
    assert props["path"]["type"] == "string"


# ── 2. 无效正则 → fail ──────────────────────────────────────

def test_10_unbalanced_paren_is_fail():
    with tempfile.TemporaryDirectory() as tmp:
        r = _tool().run({"pat": "(unclosed", "path": tmp})
        assert r["success"] is False
        assert "invalid regex" in r["content"]


def test_11_trailing_backslash_is_fail():
    with tempfile.TemporaryDirectory() as tmp:
        # 末尾的 \ 是 Python regex 中的 invalid escape (需要一个可转义字符)
        r = _tool().run({"pat": "abc\\", "path": tmp})
        assert r["success"] is False
        assert "invalid regex" in r["content"]


def test_12_invalid_quantifier_is_fail():
    with tempfile.TemporaryDirectory() as tmp:
        r = _tool().run({"pat": "*invalid", "path": tmp})
        assert r["success"] is False
        assert "invalid regex" in r["content"]


# ── 3. 命中格式 & 基础行为 ─────────────────────────────────

def test_20_single_hit_format():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "a.txt"), "hello world\nsecond line\n")
        r = _tool().run({"pat": "hello", "path": tmp})
        assert r["success"] is True
        hits = _parse_hits(r["content"])
        assert len(hits) == 1
        path, num, text = hits[0]
        assert num == 1, f"line number should be 1-based, got {num}"
        assert text == "hello world", f"expected stripped line, got {text!r}"
        assert path.endswith("a.txt"), f"path should end with a.txt, got {path!r}"


def test_21_multiple_lines_in_one_file():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "a.txt"),
               "alpha\nbeta alpha\n\ngamma\nALPHA\n")
        r = _tool().run({"pat": "alpha", "path": tmp})
        assert r["success"] is True
        hits = _parse_hits(r["content"])
        # 第 1 行 alpha, 第 2 行 beta alpha, ALPHA 大小写不同 → 不命中
        nums = [h[1] for h in hits]
        assert nums == [1, 2], f"expected line numbers [1, 2], got {nums}"


def test_22_no_match_returns_none_string():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "a.txt"), "no match here\n")
        r = _tool().run({"pat": "zzz", "path": tmp})
        assert r["success"] is True
        assert r["content"] == "none"


def test_23_empty_directory_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        r = _tool().run({"pat": "anything", "path": tmp})
        assert r["success"] is True
        assert r["content"] == "none"


def test_24_line_is_rstripped():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "a.txt"), "matched   \n")
        r = _tool().run({"pat": "matched", "path": tmp})
        hits = _parse_hits(r["content"])
        assert len(hits) == 1
        # 尾部空白应被 rstrip 去掉
        assert hits[0][2] == "matched", f"expected rstripped line, got {hits[0][2]!r}"


def test_25_case_sensitive_by_default():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "a.txt"), "Foo foo FOO\n")
        r = _tool().run({"pat": "foo", "path": tmp})
        hits = _parse_hits(r["content"])
        # 第二个 foo 命中 (1-based line 1)
        assert len(hits) == 1
        assert hits[0][2] == "Foo foo FOO"


# ── 4. 正则语义 ────────────────────────────────────────────

def test_30_anchors():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "a.txt"), "abc\nxabc\nabcx\n")
        r = _tool().run({"pat": "^abc$", "path": tmp})
        hits = _parse_hits(r["content"])
        nums = [h[1] for h in hits]
        assert nums == [1], f"^abc$ should match only line 1, got {nums}"


def test_31_character_class():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "a.txt"), "a1\nb2\nc3\n")
        r = _tool().run({"pat": "[ac]\\d", "path": tmp})
        hits = _parse_hits(r["content"])
        nums = [h[1] for h in hits]
        assert nums == [1, 3], f"expected [1, 3], got {nums}"


def test_32_quantifier():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "a.txt"), "ab\nabc\nabcd\n")
        # abc?d? = "ab" + optional "c" + optional "d"
        # → 三种长度都应该被命中
        r = _tool().run({"pat": "abc?d?", "path": tmp})
        hits = _parse_hits(r["content"])
        nums = [h[1] for h in hits]
        assert nums == [1, 2, 3], f"expected [1, 2, 3], got {nums}"


def test_33_greedy_vs_lazy_filter_behavior():
    """GrepTool 用 re.search() 判断"行是否被选中", 输出为整行 rstrip, 不是匹配片段。

    因此贪婪 / 非贪婪在输出文本上不可见, 但它们仍会影响哪些行被命中。
    此处验证: 同样的行, 用 <a> 子串 pattern 能命中, 用 <b> 子串 pattern 也能命中
    (两段 <...> 都是完整 token, 不需要测试匹配长度)。
    """
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "a.txt"), "<a><b>\n")
        r_a = _tool().run({"pat": "<a>", "path": tmp})
        r_b = _tool().run({"pat": "<b>", "path": tmp})
        hits_a = _parse_hits(r_a["content"])
        hits_b = _parse_hits(r_b["content"])
        # 两个 pattern 都能在同 1 行命中, 输出的 text 都是整行
        assert len(hits_a) == 1
        assert len(hits_b) == 1
        assert hits_a[0][2] == "<a><b>", f"expected full line, got {hits_a[0][2]!r}"
        assert hits_b[0][2] == "<a><b>", f"expected full line, got {hits_b[0][2]!r}"

    # 显式验证 regex 决定了行是否被选中: 锚点区分
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "a.txt"), "abc\nxyz\n")
        r_anchor = _tool().run({"pat": "^abc$", "path": tmp})
        hits_anchor = _parse_hits(r_anchor["content"])
        # ^abc$ 只在第 1 行命中
        assert len(hits_anchor) == 1
        assert hits_anchor[0][1] == 1


def test_34_group_and_alternation():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "a.txt"), "cat\ndog\ncow\n")
        r = _tool().run({"pat": "(cat|dog)", "path": tmp})
        hits = _parse_hits(r["content"])
        nums = [h[1] for h in hits]
        assert nums == [1, 2], f"expected [1, 2], got {nums}"


# ── 5. 递归搜索 ────────────────────────────────────────────

def test_40_matches_in_subdirectory():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "sub", "deep", "a.txt"), "needle\n")
        r = _tool().run({"pat": "needle", "path": tmp})
        hits = _parse_hits(r["content"])
        assert len(hits) == 1
        path = hits[0][0]
        # 路径应包含子目录
        assert "sub" in path and "a.txt" in path, f"path should contain subdir, got {path!r}"


def test_41_matches_in_deeply_nested():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "a", "b", "c", "d", "e", "leaf.txt"), "deep\n")
        r = _tool().run({"pat": "deep", "path": tmp})
        hits = _parse_hits(r["content"])
        assert len(hits) == 1
        assert "leaf.txt" in hits[0][0]


def test_42_search_path_is_dir_not_root():
    """显式传 path 不会扫描 cwd 的其他目录 (隔离性)。"""
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "inside.txt"), "token\n")
        # 另起一个临时目录, 里面也有 token
        with tempfile.TemporaryDirectory() as other:
            _write(os.path.join(other, "outside.txt"), "token\n")
            r = _tool().run({"pat": "token", "path": tmp})
            hits = _parse_hits(r["content"])
            assert len(hits) == 1
            assert "inside.txt" in hits[0][0]
            assert "outside.txt" not in hits[0][0]


# ── 6. 跳过: 目录 / 二进制 / 不存在 ─────────────────────────

def test_50_directories_are_skipped():
    """glob 返回的目录条目本身不应被当成文件打开。"""
    with tempfile.TemporaryDirectory() as tmp:
        # 在子目录里放一个命中文件
        _write(os.path.join(tmp, "sub", "a.txt"), "matched\n")
        r = _tool().run({"pat": "matched", "path": tmp})
        # 命中仍能找到, 说明子目录被正确遍历 (目录本身没触发 open 异常)
        assert r["success"] is True
        hits = _parse_hits(r["content"])
        assert len(hits) == 1
        assert "a.txt" in hits[0][0]


def test_51_binary_file_silently_skipped():
    """含无效 UTF-8 字节的二进制文件应被静默跳过 (open 抛异常 → except continue)。"""
    with tempfile.TemporaryDirectory() as tmp:
        # 写一个含无效 UTF-8 字节的文件
        bin_path = os.path.join(tmp, "blob.bin")
        with open(bin_path, "wb") as f:
            f.write(b"\xff\xfe\xfd\x00\x01invalid seq")
        # 另写一个含可解码命中的文本文件
        _write(os.path.join(tmp, "a.txt"), "findme\n")
        r = _tool().run({"pat": "findme", "path": tmp})
        assert r["success"] is True
        # findme 仍能找到, blob.bin 被跳过不报错
        hits = _parse_hits(r["content"])
        assert len(hits) == 1
        assert "a.txt" in hits[0][0]
        assert "blob.bin" not in r["content"]


def test_52_empty_file_is_fine():
    """空文件应能正常迭代 0 次, 不报错。"""
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "empty.txt"), "w", encoding="utf-8") as f:
            pass  # 0 字节
        _write(os.path.join(tmp, "a.txt"), "found\n")
        r = _tool().run({"pat": "found", "path": tmp})
        hits = _parse_hits(r["content"])
        assert len(hits) == 1


def test_53_directory_heavy_path_works():
    """含多个子目录与文件的典型结构不应触发任何 open 错误。"""
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(3):
            _write(os.path.join(tmp, f"d{i}", "x.txt"), f"hit{i}\n")
        r = _tool().run({"pat": "hit", "path": tmp})
        hits = _parse_hits(r["content"])
        assert len(hits) == 3


# ── 7. 命中上限 500 ────────────────────────────────────────

def test_60_exactly_500_hits_all_returned():
    with tempfile.TemporaryDirectory() as tmp:
        # 500 行, 全部命中
        _write(os.path.join(tmp, "a.txt"),
               "\n".join(f"line {i}" for i in range(500)) + "\n")
        r = _tool().run({"pat": "line", "path": tmp})
        assert r["success"] is True
        hits = _parse_hits(r["content"])
        assert len(hits) == 500, f"expected 500 hits, got {len(hits)}"


def test_61_more_than_500_hits_truncated():
    with tempfile.TemporaryDirectory() as tmp:
        # 501 行, 应截断到 500
        _write(os.path.join(tmp, "a.txt"),
               "\n".join(f"line {i}" for i in range(501)) + "\n")
        r = _tool().run({"pat": "line", "path": tmp})
        assert r["success"] is True
        hits = _parse_hits(r["content"])
        assert len(hits) == 500, f"expected 500 (truncated), got {len(hits)}"


def test_62_1000_hits_truncated_to_500():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "a.txt"),
               "\n".join(f"hit {i}" for i in range(1000)) + "\n")
        r = _tool().run({"pat": "hit", "path": tmp})
        hits = _parse_hits(r["content"])
        assert len(hits) == 500


# ── 8. 多文件聚合 ──────────────────────────────────────────

def test_70_hits_across_multiple_files():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "a.txt"), "shared\n")
        _write(os.path.join(tmp, "b.txt"), "shared\n")
        _write(os.path.join(tmp, "sub", "c.txt"), "shared\n")
        r = _tool().run({"pat": "shared", "path": tmp})
        hits = _parse_hits(r["content"])
        assert len(hits) == 3
        files = sorted(h[0] for h in hits)
        assert any("a.txt" in f for f in files)
        assert any("b.txt" in f for f in files)
        assert any("c.txt" in f for f in files)


def test_71_file_path_includes_subdir():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "sub", "x.txt"), "tag\n")
        r = _tool().run({"pat": "tag", "path": tmp})
        hits = _parse_hits(r["content"])
        assert len(hits) == 1
        # 路径应当是绝对或相对 tmpdir 下的 sub/x.txt
        path = hits[0][0]
        assert os.sep + "sub" + os.sep + "x.txt" in path or "sub/x.txt" in path, (
            f"path should contain sub/x.txt, got {path!r}")


# ── 9. line_num 1-based & 空行 ─────────────────────────────

def test_80_line_numbers_are_1_based():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "a.txt"),
               "\n"          # 1: 空行
               "x\n"         # 2
               "\n"          # 3: 空行
               "y\n")        # 4
        r = _tool().run({"pat": "x|y", "path": tmp})
        hits = _parse_hits(r["content"])
        nums = sorted(h[1] for h in hits)
        assert nums == [2, 4], f"expected line numbers [2, 4], got {nums}"


def test_81_empty_line_does_not_match_anything():
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "a.txt"), "\n\n\n")
        # 没有任何字符, 任何 pattern 都不应命中
        r = _tool().run({"pat": ".", "path": tmp})
        assert r["content"] == "none", f"empty lines should not match '.', got {r['content']!r}"


# ── 10. path 默认值 (省略时为 ".") ─────────────────────────

def test_90_omitted_path_uses_cwd():
    """省略 path 时, 应从 cwd 搜索 (实现为 args.get('path', '.') + '/**')。"""
    with tempfile.TemporaryDirectory() as tmp:
        # 在 cwd 放一个命中文件
        _write(os.path.join(tmp, "marker.txt"), "in-cwd\n")
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp)
            r = _tool().run({"pat": "in-cwd"})  # 不传 path
            assert r["success"] is True
            assert "marker.txt" in r["content"]
        finally:
            os.chdir(old_cwd)


def test_91_path_with_trailing_slash_works():
    """path 末尾有 / 不应破坏 glob。"""
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "a.txt"), "x\n")
        r = _tool().run({"pat": "x", "path": tmp + os.sep})
        assert r["success"] is True
        assert "a.txt" in r["content"]


# ── 入口 ───────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== GrepTool 单元测试 ===\n")
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
