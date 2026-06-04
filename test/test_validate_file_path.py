#!/usr/bin/env python3
"""Test _validate_file_path() —— 覆盖路径校验各分支：合法文件、目录、不存在路径、越界路径、符号链接等。

注意: 本测试依赖 mangopi_cli.project_root = os.getcwd(), 因此应在项目根目录下执行
      `python test/test_validate_file_path.py`。
"""

import sys
import os
import tempfile

# 将项目根目录加到 sys.path，以便 import mangopi_cli 中的 _validate_file_path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mangopi_cli

# ── 计数器与辅助函数 ─────────────────────────────────────────

passed = 0
failed = 0
skipped = 0


def _t(name, path, expected_error_substring=None):
    """运行一个测试用例。

    expected_error_substring=None  → 预期返回 None (合法)
    expected_error_substring=str   → 预期返回包含该子串的错误描述
    """
    global passed, failed
    try:
        result = mangopi_cli._validate_file_path(path)
        if expected_error_substring is None:
            assert result is None, f"expected None (合法), got {result!r} for path: {path!r}"
        else:
            assert result is not None, (
                f"expected error containing {expected_error_substring!r}, "
                f"got None for path: {path!r}"
            )
            assert expected_error_substring in result, (
                f"expected error containing {expected_error_substring!r}, "
                f"got {result!r} for path: {path!r}"
            )
        passed += 1
        print(f"  ✓ {name}")
    except AssertionError as e:
        failed += 1
        print(f"  ✗ {name}  FAIL: {e}")
    except Exception as e:
        failed += 1
        print(f"  ✗ {name}  ERROR: {type(e).__name__}: {e}")


def _ok(name, path):
    """便捷包装: 预期路径合法 (返回 None)。"""
    _t(name, path, None)


def _err(name, path, expected_error_substring):
    """便捷包装: 预期路径非法 (返回包含子串的错误)。"""
    _t(name, path, expected_error_substring)


# 解析项目根目录 (供相对项目外的路径构造使用)
PROJECT_ROOT = mangopi_cli.project_root


# ── 1. 合法路径: 实际存在的文件 ──────────────────────────────

def test_01_existing_file_in_root():
    _ok("项目根下的现有文件 mangopi_cli.py", "mangopi_cli.py")


def test_02_existing_file_in_subdir():
    _ok("子目录下的现有文件 test/test_check_command_safety.py",
       "test/test_check_command_safety.py")


def test_03_nested_relative_path_with_dotdot_inside():
    """含 .. 但解析后仍落在项目根内的相对路径, 应视为合法。"""
    _ok("test/../mangopi_cli.py (含 .. 但仍留在项目内)",
       "test/../mangopi_cli.py")


def test_04_pyproject_file():
    _ok("项目根下的 pyproject.toml", "pyproject.toml")


# ── 2. 合法路径: 不存在的文件 (因为 isdir 为 False) ──────────

def test_10_nonexistent_file_in_root():
    """不存在的文件名不应被误判为目录, 函数应返回 None (合法)。"""
    _ok("不存在的文件名 (不创建)",
       "_vfp_definitely_not_existing_xyz_12345.txt")


def test_11_nonexistent_file_in_subdir():
    _ok("子目录下不存在的文件名",
       "test/_vfp_nonexistent_xyz_67890.py")


# ── 3. 非法路径: 项目根下的目录 ──────────────────────────────

def test_20_test_dir_is_directory():
    _err("test/ 是目录", "test", "is a directory")


def test_21_project_root_itself():
    """项目根目录本身也会被第二分支拒绝 (因为是目录)。"""
    _err("项目根目录自身 ('.')", ".", "is a directory")


def test_22_empty_string_path():
    """空路径经 abspath 解析为 cwd (即项目根), 同样被第二分支拒绝。"""
    _err("空字符串路径解析为项目根", "", "is a directory")


# ── 4. 非法路径: 越界到项目根之外 ──────────────────────────

