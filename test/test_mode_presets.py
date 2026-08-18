"""Tests for v0.1.50 mode system — load_preset returns the preset dict, and
SystemPrompt applies prompt_overrides (base / clear_sections / append_sections).

Presets are written dynamically into a temp MANGO_PRESET_DIR (same pattern as
test_presets), so tests run without installing the shipped examples.
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("MANGO_KEY", "test-key-not-used")

sys_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if sys_path not in os.sys.path:
    os.sys.path.insert(0, sys_path)

import mangopi_cli as m  # noqa: E402

STANDARD_PRESET = '''
preset = {
    "name": "standard",
    "keep_tools": ["read", "write", "edit", "search", "grep", "bash", "use_skill", "attempt_completion"],
}
'''

MINIMAL_PRESET = '''
preset = {
    "name": "minimal",
    "keep_tools": ["bash", "edit"],
    "prompt_overrides": {
        "base": "You are a helpful software engineer assistant.",
        "clear_sections": ["safety", "builtin_rules", "tool_guidance",
                           "skills_guidance", "memory", "environment"],
    },
}
'''

CODE_PRESET = '''
preset = {
    "name": "codemode",
    "keep_tools": ["run_code", "attempt_completion"],
}
'''

APPEND_PRESET = '''
preset = {
    "name": "custom",
    "prompt_overrides": {
        "append_sections": [
            {"name": "code_only_instruction", "content": "run_code is the only tool you can call directly."},
        ],
    },
}
'''


class _PresetBase(unittest.TestCase):
    def setUp(self):
        self.orig_presets = m.MANGO_PRESET_DIR
        self.orig_dir = m.extensions_dir
        self.orig_tools = dict(m.TOOLS)
        self.orig_listeners = m._mango_events._listeners
        m._mango_events._listeners = {}
        self.tmp = tempfile.mkdtemp()
        m.MANGO_PRESET_DIR = os.path.join(self.tmp, "presets")
        m.extensions_dir = os.path.join(self.tmp, "ext")
        os.makedirs(m.MANGO_PRESET_DIR, exist_ok=True)

    def tearDown(self):
        m.TOOLS.clear()
        m.TOOLS.update(self.orig_tools)
        m._mango_events._listeners = self.orig_listeners
        m.extensions_dir = self.orig_dir
        m.MANGO_PRESET_DIR = self.orig_presets
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, content):
        os.makedirs(os.path.join(m.MANGO_PRESET_DIR, name), exist_ok=True)
        with open(os.path.join(m.MANGO_PRESET_DIR, name, "conf.py"), "w", encoding="utf-8") as f:
            f.write(content)

    def _prompt(self, preset_name):
        with mock.patch.object(m, "MANGO_PRESET", preset_name):
            return m.SystemPrompt().assemble()


class TestLoadPresetReturnsDict(_PresetBase):
    def test_returns_preset_dict(self):
        self._write("standard", STANDARD_PRESET)
        preset = m.load_preset("standard")
        self.assertEqual(preset["name"], "standard")
        self.assertEqual(len(preset["keep_tools"]), 8)

    def test_missing_returns_none(self):
        self.assertIsNone(m.load_preset("nope"))

    def test_code_preset_keeps_run_code(self):
        self._write("code", CODE_PRESET)
        preset = m.load_preset("code")
        self.assertIn("run_code", preset["keep_tools"])
        self.assertEqual(len(preset["keep_tools"]), 2)

    def test_minimal_preset_config(self):
        self._write("minimal", MINIMAL_PRESET)
        preset = m.load_preset("minimal")
        self.assertEqual(preset["keep_tools"], ["bash", "edit"])
        overrides = preset["prompt_overrides"]
        self.assertEqual(overrides["base"], "You are a helpful software engineer assistant.")
        self.assertIn("safety", overrides["clear_sections"])


class TestSystemPromptOverrides(_PresetBase):
    def test_minimal_prompt_is_one_line(self):
        self._write("minimal", MINIMAL_PRESET)
        prompt = self._prompt("minimal")
        self.assertEqual(prompt, "You are a helpful software engineer assistant.")

    def test_minimal_applies_keep_tools(self):
        self._write("minimal", MINIMAL_PRESET)
        m.load_preset("minimal")
        self.assertEqual(set(m.TOOLS), {"bash", "edit"})

    def test_base_override_keeps_other_sections(self):
        self._write("custom", '''
preset = {"name": "custom", "prompt_overrides": {"base": "Custom base line."}}
''')
        prompt = self._prompt("custom")
        self.assertIn("Custom base line.", prompt)
        self.assertIn("## Safety", prompt)  # 其他段保留
        self.assertIn("## Built-in Rules", prompt)

    def test_clear_sections_removes_only_listed(self):
        self._write("custom", '''
preset = {"name": "custom", "prompt_overrides": {"clear_sections": ["safety", "memory"]}}
''')
        prompt = self._prompt("custom")
        self.assertNotIn("## Safety", prompt)
        self.assertNotIn("## User Rules", prompt)
        self.assertIn("## Built-in Rules", prompt)  # 未列入的段保留

    def test_append_sections_adds(self):
        self._write("custom", APPEND_PRESET)
        prompt = self._prompt("custom")
        self.assertIn("run_code is the only tool you can call directly.", prompt)

    def test_no_preset_no_override(self):
        prompt = self._prompt("")
        self.assertIn("## Safety", prompt)
        self.assertIn("## Built-in Rules", prompt)
        self.assertIn("## Tool Selection", prompt)

    def test_missing_preset_no_override(self):
        # MANGO_PRESET 指向未安装 preset -> 优雅降级, 完整分层 prompt
        prompt = self._prompt("not_installed")
        self.assertIn("## Safety", prompt)


if __name__ == "__main__":
    unittest.main()
