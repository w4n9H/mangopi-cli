"""Shipped-style extension — plan_mode: plan-then-execute state machine.

按需启用:
  * 复制/软链本文件到 preset 扩展目录:
    ~/.mangocli/presets/<name>/extensions/  (需设 MANGO_PRESET=<name>)

行为:
  * enter  - 进入 plan mode (patch TOOLS, 只留不改代码 / 不执行命令的工具)
  * submit - 提交 plan → 用户批准 → 退出 plan mode
  * cancel - 取消, 退出 plan mode

plan mode 期间:
  * 允许: read / search / grep / task_tracker / ask_user / memory / plan_mode
  * 禁止: write / edit / bash / multi_edit / run_code (等所有会改代码 / 执行命令的工具)

设计说明:
  * 复用 m.TOOLS 字典; 进出 plan mode 时 snapshot/restore.
  * 注意: load_preset 的 keep_tools 也会改 TOOLS; 建议在 plan_mode 期间不要
    切换 preset. 如有需要, 在 prompt_sections 中说明.
  * 配合 task_tracker: plan 批准后, 模型可以用 task_tracker 把 plan 拆成 todo.

契约: 顶层仅 import; 其余符号一律函数体内延迟导入.
"""
from mangopi_cli import ToolBase

# 工具白名单 / 黑名单 (按名称)
PLAN_MODE_ALLOWED = {
    "read", "search", "grep",
    "task_tracker", "ask_user", "memory",
    "plan_mode",  # meta: 可以从 plan 模式里调 plan_mode 自己
}
PLAN_MODE_BLOCKED = {"write", "edit", "bash", "multi_edit", "run_code"}


def _snapshot_and_filter(m):
    """Snapshot current TOOLS and replace with the non-mutating subset."""
    if not hasattr(m, "_PRE_PLAN_TOOLS"):
        m._PRE_PLAN_TOOLS = dict(m.TOOLS)
    m.TOOLS = {n: t for n, t in m._PRE_PLAN_TOOLS.items() if n in PLAN_MODE_ALLOWED}


def _restore(m):
    """Restore pre-plan TOOLS snapshot."""
    if hasattr(m, "_PRE_PLAN_TOOLS"):
        m.TOOLS = m._PRE_PLAN_TOOLS
        del m._PRE_PLAN_TOOLS


class PlanModeTool(ToolBase):
    name = "plan_mode"
    description = (
        "Plan-then-execute workflow. In plan mode, only non-mutating tools "
        "are available (read, search, grep, task_tracker, ask_user, memory, "
        "plan_mode) — no code changes, no command execution. "
        "write/edit/bash/multi_edit/run_code are blocked.\n"
        "Actions: enter (start plan mode) / submit (propose a plan) / "
        "cancel (abort plan mode). Use enter at the start of a complex "
        "multi-step task; while in plan mode, gather context, then submit "
        "a concrete plan for the user to approve."
    )
    params = {
        "action": {
            "type": "string",
            "description": "One of: enter, submit, cancel.",
        },
        "plan": {
            "type": "string?",
            "description": "(submit) Markdown plan: goal, steps with file paths, verification (tests / type-check), risk notes.",
        },
    }
    guidance = (
        "Use plan_mode at the start of a complex multi-step task. While in plan "
        "mode you can ONLY use non-mutating tools (no code changes, no command "
        "execution). When ready, submit a concrete plan: what you'll change, "
        "which files, and how you'll verify. The user approves or rejects — only "
        "after approval do you exit plan mode and can write."
    )

    def preview(self, args):
        action = args.get("action", "?")
        if action == "submit":
            preview = (args.get("plan") or "")[:80]
            return f"plan_mode.submit: {preview!r}..."
        return f"plan_mode.{action}"

    def confirm(self, args):
        if args.get("action") != "submit":
            return True
        import mangopi_cli as m
        if m.MANGO_YOLO:
            return True
        approved = m.console.prompt_apply(
            "Apply this plan?\n"
            "The model will exit plan mode and start executing the changes above.")
        if not approved:
            try:
                m._mango_events.emit("plan:reject", args.get("plan") or "")
            except Exception:
                pass
        return approved

    def run(self, args):
        action = args.get("action")
        if action == "enter":
            return self._enter()
        if action == "submit":
            return self._submit(args)
        if action == "cancel":
            return self._cancel()
        return self.fail(f"Unknown action: {action!r}. Valid: enter / submit / cancel.")

    def _enter(self):
        import mangopi_cli as m
        if getattr(m, "MANGO_PLAN_MODE", False):
            return self.ok("Already in plan mode.")
        m.MANGO_PLAN_MODE = True
        _snapshot_and_filter(m)
        try:
            m._mango_events.emit("plan:enter")
        except Exception:
            pass
        allowed = sorted(PLAN_MODE_ALLOWED)
        blocked = sorted(PLAN_MODE_BLOCKED)
        return self.ok(
            "Entered plan mode. Only non-mutating tools are available "
            "(no code changes, no command execution).\n"
            f"  allowed: {allowed}\n  blocked: {blocked}\n"
            "Submit with action='submit', or cancel with action='cancel'.")

    def _submit(self, args):
        plan = (args.get("plan") or "").strip()
        if not plan:
            return self.fail("plan text is required for submit")
        import mangopi_cli as m
        if not getattr(m, "MANGO_PLAN_MODE", False):
            return self.fail("Not in plan mode. Call action='enter' first.")

        m.console.output("")
        m.console.output("═══ Proposed plan ═══")
        m.console.output(plan)
        m.console.output("═════════════════════")

        m.MANGO_PLAN_MODE = False
        _restore(m)
        try:
            m._mango_events.emit("plan:approve", plan)
        except Exception:
            pass
        return self.ok(
            f"Plan approved ({len(plan)} chars). Exited plan mode. "
            f"You can now use write/edit/bash/multi_edit/run_code. "
            f"Proceed with the steps above.")

    def _cancel(self):
        import mangopi_cli as m
        if not getattr(m, "MANGO_PLAN_MODE", False):
            return self.ok("Not in plan mode.")
        m.MANGO_PLAN_MODE = False
        _restore(m)
        try:
            m._mango_events.emit("plan:cancel")
        except Exception:
            pass
        return self.ok("Cancelled plan mode. All tools available again.")


# ── prompt_sections: while in plan mode, prepend instructions ──

def prompt_sections():
    import mangopi_cli as m
    if not getattr(m, "MANGO_PLAN_MODE", False):
        return []
    return [(
        "plan_mode_active",
        "## Plan mode active\n"
        "You can ONLY use non-mutating tools (no code changes, no command "
        "execution): read, search, grep, task_tracker, ask_user, memory, plan_mode.\n"
        "Write / Edit / Bash / multi_edit / run_code are BLOCKED.\n"
        "When you have a concrete plan, call:\n"
        "  plan_mode(action='submit', plan='...markdown plan...')\n"
        "The user will approve or reject."
    )]


tools = [PlanModeTool()]
