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
* Autonomous goal execution
* Context-aware conversation management
* Automatic context compacting
* Markdown memory system
* OpenAI-compatible API support
* Built-in file and shell tools
* Persistent local sessions
* Skill system support (`SKILL.md`)
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
| `/g <goal>` | `/goal <query>` | Enter Goal mode — plan, execute, verify until completion |

`/g` accepts Chinese resume keywords (`继续`, `继续执行`, `next`, `resume`, `continue`) to resume a paused plan with the same goal text.

---

# Goal Mode

Goal Mode allows Mangopi CLI to autonomously:

* plan
* execute
* verify
* iterate

until the objective is fully completed.

Example:

```bash
/g build a fastapi todo app with tests
```

The agent will continue working until it determines the task is complete.

---

# Built-in Tools

| Tool                 | Description                                                       |
|----------------------|-------------------------------------------------------------------|
| `read`               | Read a file (supports `offset` / `limit`)                         |
| `write`              | Write or overwrite a file                                         |
| `edit`               | Replace an exact string in a file, with unified-diff preview      |
| `search`             | Search files using glob patterns, sorted by mtime                 |
| `grep`               | Recursive regex content search                                    |
| `bash`               | Execute a shell command (60s timeout, output filtered)            |
| `use_skill`          | Load an installed `SKILL.md` with its scripts/references          |
| `search_memory`      | Search long-term markdown memory (multi-keyword, scored)          |
| `append_memory`      | Append a note to today's long-term memory file                    |
| `goal`               | Manage the active goal plan (`plan` / `step` / `show` / `finish`) |
| `attempt_completion` | Final step — present the result to the user                       |

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
| `MemoryManager`   | Long-term markdown memory (append + scored multi-keyword search)        |
| `GoalTool`        | Persistent goal plan (`plan` / `step` / `show` / `finish`) with human checkpoint between steps |
| `agent_loop`      | Drives the read → think → tool-call → verify loop until the model stops or calls `attempt_completion` |

---

# License

Apache License 2.0

---

# Author

Created by moofs.
