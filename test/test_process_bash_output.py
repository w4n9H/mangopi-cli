#!/usr/bin/env python3
"""Test _process_bash_output() —— 覆盖空输出分支、非目录类命令、目录类命令过滤、行数限制及组合场景。"""

import sys
import os

# 将项目根目录加到 sys.path，以便 import mangopi_cli 中的 _process_bash_output
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangopi_cli import _process_bash_output, _is_directory_heavy, _filter_directory_output, _limit_output_lines

# ── 计数器与辅助函数 ─────────────────────────────────────────

passed = 0
failed = 0


def _t(name, command, output, expected):
    """运行一个 _process_bash_output 测试用例。

    expected: 与 _process_bash_output(command, output) 返回值逐项相等的可迭代对象。
    """
    global passed, failed
    try:
        actual = _process_bash_output(command, list(output))
        assert actual == expected, (
            f"expected {expected!r}, got {actual!r} "
            f"for command: {command!r}"
        )
        passed += 1
        print(f"  ✓ {name}")
    except AssertionError as e:
        failed += 1
        print(f"  ✗ {name}  FAIL: {e}")
    except Exception as e:
        failed += 1
        print(f"  ✗ {name}  ERROR: {type(e).__name__}: {e}")


# ── 1. 空输出 / falsy 输出 —— 直接短路返回 ─────────────────

def test_01_empty_list():
    _t("空列表直接返回", "ls -la", [], [])


def test_02_empty_list_directory_command():
    _t("目录类命令遇到空输出仍直接返回", "find . -name '*.py'", [], [])


# ── 2. 非目录类命令 —— 仅受行数限制，不做目录过滤 ──────────

def test_10_non_dir_command_unchanged():
    _t("非目录类命令且行数较少时不变",
       "echo hello",
       ["hello"],
       ["hello"])


def test_11_non_dir_command_with_git_path_kept():
    """非目录类命令不应过滤 .git 等路径, 完整保留原始输出。"""
    _t("echo 命令遇到 .git 路径仍保留",
       "echo ./node_modules/foo",
       ["./node_modules/foo", "build/output.bin"],
       ["./node_modules/foo", "build/output.bin"])


def test_12_non_dir_command_preserves_1000_lines():
    lines = [f"line-{i}" for i in range(1000)]
    _t("非目录类命令, 1000 行刚好不截断", "cat big.txt", lines, lines)


# ── 3. 目录类命令 + 过滤 —— 命中 FILTERED_DIRS 的行被剔除 ─

def test_20_find_filters_node_modules():
    _t("find 命令过滤掉 node_modules 行",
       "find . -type f",
       ["./node_modules/lib/index.js", "./src/main.py"],
       ["./src/main.py"])


def test_21_find_filters_git():
    _t("find 命令过滤掉 .git 行",
       "find . -type d",
       ["./src", "./.git/objects/abc", "./README.md"],
       ["./src", "./README.md"])


def test_22_find_filters_multiple_dirs():
    _t("find 命令过滤多个 FILTERED_DIRS",
       "find .",
       ["./__pycache__/x.cpython-311.pyc", "./dist/bundle.js",
        "./build/output", "./src/a.py", "./.venv/lib/python"],
       ["./src/a.py"])


def test_23_tree_command_also_filters():
    _t("tree 命令同样会过滤 (无需尾随空格)",
       "tree -L 2",
       ["./node_modules", "./src", "./.git"],
       ["./src"])


def test_24_ls_R_command_also_filters():
    _t("ls -R 命令同样会过滤",
       "ls -R",
       ["./node_modules/foo", "./vendor/bar", "./src/main.py"],
       ["./src/main.py"])


def test_25_du_command_also_filters():
    """du 命令触发过滤; 路径中带 __pycache__ 目录前缀才会被命中, tab 分隔的纯名称不会被命中。"""
    _t("du 命令过滤带 /__pycache__/ 路径的行",
       "du -sh *",
       ["./__pycache__/x.cpython-311.pyc", "./src\t10K"],
       ["./src\t10K"])
    # tab 分隔的纯名称 "__pycache__" 不在过滤路径形态范围内, 应被保留
    _t("du 命令不过滤 tab 分隔的纯目录名",
       "du -sh *",
       ["__pycache__\t1K", "./src\t10K"],
       ["__pycache__\t1K", "./src\t10K"])


def test_26_fd_command_also_filters():
    _t("fd 命令同样会过滤",
       "fd py",
       ["./node_modules/foo.py", "./.cache/data", "./src/main.py"],
       ["./src/main.py"])


def test_27_rg_command_also_filters():
    _t("rg 命令同样会过滤",
       "rg pattern",
       ["./.git/config:token=abc", "./src/a.py:pattern"],
       ["./src/a.py:pattern"])


def test_28_filter_skips_unrelated_lines():
    _t("目录类命令不命中过滤的行全部保留",
       "find . -name '*.py'",
       ["./src/main.py", "./tests/test_a.py", "./docs/readme.py"],
       ["./src/main.py", "./tests/test_a.py", "./docs/readme.py"])


# ── 4. 行数限制 —— 超过 1000 行时截断并追加提示 ────────────

