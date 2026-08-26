"""Tests for SystemPrompt — covers layered prompt assembly.

Covers:
    * sections attribute structure (count, order, types)
    * Static-section keyword checks (base_intro, safety, builtin_rules,
      tool_guidance, environment)
    * Dynamic-section header checks (memory, skills_guidance)
    * assemble() behavior (returns non-empty str, contains keywords from
      each section, uses \\n\\n separator, deterministic, two instances
      produce equal output)
    * _build_* static-method signatures (return type, class-vs-instance
      equivalence)
    * Memory section branches (mocked project_root): no file, empty file,
      non-empty file
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# Add parent dir to sys.path so we can import mangopi_cli.
# This file lives at <project>/test/test_system_prompt.py,
# so the project root is one level up from __file__'s directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mangopi_cli  # noqa: E402
from mangopi_cli import SystemPrompt  # noqa: E402


# ── Shared helpers ───────────────────────────────────────────────────────────


class _SystemPromptBase(unittest.TestCase):
    """Base for tests that need a fresh SystemPrompt and quick access to
    a section's concatenated string content."""

    def _section_text(self, sp, name):
        """Return the concatenated string content of the named section."""
        content = next(c for n, c in sp.sections if n == name)
        return "".join(content)


# ── 1. sections attribute structure ─────────────────────────────────────────


class TestSectionsStructure(unittest.TestCase):
    """The `sections` attribute must be a list of (name, [str]) tuples."""

    def setUp(self):
        # 隔离环境扩展: 默认结构断言 (7 段/顺序) 与用户 prompt_sections 无关
        self.orig_sections = list(mangopi_cli.extension_registry.prompt_sections)
        mangopi_cli.extension_registry.prompt_sections = []

    def tearDown(self):
        mangopi_cli.extension_registry.prompt_sections = self.orig_sections

    def test_01_sections_attribute_exists_and_nonempty(self):
        sp = SystemPrompt()
        self.assertTrue(hasattr(sp, "sections"))
        self.assertIsInstance(sp.sections, list)
        self.assertGreater(len(sp.sections), 0)

    def test_02_default_sections_count_is_six(self):
        # Default has 6 sections: base_intro / safety / builtin_rules /
        # tool_guidance / memory / environment.  skills_guidance 段自 v0.1.53
        # 起由 skill 扩展 (examples/extensions/skill.py) 经 prompt_sections 通道注入.
        sp = SystemPrompt()
        self.assertEqual(len(sp.sections), 6)

    def test_03_default_sections_order(self):
        sp = SystemPrompt()
        names = [n for n, _ in sp.sections]
        expected = [
            "base_intro", "safety", "builtin_rules", "tool_guidance",
            "memory", "environment",
        ]
        self.assertEqual(names, expected)

    def test_04_each_section_is_str_list_tuple(self):
        sp = SystemPrompt()
        for item in sp.sections:
            self.assertIsInstance(item, tuple)
            self.assertEqual(len(item), 2)
            name, content = item
            self.assertIsInstance(name, str)
            self.assertTrue(name)  # non-empty
            self.assertIsInstance(content, str)

    def test_05_section_contents_are_list_of_str(self):
        sp = SystemPrompt()
        for name, content in sp.sections:
            for line in content:
                self.assertIsInstance(
                    line, str,
                    f"section {name!r} contains non-str: {line!r}",
                )


# ── 2. Static-section keyword checks ────────────────────────────────────────


class TestStaticSectionKeywords(_SystemPromptBase):
    """Static sections must contain specific keywords / phrases."""

    def test_10_base_intro_contains_keyword(self):
        sp = SystemPrompt()
        content = self._section_text(sp, "base_intro")
        self.assertIn("You are an interactive agent", content)
        self.assertIn("Use the instructions below", content)
        self.assertIn("NEVER generate or guess URLs", content)

    def test_11_safety_contains_keyword(self):
        sp = SystemPrompt()
        content = self._section_text(sp, "safety")
        self.assertIn("## Safety", content)
        self.assertIn("Destructive commands", content)
        self.assertIn("explicit user confirmation", content)

    def test_12_builtin_rules_contains_all_four_rules(self):
        sp = SystemPrompt()
        content = self._section_text(sp, "builtin_rules")
        for keyword in [
            "Think before coding",
            "Minimum code",
            "Surgical changes",
            "Verify before completion",
        ]:
            self.assertIn(keyword, content)

    def test_13_tool_guidance_mentions_key_tools(self):
        sp = SystemPrompt()
        content = self._section_text(sp, "tool_guidance")
        self.assertIn("## Tool Selection", content)
        self.assertIn("attempt_completion", content)
        self.assertIn("**edit**", content)
        self.assertIn("**bash**", content)

    def test_14_environment_contains_working_directory(self):
        sp = SystemPrompt()
        content = self._section_text(sp, "environment")
        self.assertIn("## Environment", content)
        self.assertIn("Working directory", content)
        self.assertIn("Operating system", content)
        self.assertIn("Python version", content)
        self.assertIn("Shell", content)


