"""Tests for the extension mechanism — auto-discovered tools in ~/.mangocli/extensions/*.py.

Convention: an extension file exports a `tools` list of ToolBase instances;
`_load_extensions()` collects them across files and `main()` merges them into TOOLS
(same-name tools override built-ins).
"""
import os
import shutil
import sys
import tempfile
import unittest

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
        self.tmp = tempfile.mkdtemp()
        m.extensions_dir = os.path.join(self.tmp, "ext")

    def tearDown(self):
        m.TOOLS.clear()
        m.TOOLS.update(self.orig_tools)
        m.extensions_dir = self.orig_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_ext(self, filename, content):
        os.makedirs(m.extensions_dir, exist_ok=True)
        with open(os.path.join(m.extensions_dir, filename), "w", encoding="utf-8") as f:
            f.write(content)

    def _merge(self):
        """与模块级 TOOLS 初始化后的合并逻辑一致."""
        for t in m._load_extensions():
            m.TOOLS[t.name] = t

    def test_missing_dir_returns_empty(self):
        self.assertEqual(m._load_extensions(), [])

    def test_collects_exported_tools(self):
        self._write_ext("hello.py", HELLO_EXT)
        tools = m._load_extensions()
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
        with unittest.mock.patch.object(m.console, "error") as err:
            tools = m._load_extensions()
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


if __name__ == "__main__":
    unittest.main()