def test_30_exactly_1000_lines_not_truncated():
    lines = [f"line-{i}" for i in range(1000)]
    _t("恰好 1000 行不截断", "echo loop", lines, lines)


def test_31_over_1000_lines_truncated():
    lines = [f"line-{i}" for i in range(1003)]
    expected = lines[:1000] + ["", "... truncated 3 lines ..."]
    _t("1003 行被截断为 1000 行 + 截断提示", "cat huge.txt", lines, expected)


def test_32_truncation_after_directory_filter():
    """目录过滤先于行数限制, 验证组合顺序。"""
    # 过滤后剩 1000 行刚好, 不截断
    lines = [f"./src/file-{i}.py" for i in range(1000)]
    _t("过滤后行数恰为 1000, 不截断",
       "find . -name '*.py'", lines, lines)

    # 过滤后剩 1001 行, 应截断
    lines_over = [f"./src/file-{i}.py" for i in range(1001)]
    expected_over = lines_over[:1000] + ["", "... truncated 1 lines ..."]
    _t("过滤后行数为 1001, 触发截断",
       "find . -name '*.py'", lines_over, expected_over)

    lines_mixed = (
        [f"./node_modules/f{i}.js" for i in range(500)]
        + [f"./src/file-{i}.py" for i in range(600)]
    )
    expected_mixed = [f"./src/file-{i}.py" for i in range(600)]
    _t("过滤后行数恰为 600, 不截断",
       "find .", lines_mixed, expected_mixed)


def test_33_filter_then_truncate_combo():
    """过滤后行数仍超 1000, 应再截断。"""
    lines = [f"./node_modules/f{i}.js" for i in range(500)] + \
            [f"./src/f{i}.py" for i in range(800)]
    # 过滤后剩 800 行, 未超 1000
    expected = [f"./src/f{i}.py" for i in range(800)]
    _t("过滤后剩 800 行, 不触发截断",
       "find .", lines, expected)

    lines2 = [f"./src/f{i}.py" for i in range(1200)]
    expected2 = lines2[:1000] + ["", "... truncated 200 lines ..."]
    _t("未过滤的 1200 行被截断", "find .", lines2, expected2)


# ── 5. 边界场景 —— 不做目录类命令误判的回归保护 ───────────

def test_40_non_heavy_commands_not_filtered():
    """普通 ls (无 -R)、grep、cat、echo 等不被误判为目录类命令。"""
    global passed, failed
    try:
        for cmd in ["ls -la", "ls", "grep -r pattern", "cat file.txt", "echo hi",
                    "git status", "npm install", "python script.py"]:
            result = _process_bash_output(cmd, ["./.git/HEAD", "./node_modules/x"])
            assert result == ["./.git/HEAD", "./node_modules/x"], (
                f"误过滤: command={cmd!r} result={result!r}")
        passed += 1
        print("  ✓ 普通命令不会触发目录过滤 (ls/grep/cat/echo/git/npm/python)")
    except AssertionError as e:
        failed += 1
        print(f"  ✗ 普通命令误判  FAIL: {e}")


def test_41_substring_match_does_not_misclassify():
    """子串匹配可能在边界场景误判, 此处验证 'find' 子串的常见场景。"""
    global passed, failed
    cases = [
        ("find . -name '*.py'", True),
        ("findings.txt", False),       # 单词内嵌, 不含 "find " 子串
        ("defined()", False),
        ("ls", False),
        ("ls -l", False),
        ("ls -R", True),
        ("tree", True),
        ("du -sh", True),
        ("du", False),
        ("fd pattern", True),
        ("rg foo", True),
    ]
    try:
        for cmd, expected in cases:
            actual = _is_directory_heavy(cmd)
            assert actual == expected, (
                f"_is_directory_heavy({cmd!r}) expected {expected}, got {actual}")
        passed += 1
        print("  ✓ _is_directory_heavy 边界判定正确 (find 子串不误判)")
    except AssertionError as e:
        failed += 1
        print(f"  ✗ _is_directory_heavy 边界  FAIL: {e}")


# ── 6. FILTERED_DIRS 各种路径形态都能被过滤 ────────────────

def test_50_filter_patterns_variants():
    """验证 _filter_directory_output 的多种路径形态都能被识别。"""
    cmd = "find ."
    raw = [
        "./node_modules/a",          # ./d/
        "src/node_modules/b",        # /d/
        "node_modules/c",            # 起始 d/
        "./dist:bundle.js",          # ./d:
        "vendor/lib:0.0.1",          # /d:
        "target/classes/X",          # /d/
        "./.cache/data",             # ./d/
        "endswith/__pycache__",      # 结尾 /d
        "./.idea",                   # 起始 ./
        ".venv",                     # 等于 d
        "./build",                   # 起始 ./
        "./src/keep_this.py",        # 不应过滤
    ]
    expected = ["./src/keep_this.py"]
    _t("多种路径形态的过滤匹配", cmd, raw, expected)


# ── 入口 ───────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== _process_bash_output 单元测试 ===\n")
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()

    print(f"\n{'='*40}")
    print(f"通过: {passed}  失败: {failed}  总计: {passed + failed}")
    if failed:
        sys.exit(1)
