# Mangopi CLI · ROADMAP

> The 3–6 month development roadmap for Mangopi CLI.
>
> This document is public and serves as a shared commitment to contributors, users, and potential collaborators on feature priorities and design direction.
>
> The roadmap is adjusted dynamically based on community feedback. Major pivots are announced via PR + GitHub Discussion.

---

## 🎯 Core Philosophy (Non-Negotiable Constraints)

**Every new feature must answer two questions first:**

1. **Can it be implemented with the Python standard library?**
2. **Can it live inside `mangopi_cli.py` as a single file without breaking readability?**

If the answer to both is "yes" — build it.
If one answer is "no" — use the **opt-in switch** pattern (see Long-Term §4).
If both are "no" — the feature belongs in a **separate sub-project** (see Long-Term §1 Web Console).

### Boundaries We Hold

- ✅ **Zero runtime dependencies** — `pip install mangopi-cli` introduces no third-party packages by default
- ✅ **Single-file architecture** — the core runtime always lives in `mangopi_cli.py`
- ✅ **Low LOC** — `mangopi_cli.py` stays under 3,000 lines; exceeding it triggers a split review
- ✅ **Auditable / hackable / forkable** — no heavy abstractions; a new contributor reads the whole thing in under an hour
- ✅ **Local-first** — core functionality works fully offline (network capabilities are always opt-in)

### Capabilities We Actively Reject

- ❌ TUI framework dependencies (textual / prompt_toolkit)
- ❌ Embedded browsers / Electron
- ❌ Docker images / containerized distribution
- ❌ Heavy async runtimes (uvloop / anyio)

> These aren't "impossible" — they're "out of philosophy." If the community genuinely needs them, they'll ship as separate sub-projects, not pollute the main repo.

---

## 🛠 Design & Implementation Principles

Every new feature follows these rules, in order of priority:

| Principle | Meaning |
|-----------|---------|
| **Stdlib First** | Check `urllib / json / asyncio / threading / pathlib` first |
| **Opt-in for Heavy** | If a third-party dep is unavoidable, gate it behind `MANGO_OPT_FEATURES` |
| **Feature Flag** | Experimental features ship off by default with explicit opt-in docs |
| **Backward Compatible** | Never break existing session format, config fields, or tool protocol |
| **Test Before Ship** | New features ship with unit tests; core path coverage > 80% |

---

## 📅 Mid–Short Term (1–3 Months)

> Goal: take Mangopi from "runs" to "actually good to use" — without breaking the zero-dependency baseline.

### 1. Smart Provider Routing

**Status:** 🟢 Done (Experimental Feature)

**Problem:** Within the same session, "read me this file" and "design me a distributed system" demand wildly different model capability — but every request currently hits the same `MANGO_MODEL`. Either it's too expensive, or too weak.

**Approach:**

- A **scoring-based router** that selects one of three tiers (low / medium / high) per user request, gated behind the `MANGO_ROUTING` env var (default `off` for backward compatibility).
- Provider list declared in `.mangocli/providers.json`:

  ```json
  {
    "providers": [
      {"name": "ds-flash",    "url": "https://api.deepseek.com",  "model": "deepseek-v4-flash",    "tier": "low",    "api_key_env": "DEEPSEEK_KEY"},
      {"name": "ds-v4",       "url": "https://api.deepseek.com",  "model": "deepseek-v4",          "tier": "medium", "api_key_env": "DEEPSEEK_KEY"},
      {"name": "ds-reason",   "url": "https://api.deepseek.com",  "model": "deepseek-v4-reasoning", "tier": "high",   "api_key_env": "DEEPSEEK_KEY"},
      {"name": "gpt4o",       "url": "https://api.openai.com/v1", "model": "gpt-4o",                "tier": "medium", "api_key_env": "OPENAI_KEY"}
    ],
    "routing": {
      "default_tier": "medium",
      "score_thresholds": {"low_max": 3, "medium_max": 7}
    }
  }
  ```

