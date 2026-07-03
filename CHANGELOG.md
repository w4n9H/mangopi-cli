# Changelog

All notable changes to Mangopi CLI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Note:** Versions `0.1.1` through `0.1.3` were published on the same day as the project rename
> from `mangocli` to `mangopi-cli`. Individual commit notes for these three releases are not
> preserved, so they are grouped below as a single "Initial releases" entry.

---

## [Unreleased]

### Added
- **`loop` subcommand** — new CLI entry `mangopi-cli loop <goal> [--task-id] [--max-iter] [--output]`.
- **`--task-id`** — persistent task directory under `.mangocli/loops/<task_id>/`, enabling future resume.
- **`--output jsonl`** — `Printer` layer emits structured events (`start`, `iter`, `tool`, `tool_result`, `usage`, `thinking`, `output`, `verdict`, `complete`) for web UI consumption.
- **README documentation** — Goal Mode fully replaced by Loop Engineering documentation.

### Removed
- **`MemoryManager` and `search_memory` tool** — long-term memory feature removed. `append_memory` / `search_memory` no longer available.

### Changed
- **Session persistence** — loop session files are no longer cleaned up on exit; preserved for resume.

---

## [0.1.31] - 2026-06-29

### Added
- **Loop Engineering** — `loop_engine()`: 3-agent collaborative pipeline (Implementer → Verifier → Updater) replacing `GoalTool`. Verifier runs actual tests; Updater refines prompts on failure. Entry: `/loop <goal>`.

### Removed
- **`GoalTool`** — deprecated in favor of `loop_engine`. `/goal` now shows a deprecation warning.

### Fixed
- Loop session files (`.mangocli/loops/`) are now cleaned up on exit via `finally` block.

---

## [0.1.30] - 2026-06-26

### Added
- **`doctor()` diagnostics** + `mangopi-cli --doctor` flag (env + session JSON integrity; exit code = error count).
- **Flash-ext OpenAI client support** — works with any OpenAI-compatible SDK / LangChain / LlamaIndex, not only the internal Mangopi format.
- **HumanEval benchmark harness** at `benchmark/humaneval_eval.py`, exercising the full Mangopi toolset + system prompt.
- **Flash-ext deep cooldown** (60s) to prevent duplicate `_analyze_deep` LLM calls.

### Changed
- **I18N refactor** — flat `{key: {zh, en}}` layout (was nested per-language).
- **Flash-ext perf** — `assess_complexity` thresholds tightened (`>=4` non-read tools, was `>=3`); `design` keyword set cleaned.
- **`ContextManager` helper extraction** — `_role_msgs` / `_tool_names` / `_last_user_content` / `_under_threshold` deduplicate role-filter patterns (-40 LOC, no behavior change).
- **`_analyze_deep` prompt** — adds "User question" section so the analyzer has task context for `insight`.

### Fixed
- **Flash-ext `<flash_ext>` injection** no longer accumulates across multi-turn agent loops.
- **`assess_complexity` query bug** — used `messages[-1]` (could be assistant/tool), now uses last user message.
- **`tool_context` `KeyError`** on OpenAI-standard tool messages without `tool_name`.

### Tests
- Threshold coverage in `test_flash_ext.py`.

---

## [0.1.29] - 2026-06-23

### Added
- **Flash-ext Thinking Framework Server** — OpenAI-compatible HTTP proxy (`--flash-ext`) with two-path routing (fast keyword + deep LLM analysis). Eight thinking frameworks. XML-based augmentation injected into user content.
- **`ContextManager` enhancements** — `tool_pattern`, `tool_context`, `detect_loop` (same-tool + alternating), `detect_phase`, `assess_complexity`.
- **38 unit tests** in `test/test_flash_ext.py`.

