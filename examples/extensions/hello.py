"""Example extension for mangopi-cli — copy this file to ~/.mangocli/extensions/ to enable.

扩展约定:
  * 将 .py 文件放入 ~/.mangocli/extensions/, 启动时自动发现并加载
  * 模块级导出 `tools` 列表 (ToolBase 实例)
  * 同名工具覆盖内置 (扩展优先)
  * 扩展是任意 Python 代码 (等同 pip 包信任), 仅加载可信来源
"""
from mangopi_cli import ToolBase


class HelloTool(ToolBase):
    """最简单的工具: 一个可选参数, 返回问候文本."""
    name = "hello"
    description = "Say hello (example extension tool)"
    params = {"name": {"type": "string", "description": "Who to greet"}}

    def run(self, args):
        return self.ok("Hello, %s!" % args.get("name", "world"))


class EchoTool(ToolBase):
    """演示参数必填校验 (params 中无 ? 后缀的参数为必填) 与 preview 定制."""
    name = "echo"
    description = "Echo the given text back (example extension tool)"
    params = {"text": {"type": "string", "description": "Text to echo"}}
    preview_width = 80

    def run(self, args):
        return self.ok(args["text"])


# 导出约定: tools 列表, 加载后自动进入 LLM 工具 schema 与 run_tool 分发
tools = [HelloTool(), EchoTool()]
