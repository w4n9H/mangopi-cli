"""Shipped-style extension — task_tracker: in-session TodoWrite / TaskCreate.

按需启用:
  * 复制/软链本文件到 preset 扩展目录:
    ~/.mangocli/presets/<name>/extensions/  (需设 MANGO_PRESET=<name>)
    ~/.mangocli/extensions/  (未设置 MANGO_PRESET 时)

行为:
  * 5 actions: create / list / update / get / delete
  * 4 status: pending / in_progress / completed / cancelled
  * 持久化: ~/.mangocli/tasks/<session_id>.json  (session_id 来自 MANGO_SESSION_ID,
    缺省取 cwd + pid 派生)
  * 自定义事件: task:update  (UI / audit 扩展可订阅)
  * prompt_sections: 自动注入当前任务列表到 system prompt (in_progress 优先)

契约: 顶层仅 import; 其余符号一律函数体内延迟导入.
"""
from mangopi_cli import ToolBase

import hashlib
import json
import os
import time
from pathlib import Path

_TASKS_DIR = Path("~/.mangocli/tasks").expanduser()
_STATUS_MARK = {
    "pending": "[ ]", "in_progress": "[>]",
    "completed": "[x]", "cancelled": "[-]",
}


def _session_id() -> str:
    env_id = os.environ.get("MANGO_SESSION_ID")
    if env_id:
        return env_id
    cwd = Path.cwd().as_posix()
    return hashlib.md5(cwd.encode()).hexdigest()[:12]


def _storage_path() -> Path:
    _TASKS_DIR.mkdir(parents=True, exist_ok=True)
    return _TASKS_DIR / f"{_session_id()}.json"


def _load() -> dict:
    p = _storage_path()
    if not p.exists():
        return {"tasks": []}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {"tasks": []}


def _save(data: dict) -> None:
    _storage_path().write_text(json.dumps(data, indent=2, ensure_ascii=False))
    # Custom event — UI / audit can subscribe via m._mango_events.on("task:update", ...)
    # (imported lazily to honor the extension import-time contract)
    try:
        import mangopi_cli as m
        m._mango_events.emit("task:update", data["tasks"])
    except Exception:
        pass


class TaskTrackerTool(ToolBase):
    name = "task_tracker"
    description = (
        "Track progress on multi-step tasks. Actions: create / list / update / "
        "get / delete. Status: pending / in_progress / completed / cancelled. "
        "Use at the start of a multi-step task; mark in_progress when starting "
        "and completed when done. The current task list is auto-injected into the "
        "system prompt (in_progress first), so the model always sees the plan."
    )
    params = {
        "action": {
            "type": "string",
            "description": "One of: create, list, update, get, delete.",
        },
        "task_id": {
            "type": "string?",
            "description": "(update / get / delete) Task ID returned by create.",
        },
        "subject": {
            "type": "string?",
            "description": "(create / update) Short title. 1-7 words.",
        },
        "description": {
            "type": "string?",
            "description": "(create / update) Detail. What needs to happen?",
        },
        "status": {
            "type": "string?",
            "description": "(update) One of: pending, in_progress, completed, cancelled.",
        },
        "activeForm": {
            "type": "string?",
            "description": "(create / update) Present continuous form, e.g. 'Running tests'.",
        },
    }
    guidance = (
        "Use task_tracker at the start of any multi-step task. Mark in_progress "
        "when starting and completed when done. The user sees the list update live "
        "and the model always sees the current list in the system prompt. "
        "Don't create more than ~10 tasks — too many clutters the UI."
    )

    def preview(self, args):
        action = args.get("action", "?")
        if action == "create":
            return f"task_tracker.create: {args.get('subject', '(no subject)')}"
        if action == "update":
            return f"task_tracker.update: {args.get('task_id', '?')} → {args.get('status', '?')}"
        if action == "get":
            return f"task_tracker.get: {args.get('task_id', '?')}"
        if action == "delete":
            return f"task_tracker.delete: {args.get('task_id', '?')}"
        return f"task_tracker.{action}"

    def run(self, args):
        action = args.get("action")
        if action == "create":
            return self._create(args)
        if action == "list":
            return self._list()
        if action == "update":
            return self._update(args)
        if action == "get":
            return self._get(args.get("task_id") or "")
        if action == "delete":
            return self._delete(args.get("task_id") or "")
        return self.fail(
            f"Unknown action: {action!r}. Valid: create / list / update / get / delete.")

    def _create(self, args):
        subject = (args.get("subject") or "").strip()
        if not subject:
            return self.fail("subject is required for create")
        data = _load()
        task_id = f"task_{int(time.time() * 1000)}_{len(data['tasks'])}"
        task = {
            "id": task_id,
            "subject": subject,
            "description": (args.get("description") or "").strip(),
            "status": "pending",
            "activeForm": (args.get("activeForm") or subject).strip(),
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        data["tasks"].append(task)
        _save(data)
        return self.ok(f"Created {task_id}: {subject}\n{json.dumps(task, indent=2, ensure_ascii=False)}")

    def _list(self):
        data = _load()
        if not data["tasks"]:
            return self.ok("No tasks in this session.")
        lines = [f"Tasks ({len(data['tasks'])}):"]
        for t in data["tasks"]:
            mark = _STATUS_MARK.get(t["status"], "[?]")
            lines.append(f"  {mark} {t['id']}: {t['subject']}")
        return self.ok("\n".join(lines))

    def _update(self, args):
        task_id = args.get("task_id") or ""
        if not task_id:
            return self.fail("task_id is required for update")
        data = _load()
        for t in data["tasks"]:
            if t["id"] == task_id:
                for field in ("subject", "description", "status", "activeForm"):
                    val = args.get(field)
                    if val is not None:
                        t[field] = val
                t["updated_at"] = time.time()
                _save(data)
                return self.ok(f"Updated {task_id}: {t['subject']} → {t['status']}")
        return self.fail(f"Task {task_id!r} not found")

    def _get(self, task_id):
        if not task_id:
            return self.fail("task_id is required for get")
        data = _load()
        for t in data["tasks"]:
            if t["id"] == task_id:
                return self.ok(json.dumps(t, indent=2, ensure_ascii=False))
        return self.fail(f"Task {task_id!r} not found")

    def _delete(self, task_id):
        if not task_id:
            return self.fail("task_id is required for delete")
        data = _load()
        before = len(data["tasks"])
        data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
        if len(data["tasks"]) == before:
            return self.fail(f"Task {task_id!r} not found")
        _save(data)
        return self.ok(f"Deleted {task_id}")


# ── prompt_sections: 自动注入当前任务列表到 system prompt ──

def prompt_sections():
    """Auto-inject current task list. in_progress first, then pending, then done."""
    data = _load()
    tasks = data.get("tasks") or []
    if not tasks:
        return []
    order = {"in_progress": 0, "pending": 1, "cancelled": 2, "completed": 3}
    tasks = sorted(tasks, key=lambda t: (order.get(t.get("status", ""), 9),
                                          t.get("created_at", 0)))
    lines = ["## Current tasks (in_progress first)"]
    for t in tasks:
        mark = _STATUS_MARK.get(t.get("status", ""), "[?]")
        lines.append(f"{mark} {t['subject']} (id: {t['id']})")
    return [("task_status", "\n".join(lines))]


tools = [TaskTrackerTool()]
