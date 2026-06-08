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

    def test_01_sections_attribute_exists_and_nonempty(self):
        sp = SystemPrompt()
        self.assertTrue(hasattr(sp, "sections"))
        self.assertIsInstance(sp.sections, list)
        self.assertGreater(len(sp.sections), 0)

    def test_02_default_sections_count_is_seven(self):
        # Default has 7 sections: base_intro / safety / builtin_rules /
        # tool_guidance / skills_guidance / memory / environment.
        sp = SystemPrompt()
        self.assertEqual(len(sp.sections), 7)

    def test_03_default_sections_order(self):
        sp = SystemPrompt()
        names = [n for n, _ in sp.sections]
        expected = [
            "base_intro", "safety", "builtin_rules", "tool_guidance",
            "skills_guidance", "memory", "environment",
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
            self.assertIsInstance(content, list)

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

    def test_16_skills_guidance_section_has_proper_header(self):
        sp = SystemPrompt()
        content = self._section_text(sp, "skills_guidance")
        self.assertIn("## Skills Selection Guidelines", content)


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
        "_build_skills_guidance",
        "_build_user_rules",
        "_build_environment",
    ]

    def test_30_build_methods_return_list_of_str(self):
        for name in self.BUILDERS:
            with self.subTest(builder=name):
                builder = getattr(SystemPrompt, name)
                result = builder()
                self.assertIsInstance(
                    result, list,
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


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)