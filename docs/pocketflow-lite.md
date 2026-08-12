# PocketFlow Lite 图调度框架 / Graph Scheduling Framework

> 本文档归档 mangopi-cli 内化的 PocketFlow Lite 框架知识，代码于 **v0.1.47** 随 loop_engine 一并移除。
> This document archives the PocketFlow Lite framework knowledge of mangopi-cli. The code was removed in **v0.1.47** together with loop_engine.

---

## 1. 概述 / Overview

PocketFlow Lite 是内化自 [The-Pocket/PocketFlow](https://github.com/The-Pocket/PocketFlow) 的微型图调度框架，约 65 行，内嵌于单文件 `mangopi_cli.py`。它提供：带 action 的 DSL 连边、三段式节点钩子、dispatch 表驱动的 while 循环执行。

PocketFlow Lite is a ~65-line graph scheduling framework internalized from [The-Pocket/PocketFlow](https://github.com/The-Pocket/PocketFlow), embedded in the single-file `mangopi_cli.py`. It provides: an action-aware DSL for edges, a three-phase node hook lifecycle, and a dispatch-table-driven while-loop executor.

---

## 2. 核心抽象 / Core Abstractions

| 类 / Class | 职责 / Responsibility |
|---|---|
| `Step` | 图节点：持有 `name` 与 `next`（action → Step 的 dispatch 表）；`prep` / `execute` / `post` 三段式钩子 |
| `_Edge` | 带 action 的连边中间对象（`a - "action"` 的返回值），`__rshift__` 落边 |
| `Pipeline` | 执行器：持有 `start` 节点，`run(ctx)` 沿边遍历直至无后继；`trace()` 打印拓扑 |

```python
class Step:                       # 图节点
    def __init__(self, name=""):
        self.name = name or self.__class__.__name__
        self.next = {}            # action -> Step

    def prep(self, ctx): return None                 # 读 ctx，拿上下文
    def execute(self, prep_res): raise NotImplementedError  # 干脏活
    def post(self, ctx, prep_res, exec_res): return None    # 写回 ctx，返回 action 字符串

class Pipeline:                   # dispatch 表 + while 循环
    def __init__(self, start: Step): self.start = start
    def run(self, ctx):
        curr = self.start
        while curr is not None:
            action = curr.run(ctx)
            curr = curr.next.get(action or "default")
        return ctx
```

---

## 3. DSL 语法 / DSL Syntax

| 表达式 / Expression | 语义 / Semantics |
|---|---|
| `a >> b` | 连 default 边：`a` 执行后无条件进入 `b` |
| `a - "pass" >> b` | 连命名边：`a.post` 返回 `"pass"` 时进入 `b` |
| `a - "fail" >> c` | 同上，返回 `"fail"` 时进入 `c` |
| `a >> b >> c` | 链式：`connect` 返回后继节点，可连续拼接 |
| `post` 返回 `None` | 走 default 边（`next.get(None or "default")`） |
| `post` 返回未注册 action | `next.get(...)` 落空 → 流水线终止 |

```python
design >> dev >> review
review - "pass" >> test
review - "fail" >> updater
updater - "refine" >> incr
incr - "ok" >> design      # 回环：进入下一轮迭代
```

---

## 4. 三段式钩子 / Hook Lifecycle

每个 Step 的执行由 `run(ctx)` 编排，三段钩子按需 override：

```
prep(ctx)          # 1. 读 ctx，准备输入（可返回任意 prep_res）
  ↓
execute(prep_res)  # 2. 干脏活（LLM 调用、IO…），返回 exec_res
  ↓
post(ctx, prep_res, exec_res)  # 3. 写回 ctx，返回 action 字符串决定路由
```

约定：**状态写回 ctx（共享 dict），节点自身无状态**。这使节点可复用、可单元测试、可并行推理（`execute` 不依赖 ctx）。

Each Step's execution is orchestrated by `run(ctx)`; the three hooks can be overridden as needed. Convention: **state is written back to ctx (a shared dict), nodes stay stateless** — making nodes reusable, unit-testable and easy to reason about.

---

## 5. 与 loop_engine 的集成 / Integration with loop_engine

loop_engine 是其唯一消费者，通过继承 `Step` 定义了三类节点：

| 节点 / Node | 说明 / Notes |
|---|---|
| `Agent(role, phase, prompt_fn, fresh_role, extract, route)` | 声明式 LLM 节点：prep 选择子会话（fresh_role 独立 / 共享 impl_ctx），execute 调 `agent_loop`，post 走 route |
| `IncrIter` | 迭代计数器：`iteration += 1`，超 `max_iter` 返回 `None` 终止，否则 `"ok"` 回环 |
| `SucceedStep` | 终节点：标记 `ctx["succeeded"] = True` |

`Agent` 的声明式设计（prompt_fn / extract / route 全部参数化）使五张流水线图（normal / fast / only-dev / wish / push）仅靠连边表达，引擎与节点零改动。

loop_engine was its only consumer, defining three node types by subclassing `Step`. The declarative `Agent` design (prompt_fn / extract / route fully parameterized) lets all five pipeline graphs be expressed purely by edges — zero changes to the engine or nodes.

---

## 6. 设计要点回顾 / Design Notes

- **无依赖**：纯 Python 内嵌，无第三方库，符合单文件哲学。
- **ctx 即总线**：节点间通信全部走共享 dict，无显式消息传递。
- **action 即路由**：`post` 的返回值就是图的边标签，条件分支自然表达。
- **trace 可调试**：DFS 打印完整拓扑，`--dry-run` 一键可视化。
- **取舍**：无并行执行、无动态图（运行时改边）、无节点级状态——换取 ~65 行的极简实现。

- **Zero dependency**: pure Python, fitting the single-file philosophy.
- **ctx as bus**: inter-node communication goes through a shared dict; no explicit message passing.
- **action as routing**: the `post` return value is the edge label — conditional branches fall out naturally.
- **trace for debugging**: DFS prints the full topology; `--dry-run` visualizes it in one shot.
- **Trade-offs**: no parallelism, no dynamic graph mutation, no node-level state — in exchange for a ~65-line minimal implementation.

---

## 7. 附录：完整实现（v0.1.46 最终形态）/ Appendix: Full Implementation (final form in v0.1.46)

> 以下为移除前（v0.1.46）`_Edge` / `Step` / `Pipeline` 的完整源码。
> The complete source of `_Edge` / `Step` / `Pipeline` before removal (v0.1.46).

```python
# --- PocketFlow Lite: 图调度核 (内化自 The-Pocket/PocketFlow) ---

class _Edge:  # 带 action 的连边中间对象，配合 DSL 使用
    __slots__ = ("src", "action")

    def __init__(self, src, action): self.src, self.action = src, action

    def __rshift__(self, tgt): return self.src.connect(tgt, self.action)


class Step:  # 图节点：状态保存在 ctx 里，三段式钩子（按需 override）在引擎中被自动调用
    def __init__(self, name=""):
        self.name = name or self.__class__.__name__
        self.next = {}                            # action -> Step

    def __repr__(self):
        return f"<Step {self.name}>"

    def connect(self, other, action="default"):
        self.next[action] = other
        return other               # 允许链式：a >> b >> c

    def __rshift__(self, other): return self.connect(other, "default")

    def __sub__(self, action):
        if not isinstance(action, str):
            raise TypeError("action must be a string")
        return _Edge(self, action)

    def prep(self, ctx): return None               # 读 ctx，拿上下文

    def execute(self, prep_res): raise NotImplementedError  # 干脏活

    def post(self, ctx, prep_res, exec_res): return None    # 写回 ctx，返回 action 字符串

    def run(self, ctx):  # 引擎调用
        p = self.prep(ctx)
        e = self.execute(p)
        return self.post(ctx, p, e)


class Pipeline:  # Flow：一个 dispatch 表 + while 循环
    def __init__(self, start: Step):
        self.start = start

    def run(self, ctx):  # ctx 跨节点共享。各 Step 通过 post 返回值决定路由
        curr = self.start
        while curr is not None:
            action = curr.run(ctx)
            curr = curr.next.get(action or "default")
        return ctx

    def trace(self):
        """Print full pipeline topology (DFS)。"""
        seen = set()

        def _dfs(step, indent=""):
            if not step or id(step) in seen:
                return
            seen.add(id(step))
            for action, nxt in step.next.items():
                if not isinstance(nxt, Step):
                    continue
                arrow = " → " if action == "default" else f" ──{action}──→ "
                print(f"  {DIM}{indent}{step.name}{arrow}{nxt.name}{RESET}")
                _dfs(nxt, indent=indent)
        _dfs(self.start)
```

配套测试（`test/test_pocketflow.py`，v0.1.46 形态，覆盖 DSL 运算符 / 三段式钩子调用序 / 线性与条件路由 / 终止 / 自定义 Step / 边界错误）：

Companion tests (`test/test_pocketflow.py`, as of v0.1.46) covered: DSL operators (`>>`, `-`), hook call order, linear & conditional routing, pipeline stop, custom Steps, and edge cases (NotImplementedError, invalid action type). The tests were removed together with the framework in v0.1.47.
