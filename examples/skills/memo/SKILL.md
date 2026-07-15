---
name: memo
description: Long-term memory store for the agent. Use proactively to remember user preferences, project decisions, important context, and lessons learned across sessions. Save durable knowledge (a decision, a preference, a fact) instead of chat ephemera. Search before answering questions about prior work. Do NOT save transient things (in-flight calculations, one-off lookups) — use working memory for those. Never create folders; use #tags inside the content for grouping.
---

# memo — Agent Long-term Memory

`memo.sh` is a local-first, plain-text memory store at `~/.nb/home/`.
It persists across sessions, and is **searchable**.

You have two memory tiers:

- **Working memory** (this conversation): scratch space, plans, in-flight
  reasoning. Free to use, lost on session end.
- **Long-term memory** (this skill): durable facts, decisions, preferences.
  Saved explicitly. Persists forever.

This skill is the bridge to long-term memory.

## When to save (write to memo)

Save when the user expresses something **durable**:

- A preference: "I always use vim", "I prefer tabs over spaces"
- A project decision: "We chose PostgreSQL over Mongo"
- A correction: "No, the API is at /v2, not /v1"
- A fact about the user: "They work on mangopi-cli", "Their editor is vim"
- A lesson learned: "Don't auto-commit .env files"
- A meeting outcome: "Q3 OKRs are..."

**Don't save** ephemeral stuff: temporary calculations, current task
state, things in the working set right now.

**Don't ask permission for trivial saves.** A preference is a preference
— saving it should feel as natural as noting it mentally. Only ask
when the user might object (e.g., personal info).

## When to search (read from memo)

**Always search before answering** questions like:

- "What did we decide about X?"
- "What's the convention for Y in this project?"
- "Where did I save Z?"
- "What are my preferences for W?"

If you don't search, you're flying blind across sessions.

## Quick reference

Script: `scripts/memo.sh`

| Intent                | Command                                            |
|-----------------------|----------------------------------------------------|
| Remember a fact       | `memo.sh add "title" --content "fact"`             |
| Remember with tag     | `memo.sh add "title" --content "#tag fact"`        |
| Remember a decision   | `memo.sh add "decided: X" --content "reason: ..."` |
| Remember a preference | `memo.sh add "pref: <topic>" --content "rule"`     |
| Add a todo            | `memo.sh todo "..."`                               |
| List all memories     | `memo.sh ls`                                       |
| List recent           | `memo.sh ls --limit 20`                            |
| Search memory         | `memo.sh search "keyword"`                         |
| Search AND            | `memo.sh search "api" "design"`                    |
| Search OR             | `memo.sh search --or "wifi" "url"`                 |
| Exclude               | `memo.sh search "api" --not "v1"`                  |
| Read one memory       | `memo.sh show 3` or `memo.sh show "title"`         |
| Mark todo done        | `memo.sh do 3`                                     |
| Mark todo open        | `memo.sh undone 3`                                 |
| Forget (delete)       | `memo.sh delete 3 --force`                         |

Help: `memo.sh help` or `memo.sh <command> --help`.

## Defaults

- Storage: `~/.nb/home/` (override with `NB_DIR`)
- File extension: `.md`
- Search: case-insensitive **fixed string** (no regex escaping).
  Use `--regex` for regex mode.

## Agent patterns

**Save a preference the user just stated:**
```bash
./scripts/memo.sh add "pref: editor" --content "user uses vim, not nano"
```

**Save a project decision:**
```bash
./scripts/memo.sh add "decided: API version" --content "v2 only, v1 deprecated 2026-01"
```

**Save a bug-fix lesson:**
```bash
./scripts/memo.sh add "fix: macOS xargs -d" --content "BSD xargs doesn't support -d, use while-read loops"
```

**Recall a preference before recommending something:**
```bash
out=$(./scripts/memo.sh search "editor")
# Use $out to inform your answer
```

**Recall project decisions:**
```bash
./scripts/memo.sh search "API" --not "draft"
```

**List recent context at session start (optional):**
```bash
./scripts/memo.sh ls --limit 10
```

## Conventions for memories

Use **descriptive titles** that read like memory cues, not cryptic
labels:

- ✅ `pref: indentation` (clear what this is about)
- ✅ `decided: use ripgrep` (decision + what)
- ✅ `fix: xargs BSD -d` (lesson + symptom)
- ❌ `note1` (useless)
- ❌ `important` (vague)

Use **#tags** in content for cross-cutting grouping:
```bash
memo.sh add "deploy: staging" --content "#infra #aws #staging ..."
```

Later: `memo.sh search "#aws"` to find all AWS-related memories.

## Constraints

- **No folders.** This memory store is intentionally flat. Use `#tags`.
- **No interactive editing** in non-TTY contexts. Skip `--edit` unless
  the user is at a terminal.
- **No tight loops.** Each call is ~50ms. Batch operations.
- **Always check exit code.** rc=1 means "not found" or "no match".

## Files

- `scripts/memo.sh` — single-file Bash CLI
- `SKILL.md` — this file
