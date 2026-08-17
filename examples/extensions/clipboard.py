"""Shipped extension — clipboard: 系统剪贴板读写.

按需启用:
  * 复制/软链本文件到 preset 扩展目录: ~/.mangocli/presets/<name>/extensions/ (需设 MANGO_PRESET=<name>)

平台: macOS (pbpaste/pbcopy), Linux (xclip); 其他平台返回明确错误.
安全: read 只读无需确认; write 写入剪贴板, 经核心确认机制 (confirm) 需用户同意.

契约: 顶层仅 import, 不访问 mangopi_cli 属性 (导入期半初始化); 所需符号在函数体内延迟导入.
"""
import subprocess
import sys

from mangopi_cli import ToolBase  # 顶层 import: load() 位于 ToolBase 定义之后, 安全


class ClipboardTool(ToolBase):
    name = "clipboard"
    description = (
        "Read or write the system clipboard. macOS uses pbpaste/pbcopy, Linux uses xclip; "
        "unsupported platforms return a clear error. Writing requires user confirmation.")
    params = {
        "action": {"type": "string?", "description": "'read' (default) or 'write'."},
        "text": {"type": "string?", "description": "Text to write when action='write'."},
    }
    preview_lines = 0
    preview_width = 200
    guidance = ("Use **clipboard** to exchange text with the system clipboard — read, or write "
                "(write requires confirmation).")

    @staticmethod
    def _commands():
        """平台命令对 (write_cmd, read_cmd); 不支持平台返回 None."""
        if sys.platform == "darwin":
            return ["pbcopy"], ["pbpaste"]
        if sys.platform.startswith("linux"):
            return ["xclip", "-selection", "clipboard"], ["xclip", "-selection", "clipboard", "-o"]
        return None

    def confirm(self, args):
        if (args.get("action") or "read").strip() != "write":
            return True  # 只读操作无需确认
        from mangopi_cli import console, MANGO_YOLO  # 函数体延迟导入: 执行时模块已完整初始化
        return MANGO_YOLO or console.prompt_apply("Write to system clipboard (y or n)?")

    def run(self, args):
        action = (args.get("action") or "read").strip()
        if action not in ("read", "write"):
            return self.fail(f"clipboard error: 'action' must be 'read' or 'write', got {action!r}")
        cmds = self._commands()
        if cmds is None:
            return self.fail(f"clipboard error: unsupported platform {sys.platform!r} "
                             "(macOS pbpaste/pbcopy, Linux xclip)")
        write_cmd, read_cmd = cmds
        try:
            if action == "read":
                out = subprocess.run(read_cmd, capture_output=True, text=True, timeout=10)
                if out.returncode != 0:
                    return self.fail(f"clipboard error: {read_cmd[0]} failed: {out.stderr.strip()}")
                return self.ok(out.stdout.rstrip("\n"))
            text = args.get("text")
            if text is None:
                return self.fail("clipboard error: 'text' is required when action='write'")
            out = subprocess.run(write_cmd, input=text, capture_output=True, text=True, timeout=10)
            if out.returncode != 0:
                return self.fail(f"clipboard error: {write_cmd[0]} failed: {out.stderr.strip()}")
            return self.ok(f"(clipboard written: {len(text)} chars)")
        except (subprocess.TimeoutExpired, OSError) as err:
            return self.fail(f"clipboard error: {err}")


# 导出约定: tools 列表, 加载后自动进入 LLM 工具 schema 与 run_tool 分发
tools = [ClipboardTool()]
