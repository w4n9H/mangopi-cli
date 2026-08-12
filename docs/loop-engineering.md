# Loop Engineering 多智能体流水线 / Multi-Agent Pipeline

> 本文档归档 mangopi-cli 的 Loop Engineering 功能知识，代码于 **v0.1.47** 从仓库移除。
> Credit: [@BeWater799](https://github.com/BeWater799) — inspiration for the user prompt constraints.
> This document archives the Loop Engineering knowledge of mangopi-cli. The code was removed from the repository in **v0.1.47**.

---

## 1. 背景与演进 / Background & Evolution

Loop Engineering 是 mangopi-cli 的自主多智能体任务执行模式，经历了三次迭代：

- **v0.1.31** — 引入 `loop_engine()`，以 3-agent 协作流水线（Implementer → Verifier → Updater）取代旧的 `GoalTool`；`/goal` 自此废弃。
- **v0.1.40** — 加入 Sparse Loop（`--sparse`，MailBox 集体记忆）与 `--only-dev` 模式。
- **v0.1.43** — 在 PocketFlow Lite（见 `pocketflow-lite.md`）之上重写为声明式 Pipeline：Design → Dev → Review → Test → Succeed/Updater，loop 主体从 ~80 行减到 ~25 行。
- **v0.1.44** — 移除 Sparse/MailBox 与 jsonl 输出。
- **v0.1.47** — 整体移除（代码归档于本文档与 `pocketflow-lite.md`）。

Loop Engineering went through three major iterations: born in **v0.1.31** as a 3-agent pipeline replacing the legacy `GoalTool`; extended in **v0.1.40** with Sparse Loop / `--only-dev`; rewritten in **v0.1.43** as a declarative Pipeline on top of PocketFlow Lite; Sparse/MailBox removed in **v0.1.44**; fully removed in **v0.1.47**.

---

## 2. 入口与参数 / Entry Points & Parameters

函数签名 / Function signature:

```python
def loop_engine(goal: str, max_iter: int = 5, task_id: Optional[str] = None,
                is_push: bool = False, dry_run: bool = False, fast: bool = False,
                wish: bool = False, only_dev: bool = False) -> bool
```

| 参数 / Param | 含义 / Meaning |
|---|---|
| `goal` | 任务目标（必填） |
| `max_iter` | 最大迭代轮数，默认 5；超过即失败返回 `False` |
| `task_id` | 任务标识，缺省自动生成 8 位 hex；用于跨会话恢复 |
| `is_push` | 验证通过后执行 git commit（Push 步骤），否则仅标记成功 |
| `dry_run` | 只打印 Pipeline 拓扑（`p.trace()`）后退出，不执行 |
| `fast` | 跳过 Design/Review，仅 Dev → Test |
| `wish` | 在流水线前插入 Research 阶段（需 `MANGO_SEARCH_API_KEY`） |
| `only_dev` | 仅 Dev，无 Test/Review，直接 Push/Succeed |

CLI 入口 / CLI entry:

```bash
mangopi-cli loop "<goal>" [--max-iter N] [--task-id ID] [--push] [--dry-run] [--fast] [--wish] [--only-dev]
```

REPL 入口：`/loop <goal>` 或 `/l <goal>`；`/goal` 仅显示废弃提示。

REPL entry: `/loop <goal>` or `/l <goal>`; `/goal` only shows a deprecation warning.

---

## 3. 流水线拓扑 / Pipeline Topology

五种模式对应五张图（`>>` = default 边，`- "action" >>` = 命名边）：

| 模式 / Mode | 图 / Graph |
|---|---|
| Normal（默认） | `design >> dev >> review`；`review -"pass" >> test`；`review -"fail" >> updater`；`test -"pass" >> push/succeed`；`test -"fail" >> updater`；`updater -"refine" >> incr`；`incr -"ok" >> design` |
| Fast | `dev >> test`；`test -"pass" >> push/succeed`；`test -"fail" >> updater`；`updater -"refine" >> incr`；`incr -"ok" >> dev` |
| Only-dev | `dev >> push/succeed` |
| Wish（与 Normal/Fast 叠加） | `research >> start`（research 完成后进入后续流水线） |
| Push（与上述叠加） | 通过边指向 `push` 而非 `succeed`，验证通过即提交 |

固定回环 / Fixed loop: `updater -"refine" >> incr`，`incr -"ok" >> start`（回到起点，进入下一轮迭代）。

---

## 4. 角色与 Prompt / Agent Roles & Prompts

七个角色，prompt 由模块级函数按 `ctx`（共享 dict）动态构建：

| 角色 / Role | phase | 独立子会话 | 职责 / Duty |
|---|---|---|---|
| researcher | research | ✅ | `web_search` 调研并产出摘要（仅 `--wish`） |
| designer | plan | ❌（共享 impl_ctx） | 读代码、出设计方案 |
| developer | develop | ❌（共享 impl_ctx） | 渐进式实现，禁止自测 |
| verifier | review | ✅ | `git diff` 审查，输出 `VERIFY: PASS/FAIL` |
| verifier | test | ✅ | 运行真实测试，按退出码判定 PASS/FAIL |
| updater | push | ✅ | 失败时精炼原始 prompt（只读，禁止写代码） |
| implementer | push | ❌ | 验证通过后 conventional commit |

关键设计 / Key design:

- **会话隔离**：Designer/Developer 共享 `impl_ctx`（同一实现会话）；Researcher/Reviewer/Tester/Updater 各自独立子会话（`fresh_role`），防止污染实现上下文。
- **结果传递**：Review/Test 通过 `attempt_completion` 的 content 返回一行判定；`_get_completion_result` 从子会话消息中提取。
- **文件传递**：`_extract_changed_files` 扫描实现会话中 `edit`/`write` 工具消息，产出 `impl_files` 供下游审查。

- **Session isolation**: Designer/Developer share one `impl_ctx`; Researcher/Reviewer/Tester/Updater each get an independent sub-session (`fresh_role`) to avoid polluting the implementation context.
- **Result passing**: Review/Test return a one-line verdict via `attempt_completion` content; `_get_completion_result` extracts it from the sub-session messages.
- **File passing**: `_extract_changed_files` scans `edit`/`write` tool messages in the implementation session and produces `impl_files` for downstream agents.

---

## 5. 路由机制 / Routing

路由函数签名统一为 `route(exec_result, ctx) -> Optional[str]`，返回值决定走哪条边（`None` 走 default）：

| 函数 / Function | 行为 / Behavior |
|---|---|
| `_route_noop` | 不写 ctx，返回 `None` |
| `_route_research` | 摘要写入 `ctx["research"]` |
| `_route_files` | 变更文件写入 `ctx["impl_files"]` |
| `_route_verify` | 含 `"VERIFY: PASS"` → `"pass"`；否则记录 verdict → `"fail"`（只在 fail 时输出） |
| `_route_test` | 同 verify 判定，但无论 pass/fail 都输出 verdict |
| `_route_updater` | 精炼 prompt 追加为 impl_ctx 的 user 消息 → `"refine"` |
| `_route_succeed` | 标记 `ctx["succeeded"] = True` |

---

## 6. 迭代控制 / Iteration Control

`IncrIter` 节点位于回环上：每次经过将 `ctx["iteration"] += 1`（同步 `console._round`），超过 `max_iter` 返回 `None` 终止流水线（走不到 `start` 的 `"ok"` 边）；未超过返回 `"ok"` 回到起点进入下一轮。

`IncrIter` sits on the feedback loop: each pass increments `ctx["iteration"]` (syncing `console._round`). Exceeding `max_iter` returns `None` to stop the pipeline; otherwise returns `"ok"` to restart the loop.

---

## 7. 任务持久化 / Task Persistence

- 会话文件存放于 `.mangocli/loops/<task_id>/`（`loops_dir`），`task_id` 缺省为 8 位 hex。
- 每个子会话一个文件：`<role>_loop_<ts>_<uuid6>.json`（`_get_loop_ctx`）。
- 共享 `impl_ctx` 为 `implementer_loop_*.json`，由 `agent_loop` 每轮落盘。
- 传入相同 `--task-id` 可跨会话恢复历史（v0.1.40 起支持）。

Session files live under `.mangocli/loops/<task_id>/`; each sub-session gets `<role>_loop_<ts>_<uuid6>.json`. Reusing the same `--task-id` resumes history across sessions.

---

## 8. 与 agent_loop 的关系 / Relation to agent_loop

所有 Agent 节点的执行都委托给保留至今的 `agent_loop(ctx, ctx_file, prompt)`——即单会话 read → think → tool-call → verify 主循环。`agent_loop` 通过 `"/loops/" in ctx_file_path` 识别 loop 模式（写入 trace 的 `mode` 字段）；该分支随 v0.1.47 一并移除，trace 的 `mode` 固定为 `"chat"`。

Every Agent node delegates execution to `agent_loop(ctx, ctx_file, prompt)` — the single-session read → think → tool-call → verify main loop (still present). `agent_loop` detected loop mode via `"/loops/" in ctx_file_path` for trace metadata; that branch was removed in v0.1.47 and `mode` is now fixed to `"chat"`.

---

## 9. 设计要点回顾 / Design Notes

- **状态放 ctx，不放节点**：Step 无内部状态，`shared` dict 跨节点传递（goal/max_iter/iteration/impl_ctx/prompt_runtime…），节点天然可复用、可测试。
- **图即配置**：模式差异全部由图的连边表达，引擎（Pipeline）与节点（Agent）零改动。
- **失败自愈**：Review/Test 失败不终止，由 Updater 精炼 prompt 进入下一轮，直到 `max_iter` 耗尽。
- **声明式节点**：`Agent(role, phase, prompt_fn, fresh_role, extract, route)` 一行声明一个 LLM 节点，prompt/子会话/提取/路由全部参数化。

- **State lives in ctx, not in nodes**: Steps are stateless; a shared dict carries goal/max_iter/iteration/impl_ctx across nodes, keeping nodes reusable and testable.
- **Graph as configuration**: mode differences are expressed purely by edges; the engine and nodes stay untouched.
- **Self-healing on failure**: Review/Test failures don't abort — the Updater refines the prompt for the next iteration until `max_iter` is exhausted.
- **Declarative nodes**: `Agent(role, phase, prompt_fn, fresh_role, extract, route)` declares an LLM node in one line.

---

## 10. 附录：核心代码（v0.1.46 最终形态）/ Appendix: Core Code (final form in v0.1.46)

> 以下代码为移除前（v0.1.46）的完整实现，可按章节顺序还原功能。
> The code below is the complete implementation before removal (v0.1.46); the feature can be restored by reassembling these sections in order.

### 10.1 Prompt 构建函数 / Prompt Builders

```python
def _design_prompt(ctx) -> str:
    research = ctx.get("research", "")
    research_section = f"\nResearch summary:\n{research}\n" if research else ""
    return (
        f"[Design iter {ctx['iteration']}/{ctx['max_iter']}]\n"
        f"GOAL: {ctx['goal']}{research_section}\n"
        f"You are the DESIGNER. Plan before coding.\n"
        f"1. Read relevant code (read/grep).\n"
        f"2. Plan your design.\n"
        f"3. Call `attempt_completion` when done.\n")


def _dev_prompt(ctx) -> str:
    return (
        f"[Dev iter {ctx['iteration']}/{ctx['max_iter']}]\n"
        f"GOAL: {ctx['goal']}\n\n"
        f"You are the DEVELOPER. Implement the plan.\n"
        f"1. Implement progressively: smallest working change first.\n"
        f"2. Self-review: read back your changes, verify no logic errors.\n"
        f"3. Design for extensibility: clear abstractions, hooks, avoid hard-coding.\n"
        f"4. When calling edit/write, briefly explain WHY in your thinking.\n"
        f"5. Call `attempt_completion` tool when done.\n\n"
        f"DO NOT run tests or verify your own code. That's the Reviewer and Tester's job.\n")


def _research_prompt(ctx) -> str:
    return (
        f"[Research]\n"
        f"GOAL: {ctx['goal']}\n\n"
        f"You are a RESEARCHER. Gather information before implementation.\n"
        f"1. Break the goal into 2-3 research questions.\n"
        f"2. Use `web_search` for each question to find:\n"
        f"   - Relevant documentation or API references\n"
        f"   - Best practices and common patterns\n"
        f"   - Example implementations\n"
        f"3. Synthesize findings into a concise summary.\n"
        f"4. Call `attempt_completion` to return the summary.\n")


def _review_prompt(ctx) -> str:
    return (
        f"[Review iter {ctx['iteration']}]\n"
        f"GOAL: {ctx['goal']}\n"
        f"Files changed: \n{ctx['impl_files']}\n\n"
        f"You are a REVIEWER. Inspect the changes.\n"
        f"1. Use `git diff` to see what changed.\n"
        f"2. Read individual files as needed (`read` tool).\n"
        f"3. Call `attempt_completion` with one line:\n"
        f"   - 'VERIFY: PASS' if the changes look reasonable\n"
        f"   - 'VERIFY: FAIL: <reason>' if you spot issues\n\n"
        f"Evaluate at architecture-level (module/flow, logic correctness),\n"
        f"not function-level (naming, formatting).\n")


def _test_prompt(ctx) -> str:
    return (
        f"[Test iter {ctx['iteration']}]\n"
        f"GOAL: {ctx['goal']}\n"
        f"Files changed: \n{ctx['impl_files']}\n\n"
        f"You are a TESTER. Run tests and judge PASS/FAIL.\n"
        f"1. Determine the right test command (inspect project: package.json/pyproject.toml/go.mod).\n"
        f"2. Run tests with bash tool.\n"
        f"3. Judge PASS/FAIL based on exit code (non-zero = FAIL).\n"
        f"4. Call `attempt_completion` with one line:\n"
        f"   - 'VERIFY: PASS'\n"
        f"   - 'VERIFY: FAIL: <reason>'\n"
        f"Explain at architecture-level (module/flow), not function-level.\n")


def _updater_prompt(ctx) -> str:  # Updater: 失败时 refine user prompt
    return (
        f"[Updater iter {ctx['iteration']}]\n"
        f"GOAL: {ctx['goal']}\n"
        f"Failed at: {ctx.get('verify_result', '')}\n\n"
        f"You are an UPDATER.\n"
        f"Refine the user's prompt for the next implementer iteration.\n"
        f"You MUST NOT write code or call write/edit/bash. Only read/grep for context.\n\n"
        f"Read the failure analysis above.\n"
        f"Identify what's missing or unclear in the original goal.\n\n"
        f"Output: a single prompt, 50-200 words, specific constraints.\n"
        f"Call `attempt_completion` tool to return the refined prompt.")


def _push_prompt(ctx) -> str:
    return (
        f"[Push iter {ctx['iteration']}]\n"
        f"GOAL: {ctx['goal']}\n\n"
        f"All changes are verified. Commit them now.\n"
        f"1. Use `git diff` to see uncommitted changes, then stage them.\n"
        f"2. Write a short conventional commit message (e.g. `feat: ...` or `fix: ...`).\n"
        f"3. Commit with `git commit -m \"<msg>\"`.\n"
        f"4. Call `attempt_completion` when done.\n"
        f"The commit message must be a short English sentence following conventional commits.")
