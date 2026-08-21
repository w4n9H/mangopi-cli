"""Shipped-style extension — multi_edit: apply N Edit operations in one call.

按需启用:
  * 复制/软链本文件到 preset 扩展目录:
    ~/.mangocli/presets/<name>/extensions/  (需设 MANGO_PRESET=<name>)
    ~/.mangocli/extensions/  (未设置 MANGO_PRESET 时)

行为:
  * 串行应用 N 个 edit; 失败时按逆序原子回滚已应用的 edit (best-effort).
  * 复用核心 EditTool (路径沙箱, all=True 支持).
  * 每个 edit 单独走 3 事件总线 (tool:before/after/error) — 审计/限流看得见.
  * 受 MANGO_YOLO 尊重; 不在 YOLO 时弹 m.console.prompt_apply 确认整体.

契约: 顶层仅 import; 其余符号一律函数体内延迟导入.
"""


from mangopi_cli import ToolBase


class MultiEditTool(ToolBase):
    name = "multi_edit"
    description = (
        "Apply multiple Edit operations in one call. Each edit reuses the "
        "core Edit tool (so the path sandbox still applies). Edits apply "
        "in order; if any fails, applied edits are rolled back in reverse. "
        "Use for 3+ logical edits across files in one refactor. For 1-2 "
        "edits, prefer the plain Edit tool."
    )
    params = {
        "edits": {
            "type": "array",
            "description": (
                "Ordered list of edits, each with: "
                "{path: string, old: string, new: string, all?: boolean}. "
                "Use the same param names as the Edit tool."
            ),
        },
        "stop_on_error": {
            "type": "boolean?",
            "description": "If true (default), abort on first failure and roll back. If false, skip failed edits and report.",
        },
    }
    guidance = (
        "Use multi_edit when a logical change spans 3+ edits across files. "
        "Each entry follows the Edit tool's param shape: path / old / new / all?."
    )
    preview_lines = 10
    use_spinner = True

    MAX_EDITS = 50

    def preview(self, args):
        edits = args.get("edits") or []
        files = sorted({(e or {}).get("path", "?") for e in edits if isinstance(e, dict)})
        return f"multi_edit: {len(edits)} edit(s) across {len(files)} file(s)"

    def confirm(self, args):
        import mangopi_cli as m
        if m.MANGO_YOLO:
            return True
        edits = args.get("edits") or []
        files = sorted({(e or {}).get("path", "?") for e in edits if isinstance(e, dict)})
        msg = f"Apply {len(edits)} edit(s) across {len(files)} file(s)?\nFiles: {files}\nContinue?"
        return m.console.prompt_apply(msg)

    def run(self, args):
        import mangopi_cli as m

        edits = args.get("edits") or []
        if not isinstance(edits, list) or not edits:
            return self.fail("edits array is required (at least 1 item)")
        if len(edits) > self.MAX_EDITS:
            return self.fail(
                f"Too many edits: {len(edits)} > {self.MAX_EDITS}. "
                f"Split into multiple multi_edit calls.")

        # Validate shape up front so we don't half-apply.
        for i, e in enumerate(edits):
            if not isinstance(e, dict):
                return self.fail(f"Edit #{i} is not an object: {e!r}")
            for required in ("path", "old", "new"):
                if required not in e:
                    return self.fail(
                        f"Edit #{i} missing required field {required!r}; got keys {list(e.keys())}")

        edit_tool = m.EditTool()
        applied: list[dict] = []
        files_touched: set[str] = set()
        results: list[dict] = []
        stop_on_error = bool(args.get("stop_on_error", True))

        for i, edit in enumerate(edits):
            edit_args = {
                "path": edit["path"],
                "old": edit["old"],
                "new": edit["new"],
            }
            if edit.get("all"):
                edit_args["all"] = True

            m._mango_events.emit("tool:before", "edit", edit_args)
            try:
                result = edit_tool.run(edit_args)
            except Exception as err:
                m._mango_events.emit("tool:error", "edit", err)
                if stop_on_error:
                    self._rollback(m, edit_tool, applied)
                    return self.fail(
                        f"Edit #{i} crashed: {err}. Rolled back {len(applied)} edit(s).")
                results.append({"index": i, "status": "skipped", "error": str(err)})
                continue
            m._mango_events.emit("tool:after", "edit", result)

            if not result.get("success"):
                if stop_on_error:
                    self._rollback(m, edit_tool, applied)
                    return self.fail(
                        f"Edit #{i} failed: {result.get('content')}. "
                        f"Rolled back {len(applied)} edit(s).")
                results.append({"index": i, "status": "skipped", "error": result.get("content")})
                continue

            applied.append(edit_args)
            files_touched.add(edit_args["path"])
            results.append({
                "index": i,
                "status": "applied",
                "file": edit_args["path"],
                "old_len": len(edit_args["old"]),
                "new_len": len(edit_args["new"]),
            })

        return self.ok(
            f"Applied {len(applied)}/{len(edits)} edits across "
            f"{len(files_touched)} file(s): {sorted(files_touched)}\n"
            f"Per-edit result:\n{_format_lines(results)}")

    @staticmethod
    def _rollback(m, edit_tool, applied: list[dict]) -> None:
        """Reverse applied edits in reverse order. Best-effort."""
        for edit in reversed(applied):
            try:
                edit_tool.run({
                    "path": edit["path"],
                    "old": edit["new"],
                    "new": edit["old"],
                })
            except Exception:
                pass


def _format_lines(items: list) -> str:
    """Compact one-line-per-item formatter (avoid json.dumps bloat)."""
    out = []
    for r in items:
        out.append(
            f"  [{r.get('status')}] #{r.get('index')} "
            f"{r.get('file', '')}  "
            f"{r.get('old_len', '?')}→{r.get('new_len', '?')} chars"
            f"{('  err: ' + r['error']) if r.get('error') else ''}")
    return "\n".join(out) if out else "  (none)"


tools = [MultiEditTool()]