- **Two-phase scoring** (executed before each `agent_loop` invocation):

  ```
  Phase 1 — Keyword scoring (0 ms, 0 token):
    Matches user query against a small, hardcoded keyword set.
    score ≤ 2 or ≥ 8 → short-circuit to tier directly.
    3 ≤ score ≤ 7 → proceed to Phase 2.

  Phase 2 — LLM scoring (~300–500 ms, minimal token):
    Sends compressed tool-call fingerprints from recent turns
    + current query to the tier=high model for a 1–10 rating.
    Fingerprints are compact, e.g.: [read, edit, read, grep].

  Final score = keyword_score × 0.3 + llm_score × 0.7
    ≤ 3  → low
    4–7 → medium
    ≥ 8  → high
  ```

- **Key design decisions:**
  - Once a tier is chosen, `agent_loop` uses that model for the entire turn — no mid-loop switching, upgrading, or downgrading.
  - Provider failures are surfaced as errors; no automatic fallback (a high-tier task must not be silently degraded).
  - Keyword set is hardcoded in the source (no extra config file); small and curated.
  - `MANGO_ROUTING=off` (or unset) → traditional single-model mode via `MANGO_MODEL` (current behavior, fully backward compatible).

**Why it fits the philosophy:** Pure stdlib (JSON parse, regex matching, `urllib` for LLM scoring call). Adds < 200 LOC.

**Acceptance criteria:**

- [ ] `MANGO_ROUTING` env var gates the feature; unset → traditional mode unchanged
- [ ] `.mangocli/providers.json` parsed and validated on startup
- [ ] Keyword scoring returns correct values for defined keywords
- [ ] LLM scoring prompt is compact and returns a single integer
- [ ] Final score mapping (low / medium / high) has full unit tests
- [ ] End-to-end: simple query routes to low, complex design routes to high

---

### 2. Multimodal Support (Image)

**Status:** 🟢 Done (Experimental Feature)

**Problem:** Users routinely need the AI to read screenshots, UI mockups, error screens, and diagrams — but pure-text tool chains treat images as opaque attachments.

**Approach:**

- Add tool `view_image` (extension of the existing `read`), accepting a local path or URL:
  - Local path → read as base64, assemble OpenAI-compatible `image_url` data URI
  - URL → pass through; the model fetches it
  - All stdlib: `base64` + `urllib` + `mimetypes`
- Multimodal message format follows the OpenAI Chat Completions vision spec; `DeepSeekProvider` / `OpenAIProvider` / `MinimaxProvider` all updated in lockstep.
- `read` tool auto-detects image extensions (`.png` / `.jpg` / `.gif` / `.webp`) — no extra tool call needed.

**Why it fits the philosophy:** Pure stdlib message assembly. Adds < 150 LOC, no Pillow / requests required.

**Acceptance criteria:**

- [ ] `view_image` tool works with at least one of: DeepSeek-VL, GPT-4o
- [ ] Screenshot → vision → generated code demo works end-to-end
- [ ] Clear error on non-image / oversized payloads

**Explicitly out of scope:**

- ❌ OCR (let the model see the pixels; no preprocessing)
- ❌ Image generation (different project)
- ❌ Local image preprocessing (crop / resize) — the user handles it

---

### 3. Sub Agent (Single Delegation)

**Status:** 🟡 Planned

**Problem:** In complex tasks, the main agent often gets bogged down by "first research library A's API, then library B's, then synthesize" — sequential multi-line work that should be parallel.

**Approach:**

- New tool `delegate(goal, context_files)`:
  - Spawns **one** sub-agent session with its own `ContextManager` and tool loop
  - When the sub-agent completes / times out / fails, only the **final summary** flows back to the main agent
  - The main agent sees a markdown summary as the tool result; the sub-agent's full trace never enters the main context
- Sub-agent reuses current `MANGO_KEY / MANGO_MODEL` — no new LLM-account concept
- Default timeout: 5 minutes, tunable via `MANGO_SUB_AGENT_TIMEOUT`

**Why single-agent and not parallel:** Concurrent scheduling requires thread / process / async pools, which will quickly break the single-file readability budget. That's saved for the long-term track.

**Why it fits the philosophy:** Reuses existing `agent_loop` + `ContextManager`. The whole feature is essentially "open another session and compress its result back." Adds < 250 LOC.

**Acceptance criteria:**

