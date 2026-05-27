# Mangopi CLI

> A lightweight, zero-dependency AI coding assistant running directly in your terminal.

Mangopi CLI is a local-first AI coding assistant inspired by tools like Claude Code, designed for developers who want a fast, hackable, and minimal runtime experience.

It provides an agentic coding workflow with:

* file editing
* shell execution
* tool calling
* autonomous goal execution
* context-aware conversation management
* automatic context compacting

All with instant startup and no heavyweight framework dependencies.

---

# Features

* Zero dependency (Python standard library only)
* Instant startup speed
* Claude Code–style terminal UX
* OpenAI-compatible API support
* Built-in file and shell tools
* Autonomous Goal Mode
* Automatic context compacting
* Persistent local sessions
* Skill system support (`SKILL.md`)
* Safe shell execution checks
* Fully hackable and easy to extend
* Large-context optimized architecture

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
export MANGO_MAX_CONTEXT=1000000
export MANGO_LANG=zh
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

| Command     | Description                    |
|-------------|--------------------------------|
| `/q`        | Quit                           |
| `/n`        | Start a new session            |
| `/c`        | Compact current session        |
| `/h`        | Show help                      |
| `/g <goal>` | Autonomous goal execution mode |

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

| Tool                 | Description                        |
|----------------------|------------------------------------|
| `read`               | Read files                         |
| `write`              | Write or overwrite files           |
| `edit`               | Replace exact strings in files     |
| `search`             | Search files using glob patterns   |
| `grep`               | Regex search through project files |
| `bash`               | Execute shell commands             |
| `use_skill`          | Load installed skills              |
| `attempt_completion` | Finish the current task            |

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

Mangopi CLI includes multiple compacting strategies:

* micro compact
* session memory compact
* conversation compact
* full LLM summary compact

This enables extremely long-running coding sessions while staying within model context limits.

---

# Safety

Dangerous shell commands require confirmation before execution.

Examples include:

* `rm -rf`
* `mkfs`
* `chmod 777`
* `sudo rm`
* destructive system operations

---

# Architecture

Core components:

| Component        | Responsibility                   |
|------------------|----------------------------------|
| `Printer`        | Terminal UI rendering            |
| `ContextManager` | Conversation memory & compacting |
| `ToolBase`       | Tool framework                   |
| `Provider`       | API abstraction layer            |
| `SystemPrompt`   | Runtime prompt assembly          |
| `SkillManager`   | Skill discovery & loading        |

---

# Philosophy

Mangopi CLI focuses on:

* fast startup
* zero dependency
* local-first workflows
* terminal-native AI interaction
* lightweight runtime design
* simplicity over abstraction
* hackability over frameworks

No Electron.
No Docker.
No Redis.
No heavyweight AI frameworks.

Just a fast and hackable AI coding assistant for the terminal.

---

# License

Apache License 2.0

---

# Author

Created by moofs.
