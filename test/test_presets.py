"""Tests for preset bundles — load_preset() applies a preset dict from
~/.mangocli/presets/<name>/conf.py (MANGO_PRESET_DIR): unloads a list of extension
sources via unload_source (PR 1) and emits preset:applied on the event bus
(PR 2). Returns the preset dict, or None when the preset file or its `preset`
dict is missing (so `MANGO_PRESET` typos warn instead of silently no-oping).

NOTE: the main() integration (MANGO_PRESET env -> load_preset -> warning) is
covered by the maintainer's own manual test, not here.
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock
import mangopi_cli as m

PRESET_EXT = '''
from mangopi_cli import ToolBase

class ComboTool(ToolBase):
    name = "combo"
    description = "combo tool"
    params = {}

    def run(self, args):
        return self.ok("combo")

tools = [ComboTool()]
prompt_sections = [("combo_section", "combo content")]
entry_points = {"combo_entry": lambda: 42}
'''

MINIMAL_PRESET = '''
preset = {
    "name": "minimal",
    "description": "Unload all shipped extensions: pure built-in tools",
    "unload_sources": ["combo.py", "missing.py"],
}
'''

KEEP_PRESET = '''
preset = {
    "name": "keep8",
    "keep_tools": ["read", "write", "edit", "search", "grep", "bash", "use_skill", "attempt_completion"],
}
'''

EMPTY_PRESET = 'preset = {"name": "empty", "unload_sources": []}\n'


class TestLoadPreset(unittest.TestCase):
    def setUp(self):
        self.orig_presets = m.MANGO_PRESET_DIR
        self.orig_dir = m.extensions_dir
        self.orig_tools = dict(m.TOOLS)
        self.orig_reg = (list(m.extension_registry.tools),
                         list(m.extension_registry.prompt_sections),
                         dict(m.extension_registry.entry_points),
                         {k: list(v) for k, v in m.extension_registry.get_per_source().items()})
        self.orig_listeners = m._mango_events._listeners
        m._mango_events._listeners = {}
        self.tmp = tempfile.mkdtemp()
        m.MANGO_PRESET_DIR = os.path.join(self.tmp, "presets")
        m.extensions_dir = os.path.join(self.tmp, "ext")
        os.makedirs(m.MANGO_PRESET_DIR, exist_ok=True)

    def tearDown(self):
        m.TOOLS.clear()
        m.TOOLS.update(self.orig_tools)
        m.extension_registry.tools = list(self.orig_reg[0])
        m.extension_registry.prompt_sections = list(self.orig_reg[1])
        m.extension_registry.entry_points = dict(self.orig_reg[2])
        src = m.extension_registry.get_per_source()
        src.clear()
        src.update({k: list(v) for k, v in self.orig_reg[3].items()})
        m._mango_events._listeners = self.orig_listeners
        m.extensions_dir = self.orig_dir
        m.MANGO_PRESET_DIR = self.orig_presets
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, content):
        # preset 总配置: ~/.mangocli/presets/<name>/conf.py
        os.makedirs(os.path.join(m.MANGO_PRESET_DIR, name), exist_ok=True)
        with open(os.path.join(m.MANGO_PRESET_DIR, name, "conf.py"), "w", encoding="utf-8") as f:
            f.write(content)

    def _load_combo(self):
        """与模块级初始化一致的扩展加载 (load + 合并 TOOLS)."""
        os.makedirs(m.extensions_dir, exist_ok=True)
        with open(os.path.join(m.extensions_dir, "combo.py"), "w", encoding="utf-8") as f:
            f.write(PRESET_EXT)
        m.extension_registry.load()
        for t in m.extension_registry.tools:
            m.TOOLS[t.name] = t

    def test_missing_preset_returns_none(self):
        self.assertIsNone(m.load_preset("nope"))

    def test_no_preset_dict_returns_none(self):
        self._write("bad", "x = 1\n")
        self.assertIsNone(m.load_preset("bad"))
        self._write("bad2", 'preset = "not-a-dict"\n')
        self.assertIsNone(m.load_preset("bad2"))

    def test_applies_unload_sources_and_emits_event(self):
        self._load_combo()
        self._write("minimal", MINIMAL_PRESET)
        self.assertIn("combo", m.TOOLS)
        events = []
        m.on("preset:applied", lambda name, p: events.append((name, p.get("name"))))
        preset = m.load_preset("minimal")
        self.assertEqual(preset["name"], "minimal")
        self.assertEqual(m.extension_registry.tools, [])
        self.assertEqual(m.extension_registry.prompt_sections, [])
        self.assertEqual(m.extension_registry.entry_points, {})
        self.assertNotIn("combo", m.TOOLS)  # TOOLS 同步清理
        self.assertEqual(events, [("minimal", "minimal")])

    def test_empty_unload_sources_returns_zero_not_none(self):
        self._write("empty", EMPTY_PRESET)
        self.assertIsNotNone(m.load_preset("empty"))  # 不误报 "not found"

    def test_emit_after_unload(self):
        # 事件在卸载完成后触发 (audit 看到的是 preset 应用后的状态)
        self._load_combo()
        self._write("minimal", MINIMAL_PRESET)
        seen_tools = {}

        def _on_applied(name, p):
            seen_tools["combo"] = "combo" in m.TOOLS

        m.on("preset:applied", _on_applied)
        m.load_preset("minimal")
        self.assertEqual(seen_tools, {"combo": False})

    def test_keep_tools_whitelist(self):
        # keep_tools: TOOLS 只剩名单内工具 (内置 + 扩展统一过滤)
        self._load_combo()
        self._write("keep8", KEEP_PRESET)
        keep = {"read", "write", "edit", "search", "grep", "bash", "use_skill", "attempt_completion"}
        m.load_preset("keep8")
        self.assertEqual(set(m.TOOLS), keep)  # web_search/view_image/combo 均被卸
        with self.assertRaises(KeyError):
            m.run_tool("web_search", {})

    def test_keep_tools_reversible(self):
        # 逆操作登记 __preset__ 槽位: unload_source("__preset__") 恢复全部
        self._load_combo()
        self._write("keep8", KEEP_PRESET)
        orig = dict(m.TOOLS)
        m.load_preset("keep8")
        self.assertEqual(len(m.TOOLS), 8)
        m.extension_registry.unload_source("__preset__")
        self.assertEqual(set(m.TOOLS), set(orig))

    def test_keep_tools_ignores_unknown_names(self):
        # 名单内不存在的工具名忽略, 不报错
        self._write("keep_extra", '''
preset = {"name": "keep_extra", "keep_tools": ["read", "nope_tool"]}
''')
        m.load_preset("keep_extra")
        self.assertEqual(set(m.TOOLS), {"read"})

    def test_keep_tools_combined_with_unload_sources(self):
        # 组合: 先 unload_sources (卸扩展注册) 再 keep_tools (过滤 TOOLS)
        self._load_combo()
        self._write("combined", '''
preset = {
    "name": "combined",
    "unload_sources": ["combo.py"],
    "keep_tools": ["read"],
}
''')
        preset = m.load_preset("combined")
        self.assertEqual(preset["name"], "combined")
        self.assertEqual(m.extension_registry.tools, [])  # 注册通道已清
        self.assertEqual(set(m.TOOLS), {"read"})          # TOOLS 只剩 read


if __name__ == "__main__":
    unittest.main()