```

### 10.2 辅助函数 / Helpers

```python
def _extract_changed_files(ctx: ContextManager) -> str:
    files = set()
    for m in ctx.messages:
        if m.get("role") == "tool" and m.get("tool_name") in ("edit", "write"):
            files.add(f"{m.get('content')}")
    return ",\n ".join(files) if files else "(unknown — Verifier inspect project to find)"


def _get_completion_result(ctx: ContextManager) -> str:
    for m in reversed(ctx.messages):
        if m.get("role") == "tool" and m.get("tool_name") == "attempt_completion":
            return m.get('content', '')
    return ''


def _get_loop_ctx(task_dir: str, role: str):
    _loop_id = f"loop_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    _loop_file = os.path.join(task_dir, f"{role}_{_loop_id}.json")
    _ctx = ContextManager()
    _ctx.load(_loop_file)
    return _ctx, _loop_file
```

### 10.3 路由函数 / Routing Functions

```python
def _route_noop(r, ctx):  # 默认路由:不写 ctx,返回 None(走 default 边)
    return None


def _route_research(r, ctx):  # Research:把 research 摘要写回 ctx,继续 pipeline
    ctx["research"] = r
    return None


def _route_files(r, ctx):  # Dev:把 changed files 写回 ctx['impl_files']
    ctx["impl_files"] = r
    return None


