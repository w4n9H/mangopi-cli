"""Tests for the run_code Code Mode extension (PTC).

Loads examples/extensions/run_code.py via ExtensionRegistry.load_file
(the same pattern as test_web_search), so tests run without installing
the code preset. Covers execution, safety whitelist, error handling,
timeout, output truncation, tool delegation, and the SDK prompt section.
"""
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("MANGO_KEY", "test-key-not-used")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mangopi_cli as m  # noqa: E402

_EXT = os.path.join("examples", "extensions", "run_code.py")
_wmod = m.ExtensionRegistry.load_file(_EXT)
RunCodeTool = _wmod.RunCodeTool  # noqa: E402


class TestRunCodeTool(unittest.TestCase):
    """Tests for RunCodeTool execution, safety, and output handling."""

    def _run(self, code, desc="test"):
        result = RunCodeTool().run({"code": code, "description": desc})
        self.assertTrue(result.get("success", False), result)
        return result["content"]

    def test_empty_script_rejected(self):
        result = RunCodeTool().run({"code": "", "description": "test"})
        self.assertFalse(result["success"])
        self.assertIn("Empty script", result["content"])

    def test_empty_description_rejected(self):
        result = RunCodeTool().run({"code": "print(1)", "description": ""})
        self.assertFalse(result["success"])
        self.assertIn("Empty description", result["content"])

    def test_simple_print_captured(self):
        out = self._run("print('hello world')")
        self.assertIn("hello world", out)

    def test_no_output_placeholder(self):
        out = self._run("x = 42  # no print")
        self.assertIn("no output", out)

    def test_control_flow(self):
        out = self._run(
            "total = 0\n"
            "for i in range(10):\n"
            "    total += i\n"
            "print(f'Sum: {total}')"
        )
        self.assertIn("Sum: 45", out)

    def test_closure_over_top_level_assignment(self):
        # locals 与 globals 同一命名空间: 脚本内函数可闭包访问顶层变量
        out = self._run("x = 40\n"
                        "def f():\n"
                        "    return x + 2\n"
                        "print(f())")
        self.assertIn("42", out)

    def test_try_except_in_script(self):
        out = self._run(
            "try:\n"
            "    raise ValueError('caught')\n"
            "except ValueError as e:\n"
            "    print(f'Caught: {e}')"
        )
        self.assertIn("Caught: caught", out)

    def test_exception_reported(self):
        out = self._run("raise ValueError('boom')")
        self.assertIn("Script error", out)
        self.assertIn("ValueError", out)
        self.assertIn("boom", out)

    def test_tool_exception_reported(self):
        # ReadTool.run 对不存在文件直接抛异常 -> 以 Script error 回流
        out = self._run("read('/nonexistent/x')")
        self.assertIn("Script error", out)
        self.assertIn("FileNotFoundError", out)

    def test_tool_error_raisable(self):
        # WriteTool 路径沙箱返回 fail -> CodeModeAPI 抛 ToolError, 脚本可捕获
        out = self._run(
            "try:\n"
            "    write('/etc/evil', 'x')\n"
            "except Exception as e:\n"
            "    print('caught:', type(e).__name__)"
        )
        self.assertIn("caught: ToolError", out)

    def test_tool_delegation_real_call(self):
        out = self._run('print(read("README.md")[:20])')
        self.assertIn("Mangopi CLI", out)  # README 首行内容

    def test_tools_available_when_filtered_out(self):
        # codemode keep_tools 收窄后 TOOLS 无 6 个 API 工具, 脚本内调用仍工作
        # (CodeModeAPI 独立实例化, 不依赖 TOOLS 状态)
        with mock.patch.dict(m.TOOLS, {}, clear=True):
            out = self._run('print(read("README.md")[:20])')
        self.assertIn("Mangopi CLI", out)

    def test_bash_delegation_uses_cmd_param(self):
        # 宿主 BashTool 参数名是 cmd (非 command): 脚本内 bash() 必须正确转发
        out = self._run('print(bash("echo hi"))')
        self.assertIn("hi", out)

    def test_confirm_requires_user_approval(self):
        # 整体确认在 RunCodeTool.confirm (run_tool 层, 执行脚本前一次):
        # 拒绝 -> 不执行; MANGO_YOLO -> 跳过确认
        tool = RunCodeTool()
        args = {"code": "print(1)", "description": "test script"}
        with mock.patch.object(m.console, "prompt_apply", return_value=False):
            self.assertFalse(tool.confirm(args))
        with mock.patch.object(m.console, "prompt_apply", return_value=True):
            self.assertTrue(tool.confirm(args))
        with mock.patch.object(m, "MANGO_YOLO", True), \
                mock.patch.object(m.console, "prompt_apply", return_value=False):
            self.assertTrue(tool.confirm(args))  # YOLO 跳过确认

    def test_edit_delegation(self):
        # 宿主 EditTool 参数名是 old/new (非 old_string/new_string)
        tmp = os.path.join(os.getcwd(), ".run_code_edit_tmp.txt")
        with open(tmp, "w") as f:
            f.write("alpha beta gamma")
        try:
            out = self._run(f'print(edit("{tmp}", "beta", "BETA"))')
            self.assertIn("ok", out)
            with open(tmp) as f:
                self.assertEqual(f.read(), "alpha BETA gamma")
        finally:
            os.remove(tmp)

    def test_search_delegation(self):
        # 宿主 SearchTool 参数名是 pat (非 pattern)
        out = self._run('print(search("README.md"))')
        self.assertIn("README.md", out)

    def test_grep_delegation(self):
        # 宿主 GrepTool 参数名是 pat (非 pattern); 关键字参数调用
        out = self._run('print(grep("codemode", path="examples/presets"))')
        self.assertIn("codemode", out)  # codemode/conf.py 注释含该词

    def test_dangerous_builtins_blocked(self):
        for snippet in ("__import__('os')", 'open("/etc/passwd")',
                        'eval("1+1")', 'exec("x=1")', 'globals()', 'vars()'):
            out = self._run(snippet)
            self.assertIn("Script error", out, snippet)
            self.assertIn("NameError", out, snippet)

    def test_use_skill_not_exposed(self):
        out = self._run("use_skill('memo')")
        self.assertIn("NameError", out)

    def test_output_truncated(self):
        out = self._run("print('x' * 20000)")
        self.assertIn("truncated", out)

    def test_timeout(self):
        with mock.patch.object(RunCodeTool, "TIMEOUT_SECONDS", 0.1):
            out = self._run("while True: pass")
        self.assertIn("timed out", out)

    def test_sdk_prompt_section(self):
        # SDK 段由 codemode preset 的 conf.py 经 prompt_overrides.append_sections 注入
        # (扩展本身不导出 prompt_sections)
        self.assertFalse(hasattr(_wmod, "prompt_sections"))
        conf = m.ExtensionRegistry.load_file(
            os.path.join("examples", "presets", "codemode", "conf.py"))
        sections = {s["name"]: s["content"] for s in conf.preset["prompt_overrides"]["append_sections"]}
        self.assertIn("code_only_instruction", sections)
        self.assertIn("tools_sdk", sections)
        self.assertIn("run_code", sections["tools_sdk"])
        self.assertIn("ToolError", sections["tools_sdk"])
        self.assertNotIn("use_skill", sections["tools_sdk"])


class TestSafeBuiltins(unittest.TestCase):
    """The whitelist must exclude every dangerous builtin."""

    def test_exclusions(self):
        for name in ("__import__", "open", "eval", "exec", "compile",
                     "globals", "locals", "vars", "dir", "input",
                     "breakpoint", "exit", "quit"):
            self.assertNotIn(name, _wmod._SAFE_BUILTINS)

    def test_common_helpers_present(self):
        for name in ("print", "len", "range", "str", "int", "list",
                     "dict", "sorted", "enumerate", "Exception"):
            self.assertIn(name, _wmod._SAFE_BUILTINS)


if __name__ == "__main__":
    unittest.main()