- [ ] `delegate` tool works: main agent delegates → sub-agent runs independently → main agent receives summary
- [ ] Sub-agent failure does not block the main agent
- [ ] Sub-agent session files are stored separately under `.mangocli/sub_sessions/`

**Explicitly out of scope:**

- ❌ Concurrent sub-agents (Long-Term §3)
- ❌ Sub-agents communicating with each other
- ❌ Recursive nesting (hard depth limit: 1)

---

### 4. Web Search (Bocha AI Search)

**Status:** 🟢 Done (Experimental Feature)

**Problem:** The AI frequently needs to consult the latest docs / GitHub issues / blog posts. Right now the user has to `cat` a local file by hand. A raw URL→text fetch only returns a single page; what the AI actually needs is a **synthesized, citation-backed answer across multiple sources** — i.e., a search engine result, not a HTML parser.

**Approach:**

- New tool `web_search(query, top_k=10)`: call the **博查 (Bocha) AI Search** API, return a synthesized answer + source list
- Endpoint: `https://api.bochaai.com/v1/ai-search`
- Single configuration: `MANGO_SEARCH_API_KEY` (no provider selector — see "Why Bocha" below)
- **Return shape** (fed to the LLM as a single markdown block):

  ```markdown
  ## Answer
  <synthesized answer from Bocha>

  ## Sources
  1. [title](url) — snippet
  2. [title](url) — snippet
  ...
  ```

- The tool can be **called multiple times per turn** to gather different angles; the main agent merges them.

**Why Bocha (not Metaso / not multi-provider):**

- **API contract stability**: Bocha's response shape (`messages` + `references`) is stable; Metaso's differs by mode (research vs concise) and the API is still iterating. CLI tools need predictable callers.
- **English + Chinese balance**: Bocha is more even across both; Metaso skews Chinese.
- **Lower normalization cost**: less code in the single-file budget, fits the "Stdlib First" principle.
- **No `MANGO_SEARCH_PROVIDER` env var**: deliberately pick one. Adding a provider switch doubles the adapter surface for marginal benefit. If we ever migrate to another provider, that's a one-shot PR — not a permanent abstraction.

**Why it fits the philosophy:** Pure stdlib — `urllib.request` + `json` are enough to call the API and parse the response. The "third party" here is the **API provider**, not a Python package: no `pip install`, no opt-in dep, no `MANGO_OPT_FEATURES` flag. This is the cleanest possible answer to "the AI needs the live web."

**Acceptance criteria:**

- [ ] `web_search` works end-to-end against `api.bochaai.com`
- [ ] `MANGO_SEARCH_API_KEY` config flow validated; clear error on missing key, 401, 429, or 5xx
- [ ] Sources are surfaced in the LLM context (not just the synthesized answer)
- [ ] End-to-end test with a real multi-source query (e.g., "compare FastAPI vs Flask in 2026")

**Explicitly out of scope:**

- ❌ Raw URL fetching & HTML→Markdown parsing (a separate `web_fetch` tool only if the community demands it later)
- ❌ Multi-provider abstraction / `MANGO_SEARCH_PROVIDER` switch (single opinionated choice)
- ❌ Paid-tier / enterprise features of Bocha
- ❌ Local search index / RAG over the user's own documents (different project)
- ❌ Crawling / spidering (search APIs already do the indexing)

---

### 5. Flash-ext Thinking Framework Server

**Status:** 🟢 Done (Experimental Feature)

> Provides an OpenAI-compatible HTTP proxy that injects phase-aware structured thinking frameworks before each model call. Designed for IDEs that cannot run the full Mangopi agent loop — the proxy silently augments API requests with debugging/design/optimization checklists, loop detection, and tool-call context.
>
> **Core insight:** memory and web-search let the model "know more"; thinking frameworks let the model "think better." Inspired by the Fable 5 revelation that a medium model + agent shell outperforms a strong model running bare, Flash-ext applies the same principle transparently: it wraps any OpenAI-compatible model API with cognitive enhancement without ever touching file I/O or execution tools.

**Problem:** The agent often gets stuck in loops, loses context across turns, or fails to apply structured thinking frameworks when debugging/designing complex tasks. A server-side augmentation layer can inject phase-aware thinking guidance before each model call.

