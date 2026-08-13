# Shipped Extensions / 随仓库分发的扩展

本目录存放随 mangopi-cli 仓库分发的**可选扩展**，与核心单文件解耦，按需启用。
This directory holds **optional extensions** shipped with the mangopi-cli repo,
decoupled from the single-file core and enabled on demand.

---

## Overview / 概述

启用方式（二选一）— Enable either way:

1. 将需要的 `.py` 复制/软链到 `~/.mangocli/extensions/`
   Copy or symlink the wanted `.py` files into `~/.mangocli/extensions/`
2. 设置环境变量指向本目录 — Set the env var to point at this dir:
   ```bash
   export MANGO_EXTENSIONS_DIR=examples/extensions
   ```

启动时 `ExtensionRegistry` 扫描目录内所有顶层 `*.py`（非递归），按三通道契约收获；
单个扩展加载失败仅记录诊断，不影响其他扩展。
At startup `ExtensionRegistry` scans every top-level `*.py` (non-recursive) and
harvests the three channels; a broken extension only logs a diagnostic and is skipped.

---

## Extension Contract (Three Channels) / 扩展契约（三通道）

每个文件可导出以下任意组合（全部可选）— Each file may export any combination (all optional):

| 通道 Channel | 导出 Export | 效果 Effect |
|---|---|---|
| Tools | `tools` | `ToolBase` 实例列表；并入全局 TOOLS，同名覆盖内置（扩展优先）。进入 LLM 工具 schema、`run_tool` 分发、ACP 模式可用。<br>List of `ToolBase` instances; merged into TOOLS, same-name overrides built-ins (extension wins). |
| Prompt sections | `prompt_sections` | `(name, content)` 列表；注入 SystemPrompt——同名覆盖默认段（强化），异名追加于 `environment` 之后。<br>Injected into SystemPrompt — same-name overrides the default section (enhancement), new names append after `environment`. |
| Entry points | `entry_points` | `name -> Callable[[], int]` 字典；同名首个生效（文件名字典序）。内置 `--acp` 分派取 `entry_points["acp"]`。<br>Dict of name → callable; same-name first file wins (lexicographic). Built-in `--acp` dispatches to `entry_points["acp"]`. |

### Minimal examples / 最小示例

```python
# tools 通道: 定义工具类并导出
from mangopi_cli import ToolBase

class HelloTool(ToolBase):
    name = "hello"
    description = "Say hello"
    params = {"name": {"type": "string", "description": "Who to greet"}}
    guidance = "Use **hello** to greet people."   # 可选: 注入 tool_guidance 段

    def run(self, args):
        return self.ok("Hello, %s!" % args.get("name", "world"))

tools = [HelloTool()]
```

```python
# prompt_sections 通道: 纯数据, 同名覆盖 / 异名追加
prompt_sections = [
    ("safety", "## Safety\n\n...custom policy..."),   # 同名 → 覆盖默认段
    ("project_note", "## Project Note\n\n..."),        # 异名 → 追加
]
```

```python
# entry_points 通道: 入口函数 (返回退出码)
def acp_main() -> int:
    from mangopi_cli import initialize_system  # 函数体内延迟导入
    initialize_system()
    return 0

entry_points = {"acp": acp_main}
```

---

## Import-Time Contract / 导入期契约

扩展在**模块导入期**被扫描，此时 `mangopi_cli` 处于半初始化状态——只有 `ToolBase`
等少数早于扫描点的符号可用，`agent_loop`/`ContextManager`/`console` 等尚未定义。
Extensions are scanned during module import, when `mangopi_cli` is only
half-initialized — only `ToolBase` and a few symbols defined before the scan point
are available; `agent_loop`/`ContextManager`/`console` etc. are not yet defined.

**规则 Rule**：
- 顶层只允许 `import`（含 `from mangopi_cli import ToolBase`），禁止访问其他
  `mangopi_cli` 属性 — Top level may only `import` (incl. `from mangopi_cli import ToolBase`);
  no other `mangopi_cli` attribute access.
- 所需核心符号一律在**函数体内**延迟导入 — Import needed core symbols lazily **inside function bodies**:

```python
import mangopi_cli  # 顶层仅 import

def serve() -> None:
    from mangopi_cli import console, agent_loop  # 执行时模块已完整初始化
    console.output("ready")
```

---

## Extension Index / 扩展清单

| 文件 File | 功能 Function | 依赖 Dependencies | 入口 Entry |
|---|---|---|---|
| `acp.py` | ACP (Agent Client Protocol) v1 agent server over stdio；`mangopi-cli --acp` 分派目标<br>ACP v1 stdio JSON-RPC agent endpoint; target of `--acp` | 无 none | `entry_points["acp"]` |
| `clipboard.py` | 系统剪贴板读写（read 免确认 / write 需确认）<br>System clipboard read/write (read unconfirmed / write confirmed) | macOS pbpaste/pbcopy, Linux xclip | `tools` |
| `git_status.py` | 只读 git 仓库状态：status/log/diff 结构化摘要<br>Read-only git repo state: structured status/log/diff | git | `tools` |

---

## Writing Your Own Extension / 编写扩展

1. 新建 `~/.mangocli/extensions/<name>.py`（或本目录随仓库分发）
2. 顶层 `from mangopi_cli import ToolBase`，类定义继承 `ToolBase`
3. 定义 `name`/`description`/`params`（`?` 后缀参数可选）与 `run(self, args) -> dict`
   （返回 `self.ok(text)` 或 `self.fail(msg)`）
4. 可选：`guidance` 属性（进入 tool_guidance 段）、`preview()`、`confirm()`（需要用户确认时）、`use_spinner`
5. 导出 `tools = [YourTool()]`；需要更多能力时叠加 `prompt_sections` / `entry_points`
6. 测试：在 `test/` 下新建 `test_<name>.py`，用 importlib 从扩展文件加载模块（参考 `test_clipboard.py` / `test_git_status.py` / `test_acp.py`）

---

## Notes / 注意事项

- 扩展是任意 Python 代码（等同 pip 包信任），仅从可信来源安装 —
  Extensions run arbitrary Python code (equivalent to trusting a pip package); install only from trusted sources.
- 同名工具/入口的裁决：工具由 TOOLS 合并时扩展覆盖内置；入口按文件名字典序首个生效 —
  Conflict resolution: tools — extension overrides built-in on merge; entry points — first file in lexicographic order wins.
- 契约细节与完整示例见仓库根 `README.md` 的 Extension System 章节 —
  Full contract details and examples live in the repo-root `README.md`, "Extension System" section.
