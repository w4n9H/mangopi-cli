# Changelog

All notable changes to Mangopi CLI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Note:** Versions `0.1.1` through `0.1.3` were published on the same day as the project rename
> from `mangocli` to `mangopi-cli`. Individual commit notes for these three releases are not
> preserved, so they are grouped below as a single "Initial releases" entry.

---

## [0.1.49] - 2026-08-17

### Changed
- **Per-preset extension model** — single entry `MANGO_PRESET=<name>`: `~/.mangocli/presets/<name>/conf.py` (total config: `keep_tools` whitelist / `unload_sources`) + `extensions/` (tools / prompt_sections / entry_points / event hooks); without it the CLI runs pure 8 built-in tools; banner shows the active preset and tool count (e.g. `minimal[8 tool]`)
- **Reversible registration & event bus** — `unload_source()` / `reload_source()` per-file rollback (same-name conflicts never remove later registrations); `on()`/`emit()` bus with `tool:before|after|error` plus session-level `agent:user_input|assistant|compact|end`
- **Core slimmed to 8 tools** — `web_search` / `view_image` moved to extensions (lazy-import contract); `read` no longer auto-routes images (1910 lines)

### Removed
- `MANGO_TRACE` (replaced by the `trace.py` extension), `MANGO_EXTENSIONS_DIR` and `MANGO_PROFILE` (unified under `MANGO_PRESET`)

### Added
- Preset `keep_tools` whitelist with reversible `__preset__` slot; 9 shipped extensions (`acp` / `web_search` / `view_image` / `clipboard` / `git_status` / `audit` / `debug` / `ratelimit` / `trace`); 431 tests

---

## [0.1.48] - 2026-08-13

### Changed
- **Extension system upgrade (three-channel contract)** — `ExtensionRegistry` singleton (replaces `_load_extensions`) harvests `tools`, `prompt_sections` and `entry_points` from `~/.mangocli/extensions/*.py` in one scan; `MANGO_EXTENSIONS_DIR` env var overrides the extensions directory; `prompt_sections` inject into SystemPrompt (same-name sections override defaults, new names append after `environment`); `--acp` dispatches to `entry_points["acp"]` when present; reload semantics (re-scan clears previous state); import-time contract documented (top-level import only, lazy imports inside function bodies)
- **Tool guidance** — `ToolBase.guidance` attribute; `tool_guidance` prompt section now assembled dynamically from registered tools (built-in + extension unified), closing sentence (`attempt_completion`) stably sorted last

### Removed
- **ACP server from core** — `AcpError`/`_prompt_text`/`AcpServer`/`acp_main` (~340 lines) moved out of the single file; core `--acp` now errors with an install hint when the extension is missing (Printer emitter/permission hooks kept)

### Added
- **Shipped extensions** (`examples/extensions/`, enabled by copy/symlink or `MANGO_EXTENSIONS_DIR`) — `acp.py` (ACP v1 agent server, ~380 lines), `clipboard.py` (read/write system clipboard, write requires confirmation; macOS/Linux), `git_status.py` (read-only git status/log/diff summaries); bilingual directory README with full three-channel contract
- **Tests** — 398 total (was 370): extension registry channels (8), prompt-section injection & dynamic tool guidance (6), import-time loading via subprocess (2), clipboard (8), git_status (6); user-extension isolation hardening for schema/system-prompt count tests

---

## [0.1.47] - 2026-08-12

### Removed
- **`loop_engine` + PocketFlow Lite** — Loop Engineering (CLI `loop` subcommand, `/loop` `/goal` REPL commands, `--max-iter`/`--task-id`/`--push`/`--dry-run`/`--fast`/`--wish`/`--only-dev` flags) removed along with the embedded Step/Pipeline framework and their tests; `agent_loop` trace `mode` fixed to `"chat"`, `loops_dir` dropped
- **Docs archive** — knowledge and core code archived in `docs/loop-engineering.md` & `docs/pocketflow-lite.md` (bilingual); ROADMAP Loop Engineering section marked removed/archived; README and landing page (`index.html`) cleaned of loop references (routing merged into feature cards, version v0.1.47, tool count 13 → 10)

---

## [0.1.46] - 2026-08-11

### Added
- **Session switching (CLI)** — `/s` lists sessions, `/s <name>` switches or creates; current session persisted in `.current` and auto-restored on restart (`session.json` default unchanged, zero migration)
- **Session switching (ACP)** — `session/list` + `session/load` with full history replay (`session/update` notifications), `loadSession: true` capability; deterministic sid naming (`sess_acp_*`) survives agent restarts; ACP only exposes its own `acp_*` sessions

---

## [0.1.45] - 2026-08-06

