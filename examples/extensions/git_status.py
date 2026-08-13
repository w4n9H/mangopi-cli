"""Shipped extension — git_status: 只读 git 仓库状态 (status/log/diff 结构化摘要).

按需启用:
  * 复制/软链本文件到 ~/.mangocli/extensions/, 或
  * MANGO_EXTENSIONS_DIR=examples/extensions

用途: agent 需要了解仓库状态时, 比裸 bash git 更结构化 (分支/变更计数/空态提示);
全部为只读命令, 无需确认.

契约: 顶层仅 import, 不访问 mangopi_cli 属性 (导入期半初始化); 所需符号在函数体内延迟导入.
"""
import subprocess

from mangopi_cli import ToolBase  # 顶层 import: load() 位于 ToolBase 定义之后, 安全


class GitStatusTool(ToolBase):
    name = "git_status"
    description = (
        "Read-only git repo state: status / log / diff summarized. Runs git in the project root; "
        "prefer it over raw bash git for structured output. Not a git repo returns a clear error.")
    params = {
        "action": {"type": "string?", "description": "'status' (default), 'log', or 'diff'."},
        "limit": {"type": "number?", "description": "Max log entries (default 20, max 100)."},
    }
    preview_lines = 60
    preview_width = 150
    guidance = ("Use **git_status** for repo state — status/log/diff summarized "
                "(read-only; prefer it over raw bash git for structured output).")

    def _git(self, root, *args):
        return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=30)

    def _status(self, root):
        out = self._git(root, "status", "--short", "--branch")
        if out.returncode != 0:
            return self.fail(f"git_status error: {out.stderr.strip()}")
        lines = [l for l in out.stdout.splitlines() if l.strip()]
        if not lines:
            return self.ok("(working tree clean)")
        changed = sum(1 for l in lines if not l.startswith("##"))
        head = lines[0] if lines[0].startswith("##") else "(no branch info)"
        body = "\n".join(lines[1:]) if len(lines) > 1 else ""
        return self.ok(f"{head}\n{body}\n({changed} changed file(s))".rstrip())

    def _log(self, root, limit):
        out = self._git(root, "log", "--oneline", f"-{limit}")
        if out.returncode != 0:
            return self.fail(f"git_status error: {out.stderr.strip()}")
        lines = [l for l in out.stdout.splitlines() if l.strip()]
        if not lines:
            return self.ok("(no commits yet)")
        return self.ok(f"## Last {len(lines)} commit(s)\n" + "\n".join(lines))

    def _diff(self, root):
        wt = self._git(root, "diff", "--stat")
        if wt.returncode != 0:
            return self.fail(f"git_status error: {wt.stderr.strip()}")
        st = self._git(root, "diff", "--cached", "--stat")
        sections = []
        wt_lines = [l for l in wt.stdout.splitlines() if l.strip()]
        sections.append("## Working tree\n" + ("\n".join(wt_lines) if wt_lines else "(no changes)"))
        st_lines = [l for l in st.stdout.splitlines() if l.strip()]
        sections.append("## Staged\n" + ("\n".join(st_lines) if st_lines else "(nothing staged)"))
        return self.ok("\n\n".join(sections))

    def run(self, args):
        action = (args.get("action") or "status").strip()
        if action not in ("status", "log", "diff"):
            return self.fail(f"git_status error: 'action' must be status/log/diff, got {action!r}")
        raw_limit = args.get("limit")
        try:
            limit = int(raw_limit) if raw_limit not in (None, "") else 20
        except (TypeError, ValueError):
            return self.fail(f"git_status error: 'limit' must be an integer, got {raw_limit!r}")
        limit = max(1, min(limit, 100))
        from mangopi_cli import project_root  # 函数体延迟导入: 执行时模块已完整初始化
        if action == "status":
            return self._status(project_root)
        if action == "log":
            return self._log(project_root, limit)
        return self._diff(project_root)


# 导出约定: tools 列表, 加载后自动进入 LLM 工具 schema 与 run_tool 分发
tools = [GitStatusTool()]