def _route_verify(r, ctx):  # Review:识别 'VERIFY: PASS' 决定 pass/fail 路由,只在 fail 时输出 verdict
    if r and "VERIFY: PASS" in r:
        return "pass"
    ctx["verify_result"] = r or "FAIL: review rejected"
    return "fail"


def _route_test(r, ctx):  # Test:与 verify 类似,但无论 pass/fail 都输出 verdict
    if r and "VERIFY: PASS" in r:
        return "pass"
    ctx["verify_result"] = r
    return "fail"


def _route_updater(r, ctx):  # Updater:把 refined prompt 追加到 impl_ctx 触发下一轮
    if r:
        ctx["impl_ctx"].append_user(f"[Refined prompt from updater iter {ctx['iteration']}]\n{r}")
    return "refine"


def _route_succeed(r, ctx):  # Push/Succeed:标记 succeeded
    ctx["succeeded"] = True
    return None
```

### 10.4 节点类 / Step Subclasses（依赖 10.2 与 PocketFlow 框架）

```python
class SucceedStep(Step):
    def execute(self, data): pass

    def post(self, ctx, p, e): return _route_succeed(None, ctx)


class IncrIter(Step):
    def execute(self, data): pass

    def post(self, ctx, p, e):
        ctx["iteration"] += 1
        console._round = ctx["iteration"]
        if ctx["iteration"] > ctx["max_iter"]:
            return None
        return "ok"