### Added
- **Extension system** — custom tools via `~/.mangocli/extensions/*.py`, auto-merged into `TOOLS` (extension wins on name conflict), broken extensions isolated; example in `examples/extensions/hello.py`
- **AGENT.md support** — user rules read `.mangocli/AGENT.md` (takes precedence) alongside `.mangocli/MANGO.md`

### Fixed
- **ACP stop button** — `session/cancel` now actually stops the turn (agent_loop checks the cancel flag between LLM calls / tools); `RequestPermissionOutcome::Cancelled` handled correctly

---

## [0.1.44] - 2026-08-05

### Added
- **ACP (Agent Client Protocol) v1 server** — `--acp` runs mangopi as a stdio JSON-RPC agent, connectable from Zed / JetBrains / codecompanion.nvim etc.: `initialize` (capability negotiation), `session/new` / `session/prompt` / `session/cancel`, `session/update` notifications (`agent_message_chunk`, `agent_thought_chunk`, `tool_call`, `tool_call_update`, `usage_update`), and the `session/request_permission` approval flow; tools still execute locally, one `session/prompt` = one turn; 15 tests in `test/test_acp.py`

### Removed
- **`--output jsonl`** — structured event output mode for `loop` (Printer jsonl branches, `_output_event` event chain)
- **Sparse Loop / MailBox collective memory** — `--sparse`, `MailBox` class, `mailbox_post`/`mailbox_read`/`mailbox_check` tools, `_mailbox_guidance` prompt injection; `test/test_mailbox.py` removed

### Changed
- **Printer native extension points** — `mode` ("acp"), `emitter`, `permission_handler` replace the previous runtime monkey-patching of console methods
- **Docs synced** — README / ROADMAP / index.html updated for the ACP server and removed features

---

## [0.1.43] - 2026-08-03

### Changed
- **Declarative `Agent` refactor** — the 7 role classes are replaced by one parameterized `Agent` (`role`, `phase`, `prompt_fn`, `fresh_role`, `extract`, `route`); prompt builders unified to a `(ctx) -> str` signature; routing extracted into standalone `_route_*` functions
- **24-bit Catppuccin Mocha color system** — ANSI 16-color palette replaced with truecolor role-mapped colors (`BLUE`/`CYAN`/`GREEN`/`YELLOW`/`RED`/`GREY`/`ACCENT`/`SOFT`) via new `_fg()` converter and a slimmed `MOCHA` palette (8 active roles only); `ORANGE` renamed to `ACCENT`
- **Research mode guard** — starting research mode now requires `MANGO_SEARCH_API_KEY`, with a clear error otherwise
- **Terminal width detection** — `os.get_terminal_size()` replaced with `shutil.get_terminal_size()` for portability when stdout is redirected

---

## [0.1.42] - 2026-07-30

### Added
- **Multi-hit keyword aggregation** — `_keyword_score()` now collects all matched frameworks and computes a weighted score (`max×70% + avg×30%`) instead of returning on first hit; multi-framework queries (e.g. "优化 bug 并重构 design") now correctly score higher
- **FlashThinking.KEYWORDS expansion** — ~63 new keywords across all 5 frameworks (debug +12, design +8, explain +10, optimize +20, implement +13); greatly reduces cold-miss rate for common coding scenarios

### Changed
- **`FlashThinking.match( )`** — removed unused `tool_pattern` parameter and phase-detection logic (`PHASES`, `PHASE_MAP`); simplified `self.frameworks` initialisation; added `match_all( )` helper
- **`RoutedProvider._FRAMEWORK_SCORE`** — stripped unreferenced frameworks (`reevaluate`, `investigate`, `verify`)
- **3 test expectations** updated for improved scoring accuracy; **7 new Chinese-first multi-framework tests** added

---

## [0.1.41] - 2026-07-29

### Added
- **Call Trace System** — `MANGO_TRACE=on` enables structured trace capture; per-run JSON event files written to `.mangocli/traces/run_*.json`
- **Trace events** — 6 event types (`user_input`, `assistant`, `tool_call`, `tool_result`, `compact`, `end`) captured at hook points in `agent_loop()` and `ContextManager`
- **`eval/eval_analyzer.py`** — offline analyzer that reads trace files and produces aggregate/per-run reports (table or JSON)
- **Compact event tracking** — compression logged to trace when context reduction occurs (`prepare_for_api`)

### Changed
- **`run_tool()` return type** — unified to always return `{"success": bool, "content": ...}` instead of mixed string/dict; updated consumer in `agent_loop()` and 3 `test_view_image` tests accordingly

---

## [0.1.40] - 2026-07-24

