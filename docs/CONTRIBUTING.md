# Contributing to Mangopi CLI

> Thank you for your interest in contributing. Mangopi CLI is a single-file, zero-dependency AI coding assistant — please read this short guide before opening a PR so we stay consistent with the project's philosophy.

> 感谢你有兴趣贡献。Mangopi CLI 是一个单文件、零依赖的 AI 编码助手 —— 在提 PR 之前请先读完这份简短的指南,以保持项目哲学的一致性。

---

## Philosophy (read this first)

Mangopi CLI intentionally keeps the runtime extremely small:

- **No frameworks.** No `requests`, no `click`, no `rich`, no `httpx`.
- **No Electron. No Docker. No dependency hell.**
- **Single-file architecture** — everything lives in `mangopi_cli.py`.
- **Easy to audit, easy to hack, easy to fork.**

A pull request that introduces a third-party dependency, or that splits `mangopi_cli.py` into multiple modules **without an opt-in flag**, will be declined. If you have a strong reason to do either, please open an issue first to discuss.

> 中文版:不引入第三方依赖,不在没有 opt-in 开关的情况下拆分主文件。如果有充分理由,请先开 issue 讨论。

---

## Development Setup

Requirements:

- Python **3.8+** (the project supports 3.8 / 3.9 / 3.10 / 3.11 / 3.12)
- `git`
- No virtualenv dependency installation is required — the project is **zero-dependency**.

Clone and run:

```bash
git clone https://github.com/w4n9H/mangopi-cli.git
cd mangopi-cli
python mangopi_cli.py
```

Set the required environment variable:

```bash
export MANGO_KEY="your_api_key"
export MANGO_API_URL="https://api.deepseek.com"   # or any OpenAI-compatible endpoint
export MANGO_MODEL="deepseek-v4-flash"
```

Optional:

```bash
export MANGO_LANG=en        # en (default) | zh
export MANGO_MAX_CONTEXT=1000000
```

---

## Running Tests

All tests live in `test/` as standalone Python scripts (no `pytest` dependency). Each test is self-contained and exits non-zero on failure.

Run them all:

```bash
for f in test/test_*.py; do python "$f" || echo "FAIL: $f"; done
```

Or one at a time:

```bash
python test/test_micro_compact.py
python test/test_session_memory_compact.py
python test/test_compact_conversation.py
python test/test_full_compact.py
python test/test_goal_tool.py
python test/test_check_command_safety.py
python test/test_process_bash_output.py
```

When you add or change behavior, **add a test in the same style as the existing ones** (standalone script, no external runner, clear `passed / failed` counters). See `test/test_micro_compact.py` for the canonical pattern.

> 中文版:测试都是独立脚本,不依赖 pytest。新增/修改行为时,请按现有风格加一个 `test/test_xxx.py`,参考 `test/test_micro_compact.py` 的写法。

---

## Code Style

This project has no `black` / `ruff` / `flake8` config — and intentionally so. Match the existing style:

- **2-space indentation** (see `mangopi_cli.py`).
- **Type hints on public function signatures**; inline `Dict[str, Any]` / `List[str]` style is fine.
- **f-strings** for formatting, never `%` or `.format()`.
- **Section banner comments** using `# --- Section Name ---` (see line ~31 of `mangopi_cli.py`).
- **Bilingual comments / strings** are welcome when the surrounding code is bilingual (e.g. i18n table). For new UI text, always add both `zh` and `en` entries in the `I18N` dict.
- **No abstractions for their own sake.** If a 5-line block can be inlined, inline it.

---

## Pull Request Process

1. **Fork** the repo and create a topic branch:
   ```bash
   git checkout -b feat/short-description
   ```
2. **Keep diffs minimal.** Touch only what your change requires. Don't reformat unrelated code.
3. **Run all tests** locally before pushing — they should still pass:
   ```bash
   for f in test/test_*.py; do python "$f"; done
   ```
4. **Add a test** for any new behavior or bug fix.
5. **Update the README** if your change is user-visible (new tool, new command, new env var, new behavior).
6. **Update `__version__`** in `mangopi_cli.py` if your change is shipped to PyPI.
7. **One feature per PR.** Don't bundle unrelated fixes.
8. **Write a clear PR description** explaining *what* and *why*. Screenshots / GIFs are encouraged for UI changes.

A maintainer will review within a few days. Be patient — this is a small project.

---

## Commit Message Convention

The existing history uses lightweight conventional commits. Match it:

