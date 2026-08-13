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
* Smart provider routing with tiered models (high/medium/low)
* Multimodal support (image reading via `view_image`)
* Web search via Bocha AI Search (`web_search` tool)
* Context-aware conversation management
* Automatic context compacting
* OpenAI-compatible API support
* Built-in file and shell tools
* Persistent local sessions
* Skill system support (`SKILL.md`)
* Extension system — auto-discovered custom tools via `~/.mangocli/extensions/*.py`
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



# Smart Provider Routing

Enable multi-model routing with the `MANGO_ROUTING` env var:

```bash
export MANGO_ROUTING=on
```

Define providers in `.mangocli/providers.json` (tiers: low/medium/high):

```json
{
  "providers": [
    {"name": "low",    "url": "https://api.deepseek.com", "model": "deepseek-v4-flash",    "tier": "low",    "api_key": "sk-xxx"},
    {"name": "medium", "url": "https://api.deepseek.com", "model": "deepseek-v4",          "tier": "medium", "api_key": "sk-xxx"},
    {"name": "high",   "url": "https://api.deepseek.com", "model": "deepseek-v4-reasoning", "tier": "high",   "api_key": "sk-xxx"}
  ],
  "routing": {
    "default_tier": "medium",
    "score_thresholds": {"low_max": 3, "medium_max": 7}
  }
}
```

Mangopi CLI auto-selects the appropriate tier based on task complexity — keyword matching + LLM scoring. Each turn uses one model; no mid-loop switching. A sample config is at `providers.json.example`.

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
| `read`               | Read a file or image (png/jpg/gif/webp auto-routed to vision)  |
| `write`              | Write or overwrite a file                                       |
| `edit`               | Replace an exact string in a file, with unified-diff preview    |
| `search`             | Search files using glob patterns, sorted by mtime               |
| `grep`               | Recursive regex content search                                  |
| `bash`               | Execute a shell command (60s timeout, output filtered)          |
| `view_image`         | Load a local image into the model's vision context              |
| `web_search`         | Search the live web via Bocha AI Search API                     |
| `use_skill`          | Load an installed `SKILL.md` with its scripts/references        |
| `attempt_completion` | Final step — present the result to the user                     |

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

Mangopi CLI is extensible via auto-discovered extension files: drop a Python file into `~/.mangocli/extensions/` — or point the `MANGO_EXTENSIONS_DIR` env var at any directory (e.g. a repo-local `extensions/` folder) — and it is loaded at startup. Extensions shipped with the repo live in `examples/extensions/`; enable them by copying/symlinking into `~/.mangocli/extensions/` or setting `MANGO_EXTENSIONS_DIR=examples/extensions`. Each file may export any combination of three channels (all optional):

| Channel | Export | Effect |
|---|---|---|
| Tools | `tools` | `ToolBase` instances join the built-in registry — visible in the LLM tool schema, dispatched through `run_tool`, available in ACP mode; same-name tools override built-ins (extension wins) |
| Prompt sections | `prompt_sections` | `(name, content)` pairs injected into the system prompt: a name matching a default section (`base_intro` / `safety` / `builtin_rules` / `tool_guidance` / `skills_guidance` / `memory` / `environment`) overrides it (enhancement); a new name appends after `environment` |
| Entry points | `entry_points` | `name -> Callable[[], int]` registry (same-name: first file in scan order wins); the built-in `--acp` flag dispatches to `entry_points["acp"]` when present |

Contract: extension top-level code may `import` but must not access `mangopi_cli` attributes — the scan runs during module import, when the module is only half-initialized (importing `ToolBase` at top level is fine; everything else goes inside function bodies). Extensions run arbitrary Python code, so only install from trusted sources. A broken extension logs a diagnostic and is skipped without affecting others.

### Tools channel

```python
# ~/.mangocli/extensions/hello.py
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
# ~/.mangocli/extensions/prompt_sections.py
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
# ~/.mangocli/extensions/entry_points.py
import mangopi_cli  # top-level: import only, no attribute access (import-time scan)

def hello_serve() -> int:
    # Lazy import: the module is fully initialized by the time this runs
    from mangopi_cli import __version__
    print(f"hello_serve: mangopi-cli v{__version__} entry point invoked")
    return 0

entry_points = {"hello": hello_serve}
```

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
