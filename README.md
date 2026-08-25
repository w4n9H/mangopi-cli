# Mangopi CLI

<p>
<a href="https://github.com/w4n9H/mangopi-cli/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/w4n9H/mangopi-cli/ci.yml?branch=main&label=CI" alt="CI"></a>
<a href="https://pypi.org/project/mangopi-cli/"><img src="https://img.shields.io/pypi/v/mangopi-cli" alt="PyPI"></a>
<a href="https://pypi.org/project/mangopi-cli/"><img src="https://img.shields.io/pypi/pyversions/mangopi-cli" alt="Python"></a>
<a href="https://github.com/w4n9H/mangopi-cli/blob/main/LICENSE"><img src="https://img.shields.io/github/license/w4n9H/mangopi-cli" alt="License"></a>
<br>
<a href="https://github.com/w4n9H/mangopi-cli/stargazers"><img src="https://img.shields.io/github/stars/w4n9H/mangopi-cli?style=social" alt="Stars"></a>
<a href="https://github.com/w4n9H/mangopi-cli/releases"><img src="https://img.shields.io/github/v/release/w4n9H/mangopi-cli?include_prereleases" alt="Release"></a>
<a href="https://pepy.tech/project/mangopi-cli"><img src="https://img.shields.io/pepy/dt/mangopi-cli" alt="Downloads"></a>
<a href="https://github.com/w4n9H/mangopi-cli/commits/main"><img src="https://img.shields.io/github/last-commit/w4n9H/mangopi-cli" alt="Last commit"></a>
</p>

![Mangopi CLI demo](./mangopi-demo.gif)

> Single-file, zero-dependency AI coding assistant for the terminal.

Mangopi CLI is a local-first autonomous coding agent built with only the Python standard library.

No frameworks.
No Electron.
No Docker.
No dependency hell.

Just one fast, hackable Python file.

---

# Design Philosophy

**Seeking a perfect balance between code size, complexity, and the functionality & effectiveness of the agent.**

Mangopi CLI intentionally keeps the runtime extremely small.

Why?

* easier to audit 
* easier to hack 
* easier to fork 
* easier to understand 
* easier to run locally

The project avoids unnecessary abstractions, frameworks, and dependencies whenever possible.

---

# Why Mangopi CLI?

| Mangopi CLI                  | Typical AI Agent Frameworks  |
|------------------------------|------------------------------|
| Single-file runtime          | Large multi-module codebases |
| Python standard library only | Heavy dependency trees       |
| Instant startup              | Slow boot time               |
| Fully hackable               | Framework-heavy              |
| Local-first                  | Cloud-oriented               |
| Minimal abstractions         | Over-engineered              |
| Easy to fork                 | Hard to customize            |


---


# Ideal For

* developers who prefer terminal workflows 
* users who dislike heavyweight AI frameworks 
* hackers and tinkerers 
* local-first enthusiasts 
* people who want full runtime control 
* building custom coding agents

---

# Features

* Single-file architecture
* Python standard library only
* Instant startup speed
* Local-first workflow design
* ACP agent server (`--acp`) — Agent Client Protocol v1 over stdio, connectable from Zed / JetBrains etc.
* Multimodal support (image reading via `view_image` extension)
* Web search via Bocha AI Search (`web_search` extension)
* Context-aware conversation management
* Automatic context compacting
* OpenAI-compatible API support
* Built-in file and shell tools
* Persistent local sessions
* Skill system support (`SKILL.md`)
* Extension system — per-preset dirs: `~/.mangocli/presets/<name>/` (`conf.py` + `extensions/`), activated via `MANGO_PRESET`
* Safe shell execution checks
* Fully hackable and easy to extend
* Large-context optimized runtime

---

# Installation

## From PyPI

```bash
pip install mangopi-cli
```

Start Mangopi CLI:

```bash
mangopi-cli
```

---

## From Source

```bash
git clone git@github.com:w4n9H/mangopi-cli.git
cd mangopi-cli
python mangopi_cli.py
```

---

# Configuration

Required:

```bash
export MANGO_KEY="your_api_key"
```

Recommended:

```bash
export MANGO_API_URL="https://api.deepseek.com"
export MANGO_MODEL="deepseek-v4-flash"
```

Optional:

```bash
export MANGO_MAX_CONTEXT=1000000   # default 1,000,000 tokens
export MANGO_LANG=en               # en (default) | zh — controls UI text and CLI help language
```

---


---

# Supported Providers

Mangopi CLI supports:

* DeepSeek
* OpenAI-compatible APIs
* MiniMax
* Custom compatible endpoints

Example:

```bash
export MANGO_API_URL="https://api.openai.com/v1"
export MANGO_MODEL="gpt-4o-mini"
```

---

# Usage

Start the CLI:

```bash
mangopi-cli
```

or:

```bash
python mangopi_cli.py
```

---

# Built-in Commands

| Command     | Aliases         | Description                                              |
|-------------|-----------------|----------------------------------------------------------|
| `/q`        | `/quit`         | Quit                                                     |
| `/n`        | `/new`          | Start a new session (old session is auto-backed-up)      |
| `/c`        | `/compact`      | Manually trigger full conversation compact               |
| `/h`        | `/help`         | Show built-in command help                               |

| Flag | Description |
|------|-------------|
| `--acp` | Run as ACP (Agent Client Protocol) v1 agent server over stdio (JSON-RPC) |

---

## ACP Agent Server (`--acp`)

Run mangopi as an **Agent Client Protocol v1** agent over stdio — a resident JSON-RPC server that ACP-capable editors (Zed, JetBrains, codecompanion.nvim, etc.) can launch as a subprocess:

```bash
mangopi-cli --acp
```

The client drives the conversation via `session/new` + `session/prompt` messages; mangopi executes tools locally, streams progress via `session/update` notifications, and asks for permission through `session/request_permission` (rendered as a client-side prompt). One `session/prompt` = one turn; `session/cancel` ends the current turn.

# Built-in Tools

| Tool                 | Description                                                       |
|----------------------|-------------------------------------------------------------------|
| `read`               | Read a text file (use `view_image` extension for images)          |
| `write`              | Write or overwrite a file                                       |
| `edit`               | Replace an exact string in a file, with unified-diff preview    |
| `search`             | Search files using glob patterns, sorted by mtime               |
| `grep`               | Recursive regex content search                                  |
| `bash`               | Execute a shell command (60s timeout, output filtered)          |
| `use_skill`          | Load an installed `SKILL.md` with its scripts/references        |
| `attempt_completion` | Final step — present the result to the user                     |

`web_search` / `view_image` are shipped as optional extensions (`examples/extensions/`) since v0.1.49.

Mangopi CLI can autonomously inspect files, modify code, search projects, and execute shell commands.

---

# Skill System

Mangopi CLI supports reusable workflow skills.

Example structure:

```text
~/.mangocli/skills/python_backend/

├── SKILL.md
├── scripts/
└── references/
```

Example `SKILL.md`:

```md
---
description: Python backend workflow
tags: ["python", "backend"]
---

Use pytest for tests.
Prefer small functions.
```

The model can automatically discover and load relevant skills during execution.

---

# Extension System

Mangopi CLI is extensible via per-preset directories: each preset `<name>` lives at `~/.mangocli/presets/<name>/` with a `conf.py` (total config: `keep_tools` whitelist, `unload_sources`) and an `extensions/` folder holding extension files — set `MANGO_PRESET=<name>` to activate it. Without `MANGO_PRESET` the CLI runs pure built-in tools (no extensions). Extensions shipped with the repo live in `examples/extensions/`; enable them by copying/symlinking into `~/.mangocli/presets/<name>/extensions/`. Each file may export any combination of three channels (all optional):

| Channel | Export | Effect |
|---|---|---|
| Tools | `tools` | `ToolBase` instances join the built-in registry — visible in the LLM tool schema, dispatched through `run_tool`, available in ACP mode; same-name tools override built-ins (extension wins) |
| Prompt sections | `prompt_sections` | `(name, content)` pairs injected into the system prompt: a name matching a default section (`base_intro` / `safety` / `builtin_rules` / `tool_guidance` / `skills_guidance` / `memory` / `environment`) overrides it (enhancement); a new name appends after `environment` |
| Entry points | `entry_points` | `name -> Callable[[], int]` registry (same-name: first file in scan order wins); the built-in `--acp` flag dispatches to `entry_points["acp"]` when present |

Contract: extension top-level code may `import` but must not access `mangopi_cli` attributes — the scan runs during module import, when the module is only half-initialized (importing `ToolBase` at top level is fine; everything else goes inside function bodies). Extensions run arbitrary Python code, so only install from trusted sources. A broken extension logs a diagnostic and is skipped without affecting others.

### Tools channel

```python
# ~/.mangocli/presets/<name>/extensions/hello.py
from mangopi_cli import ToolBase

class HelloTool(ToolBase):
    name = "hello"
    description = "Say hello"
    params = {"name": {"type": "string", "description": "Who to greet"}}

    def run(self, args):
        return self.ok("Hello, %s!" % args.get("name", "world"))

tools = [HelloTool()]
```