### Changed
- **Unified keyword rules** — all keyword matching centralized in `FlashThinking.KEYWORDS`; removed `RoutedProvider._KEYWORD_RULES`.
- **English frameworks** — all `FlashThinking.frameworks` steps translated.
- **`--memory`/`--web-search`** — flipped from default-on to default-off.
- **ROADMAP.md / README.md** — updated with Smart Provider Routing and Flash-ext sections.

### Fixed
- `_analyze_deep` JSON parse protection.
- `detect_loop` alternating tool failure patterns.
- `_augment` query extraction uses last user message, not list tail.

---

## [0.1.28] - 2026-06-18

### Added
- **Smart Provider Routing** — `MANGO_ROUTING` env var gates multi-model routing via `.mangocli/providers.json`. Three-tier scoring (low/medium/high) with keyword + LLM two-phase judgment; `RoutedProvider` delegates API calls to the selected sub-provider. Cross-provider message sanitization via `BaseProvider._sanitize_messages`.
- **`ContextManager.tool_fingerprint()`** — extracts `[user_query, [tool,...]]` pairs from recent turns.
- **34 unit tests** in `test/test_provider_routing.py`.
- Add `providers.json.example`

### Changed
- **ROADMAP.md** — updated Smart Provider Routing section to final design.
- **`create_provider()`** — refactored to shared `_new_provider()` factory.
- **Startup banner** — shows `smart-routing[N]` when routing is enabled; prints `→ tier: model` on each auto-switch.

## [0.1.27] - 2026-06-16

### Added
- **`MANGO_MAX_ITER` guard** — new env var (default 100) caps `agent_loop` iterations to prevent runaway loops.
- **Tool `preview()` methods** for `read`, `write`, `edit`, `search_memory` — improve tool-call display in console.
- **Benchmark coverage** — 4 new L1 tasks: `L1_append_memory`, `L1_search_memory`, `L1_web_search`, `L1_view_image`.

### Changed
- **System prompt** — `web_search` guidance now says "use sparingly, at most 3 times per user query".

### Fixed
- **Python 3.6+ compatibility** — replaced walrus operator in `ContextManager.prepare_for_api()` with explicit `after = self.total_tokens()`.

---

## [0.1.26] - 2026-06-15

### Added
- **Benchmark suite** (`benchmark/`) — end-to-end evaluation with real LLM calls: 14 tasks (L1–L4), tool-efficiency tracking, baseline save/compare for prompt iteration, JSON CI output.

### Fixed
- **BashTool 60s timeout** — `proc.stdout.readline()` had no timeout guard; `proc.wait(timeout=60)` ran after the process had already exited and never fired. Replaced with `proc.communicate(timeout=60)`.

---

## [0.1.25] - 2026-06-11

### Added
- **`web_search` tool** (`WebSearchTool`) — live web search via the 博查 (Bocha) AI Search API. 
- **README badges** — CI status, PyPI version, Python version, License, Stars, Release, Downloads, Last commit.

### Changed
- **ROADMAP §4** rewritten: "Web Fetch (Depends on Third-Party)" → "Web Search (Bocha AI Search)". 

---

## [0.1.24] - 2026-06-09

### Fixed
- ci: drop `--target` from `gh release create` (HTTP 422 fix)
- ci: add syntax check step to catch 3.10+ syntax early

---

## [0.1.23] - 2026-06-08

### Fixed
- ci: pass bare tag name to `gh release create --target` (was `refs/tags/...`, HTTP 422)

---

## [0.1.22] - 2026-06-08

### Added
- **`view_image` tool** (`ViewImageTool`) — loads a local image (screenshot / UI mockup / error screen / diagram) into the model's vision context. Accepts absolute paths only (URLs rejected), supports `png` / `jpg` / `jpeg` / `gif` / `webp`, with a 5 MB hard cap and base64 data-URI encoding for the multimodal payload
- **`read` tool** — when called on a `png` / `jpg` / `jpeg` / `gif` / `webp` path (without `offset` / `limit`), it auto-routes the file to `ViewImageTool`, so image inputs are transparent to the model
- **GitHub Actions CI/CD** (`.github/workflows/ci.yml`):
  - PR / push to `main`: runs the test suite across a Python 3.8 – 3.12 matrix on Linux, macOS, and Windows
  - Tag matching `v*`: builds sdist + wheel via `python -m build` and publishes to PyPI using OIDC Trusted Publishing (no API tokens to manage)
