"""Tests for the extension mechanism — auto-discovered extensions in
~/.mangocli/extensions/*.py (or MANGO_EXTENSIONS_DIR).

Three-channel contract (all optional per file):
  * `tools`           — list of ToolBase instances; merged into TOOLS
                        (same-name tools override built-ins)
  * `prompt_sections` — list of (name, content); injected into SystemPrompt
                        (same-name overrides default section, new names append)
  * `entry_points`    — dict of name -> callable (e.g. {"acp": acp_main});
                        same-name entries: first file found wins
                        (extension_registry.entry_points)
`extension_registry.load()` rescans the directory (reload semantics).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MANGO_KEY", "test-key-not-used")

import mangopi_cli as m  # noqa: E402

HELLO_EXT = '''
from mangopi_cli import ToolBase

class HelloTool(ToolBase):
    name = "hello"
    description = "Say hello"
    params = {"name": {"type": "string", "description": "Who to greet"}}

    def run(self, args):
        return self.ok("Hello, %s!" % args.get("name", "world"))

tools = [HelloTool()]
'''

BROKEN_EXT = "this is not valid python {{{"


class TestExtensions(unittest.TestCase):
    def setUp(self):
        self.orig_dir = m.extensions_dir
        self.orig_tools = dict(m.TOOLS)  # 快照: tearDown 恢复, 防污染其他测试
        self.orig_reg = (list(m.extension_registry.tools),
                         list(m.extension_registry.prompt_sections),
                         dict(m.extension_registry.entry_points))
        self.tmp = tempfile.mkdtemp()
        m.extensions_dir = os.path.join(self.tmp, "ext")

    def tearDown(self):
        m.TOOLS.clear()
        m.TOOLS.update(self.orig_tools)
        m.extension_registry.tools = list(self.orig_reg[0])
        m.extension_registry.prompt_sections = list(self.orig_reg[1])
        m.extension_registry.entry_points = dict(self.orig_reg[2])
        m.extensions_dir = self.orig_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_ext(self, filename, content):
        os.makedirs(m.extensions_dir, exist_ok=True)
        with open(os.path.join(m.extensions_dir, filename), "w", encoding="utf-8") as f:
            f.write(content)

    def _merge(self):
        """与模块级 TOOLS 初始化后的合并逻辑一致 (load + 合并)."""
        m.extension_registry.load()
        for t in m.extension_registry.tools:
            m.TOOLS[t.name] = t

    def test_missing_dir_keeps_registry_empty(self):
        self.assertEqual(m.extension_registry.load().tools, [])

    def test_collects_exported_tools(self):
        self._write_ext("hello.py", HELLO_EXT)
        tools = m.extension_registry.load().tools
        self.assertEqual(len(tools), 1)
        tool = tools[0]
        self.assertEqual(tool.name, "hello")
        self.assertEqual(tool.schema()["function"]["name"], "hello")
        r = tool.run({"name": "pi"})
        self.assertEqual(r, {"success": True, "content": "Hello, pi!"})

    def test_merge_into_tools_and_run_tool(self):
        self._write_ext("hello.py", HELLO_EXT)
        self._merge()
        self.assertIn("hello", m.TOOLS)
        # run_tool 全链路可用 (与内置工具同路径)
        r = m.run_tool("hello", {"name": "mango"})
        self.assertTrue(r["success"])
        self.assertEqual(r["content"], "Hello, mango!")

    def test_broken_extension_isolated(self):
        self._write_ext("broken.py", BROKEN_EXT)
        self._write_ext("hello.py", HELLO_EXT)
        with mock.patch.object(m.console, "error") as err:
            tools = m.extension_registry.load().tools
        err.assert_called_once()  # 语法错误被记录诊断
        self.assertIn("broken.py", str(err.call_args))
        self.assertEqual([t.name for t in tools], ["hello"])  # 其他扩展不受影响

    def test_extension_overrides_builtin(self):
        # 扩展优先: 同名工具覆盖内置
        self._write_ext("override.py", '''
from mangopi_cli import ToolBase

class FakeReadTool(ToolBase):
    name = "read"
    description = "overridden read"
    params = {}

    def run(self, args):
        return self.ok("overridden")

tools = [FakeReadTool()]
''')
        self._merge()
        self.assertEqual(m.TOOLS["read"].description, "overridden read")
        r = m.run_tool("read", {})
        self.assertEqual(r["content"], "overridden")

    def test_prompt_sections_collected(self):
        self._write_ext("sections.py", '''
prompt_sections = [("extra_rule", "Never use recursion."), ("style_guide", "Use tabs.")]
''')
        self._merge()
        self.assertEqual(m.extension_registry.prompt_sections,
                         [("extra_rule", "Never use recursion."), ("style_guide", "Use tabs.")])

    def test_prompt_sections_override_and_append(self):
        # 同名覆盖默认段, 异名追加
        self._write_ext("sections.py", '''
prompt_sections = [("builtin_rules", "Custom rules replace defaults."), ("project_note", "Pinned note.")]
''')
        self._merge()
        sp = m.SystemPrompt()
        names = [n for n, _ in sp.sections]
        self.assertIn("project_note", names)                       # 异名追加
        self.assertGreater(names.index("project_note"), names.index("environment"))
        self.assertEqual(names.count("builtin_rules"), 1)          # 同名不重复
        content = next(c for n, c in sp.sections if n == "builtin_rules")
        self.assertEqual(content, "Custom rules replace defaults.")  # 内容被覆盖
        self.assertIn("Pinned note.", "\\n\\n".join(c for _, c in sp.sections))

    def test_entry_points_registered_first_wins(self):
        self._write_ext("acp.py", '''
def acp_main():
    return 7

entry_points = {"acp": acp_main}
''')
        self._write_ext("acp2.py", '''
def acp_main():
    return 9

entry_points = {"acp": acp_main}
''')
        self._merge()
        self.assertEqual(m.extension_registry.entry_points["acp"](), 7)  # 同名首个生效 (确定性)

    def test_file_without_entry_points_not_registered(self):
        self._write_ext("hello.py", HELLO_EXT)
        self._merge()
        self.assertEqual(m.extension_registry.entry_points, {})

    def test_all_three_channels_from_one_file(self):
        self._write_ext("combo.py", '''
from mangopi_cli import ToolBase

class NoteTool(ToolBase):
    name = "note"
    description = "Write a note"
    params = {}

    def run(self, args):
        return self.ok("noted")

def acp_main():
    return 0

def web_main():
    return 1

tools = [NoteTool()]
prompt_sections = [("combo_section", "Combo content.")]
entry_points = {"acp": acp_main, "web": web_main}
''')
        self._merge()
        self.assertIn("note", m.TOOLS)
        self.assertIn(("combo_section", "Combo content."), m.extension_registry.prompt_sections)
        self.assertEqual(m.extension_registry.entry_points["acp"](), 0)   # 多入口共存
        self.assertEqual(m.extension_registry.entry_points["web"](), 1)

    def test_reload_clears_stale_channels(self):
        # 重载语义: 上次扫描的结果不残留
        self._write_ext("sections.py", 'prompt_sections = [("stale", "old")]\n')
        self._merge()
        self.assertEqual(m.extension_registry.prompt_sections, [("stale", "old")])
        os.remove(os.path.join(m.extensions_dir, "sections.py"))
        self._merge()
        self.assertEqual(m.extension_registry.prompt_sections, [])
        self.assertEqual(m.extension_registry.entry_points, {})


class TestImportTimeLoading(unittest.TestCase):
    """导入期集成: 真实子进程执行 import mangopi_cli, 验证扩展在模块
    半初始化期 (ExtensionRegistry.load 位于 ToolBase 定义之后) 可顶层
    `from mangopi_cli import ToolBase` 而不 ImportError (回归: 曾因单例
    load 提前于 ToolBase 定义而失败)."""

    def _run_import(self, ext_content, assert_code):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "ext"), exist_ok=True)
            with open(os.path.join(tmp, "ext", "hello.py"), "w", encoding="utf-8") as f:
                f.write(ext_content)
            env = dict(os.environ)
            env["MANGO_EXTENSIONS_DIR"] = os.path.join(tmp, "ext")
            env["MANGO_KEY"] = "test-key-not-used"
            code = ("import mangopi_cli as m; " + assert_code)
            proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                                  cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            return proc

    def test_top_level_toolbase_import_at_import_time(self):
        # HELLO_EXT 顶层 from mangopi_cli import ToolBase
        proc = self._run_import(HELLO_EXT, "assert 'hello' in m.TOOLS, m.TOOLS")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_entry_points_at_import_time(self):
        proc = self._run_import('''
def acp_main():
    return 0

entry_points = {"acp": acp_main}
''', "assert m.extension_registry.entry_points['acp']() == 0")
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