### Prompt sections channel

```python
# ~/.mangocli/presets/<name>/extensions/prompt_sections.py
prompt_sections = [
    # Same name as a default section ("safety") → overrides it (enhancement)
    ("safety",
     "## Safety\n\n"
     "Destructive commands and any access outside the project root require explicit user confirmation.\n"
     "Never delete data without asking first.\n"),
    # New name → appended after all default sections
    ("project_note",
     "## Project Note\n\n"
     "This project is managed with mangopi-cli. Keep commits small and focused.\n"),
]
```

### Entry points channel

```python
# ~/.mangocli/presets/<name>/extensions/entry_points.py
import mangopi_cli  # top-level: import only, no attribute access (import-time scan)

def hello_serve() -> int:
    # Lazy import: the module is fully initialized by the time this runs
    from mangopi_cli import __version__
    print(f"hello_serve: mangopi-cli v{__version__} entry point invoked")
    return 0

entry_points = {"hello": hello_serve}
```

### Presets (total config)

Each preset `<name>` is a directory `~/.mangocli/presets/<name>/` with an optional `conf.py` (total config applied at startup) and the `extensions/` folder above. Set `MANGO_PRESET=<name>` to activate; **without it the CLI runs pure built-in tools (no extensions)**. The banner shows the active preset and tool count, e.g. `... | minimal[2 tool]`.

```python
# ~/.mangocli/presets/minimal/conf.py
preset = {
    "name": "minimal",
    "description": "Benchmark mode: bash + edit only, one-line system prompt",
    "keep_tools": ["bash", "edit"],
    # optional: "unload_sources": ["clipboard.py", "git_status.py"],
    # optional: prompt overrides (v0.1.50 mode system)
    "prompt_overrides": {
        "base": "You are a helpful software engineer assistant.",  # replaces the base_intro section
        "clear_sections": ["safety", "builtin_rules", "tool_guidance",  # removes sections
                           "skills_guidance", "memory", "environment"],
        # "append_sections": [{"name": "custom", "content": "..."}],  # appends sections
    },
}
```

* `keep_tools` — whitelist: `TOOLS` keeps only the listed tools (built-in + extensions unified); the inverse is registered under the `__preset__` slot, `unload_source("__preset__")` restores
* `unload_sources` — optional: reversibly unload extension registrations (three channels), combinable with `keep_tools`
* `prompt_overrides` — optional: `base` replaces the `base_intro` section, `clear_sections` removes sections, `append_sections` appends new ones (see Run Modes below)
* Applying a preset emits the `preset:applied` event (extensions such as `trace.py` can listen)

## Run Modes

Mangopi CLI ships three run-mode presets in `examples/presets/` (copy a directory into `~/.mangocli/presets/` to enable). Modes are a preset-level combination of tool whitelist and system-prompt overrides, modeled after DeepSeek Harness:

| Mode | Tools | System Prompt | Use case |
|---|---|---|---|
| `standard` | 8 core tools | Full layered assembly | Daily development (same as no preset) |
| `minimal` | `bash` + `edit` only | One line | Model benchmark / capability baseline |
| `codemode` | `run_code` + `attempt_completion` | Full + SDK declarations | Batch operations with fewer round-trips |

```bash
export MANGO_PRESET=minimal   # or: standard / codemode
mangopi-cli
```

* `standard` — the default behavior made explicit: 8 core tools and the complete layered system prompt.
* `minimal` — strips every peripheral enhancement (safety rules, tool guidance, skills, memory, environment) to purely measure the model's autonomous planning, code editing and terminal capability. Mirrors DeepSeek Harness minimal mode (`bash` + editor only, one-line persona).
* `codemode` — Programmatic Tool Calling (PTC): `run_code` is the only directly callable file/shell tool; the six tools (`read`/`write`/`edit`/`search`/`grep`/`bash`) are reached from inside the program — the model writes one Python script orchestrating multiple tool calls in a single execution. Intermediate tool results stay out of the conversation — only `print` output flows back, cutting token usage and model round-trips. The code-only instruction and SDK declarations are declared in `examples/presets/codemode/conf.py` via `prompt_overrides.append_sections`.

**Security note**: `run_code` executes in a restricted scope — whitelist builtins (no `__import__`/`open`/`eval`/`exec`/`globals`), only six tool APIs bound (`read`/`write`/`edit`/`search`/`grep`/`bash`), a SIGALRM timeout (30s, main thread only), and output truncation. Tool calls inside the script inherit the core safety checks (path sandbox, dangerous-command detection). This is a reasonable guardrail for model-generated scripts, not a hard sandbox.

### Shipped extensions