```
feat:<short summary>           # new feature
fix:<short summary>            # bug fix
refactor:<short summary>       # internal restructure, no behavior change
docs:<short summary>           # README / docs only
test:<short summary>           # tests only
chore:<short summary>          # build, CI, deps
```

The summary is **Chinese OR English**, kept under 60 characters, no trailing period. Examples from recent history:

```
feat:v0.1.19,强化/goal模式,精简system prompt,补充单元测试,以及更新README,index.html
feat:v0.1.18,新增compact rules,上下文压缩更灵活,新增memory system
fix:修复版本获取异常导致打包失败
```

---

## Things That Will Get a PR Declined

To save everyone's time, here is a non-exhaustive list of things we won't merge:

1. **Adding any runtime dependency** (`requests`, `httpx`, `rich`, `click`, `prompt_toolkit`, `pydantic`, ...). The zero-dependency promise is a feature, not a constraint to negotiate.
2. **Splitting `mangopi_cli.py` into multiple modules** without an opt-in flag and a discussion in an issue first.
3. **Removing or weakening the 7-class dangerous-command detection** or the path sandbox. New safety patterns can be added; existing ones cannot be removed.
4. **Removing i18n strings** in either language.
5. **Bumping the minimum Python version** above 3.8 without an issue + deprecation cycle.
6. **Refactors that touch > 200 lines without behavior change** — please split into smaller PRs.
7. **Generated code** (auto-formatters, AI-generated boilerplate dumps) without human review and a clear justification.
8. **Any change that breaks the public CLI contract** (`/q /c /n /g /h`, env vars `MANGO_*`, file paths under `.mangocli/`) without a deprecation notice.

---

## Reporting Bugs

Open a GitHub issue with:

- **Python version** (`python --version`)
- **OS** and shell (`uname -a`, `echo $SHELL`)
- **Model provider** and model name (`MANGO_API_URL`, `MANGO_MODEL`)
- **Mangopi CLI version** (`python mangopi_cli.py` shows it in the banner)
- **Minimal reproduction** — the shortest user input + tool calls that trigger the bug
- **Expected vs actual output**
- **Relevant logs** — particularly tool call output, error messages, and the contents of `.mangocli/session/session.json` if it relates to context issues

If the bug corrupts `session.json`, you can safely delete it — the project will start a fresh session. The previous session is **not** auto-recovered.

---

## Suggesting Features

Open an issue with:

- **The user problem** you are trying to solve (not the solution).
- **Why the existing tools / commands don't already cover it.**
- **Whether your proposal would violate the zero-dependency or single-file rules.** If yes, propose an opt-in path.
- **A sketch of the user-facing change** (new command, new tool, new env var, etc.)

We love ambitious ideas, but the bar for "adds a dependency" or "splits the file" is high. Most features should fit inside the existing surface.

---

## Project Structure (for newcomers)

```
mangopi-cli/
├── mangopi_cli.py            # the entire runtime (~1500 lines)
├── README.md                 # user-facing docs
├── CONTRIBUTING.md           # this file
├── index.html                # project landing page (PyPI, GitHub Pages)
├── pyproject.toml            # setuptools, zero deps
├── deploy.sh                 # build → install → twine upload
├── LICENSE                   # Apache 2.0
└── test/
    ├── test_micro_compact.py
    ├── test_session_memory_compact.py
    ├── test_compact_conversation.py
    ├── test_full_compact.py
    ├── test_goal_tool.py
    ├── test_check_command_safety.py
    └── test_process_bash_output.py
```

The main file is organized in this order:

1. Env vars / constants / i18n
2. `Printer` (terminal UI)
3. `initialize_system` / helper
4. Bash output filter / safety / path validation
5. `_request` (HTTP)
6. Goal / memory / skill persistence helpers
7. `MemoryManager`, `SkillManager`
8. `ToolBase` + 11 built-in tools
9. `ContextManager` (4-tier compaction)
10. `Provider` (OpenAI / DeepSeek / MiniMax)
11. `SystemPrompt` (layered assembly)
12. `agent_loop`, `main`

When adding code, place it in the layer that matches its responsibility.

---

## License

By contributing, you agree that your contributions will be licensed under **Apache License 2.0**, the same license as the project.

---

## Questions?

- Open a GitHub issue with the `question` label.
- Read the README first — most "how do I..." questions are already answered there.
- Read `mangopi_cli.py` — it is intentionally short and well-commented.

Welcome aboard. 🛠️