def test_30_absolute_path_outside_etc():
    _err("绝对路径 /etc/passwd", "/etc/passwd", "is outside project root")


def test_31_absolute_path_tmp():
    _err("绝对路径 /tmp 下的文件",
       "/tmp/some_random_file_outside_project_xyz.txt",
       "is outside project root")


def test_32_parent_dir_traversal():
    """使用 ../ 跳出项目根。"""
    _err("../ 跳出项目根", "../etc/passwd", "is outside project root")


def test_33_deep_parent_dir_traversal():
    """多层 ../ 跳出项目根。"""
    _err("多层 ../ 跳出项目根", "../../../etc/hosts", "is outside project root")


def test_34_sibling_dir_outside():
    """项目根的兄弟目录 (祖父级 + sibling/) 越界。"""
    sibling = os.path.join(PROJECT_ROOT, "..", "sibling_dir_outside_project_xyz")
    _err("兄弟目录 (祖父级 + sibling/)", sibling, "is outside project root")


def test_35_prefix_collision_evil_sibling():
    """前缀冲突防护: 名字以项目根名作前缀的"邪恶兄弟"目录不应被误判为项目内。

    项目根为 /Users/moofs/Code/mangopi-cli, 路径 mangopi-cli_evil/foo 在
    abspath 后变为 /Users/moofs/Code/mangopi-cli_evil/foo。
    若边界检查漏写 + os.sep 而仅用 startswith(real_root), 该路径会被误判合法;
    正确实现应拒绝。
    """
    # 构造一个以项目根名 mangopi-cli 为前缀的兄弟路径
    parent = os.path.dirname(PROJECT_ROOT)   # /Users/moofs/Code
    root_basename = os.path.basename(PROJECT_ROOT)  # mangopi-cli
    evil_sibling = os.path.join(parent, root_basename + "_evil_xyz", "foo.txt")
    # sanity: 绝对路径解析后确实以前缀 mangopi-cli (无 /) 起始
    assert os.path.abspath(evil_sibling).startswith(PROJECT_ROOT), (
        "测试前置条件不成立: 构造的 evil 兄弟路径应与项目根共享前缀"
    )
    _err("前缀冲突 (evil 兄弟目录)", evil_sibling, "is outside project root")


# ── 5. 非法路径: 符号链接指向项目外 ─────────────────────────

def test_40_symlink_to_outside_file():
    """符号链接指向项目外文件时, realpath 解析后越界, 仍应被拒绝。"""
    global skipped
    # 在 /tmp 创建一个真实目标 (项目外)
    fd, outside_path = tempfile.mkstemp(prefix="vfp_target_", dir="/tmp")
    os.close(fd)
    # 在项目根内创建指向它的符号链接
    link_name = "_vfp_symlink_outside_test_link"
    link_path = os.path.join(PROJECT_ROOT, link_name)
    try:
        if os.path.lexists(link_path):
            os.unlink(link_path)
        try:
            os.symlink(outside_path, link_path)
        except (OSError, NotImplementedError) as e:
            # 某些平台 (如 Windows 非管理员) 不支持符号链接
            skipped += 1
            print(f"  ⚠ test_40_symlink_to_outside_file  SKIP: "
                  f"{type(e).__name__}: {e}")
            return
        _err(f"符号链接 {link_name} → /tmp 下的文件",
             link_path, "is outside project root")
    finally:
        # 清理: 删除符号链接与 /tmp 下的临时文件
        if os.path.lexists(link_path):
            os.unlink(link_path)
        if os.path.exists(outside_path):
            os.unlink(outside_path)


# ── 入口 ───────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== _validate_file_path 单元测试 ===\n")
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()

    print(f"\n{'='*40}")
    print(f"通过: {passed}  失败: {failed}  跳过: {skipped}  "
          f"总计: {passed + failed + skipped}")
    if failed:
        sys.exit(1)
