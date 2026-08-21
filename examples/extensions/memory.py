"""Shipped-style extension — memory: long-term memory across sessions.

按需启用:
  * 复制/软链本文件到 preset 扩展目录:
    ~/.mangocli/presets/<name>/extensions/  (需设 MANGO_PRESET=<name>)
    ~/.mangocli/extensions/  (未设置 MANGO_PRESET 时)

两类文件:
  1. 稳定/精选 (4 个 priority 文件, 总是加载):
       <cwd>/.mangocli/AGENT.md      项目规则 (top priority)
       <cwd>/.mangocli/MANGO.md      项目精选笔记
       ~/.mangocli/AGENT.md          用户级规则
       ~/.mangocli/MANGO.md          用户级笔记
  2. 每日追加 journal (per-day, 频繁写):
       <cwd>/.mangocli/memory/YYYY-MM-DD.md
       ~/.mangocli/memory/YYYY-MM-DD.md

3 个 actions:
  * read   - 显示所有加载的 memory (priority + 近期 date files, 按大小截断)
  * write  - 追加; 默认目标 = 今天 project journal
  * search - regex 搜索, 支持 scope 过滤

write target 覆盖:
  * 默认 (target=auto / journal) → 今天 project journal
  * target=AGENT.md / rules      → project AGENT.md
  * target=MANGO.md              → project MANGO.md
  * target=user                  → 今天 user journal
  * date=YYYY-MM-DD              → 指定日期的 project journal (backfill)

search scope:
  * all / project / user / rules / journal

契约: 顶层仅 import; 其余符号一律函数体内延迟导入.
"""
from mangopi_cli import ToolBase

import json
import re
import time
from datetime import date as _date
from pathlib import Path

_PROJECT_DIR = Path.cwd() / ".mangocli"
_USER_DIR = Path("~/.mangocli").expanduser()
_PROJECT_MEMORY_DIR = _PROJECT_DIR / "memory"
_USER_MEMORY_DIR = _USER_DIR / "memory"

PRIORITY_FILES = [
    _PROJECT_DIR / "AGENT.md",
    _PROJECT_DIR / "MANGO.md",
    _USER_DIR / "AGENT.md",
    _USER_DIR / "MANGO.md",
]

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")

MAX_WRITE_BYTES = 50_000
MAX_READ_BYTES = 100_000
MAX_SEARCH_RESULTS = 50


def _is_valid_date(s: str) -> bool:
    try:
        _date.fromisoformat(s)
        return True
    except ValueError:
        return False


def _today_file(memory_dir: Path) -> Path:
    return memory_dir / f"{_date.today().isoformat()}.md"


def _iter_date_files(newest_first: bool = True, base: Path | None = None) -> list[Path]:
    """List YYYY-MM-DD.md files in memory/, optionally newest-first."""
    bases = [base] if base is not None else [_PROJECT_MEMORY_DIR, _USER_MEMORY_DIR]
    results: list[Path] = []
    for b in bases:
        if not b.exists():
            continue
        for p in b.iterdir():
            if p.is_file() and _DATE_PATTERN.match(p.name):
                results.append(p)
    # Lex sort on YYYY-MM-DD.md = chronological sort.
    results.sort(key=lambda p: p.name, reverse=newest_first)
    return results


def _read_capped(path: Path, already: int) -> str:
    """Read file text, truncating to remaining size budget. '' if cap already exceeded."""
    remaining = MAX_READ_BYTES - already
    if remaining <= 0:
        return ""
    try:
        text = path.read_text()
    except OSError:
        return ""
    if len(text) > remaining:
        text = text[:remaining] + f"\n[truncated: {remaining}/{len(text)} chars shown]"
    return text