**Approach:**

- **`FlashThinking`** — keyword + tool-pattern-driven framework selector (debug/design/explain/optimize/implement/investigate/verify/reevaluate) with English checklist steps per framework. All keyword matching centralized here; `RoutedProvider._keyword_score` and `ContextManager.assess_complexity` derive their decisions from it.
- **`FlashExtServer`** — OpenAI-compatible HTTP proxy (`--flash-ext --debug`) that wraps a backend model API, injects structured `<flash_ext>` XML context into the last user message before forwarding.
- **Two-path routing:**
  - **Fast path** (0ms): keyword + tool-pattern match → inject framework + tool context.
  - **Deep path** (~300ms): Flash-ext calls its own LLM to analyze session state (loop detection, phase inference, framework recommendation), then injects tailored guidance. Triggered by large tool contexts, diverse tool patterns, or design/optimize keywords.
- **`ContextManager` enhancements** — `tool_pattern()`, `tool_context()`, `detect_loop()` (same-tool + alternating), `detect_phase()`, `assess_complexity()`, `summarize_recent_turns()`.
- **Cognitive-only, no execution** — Flash-ext never touches file I/O or bash; it only enhances reasoning before the request reaches upstream.
- Optional memory and web search, disabled by default (`--memory`, `--web-search`).
- Zero new system messages — all context injected into the last user message's content via XML tags.

**Why it fits the philosophy:** Pure stdlib (`http.server`, `json`, `logging`). Single-file addition. Adds ~340 LOC.

**Acceptance criteria:**

- [x] `FlashThinking.match()` returns correct framework for keywords
- [x] `FlashExtServer._augment()` injects XML context into user content
- [x] `ContextManager.detect_loop()` catches same-tool + alternating loops
- [x] `ContextManager.assess_complexity()` routes deep vs fast correctly
- [x] 38 unit tests covering all modules (`test/test_flash_ext.py`)
- [ ] Live server integration tests pass

---

## 🌐 Long-Term (3–6 Months)

> Goal: take Mangopi toward "professional AI coding platform" tier while keeping the main repo's zero-dependency boundary intact.
> Note: some features in this phase **will exceed the main repo's constraints** — they ship via opt-in switches or as separate sub-projects.

### 1. Web Console (Separate Sub-Project: `mangopi-web`)

**Status:** ⚪ Backlog

**Positioning:** **Not in the `mangopi-cli` main repo** — published as an independent sub-project to keep the single-file philosophy clean.

**Form:**

- Backend: `mangopi-cli` exposes a local HTTP / WebSocket interface (short-lived)
- Frontend: lightweight SPA (Vue or Svelte — Svelte preferred for size), deployable independently
- Core capabilities:
  - Live session state, token usage, context occupancy
  - Cross-device session sync (user-hosted backend, no cloud)
  - Team-shared goal plans (permissions in the enterprise edition)
  - Visual diff (current `Printer.diff` upgraded to a side-by-side view)

**Why split it out:** Any frontend framework violates zero-dependency; even pure HTML+JS, a 3,000+ line console blows the main-file budget.

**Relationship to the main repo:** Main repo only exposes the necessary HTTP interface; console lives in a sibling repo, optional install.

**Acceptance criteria:**

- [ ] New repo `w4n9H/mangopi-web` created
- [ ] Main repo README points to Web Console install instructions
- [ ] Main repo `mangopi_cli.py` adds zero web-framework dependencies

---

### 2. MCP Client Integration

**Status:** ⚪ Backlog

**Positioning:** Let Mangopi consume community MCP servers — the tool ecosystem is no longer limited to the 10 built-in tools.

**Implementation strategy (key):**

- **Strictly opt-in**: `export MANGO_OPT_FEATURES=mcp` enables `mcp` SDK import
- Default install remains zero-dependency
- MCP servers declared in `~/.mangocli/mcp_servers.json`:

  ```json
  {
    "servers": [
      {"name": "filesystem", "command": "uvx", "args": ["mcp-server-filesystem", "/tmp"]},
      {"name": "github",     "command": "npx",   "args": ["-y", "@modelcontextprotocol/server-github"]}
    ]
  }
  ```

