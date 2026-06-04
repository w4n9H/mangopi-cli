#!/usr/bin/env python3
"""Test SystemPrompt —— 覆盖分层提示词装配：默认 sections 数量/顺序/类型、静态 section 关键词、动态 section 装配、assemble() 拼接与确定性、_build_* 静态方法签名、memory section 三种分支。"""

import sys
import os
import tempfile
from unittest.mock import patch

# 将项目根目录加到 sys.path，以便 import mangopi_cli 中的 SystemPrompt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangopi_cli import SystemPrompt

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


# ── 1. sections 属性结构 ─────────────────────────────────────

def test_01_sections_attribute_exists_and_nonempty():
    sp = SystemPrompt()
    assert hasattr(sp, "sections"), "missing 'sections' attribute"
    assert isinstance(sp.sections, list), f"sections should be list, got {type(sp.sections)}"
    assert len(sp.sections) > 0, "sections list should not be empty"


def test_02_default_sections_count_is_seven():
    """默认应有 7 个 sections: base_intro / safety / builtin_rules / tool_guidance / skills_guidance / memory / environment。"""
    sp = SystemPrompt()
    assert len(sp.sections) == 7, f"expected 7 sections, got {len(sp.sections)}"


def test_03_default_sections_order():
    sp = SystemPrompt()
    names = [n for n, _ in sp.sections]
    expected = ["base_intro", "safety", "builtin_rules", "tool_guidance",
                "skills_guidance", "memory", "environment"]
    assert names == expected, f"expected order {expected}, got {names}"


def test_04_each_section_is_str_list_tuple():
    sp = SystemPrompt()
    for item in sp.sections:
        assert isinstance(item, tuple), f"section item should be tuple, got {type(item)}"
        assert len(item) == 2, f"section tuple should have 2 elements, got {len(item)}"
        name, content = item
        assert isinstance(name, str) and name, f"section name should be non-empty str, got {name!r}"
        assert isinstance(content, list), f"section content should be list, got {type(content)}"


def test_05_section_contents_are_list_of_str():
    sp = SystemPrompt()
    for name, content in sp.sections:
        for line in content:
            assert isinstance(line, str), f"section {name!r} contains non-str: {line!r}"


# ── 2. 静态 section 内容关键词 ──────────────────────────────

def test_10_base_intro_contains_keyword():
    sp = SystemPrompt()
    base = sp.sections[0][1]    # base_intro 是第 0 个 section
    content = "".join(base)
    assert "You are an interactive agent" in content
    assert "Use the instructions below" in content
    assert "NEVER generate or guess URLs" in content


def test_11_safety_contains_keyword():
    sp = SystemPrompt()
    safety = next(c for n, c in sp.sections if n == "safety")
    content = "".join(safety)
    assert "## Safety" in content
    assert "Destructive commands" in content
    assert "explicit user confirmation" in content


def test_12_builtin_rules_contains_all_four_rules():
    """Built-in Rules 应包含 4 条编号规则的关键短语。"""
    sp = SystemPrompt()
    rules = next(c for n, c in sp.sections if n == "builtin_rules")
    content = "".join(rules)
    for keyword in ["Think before coding", "Minimum code", "Surgical changes", "Verify before completion"]:
        assert keyword in content, f"missing rule keyword: {keyword!r}"


def test_13_tool_guidance_mentions_key_tools():
    sp = SystemPrompt()
    tools = next(c for n, c in sp.sections if n == "tool_guidance")
    content = "".join(tools)
    assert "## Tool Selection" in content
    assert "attempt_completion" in content
    assert "**edit**" in content
    assert "**bash**" in content


def test_14_environment_contains_working_directory():
    sp = SystemPrompt()
    env = next(c for n, c in sp.sections if n == "environment")
    content = "".join(env)
    assert "## Environment" in content
    assert "Working directory" in content
    assert "Operating system" in content
    assert "Python version" in content
    assert "Shell" in content


# ── 3. 动态 section 结构 ─────────────────────────────────────

def test_15_memory_section_has_proper_header():
    """memory section 必有 ## Memory 或 ## Persisted Memory 头部。"""
    sp = SystemPrompt()
    memory = next(c for n, c in sp.sections if n == "memory")
    content = "".join(memory)
    assert ("No persistent memory available" in content
            or "## Persisted Memory" in content), \
        f"memory section header missing, got: {content!r}"


def test_16_skills_guidance_section_has_proper_header():
    sp = SystemPrompt()
    skills = next(c for n, c in sp.sections if n == "skills_guidance")
    content = "".join(skills)
    assert "## Skills Selection Guidelines" in content


# ── 4. assemble() 行为 ──────────────────────────────────────

def test_20_assemble_returns_nonempty_str():
    sp = SystemPrompt()
    result = sp.assemble()
    assert isinstance(result, str), f"assemble() should return str, got {type(result)}"
    assert len(result) > 0, "assemble() should return non-empty string"


def test_21_assemble_contains_keywords_from_all_static_sections():
    sp = SystemPrompt()
    result = sp.assemble()
    # 来自 base_intro
    assert "You are an interactive agent" in result
    # 来自 safety
    assert "Destructive commands" in result
    # 来自 builtin_rules
    assert "Think before coding" in result
    # 来自 tool_guidance
    assert "## Tool Selection" in result
    # 来自 environment
    assert "## Environment" in result