class MemoryTool(ToolBase):
    name = "memory"
    description = (
        "Manage long-term memory. Two kinds: "
        "(1) priority files (AGENT.md / MANGO.md) for stable rules, and "
        "(2) per-day journals (memory/YYYY-MM-DD.md) for session notes. "
        "Actions: read / write / search. By default write appends to today's "
        "project journal. Use target='AGENT.md' for stable rules."
    )
    params = {
        "action": {
            "type": "string",
            "description": "One of: read, write, search.",
        },
        "content": {
            "type": "string?",
            "description": "(write) Markdown content to append. Use headings to organise.",
        },
        "pattern": {
            "type": "string?",
            "description": "(search) Regex or substring. Case-insensitive.",
        },
        "scope": {
            "type": "string?",
            "description": "(search) One of: all, project, user, rules, journal. Default all.",
        },
        "target": {
            "type": "string?",
            "description": "(write) auto (default; today's project journal) / AGENT.md / MANGO.md / user / journal / rules.",
        },
        "date": {
            "type": "string?",
            "description": "(write) YYYY-MM-DD. If set, write to that specific date's project journal (backfill).",
        },
    }
    guidance = (
        "Use memory to record persistent context — coding conventions, deploy "
        "notes, gotchas, or what you learned this session. Default target is "
        "today's journal. For stable rules that should appear in every session's "
        "prompt, use target='AGENT.md'. Use search to recall previously saved info."
    )

    def preview(self, args):
        action = args.get("action", "?")
        if action == "write":
            target = self._resolve_write_target(args)
            preview = (args.get("content") or "")[:50]
            return f"memory.write → {target}: {preview!r}..."
        if action == "search":
            return f"memory.search: {args.get('pattern', '?')!r} scope={args.get('scope', 'all')}"
        return f"memory.{action}"

    def confirm(self, args):
        if args.get("action") != "write":
            return True
        import mangopi_cli as m
        if m.MANGO_YOLO:
            return True
        target = self._resolve_write_target(args)
        return m.console.prompt_apply(
            f"Append to {target}?\n"
            f"Content: {(args.get('content') or '')[:120]!r}...")

    def run(self, args):
        action = args.get("action")
        if action == "read":
            return self._read_all()
        if action == "write":
            return self._write(args)
        if action == "search":
            return self._search(args)
        return self.fail(f"Unknown action: {action!r}. Valid: read / write / search.")

    # ── read ──────────────────────────────────────────────────

    def _read_all(self):
        loaded: list[tuple[Path, str]] = []
        total = 0
        # Priority files first (fixed order)
        for path in PRIORITY_FILES:
            if not path.exists():
                continue
            text = _read_capped(path, total)
            if not text:
                continue
            loaded.append((path, text))
            total += len(text)
        # Date files (newest first; stop when cap hit)
        for path in _iter_date_files(newest_first=True):
            text = _read_capped(path, total)
            if not text:
                continue  # 空文件/预算耗尽: 跳过, 不截断后续文件
            loaded.append((path, text))
            total += len(text)

        if not loaded:
            return self.ok(
                f"No memory found. Use action='write' to start. "
                f"Default target: {_today_file(_PROJECT_MEMORY_DIR)}")
        header = (
            f"Memory loaded ({len(loaded)} files, {total} chars total). "
            f"Priority files first, then date files newest-first.\n"
        )
        body = "\n\n".join(f"## {p}\n{t}" for p, t in loaded)
        return self.ok(header + body)

    # ── write ─────────────────────────────────────────────────

    def _write(self, args):
        content = (args.get("content") or "").strip()
        if not content:
            return self.fail("content is required for write")
        if len(content) > MAX_WRITE_BYTES:
            return self.fail(
                f"content too long: {len(content)} > {MAX_WRITE_BYTES}. "
                f"Split into multiple write calls.")
        target = self._resolve_write_target(args)
        target.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        existing = ""
        if target.exists():
            existing = target.read_text()
            if existing and not existing.endswith("\n"):
                existing += "\n"
        target.write_text(f"{existing}\n<!-- appended {stamp} -->\n{content}\n")
        # Custom event — UI / audit can subscribe.
        try:
            import mangopi_cli as m
            m._mango_events.emit("memory:write", str(target), len(content))
        except Exception:
            pass
        return self.ok(
            f"Appended {len(content)} chars to {target}\nFile size: {target.stat().st_size} chars")

    def _resolve_write_target(self, args) -> Path:
        explicit_date = (args.get("date") or "").strip()
        if explicit_date and _is_valid_date(explicit_date):
            return _PROJECT_MEMORY_DIR / f"{explicit_date}.md"
        target = (args.get("target") or "auto").lower()
        if target == "agent.md":
            return _PROJECT_DIR / "AGENT.md"
        if target == "mango.md":
            return _PROJECT_DIR / "MANGO.md"
        if target == "user":
            return _today_file(_USER_MEMORY_DIR)
        if target == "rules":
            return _PROJECT_DIR / "AGENT.md"
        # default (auto / journal / anything else): today's project journal
        return _today_file(_PROJECT_MEMORY_DIR)

    # ── search ────────────────────────────────────────────────

    def _search(self, args):
        pattern = (args.get("pattern") or "").strip()
        if not pattern:
            return self.fail("pattern is required for search")
        scope = args.get("scope") or "all"
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return self.fail(f"invalid regex: {e}")

        paths = self._paths_for_scope(scope)
        if not any(p.exists() for p in paths):
            return self.ok(f"No memory files match scope={scope!r}")

        matches: list[dict] = []
        for path in paths:
            if not path.exists():
                continue
            try:
                text = path.read_text()
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    matches.append({
                        "file": str(path),
                        "line": i,
                        "content": line[:200],
                    })
                    if len(matches) >= MAX_SEARCH_RESULTS:
                        matches.append({"truncated": True,
                                        "note": f"hit {MAX_SEARCH_RESULTS}-result cap"})
                        return self.ok(json.dumps(matches, indent=2, ensure_ascii=False))
        if not matches:
            return self.ok(f"No matches for /{pattern}/i in scope={scope!r}")
        return self.ok(json.dumps(matches, indent=2, ensure_ascii=False))

    def _paths_for_scope(self, scope: str) -> list[Path]:
        if scope == "project":
            return [_PROJECT_DIR / "AGENT.md", _PROJECT_DIR / "MANGO.md",
                    *_iter_date_files(newest_first=True, base=_PROJECT_MEMORY_DIR)]
        if scope == "user":
            return [_USER_DIR / "AGENT.md", _USER_DIR / "MANGO.md",
                    *_iter_date_files(newest_first=True, base=_USER_MEMORY_DIR)]
        if scope == "rules":
            return list(PRIORITY_FILES)
        if scope == "journal":
            return list(_iter_date_files(newest_first=True))
        # all
        return [*PRIORITY_FILES, *_iter_date_files(newest_first=True)]


# ── prompt_sections: auto-inject all memory into system prompt ──

def prompt_sections():
    """Inject priority files + recent date files (newest first, size-capped)."""
    chunks: list[str] = []
    total = 0
    for path in PRIORITY_FILES:
        if not path.exists():
            continue
        text = _read_capped(path, total)
        if not text:
            continue
        chunks.append(f"### {path}\n{text}")
        total += len(text)
    for path in _iter_date_files(newest_first=True):
        text = _read_capped(path, total)
        if not text:
            continue  # 空文件/预算耗尽: 跳过, 不截断后续文件
        chunks.append(f"### {path}\n{text}")
        total += len(text)
    if not chunks:
        return []
    body = (
        f"## Long-term memory\n"
        f"Priority files (AGENT.md / MANGO.md) first, then per-day journals "
        f"(memory/YYYY-MM-DD.md) newest-first. Total size capped at "
        f"{MAX_READ_BYTES} chars.\n"
        f"Update with `memory(action='write', content=...)`. "
        f"Use target='AGENT.md' for stable rules, default (today's journal) for "
        f"session notes.\n\n"
        + "\n\n".join(chunks)
    )
    return [("memory", body)]


tools = [MemoryTool()]