# ── 3. Dynamic-section header checks ────────────────────────────────────────


class TestDynamicSectionHeaders(_SystemPromptBase):
    """Dynamic sections must carry a stable header line."""

    def test_15_memory_section_has_user_rules_header(self):
        # The 'memory' section is built by _build_user_rules and must
        # carry the '## User Rules' header.
        sp = SystemPrompt()
        content = self._section_text(sp, "memory")
        self.assertIn("## User Rules", content)

    def test_16_core_has_no_skills_guidance_default(self):
        # skills_guidance 段已从核心移除: 由 skill 扩展注入 (见 TestSkillExtensionChannel)
        sp = SystemPrompt()
        self.assertNotIn("skills_guidance", [n for n, _ in sp.sections])


# ── 4. assemble() behavior ──────────────────────────────────────────────────


class TestAssembleBehavior(_SystemPromptBase):
    """assemble() joins sections deterministically with \\n\\n."""

    def test_20_assemble_returns_nonempty_str(self):
        sp = SystemPrompt()
        result = sp.assemble()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_21_assemble_contains_keywords_from_all_static_sections(self):
        sp = SystemPrompt()
        result = sp.assemble()
        # Pulls a representative keyword from each static section.
        self.assertIn("You are an interactive agent", result)   # base_intro
        self.assertIn("Destructive commands", result)           # safety
        self.assertIn("Think before coding", result)            # builtin_rules
        self.assertIn("## Tool Selection", result)               # tool_guidance
        self.assertIn("## Environment", result)                  # environment

    def test_22_assemble_uses_double_newline_separator(self):
        sp = SystemPrompt()
        result = sp.assemble()
        chunks = result.split("\n\n")
        # base_intro's leading line must be a complete chunk after
        # splitting on the "\n\n" separator.
        self.assertTrue(
            any("You are an interactive agent" in chunk for chunk in chunks),
            "expected base_intro to be a chunk when splitting on \\n\\n",
        )

    def test_23_assemble_is_deterministic(self):
        # Two consecutive assemble() calls on the same instance must
        # return identical strings.
        sp = SystemPrompt()
        self.assertEqual(sp.assemble(), sp.assemble())

    def test_24_two_instances_produce_same_output(self):
        # Two fresh instances (under default conditions) must produce
        # identical assemble() output.
        sp1 = SystemPrompt()
        sp2 = SystemPrompt()
        self.assertEqual(sp1.assemble(), sp2.assemble())


# ── 5. _build_* static-method signatures ────────────────────────────────────


class TestStaticBuilderSignatures(unittest.TestCase):
    """All _build_* static methods must return List[str]; class- and
    instance-call forms must be equivalent."""

    BUILDERS = [
        "_build_base_intro",
        "_build_safety",
        "_build_builtin_rules",
        "_build_tool_guidance",
        "_build_user_rules",
        "_build_environment",
    ]

    def test_30_build_methods_return_list_of_str(self):
        for name in self.BUILDERS:
            with self.subTest(builder=name):
                builder = getattr(SystemPrompt, name)
                result = builder()
                self.assertIsInstance(
                    result, str,
                    f"{name} should return list, got {type(result)}",
                )
                self.assertTrue(
                    all(isinstance(x, str) for x in result),
                    f"{name} should return list of str",
                )

    def test_31_static_builders_are_truly_static(self):
        # Class-call and instance-call must return identical strings.
        a = SystemPrompt._build_base_intro()
        b = SystemPrompt()._build_base_intro()
        self.assertEqual(a, b)