class Agent(Step):  # 声明式 LLM 节点:prompt 构建、子会话来源、结果提取、路由全部由构造参数决定
    def __init__(self, role, phase, prompt_fn, *, fresh_role=None, extract=None, route=None, name=None):
        super().__init__(name=name or f"{role}:{phase}")
        self.role, self.phase = role, phase
        self.prompt_fn = prompt_fn          # (ctx) -> str
        self.fresh_role = fresh_role        # None=共享 impl_ctx; str=该角色的独立子会话
        self.extract = extract              # None=不提取子会话结果 (execute 返回 None)
        self.route = route or _route_noop

    def prep(self, ctx):
        if self.fresh_role:
            sub_ctx, sub_file = _get_loop_ctx(ctx["task_dir"], self.fresh_role)
            sub_ctx.append_system(ctx["prompt_runtime"])
        else:
            sub_ctx, sub_file = ctx["impl_ctx"], ctx["impl_ctx_file"]
        return {"impl_ctx": sub_ctx, "impl_ctx_file": sub_file, "prompt": self.prompt_fn(ctx)}

    def execute(self, data):
        agent_loop(data["impl_ctx"], data["impl_ctx_file"], data["prompt"])
        return self.extract(data["impl_ctx"]) if self.extract else None

    def post(self, ctx, prep_res, exec_res):
        return self.route(exec_res, ctx)