- **`test_view_image.py`** unit tests covering path validation, URL rejection, size cap, format allowlist, and happy-path base64 encoding

### Changed
- Test suite converted from script-style to standard `unittest` style for clean integration with CI test discovery

### Fixed
- `TypeError: unsupported operand type(s) for |: 'type' and 'type'` on Python 3.8 / 3.9 — `ToolBase.ok()` annotation changed from `str | dict` to `Any` (PEP 604 union syntax is rejected on those interpreters)

---

## [0.1.21] - 2026-06-04

### Added
- `CHANGELOG.md` at project root following the [Keep a Changelog](https://keepachangelog.com/) format
- `ROADMAP.md` outlining the 3–6 month development direction
- `mangopi-demo.gif` terminal demo, embedded at the top of `README.md`
- `CONTRIBUTING.md` promoted to the project root for higher visibility

### Changed
- `README.md` opens with the demo animation banner
- `CONTRIBUTING.md` relocated from `docs/` to the repository root

---

## [0.1.20] - 2026-06-04

### Added
- More unit tests covering memory manager, system prompt, and tool execution

### Changed
- Refined memory API and persistence layout under `.mangocli/memory/`
- Updated `README.md` and `index.html` landing page

---

## [0.1.19] - 2026-06-03

### Added
- More unit tests covering compaction, safety, and tool lifecycle
- Stronger Chinese-language resume keywords for `/g` (Goal Mode) — `继续`, `继续执行`, `next`, `resume`, `continue`

### Changed
- `/g` / `/goal` Goal Mode strengthened with clearer plan / step / show / finish semantics
- System prompt simplified and rebalanced
- `README.md` and `index.html` updated

---

## [0.1.18] - 2026-05-29

### Added
- Memory system foundation: `append_memory` and `search_memory` tools, Markdown files under `.mangocli/memory/`
- Compact rules registry for tunable per-content-type compression

### Changed
- Context compression made more flexible via `COMPACT_RULES` configuration
- `ContextManager` rewired to use the new rules across all three compact tiers

---

## [0.1.17] - 2026-05-28

### Added
- Directory-aware output filtering in `bash` tool for `find` / `tree` / `ls -R` / `du` / `fd` / `rg` commands
- Hard output line cap (1000 lines by default) for any single `bash` invocation
- `EditTool` unified-diff preview before applying changes

### Changed
- `EditTool` now shows diff and confirmation for safer in-place edits
- Bash output pipeline: command → directory filter → line limit

### Security
- Output filtering reduces the risk of accidentally leaking large directory trees into the LLM context

---

## [0.1.16] - 2026-05-27

### Added
- Goal Mode: `/g` / `/goal <query>` command for autonomous plan → execute → verify → iterate workflows
- `GoalTool` with `plan` / `step` / `show` / `finish` actions
- Human checkpoint between Goal Mode steps

### Changed
- `agent_loop` extracted out of `main()` for cleaner separation of concerns
- Updated `README.md` and `index.html` to document Goal Mode

---

## [0.1.15] - 2026-05-25

### Changed
- **Major refactor of the context compression system.** Replaced the previous single-tier compact with a three-tier pipeline:
  - `micro_compact` — head/tail truncation of individual tool outputs and long assistant messages
  - `session_memory_compact` — force-compact old turns, retain the last 10 turns in full
  - `compact_conversation` — drop-while-overflow, strip oldest turns first, then trim recent turns
- `ContextManager.prepare_for_api()` is now the single entry point that runs compact before every model call
- `auto_compact_threshold` set to 80% of `MANGO_MAX_CONTEXT`

### Added
- Manual `/c` / `/compact` command triggers `full_compact` (LLM-driven structured summary)

---

## [0.1.13] - 2026-05-21

### Fixed
- `attempt_completion` was being output twice in some sessions — now rendered exactly once

### Added
- `ToolBase.ok()` and `ToolBase.fail()` helpers for clean tool execution status checking

---

## [0.1.12] - 2026-05-20

### Changed
- **Refactored the Tool system** for greater flexibility:
  - Unified `ToolBase` with `schema` / `confirm` / `before` / `after` / `preview` hooks
  - Tools now expose a consistent `preview()` for `Printer.tool_call` rendering
  - Cleaner separation between tool definition and execution

---

## [0.1.11] - 2026-05-19

### Changed
- `Printer` now renders `thinking` (reasoning content) and `output` (final answer) with distinct color styles
- `attempt_completion` tool output is no longer truncated — full result is rendered

---

## [0.1.10] - 2026-05-19

### Added
- **Skill system**: discover and load `SKILL.md` workflows from `~/.mangocli/skills/` and `<project>/.mangocli/skills/`
- New `use_skill` tool
- Completed `full_compact` implementation (LLM-driven structured summary) — previously a stub

### Changed
- Minor UI polish around spinner and tool result rendering

---

## [0.1.9] - 2026-05-17

### Added
- **Minimax provider** (`MiniMaxProvider`) for OpenAI-compatible models that use `reasoning_split: true` and `reasoning_details`

### Fixed
- `input()` prompt on Unix-like systems could not correctly delete Chinese characters — added `readline` import fallback (Unix only, gracefully skipped on Windows)

---

## [0.1.8] - 2026-05-15

### Added
- New `builtin_rules` section in `SystemPrompt` (think before coding, minimum code, surgical changes, verify before completion)

### Changed
- `ContextManager.estimated_tokens` reworked for more accurate token accounting

### Fixed
- Runtime exception when running on Python 3.8 — installation now explicitly supports 3.8 / 3.9 / 3.10 / 3.11 / 3.12

---

## [0.1.7] - 2026-05-14

### Added
- **Internationalization (i18n)** — `MANGO_LANG=en|zh` switches UI text and CLI help between English and Chinese

### Changed
- `chat_completion` timeout / retry exception handling improved
- Updated `index.html` landing page

---

## [0.1.6] - 2026-05-13

### Changed
- `Current date` moved from system prompt into a per-turn user message to improve LLM prompt cache hit rate
- `Printer` now shows more lines in the `tool_call` preview before truncation

---

## [0.1.5] - 2026-05-13

> Patch release following 0.1.4. No user-facing change note preserved.

---

## [0.1.4] - 2026-05-13

### Changed
- Release process optimized: `deploy.sh` now auto-extracts `__version__` from `mangopi_cli.py`
- `pyproject.toml` cleaned up to match the publish pipeline

### Fixed
- `twine upload` failure when version string contained unintended whitespace

---

## [0.1.1] – [0.1.3] - 2026-05-12

> **Initial releases** published on the same day as the project rename from `mangocli` to `mangopi-cli`. Individual change notes are not preserved in the git log.

### Milestones in this batch

- **Project rename** `mangocli` → `mangopi-cli`
- **`pyproject.toml`** added, with `pip install -e .` workflow established
- **`deploy.sh`** added: clean → uninstall → `python -m build` → install → `twine upload`
- **`index.html`** landing page added (single-file 67KB marketing page)
- **SystemPrompt** layered prompt system introduced (base / safety / rules / tools / env)
- **Provider abstraction** (`BaseProvider` + `OpenAIProvider` + `DeepSeekProvider`) introduced — sets the stage for later `MinimaxProvider` in 0.1.9
- **UI enhancements** — `Printer` color system refined, compact-status display added

---

## Links

- PyPI: https://pypi.org/project/mangopi-cli/
- Repository: https://github.com/w4n9H/mangopi-cli
- Author: moofs (https://github.com/w4n9H)