# ── 6. Memory section branches (mocked project_root) ───────────────────────


class TestMemorySectionBranches(unittest.TestCase):
    """The 'memory' section depends on .mangocli/MANGO.md under
    project_root. We mock project_root via unittest.mock.patch so each
    subtest sees a controlled filesystem state.
    """

    # _build_user_rules checks these two markers.
    UNAVAILABLE_MARKER = "No user-defined rules."
    HEADER = "## User Rules"

    def test_40_memory_no_file_shows_unavailable(self):
        """When .mangocli/MANGO.md doesn't exist, the memory section must
        show the '## User Rules' header followed by the 'unavailable'
        marker."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch("mangopi_cli.project_root", tmp):
                sp = SystemPrompt()
                memory = next(c for n, c in sp.sections if n == "memory")
                content = "".join(memory)
            self.assertIn(self.HEADER, content)
            self.assertIn(self.UNAVAILABLE_MARKER, content)

    def test_41_memory_empty_file_shows_unavailable(self):
        """When .mangocli/MANGO.md exists but is empty, the memory section
        must still show the 'unavailable' marker (zero-byte file)."""
        with tempfile.TemporaryDirectory() as tmp:
            mangocli = os.path.join(tmp, ".mangocli")
            os.makedirs(mangocli)
            open(os.path.join(mangocli, "MANGO.md"), "w", encoding="utf-8").close()
            with patch("mangopi_cli.project_root", tmp):
                sp = SystemPrompt()
                memory = next(c for n, c in sp.sections if n == "memory")
                content = "".join(memory)
            self.assertIn(self.HEADER, content)
            self.assertIn(self.UNAVAILABLE_MARKER, content)

    def test_42_memory_nonempty_file_shows_persisted_content(self):
        """When .mangocli/MANGO.md has content, the memory section must
        include the header and inject the file content under it."""
        with tempfile.TemporaryDirectory() as tmp:
            mangocli = os.path.join(tmp, ".mangocli")
            os.makedirs(mangocli)
            memory_file = os.path.join(mangocli, "MANGO.md")
            with open(memory_file, "w", encoding="utf-8") as f:
                f.write(
                    "- User prefers tabs over spaces\n"
                    "- Always use type hints\n"
                )
            with patch("mangopi_cli.project_root", tmp):
                sp = SystemPrompt()
                memory = next(c for n, c in sp.sections if n == "memory")
                content = "".join(memory)
            self.assertIn(self.HEADER, content)
            self.assertIn("User prefers tabs over spaces", content)
            self.assertIn("Always use type hints", content)
            self.assertNotIn(self.UNAVAILABLE_MARKER, content)

    def test_43_agent_md_only_injected(self):
        """仅存在 .mangocli/AGENT.md 时, memory 节必须注入其内容."""
        with tempfile.TemporaryDirectory() as tmp:
            mangocli = os.path.join(tmp, ".mangocli")
            os.makedirs(mangocli)
            with open(os.path.join(mangocli, "AGENT.md"), "w", encoding="utf-8") as f:
                f.write("- Follow repo conventions from AGENT.md\n")
            with patch("mangopi_cli.project_root", tmp):
                sp = SystemPrompt()
                memory = next(c for n, c in sp.sections if n == "memory")
                content = "".join(memory)
            self.assertIn(self.HEADER, content)
            self.assertIn("Follow repo conventions from AGENT.md", content)
            self.assertNotIn(self.UNAVAILABLE_MARKER, content)

    def test_44_agent_md_takes_precedence_over_mango_md(self):
        """两者并存时合并注入, 且 AGENT.md 内容在前 (为主)."""
        with tempfile.TemporaryDirectory() as tmp:
            mangocli = os.path.join(tmp, ".mangocli")
            os.makedirs(mangocli)
            agent_text = "- AGENT rule: tabs\n"
            mango_text = "- MANGO rule: type hints\n"
            with open(os.path.join(mangocli, "AGENT.md"), "w", encoding="utf-8") as f:
                f.write(agent_text)
            with open(os.path.join(mangocli, "MANGO.md"), "w", encoding="utf-8") as f:
                f.write(mango_text)
            with patch("mangopi_cli.project_root", tmp):
                sp = SystemPrompt()
                memory = next(c for n, c in sp.sections if n == "memory")
                content = "".join(memory)
            self.assertIn(self.HEADER, content)
            self.assertLess(content.find("AGENT rule"), content.find("MANGO rule"),
                            "AGENT.md 内容必须排在 MANGO.md 之前")
            self.assertNotIn(self.UNAVAILABLE_MARKER, content)

    def test_45_empty_agent_md_falls_back_to_mango_md(self):
        """AGENT.md 存在但为空时, 回退到 MANGO.md 内容."""
        with tempfile.TemporaryDirectory() as tmp:
            mangocli = os.path.join(tmp, ".mangocli")
            os.makedirs(mangocli)
            open(os.path.join(mangocli, "AGENT.md"), "w", encoding="utf-8").close()
            with open(os.path.join(mangocli, "MANGO.md"), "w", encoding="utf-8") as f:
                f.write("- Only MANGO rule\n")
            with patch("mangopi_cli.project_root", tmp):
                sp = SystemPrompt()
                memory = next(c for n, c in sp.sections if n == "memory")
                content = "".join(memory)
            self.assertIn(self.HEADER, content)
            self.assertIn("Only MANGO rule", content)
            self.assertNotIn(self.UNAVAILABLE_MARKER, content)


# ── 5. Extension channel: extension_registry.prompt_sections ───────────────────────────────


class TestExtensionPromptSections(unittest.TestCase):
    """扩展通道: extension_registry.prompt_sections 由 ExtensionRegistry.load 收获, SystemPrompt
    构造时同名段覆盖默认内容 (强化), 异名段追加于 environment 之后."""

    def setUp(self):
        self.orig = list(mangopi_cli.extension_registry.prompt_sections)
        mangopi_cli.extension_registry.prompt_sections[:] = []

    def tearDown(self):
        mangopi_cli.extension_registry.prompt_sections[:] = self.orig

    def test_50_no_extensions_keeps_six_sections(self):
        sp = SystemPrompt()
        self.assertEqual(len(sp.sections), 6)

    def test_51_override_default_section(self):
        mangopi_cli.extension_registry.prompt_sections[:] = [("safety", "Extension safety policy.")]
        sp = SystemPrompt()
        self.assertEqual(next(c for n, c in sp.sections if n == "safety"),
                         "Extension safety policy.")
        self.assertEqual([n for n, _ in sp.sections].count("safety"), 1)  # 覆盖不产生重复段
        self.assertEqual(len(sp.sections), 6)

    def test_52_append_new_section(self):
        mangopi_cli.extension_registry.prompt_sections[:] = [("project_note", "Pinned note.")]
        sp = SystemPrompt()
        names = [n for n, _ in sp.sections]
        self.assertEqual(names[-1], "project_note")  # 异名段追加于末尾
        self.assertEqual(len(sp.sections), 7)
        self.assertIn("Pinned note.", sp.assemble())

    def test_53_mixed_override_and_append(self):
        mangopi_cli.extension_registry.prompt_sections[:] = [
            ("builtin_rules", "Replaced rules."), ("extra_a", "A"), ("extra_b", "B")]
        sp = SystemPrompt()
        names = [n for n, _ in sp.sections]
        self.assertEqual(names.count("builtin_rules"), 1)
        self.assertIn("extra_a", names)
        self.assertIn("extra_b", names)
        self.assertEqual(len(sp.sections), 8)
        self.assertEqual(next(c for n, c in sp.sections if n == "builtin_rules"),
                         "Replaced rules.")


class TestSkillExtensionChannel(unittest.TestCase):
    """skill 扩展 (examples/extensions/skill.py) 双通道:
    tools 通道 → use_skill 并入 TOOLS, guidance 注入 tool_guidance;
    prompt_sections 通道 → skills_guidance 动态段 (核心默认段 v0.1.53 已移除, 现为追加)。
    注册路径与 ExtensionRegistry.load 一致 (load_file + _register_*),
    run 行为与提示词断言均用临时技能目录, 不依赖仓库磁盘状态。"""

    EXT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "examples", "extensions", "skill.py")

    def setUp(self):
        self._orig_tools = dict(mangopi_cli.TOOLS)
        self._orig_sections = list(mangopi_cli.extension_registry.prompt_sections)
        self._orig_reg_tools = list(mangopi_cli.extension_registry.tools)
        self.mod = mangopi_cli.ExtensionRegistry.load_file(self.EXT)
        for t in self.mod.tools:
            mangopi_cli.extension_registry._register_tool(t, "skill.py")
            mangopi_cli.TOOLS[t.name] = t
        mangopi_cli.extension_registry._register_prompt_section(self.mod.prompt_sections, "skill.py")

    def tearDown(self):
        mangopi_cli.extension_registry.unload_source("skill.py")
        mangopi_cli.extension_registry.tools = self._orig_reg_tools
        mangopi_cli.extension_registry.prompt_sections[:] = self._orig_sections
        mangopi_cli.TOOLS.clear()
        mangopi_cli.TOOLS.update(self._orig_tools)

    @staticmethod
    def _make_skill(tmp, name="demo", desc="demo skill"):
        d = os.path.join(tmp, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(f"---\ndescription: {desc}\ntags: [\"demo\"]\n---\nDemo body.\n")
        return tmp

    def test_70_tools_merged_into_TOOLS(self):
        self.assertIs(mangopi_cli.TOOLS["use_skill"], self.mod.tools[0])

    def test_71_guidance_injected_into_tool_guidance(self):
        sp = SystemPrompt()
        content = next(c for n, c in sp.sections if n == "tool_guidance")
        self.assertIn("call **use_skill** first", content)

    def test_72_skills_guidance_dynamic_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = self.mod.SkillManager(base_paths=[self._make_skill(tmp)])
            with patch.object(self.mod, "_manager", mgr):
                sp = SystemPrompt()
                content = next(c for n, c in sp.sections if n == "skills_guidance")
                self.assertIn("## Skills Selection Guidelines", content)
                self.assertIn("- demo: demo skill", content)

    def test_73_no_skills_section_disappears(self):
        mgr = self.mod.SkillManager(base_paths=["/nonexistent-skills-dir"])
        self.assertEqual(mgr.all(), {})
        with patch.object(self.mod, "_manager", mgr):
            sp = SystemPrompt()
            self.assertNotIn("skills_guidance", [n for n, _ in sp.sections])

    def test_74_use_skill_runs_and_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = self.mod.SkillManager(base_paths=[self._make_skill(tmp)])
            with patch.object(self.mod, "SkillManager", lambda: mgr):
                tool = mangopi_cli.TOOLS["use_skill"]
                ok = tool.run({"name": "demo"})
                self.assertTrue(ok["success"])
                self.assertIn("# Skill: demo", ok["content"])
                self.assertIn("Demo body.", ok["content"])
                self.assertFalse(tool.run({"name": "nope"})["success"])

    def test_75_unload_removes_tool_and_section(self):
        mangopi_cli.extension_registry.unload_source("skill.py")
        self.assertNotIn("use_skill", mangopi_cli.TOOLS)
        sp = SystemPrompt()
        self.assertNotIn("skills_guidance", [n for n, _ in sp.sections])


class TestDynamicToolGuidance(unittest.TestCase):
    """tool_guidance 段: 核心静态部分 + 已注册工具的 guidance 动态拼接
    (web_search 等随扩展加载后自动进入提示词)."""

    def setUp(self):
        self._orig = dict(mangopi_cli.TOOLS)

    def tearDown(self):
        mangopi_cli.TOOLS.clear()
        mangopi_cli.TOOLS.update(self._orig)

    def _guidance(self):
        sp = SystemPrompt()
        return next(c for n, c in sp.sections if n == "tool_guidance")

    def test_60_extension_tool_guidance_injected(self):
        class FakeTool(mangopi_cli.ToolBase):
            name = "fake"
            description = "fake"
            params = {}
            guidance = "Use **fake** for testing."

        mangopi_cli.TOOLS["fake"] = FakeTool()
        content = self._guidance()
        self.assertIn("Use **fake** for testing.", content)
        self.assertIn("Always finish with **attempt_completion**", content)  # 收尾句仍在

    def test_61_no_guidance_no_extra_lines(self):
        class QuietTool(mangopi_cli.ToolBase):
            name = "quiet"
            description = "quiet"
            params = {}

        mangopi_cli.TOOLS["quiet"] = QuietTool()  # guidance 默认 "" → 不注入
        content = self._guidance()
        self.assertNotIn("quiet", content)


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)