```

### 10.5 loop_engine 本体 / The Engine

```python
def loop_engine(goal: str, max_iter: int = 5, task_id: Optional[str] = None, is_push: bool = False,
                dry_run: bool = False, fast: bool = False, wish: bool = False,
                only_dev: bool = False):
    """Pipeline 版本 loop_engine。"""
    if task_id is None:
        task_id = uuid.uuid4().hex[:8]

    if wish and not fast:
        if not os.environ.get("MANGO_SEARCH_API_KEY"):
            raise RuntimeError("MANGO_SEARCH_API_KEY is required for research mode")
        research = Agent("researcher", "research", _research_prompt,
                         fresh_role="researcher", extract=_get_completion_result, route=_route_research)
    else:
        research = None
    dev = Agent("implementer", "develop", _dev_prompt, route=_route_files, extract=_extract_changed_files)
    review = Agent("verifier", "review", _review_prompt,
                   fresh_role="reviewer", extract=_get_completion_result, route=_route_verify)
    test = Agent("verifier", "test", _test_prompt,
                 fresh_role="tester", extract=_get_completion_result, route=_route_test)
    updater = Agent("updater", "push", _updater_prompt,
                    fresh_role="updater", extract=_get_completion_result, route=_route_updater)
    push = Agent("implementer", "push", _push_prompt, route=_route_succeed)
    incr, succeed = IncrIter(), SucceedStep()

    if only_dev:
        start = dev
        dev >> (push if is_push else succeed)
    elif fast:
        start = dev
        dev >> test
        test - "pass" >> (push if is_push else succeed)
        test - "fail" >> updater
    else:
        design = Agent("implementer", "plan", _design_prompt)
        start = design
        design >> dev >> review
        review - "pass" >> test
        review - "fail" >> updater
        if is_push:
            test - "pass" >> push
        else:
            test - "pass" >> succeed
        test - "fail" >> updater
        updater - "refine" >> incr
        incr - "ok" >> design

    updater - "refine" >> incr
    incr - "ok" >> start
    if wish and not fast:
        research >> start
        start = research
    p = Pipeline(start)
    if dry_run:
        p.trace()
        return True

    task_dir = os.path.join(loops_dir, task_id)
    os.makedirs(task_dir, exist_ok=True)
    console.text(f"Task ID: {task_id}  (files stored under {task_dir})")

    loop_prompt_runtime = SystemPrompt()
    prompt_text = loop_prompt_runtime.assemble()
    impl_ctx, impl_ctx_file = _get_loop_ctx(task_dir, "implementer")
    impl_ctx.append_system(prompt_text)

    shared = {"goal": goal, "max_iter": max_iter, "task_dir": task_dir, "iteration": 1, "impl_ctx": impl_ctx,
              "impl_ctx_file": impl_ctx_file, "prompt_runtime": prompt_text}

    console._round = 1
    try:
        p.run(shared)
    except Exception as e:
        console.error(f"Loop error: {e}")
        return False

    if shared.get("succeeded"):
        return True
    console.error(f"Loop failed after {max_iter} iterations")
    return False
```

### 10.6 依赖项清单 / Dependency Checklist

还原功能还需以下仍在代码库中的依赖（未随 v0.1.47 移除）：

- `agent_loop(ctx, ctx_file_path, user_input, cancel_event)` — 单会话主循环（Agent.execute 调用）
- `ContextManager`（`append_system` / `append_user` / `load` / `save` / `messages`）
- `SystemPrompt().assemble()` — 运行时 prompt 组装
- `console`（`text` / `error` / `_round`）
- `loops_dir` 全局变量 + `initialize_system()` 中 `os.makedirs(loops_dir, exist_ok=True)`
- CLI `loop` subparser（7 个参数）→ `main()` 入口分支 → REPL `/loop` `/goal` 分支（见 `pocketflow-lite.md` 附录）

Restoring the feature also requires the following dependencies that remain in the codebase (not removed in v0.1.47): `agent_loop`, `ContextManager`, `SystemPrompt().assemble()`, `console`, the `loops_dir` global + its `os.makedirs` in `initialize_system()`, and the CLI/REPL entry points.