def test_22_assemble_uses_double_newline_separator():
    """assemble() 应以 \\n\\n 拼接各 section, base_intro 的内容应独立成为一个 chunk。"""
    sp = SystemPrompt()
    result = sp.assemble()
    chunks = result.split("\n\n")
    assert any("You are an interactive agent" in chunk for chunk in chunks), \
        "expected base_intro to be a chunk when splitting on \\n\\n"


def test_23_assemble_is_deterministic():
    """同一实例连续调用 assemble() 应返回完全一致的内容。"""
    sp = SystemPrompt()
    a = sp.assemble()
    b = sp.assemble()
    assert a == b, "two consecutive assemble() calls should return identical strings"


def test_24_two_instances_produce_same_output():
    """两个独立实例 (默认状态下) 应产生相同的 assemble() 结果。"""
    sp1 = SystemPrompt()
    sp2 = SystemPrompt()
    assert sp1.assemble() == sp2.assemble(), \
        "two fresh SystemPrompt instances should produce identical prompts"


# ── 5. _build_* 静态方法签名 ────────────────────────────────

def test_30_build_methods_return_list_of_str():
    """所有 _build_* 静态方法都应返回 List[str] 且元素均为 str。"""
    builders = [
        SystemPrompt._build_base_intro,
        SystemPrompt._build_safety,
        SystemPrompt._build_builtin_rules,
        SystemPrompt._build_tool_guidance,
        SystemPrompt._build_skills_guidance,
        SystemPrompt._build_memory,
        SystemPrompt._build_environment,
    ]
    for builder in builders:
        result = builder()
        assert isinstance(result, list), \
            f"{builder.__name__} should return list, got {type(result)}"
        assert all(isinstance(x, str) for x in result), \
            f"{builder.__name__} should return list of str"


def test_31_static_builders_are_truly_static():
    """_build_* 静态方法被类或实例调用, 结果应一致。"""
    # 类调用
    a = SystemPrompt._build_base_intro()
    # 实例调用
    b = SystemPrompt()._build_base_intro()
    assert a == b, "static method should return same result whether called on class or instance"


# ── 6. memory section 三种分支 (mock project_root) ──────────

def test_40_memory_no_file_shows_unavailable():
    """当 .mangocli/MANGO.md 不存在时, memory section 应提示 No persistent memory available。"""
    with tempfile.TemporaryDirectory() as tmp:
        with patch("mangopi_cli.project_root", tmp):
            sp = SystemPrompt()
            memory = next(c for n, c in sp.sections if n == "memory")
            content = "".join(memory)
        assert "## Memory" in content, \
            f"expected '## Memory' header, got: {content!r}"
        assert "No persistent memory available" in content, \
            f"expected 'No persistent memory available', got: {content!r}"
        assert "Persisted Memory" not in content, \
            f"should NOT contain 'Persisted Memory' for missing file, got: {content!r}"


def test_41_memory_empty_file_shows_unavailable():
    """当 .mangocli/MANGO.md 存在但为空时, memory section 同样应提示 No persistent memory available。"""
    with tempfile.TemporaryDirectory() as tmp:
        mangocli = os.path.join(tmp, ".mangocli")
        os.makedirs(mangocli)
        open(os.path.join(mangocli, "MANGO.md"), "w", encoding="utf-8").close()    # 空文件
        with patch("mangopi_cli.project_root", tmp):
            sp = SystemPrompt()
            memory = next(c for n, c in sp.sections if n == "memory")
            content = "".join(memory)
        assert "## Memory" in content
        assert "No persistent memory available" in content, \
            f"expected 'No persistent memory available' for empty file, got: {content!r}"
        assert "Persisted Memory" not in content


def test_42_memory_nonempty_file_shows_persisted_content():
    """当 .mangocli/MANGO.md 存在且有内容时, memory section 应以 '## Persisted Memory' 头部注入文件内容。"""
    with tempfile.TemporaryDirectory() as tmp:
        mangocli = os.path.join(tmp, ".mangocli")
        os.makedirs(mangocli)
        memory_file = os.path.join(mangocli, "MANGO.md")
        with open(memory_file, "w", encoding="utf-8") as f:
            f.write("- User prefers tabs over spaces\n- Always use type hints\n")
        with patch("mangopi_cli.project_root", tmp):
            sp = SystemPrompt()
            memory = next(c for n, c in sp.sections if n == "memory")
            content = "".join(memory)
        assert "## Persisted Memory" in content, \
            f"expected '## Persisted Memory' header, got: {content!r}"
        assert "User prefers tabs over spaces" in content
        assert "Always use type hints" in content
        assert "No persistent memory available" not in content


# ── 入口 ───────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== SystemPrompt 单元测试 ===\n")
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            _run(name, fn)

    print(f"\n{'='*40}")
    print(f"通过: {passed}  失败: {failed}  跳过: {skipped}  "
          f"总计: {passed + failed + skipped}")
    if failed:
        sys.exit(1)