- On startup, check the opt-in flag, dynamically import, map MCP tools onto the existing `ToolBase` interface
- The LLM sees a merged tool schema (built-in + MCP)

**Why it fits the philosophy:** Zero-dependency baseline preserved; users who need MCP opt in; reuses the existing Tool framework.

**Acceptance criteria:**

- [ ] Opt-in flag + dynamic import mechanism is stable
- [ ] At least one official MCP server runs (filesystem / github)
- [ ] MCP tool errors propagate cleanly without breaking the main agent loop

---

### 3. Sub Agent (Parallel)

**Status:** ⚪ Backlog (depends on Mid-Short §3 completion)

**Upgrades:**

- `delegate` tool supports a `mode: "parallel"` argument
- Concurrency limit via `MANGO_SUB_AGENT_MAX_CONCURRENT` (default 3)
- Use stdlib `concurrent.futures.ThreadPoolExecutor` for thread-level parallelism
- After all sub-agents complete, the main agent receives a merged summary

**Risks & tradeoffs:**

- Parallelism drives up token usage — needs a hard `MANGO_SUB_AGENT_BUDGET` cap
- Rollback strategy for partial failures needs careful design
- Single-file LOC near the critical line — may need to extract an internal `_sub_agent.py` (same directory as `mangopi_cli.py`, imported as `from _sub_agent import ...`)

**Acceptance criteria:**

- [ ] `delegate(mode="parallel", goals=[...])` works
- [ ] Thread pool + budget cap have full tests
- [ ] Single-file LOC stays under 3,500

---

### 4. Opt-in Switch Mechanism (Core Infrastructure)

**Status:** ⚪ Backlog — shared by §1, §2, §3

**Goal:** Formalize the "zero-dependency vs feature richness" tradeoff as a first-class engineering mechanism — the project's meta-capability.

**Design:**

```bash
# Comma-separated list of opt-in features
export MANGO_OPT_FEATURES=mcp,stream

# Or in ~/.mangocli/config.json
{
  "opt_features": ["mcp", "stream"]
}
```

**Implementation details:**

- Top of the main file: add `_OPT_FEATURES = set(...)` parsing logic
- Each opt-in module is wrapped in `try: import xxx except ImportError: xxx = None`
- Public tool entry point checks: `if xxx is None: return "error: feature xxx not enabled, install ... and set MANGO_OPT_FEATURES=xxx"`
- `pyproject.toml` changes to use `optional-dependencies`:

  ```toml
  [project.optional-dependencies]
  mcp    = ["mcp>=1.0"]
  stream = ["sseclient-py>=1.7"]
  ```

  ```bash
  # User install
  pip install mangopi-cli[mcp]
  ```

**Hard constraints:**

- Any opt-in dep must produce a **clear runtime error when missing**, not an `ImportError` crash
- Opt-in deps should be **pure Python + lightweight + Apache 2.0 / MIT**
- Every new opt-in dep must justify itself in its PR: "Why not stdlib? Is there a lighter alternative?"

**Acceptance criteria:**

- [ ] Opt-in parsing logic fits in < 30 lines at the top of `mangopi_cli.py`
- [ ] `pip install mangopi-cli` installs no opt-in deps
- [ ] `pip install mangopi-cli[mcp,stream]` enables them in one go
- [ ] Both example opt-in features (mcp / stream) work end-to-end

---

## 🧭 Direction Adjustment Principles

- A feature requested by **> 30% of the community** may be pulled forward from long-term to mid-short
- A feature whose implementation exceeds **500 LOC** is the first candidate for a sub-project
- **Architecture review triggers**: any sign of zero-dependency erosion (single file > 3,500 LOC / > 5 opt-in features / any feature broken when its flag is off)
- Major adjustments go through GitHub Discussion first, then merge into this ROADMAP

---

## 🤝 Contributing

Want to pick up a feature?

1. Comment on the relevant section / open an issue, flip its status to 🟢
2. PR title: `[roadmap] <feature name>`
3. For large features (> 500 LOC), sync the design in Discussion first

---

## 📜 License

Apache License 2.0 · this ROADMAP document shares the codebase license.

---

Last updated: 2026-06-10