The repo ships 15 optional extensions in `examples/extensions/` (copy/symlink into `~/.mangocli/presets/<name>/extensions/` to enable; without `MANGO_PRESET`, `~/.mangocli/extensions/`):

| File | Function |
|---|---|
| `acp.py` | ACP v1 agent server over stdio (`mangopi-cli --acp` dispatches to `entry_points["acp"]`) |
| `ask_user.py` | Structured multi-choice questions to clarify requirements |
| `clipboard.py` | System clipboard read/write (macOS / Linux) |
| `debug.py` | Per-call args/results debug prints (event bus) |
| `git_status.py` | Read-only git status/log/diff summaries |
| `memory.py` | Long-term memory: AGENT.md / MANGO.md + per-day journals, auto-injected into the prompt |
| `multi_edit.py` | Apply N Edit operations in one call with best-effort rollback |
| `plan_mode.py` | Plan-then-execute state machine (read-only tool subset while active) |
| `ratelimit.py` | Sliding-window rate warning (event bus, warn only) |
| `run_code.py` | Code Mode / PTC tool: batch tool orchestration in one execution (used by the `codemode` preset) |
| `task_tracker.py` | In-session task tracking (create/list/update/get/delete), auto-injected into the prompt |
| `trace.py` | Session event stream to `~/.mangocli/traces/run_*.json` (replaces core MANGO_TRACE; includes tool errors) |
| `view_image.py` | Local image into vision context |
| `web_fetch.py` | Fetch a URL's content into context (http/https only) |
| `web_search.py` | Live web search via Bocha AI Search (`MANGO_SEARCH_API_KEY`) |

---

# Session Persistence

Sessions are stored locally:

```text
.mangocli/session/session.json
```

Mangopi CLI automatically:

* restores previous sessions
* preserves important context
* compacts old conversations
* manages long-running workflows

---

# Context Compacting

Mangopi CLI uses a **three-tier compacting strategy** that triggers automatically once context exceeds 80% of `MANGO_MAX_CONTEXT`:

| Tier                  | Strategy              | Scope                                                   |
|-----------------------|-----------------------|---------------------------------------------------------|
| `micro_compact`       | Head/tail truncation  | Individual tool outputs and long assistant messages     |
| `session_memory_compact` | Force-compact old turns | Drops the oldest turns, keeps last 10 turns in full |
| `compact_conversation`   | Drop-while-overflow  | Strips oldest turns first, then trims recent turns     |
| `full_compact`        | LLM-driven summary    | Replaces the whole conversation with a structured recap (manual `/c`) |

The compact pipeline is invoked by `ContextManager.prepare_for_api()` before every model call, so long-running autonomous workflows stay within the configured context budget without manual intervention.

---

# Safety

Mangopi CLI enforces safety at two layers:

**Dangerous command detection** — the following patterns require explicit `y/n` confirmation before execution:

* File deletion — `rm -rf`, `unlink`
* Disk / partition — `mkfs`, `fdisk`, `parted`, `dd if=... of=...`
* Permission changes — `chmod 777` (and similar `*7*7*` modes), `chown ... root`
* Privilege escalation — `sudo rm`, `su -`, `su root`
* Dangerous process control — `kill -9 1`, `killall -9`, `pkill -9`
* Environment tampering — `export PATH=...`, `unset PATH`, writes to `/etc/`
* History / log clearing — `history -c`, `> /dev/null 2>&1`

**Path sandbox** — `write` and `edit` resolve the target path with `realpath` and reject any file outside the project root. Operating on a directory path (rather than a file) is also rejected. This prevents the model from escaping the working directory.

---

# Architecture

Core components:

| Component         | Responsibility                                                          |
|-------------------|-------------------------------------------------------------------------|
| `Printer`         | Terminal UI rendering (spinner, diff, tool call/result)                 |
| `ContextManager`  | Conversation memory, three-tier compact, session save/restore           |
| `ToolBase`        | Tool framework (schema, confirm, before/after hooks, preview)            |
| `Provider`        | API abstraction (`OpenAIProvider`, `DeepSeekProvider`, `MiniMaxProvider`) |
| `SystemPrompt`    | Layered runtime prompt assembly (base, safety, rules, tools, env)        |
| `SkillManager`    | Discovers and loads `SKILL.md` + scripts/references                      |
| `AcpServer`        | ACP (Agent Client Protocol) v1 server: stdio JSON-RPC dispatch, sessions, permissions |
| `agent_loop`      | Drives the read → think → tool-call → verify loop until the model stops or calls `attempt_completion` |

---

# License

Apache License 2.0

---

---

# Author

Created by moofs.