### Added
- **MailBox** — file-based async messaging system for long-running sparse tasks, multi-agent coordination, and human-in-the-loop collaboration
- **Mailbox tools** — `mailbox_post`, `mailbox_read`, `mailbox_check` (3 tools, zero deps)
- **Sparse Loop (`--sparse HANDLE`)** — extends `loop_engine` with MailBox collective memory; agents share a persistent group thread across sessions; same `--task-id` resumes history across days
- **`--only-dev` mode** — `loop_engine` pipeline: DevAgent → Push/Succeed, no test/review
- **Prompt injection** — `_mailbox_guidance()` appended to all agent prompts when `--sparse` is set; agents follow: Start → `mailbox_read`, Claim → `mailbox_post`, Update → `mailbox_post [State]`, Finish → `mailbox_post [Result]`

### Changed
- **`loop_engine`** — accepts `sparse` and `only_dev` parameters; injects `gid`/`sparse` into shared ctx
- **`_dev_prompt`, `_design_prompt`, `_review_prompt`, `_test_prompt`, `_research_prompt`** — accept `sparse`, `gid` params for conditional guidance
- **README / ROADMAP / index.html** — document Sparse Loop and MailBox features
- **`test/test_mailbox.py`** — 39 tests covering MailBox class and 3 mailbox tools

---

## [0.1.39] - 2026-07-15

### Fixed
- **`verify_result` key** — `ReviewAgent` now writes `ctx["verify_result"]` instead of `ctx["review_fail"]`, fixing review failures not reaching UpdaterAgent.

### Changed
- **Prompt improvements** — `_test_prompt` adds project inspection hints; `_review_prompt` adds architecture-level evaluation criteria; `_dev_prompt` / `_updater_prompt` remove outdated "Verifier" references.

---

## [0.1.38] - 2026-07-15

### Fixed
- **`test/test_loop_engine.py`** - not set `MANGO_SEARCH_API_KEY`

---

## [0.1.37] - 2026-07-15

### Fixed
- **`--wish` mode** — `ResearchAgent.post` returns `None` instead of `"ok"`, fixing premature pipeline exit after research.

### Added
- **`test/test_loop_engine.py`** — 11 unit tests covering success/failure/fast/wish/error paths.

### Changed
- **Resource cleanup** — 4 unclosed file handles fixed (`MANGO.md`, skill scripts, edit tool, grep tool).

---

## [0.1.36] - 2026-07-15

### Added
- **`--wish` mode** — prepend ResearchAgent with `web_search` before normal pipeline.
- **ResearchAgent** — independent ctx, `_research_prompt`, checks `MANGO_SEARCH_API_KEY`.
- **Memo skill** — `examples/skills/memo/` for long-term memory persistence.

### Changed
- **Research → Design data flow** — `ctx["research"]` injected into `_design_prompt`.
- **Doc sync** — ROADMAP, README, index.html updated to reflect current pipeline and modes.

---

## [0.1.35] - 2026-07-14

### Added
- **`loop --fast`** — skip design/review, only dev → test → push.
- **`loop --dry-run`** — print pipeline topology and exit.
- **ReviewAgent** — full agent with independent ctx, inspects changes via `_review_prompt`.

### Changed
- **Prompt split** — `_implementer_prompt` → `_design_prompt` + `_dev_prompt`; `_verifier_prompt` → `_review_prompt` + `_test_prompt`.
- **ReviewAgent** — from stub to real agent loop with `VERIFY: PASS/FAIL` routing.
- **`_Edge` operator precedence fix** — split chained `-`/`>>` into separate lines.

---

## [0.1.34] - 2026-07-08

### Removed
- **FlashExtServer and Flash-thinking framework** — all related code removed.
- **Old `loop_engine`** — replaced by Pipeline-based version.

### Added
- **PocketFlow Lite** — `Step` + `Pipeline` graph scheduler with DSL (`>>`, `-`).
- **`loop --push`** — commit verified changes on PASS.
- **`SucceedStep`** — explicit success endpoint in Pipeline.

### Changed
- **`loop_engine` rewritten on Pipeline** — `PlanAgent` → `DevAgent` → `ReviewAgent` → `TestAgent` → `SucceedStep` / `UpdaterAgent`.
- **`_get_loop_ctx` extracted** to module-level, shared by all agents.

---

## [0.1.33] - 2026-07-06

### Added
- **YOLO mode** — `MANGO_YOLO` env var / `--yolo` flag to skip edit/bash confirmations. Tagged in startup banner.
- **Push phase** — `loop_engine` now commits verified changes via conventional commit messages.

### Changed
- **loop_engine refactor** — agent prompts extracted to module-level functions; loop body reduced from ~80 to ~25 lines.

---

## [0.1.32] - 2026-07-03

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
