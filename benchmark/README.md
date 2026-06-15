# mangopi-cli Benchmark

端到端评测框架，调用真实 LLM 模型验证 AI Agent 的任务正确性与工具调用效率。

## 核心用途：度量 system prompt 的好坏

`mangopi_cli.py` 的 system prompt（`_build_base_intro`、`_build_tool_guidance` 等 7 个 section）直接决定了 Agent 的行为。benchmark 使用**真实的 SystemPrompt.assemble()**，不是硬编码拷贝。修改 `mangopi_cli.py` 中的任意提示词后重新跑 benchmark，就能量化影响：

| 修改了什么                  | 关注的指标变化               |
|------------------------|-----------------------|
| `_build_tool_guidance` | 工具选择是否更精准？冗余调用是否减少？   |
| `_build_builtin_rules` | 通过率是否提高？是否避免了过度修改？    |
| `_build_safety`        | 危险命令误报率？              |
| 新增 section             | 综合影响：通过率、工具数、Token 消耗 |

**工作流：** 改提示词 → 跑对比 → 看工具数/Tokens/通过率变化 → 决定是否采纳。

## 与单元测试的区别

|         | `test/` 单元测试 | `benchmark/` 端到端评测    |
|---------|--------------|-----------------------|
| 被测对象    | 单个函数/类       | 完整 Agent 管线           |
| 数据      | 合成数据         | 真实文件 + 真实模型调用         |
| 验证方式    | assert 预期输出  | 校验工作区文件状态             |
| 关注指标    | 逻辑正确性        | 正确性 + 工具效率 + Token 消耗 |
| 是否调 API | 否            | 是（需要 `MANGO_KEY`）     |

## 快速开始

```bash
# 前置条件：设置 API Key
export MANGO_KEY="your-api-key"
export MANGO_MODEL="deepseek-v4-flash"  # 可选

# 列出所有任务
python benchmark/run.py --dry-run

# 运行 Level 1 任务（快速验证）
python benchmark/run.py --level 1

# 运行全部评测
python benchmark/run.py
```

## 任务体系

14 个任务按照复杂度分为 4 个级别：

### Level 1 — 单工具任务

验证 Agent 能否用最少的工具调用完成简单操作。

| 任务                       | 需求                  | 期望工具   |
|--------------------------|---------------------|--------|
| `L1_read_file`           | 读取 `data.txt` 并报告内容 | read   |
| `L1_search_python_files` | 查找所有 `.py` 文件       | search |
| `L1_grep_todo`           | 查找包含 `TODO` 的行      | grep   |

### Level 2 — 双工具任务

验证 Agent 能否组合两个工具完成读写链路。

| 任务                       | 需求             | 期望工具          |
|--------------------------|----------------|---------------|
| `L2_read_and_write`      | 读取→提取→写入新文件    | read, write   |
| `L2_search_and_count`    | 搜索文件→计数→写入结果   | search, write |
| `L2_simple_edit`         | 编辑文件替换指定字符串    | read, edit    |
| `L2_bash_list_and_write` | bash 列出文件→写入文件 | bash, write   |

### Level 3 — 多步骤任务

验证 Agent 能否规划并执行多步操作、精确控制修改范围。

| 任务                        | 需求                 | 期望工具        |
|---------------------------|--------------------|-------------|
| `L3_create_python_module` | 创建带类型标注的 Python 模块 | write, bash |
| `L3_multi_file_edit`      | 跨目录替换文本，不污染目录外文件   | edit × N    |
| `L3_data_processing`      | JSON 提取→排序→写入      | read, write |
| `L3_bash_pipeline`        | bash 管道统计文件行数      | bash, write |

### Level 4 — 复杂工作流

验证 Agent 能否完成需要规划、执行、验证的完整工程任务。

| 任务                    | 需求                           | 期望工具        |
|-----------------------|------------------------------|-------------|
| `L4_create_and_test`  | 创建模块 + 编写 unittest + 运行测试并修复 | write, bash |
| `L4_refactor_module`  | 重构旧代码（f-string/列表推导/类型标注）    | read, edit  |
| `L4_project_scaffold` | 搭建完整 Python 包结构并验证可导入        | write, bash |

## 命令行参数

```
python benchmark/run.py [OPTIONS]

运行控制:
  --level LEVEL         指定级别，逗号分隔 (例如: "1,2")
  --task TASK           运行单项任务 (例如: "L3_multi_file_edit")
  --dry-run             仅列出任务，不执行
  --retries N           失败重试次数 (默认: 1)
  --timeout SECONDS     单任务超时秒数 (默认: 180)
  --keep-workspace      保留临时工作区以便调试
  --json                以 JSON 格式输出结果（用于 CI）

基线管理:
  --baseline [NAME]     运行后将结果保存为基线 (默认名称: "main")
  --compare NAME        运行后与已保存的基线对比
  --baselines           列出所有已保存的基线
  --delete-baseline NAME  删除指定基线
```

### 基线对比工作流 (度量提示词好坏)

这是 benchmark 的核心场景——修改 `mangopi_cli.py` 中的 system prompt 后，对比效果变化。

```bash
# 1. 建立基线 (当前提示词的表现)
python benchmark/run.py --level 1,2 --baseline main

# 2. 修改 mangopi_cli.py 中的 system prompt (如 _build_tool_guidance)
#    ...

# 3. 对比新提示词与基线的差异
python benchmark/run.py --level 1,2 --compare main
```

对比报告会逐任务展示：

```
Task                                 Pass        Tools         Tokens         Time
----------------------------------------------------------------------------------
L1_read_file                              1→1      0 1,114→1,102   -12.0 4.0s→3.6s -0.3s
L2_read_and_write                         3→5  +2  ⬆ 1,660→2,340  +680.0 8.3s→12.1s +3.8s (REGRESSION)
...

Summary:
  Pass rate:  7/7  →  5/7  (2 regressions)
  Total tokens: 9,525  →  12,300  (+2,775)
  Total tool calls: 16  →  22  (+6 ⬆)
  Tool trend: +1.2 avg per task (more tools)

Tool usage distribution:
  read                     ████████░░░░░░░░░░░░   5→8 (+3)
  write                    ██████░░░░░░░░░░░░░░   3→4 (+1)
```

**关键信息：**
- 报告顶部显示基线/当前的 system prompt hash，明确标注 "CHANGED" 或 "UNCHANGED"
- 如果 tasks 定义有变化也会警告
- `--baselines` 列出所有基线，含 prompt hash、模型、通过率

```bash
# 查看基线列表
python benchmark/run.py --baselines

# 输出:
# Name        Created                 Model              Pass    Prompt            Tasks
# main        2026-06-15T09:48:03     deepseek-v4-pro    3/3     5d218be0509edbdf  364eaed31e64f55d
# no-tool-guide 2026-06-15T10:00:00   deepseek-v4-pro    2/3     a1b2c3d4e5f67890  364eaed31e64f55d
```

### 常用场景

```bash
# CI 集成 — 输出 JSON (自动包含 prompt_hash)
python benchmark/run.py --json > benchmark_results.json

# 快速冒烟测试
python benchmark/run.py --level 1

# 调试单个失败任务
python benchmark/run.py --keep-workspace --retries 0 --task L4_project_scaffold

# 严格模式 — 不重试
python benchmark/run.py --retries 0
```

## 报告解读

### 表格输出 (默认)

```
Task                                Level  Pass  Tools    Time   Tokens Iters
-----------------------------------------------------------------------------
L1_read_file                            1     ✓      1    4.6s   1,119     2
L1_search_python_files                  1     ✓      1    5.3s   1,262     2
...
-----------------------------------------------------------------------------
Results: 14/14 passed  |  Total time: 164.0s  |  Total tokens: 31,116
  L1: ███ 3/3
  L2: ████ 4/4
  L3: ████ 4/4
  L4: ███ 3/3

Avg tool calls/task: 5.0  |  Avg tokens/task: 2,222  |  Avg time/task: 11.7s

Tool usage distribution:
  read                     █████░░░░░░░░░░░░░░░   18 ( 25.7%)
  bash                     ███░░░░░░░░░░░░░░░░░   13 ( 18.6%)
  ...
```

各列含义：

- **Tools** — Agent 调用的工具总次数
- **Time** — 墙钟时间
- **Tokens** — 上下文中的 token 估算总量
- **Iters** — Agent 与 LLM 的交互轮次（每轮 = 一次 API 调用）

效率标记：
- `(inefficient: N tool calls, expected ≤M)` — 任务完成但工具调用超出预期，可能存在重复或低效路径

### JSON 输出 (CI)

```json
{
  "summary": {
    "total": 14, "passed": 13, "failed": 1,
    "total_time_s": 164.0, "total_tokens": 31116,
    "model": "deepseek-v4-pro",
    "timestamp": "2026-06-15T09:28:39"
  },
  "results": [
    {
      "task": "L1_read_file", "level": 1, "passed": true,
      "tool_call_count": 1, "wall_time_s": 4.6,
      "total_tokens": 1119, "iterations": 2,
      "tool_calls": ["read"], "detail": "OK · 1 tools, 4.6s"
    }
  ]
}
```

## 添加新任务

继承 `BenchmarkTask` 或 `_FileContentTask`：

```python
# 文件内容验证类
class MyNewTask(_FileContentTask):
    name = "L3_my_new_task"
    description = "描述这个任务在测什么"
    level = 3
    max_tool_calls = 8
    prompt = "自然语言的需求描述"
    setup_files = {"input.txt": "initial content"}
    expected_file = "output.txt"
    expected_contains = "must contain this"
    expected_not_contains = "must NOT contain this"

# 在 tasks.py 末尾注册
ALL_TASKS = [..., MyNewTask()]
```

对于复杂验证逻辑，直接重写 `verify(workspace)` 方法，返回 `(passed: bool, detail: str)`。

## 设计约束

- **零外部依赖** — 与主项目一致，仅使用 Python stdlib
- **隔离执行** — 每个任务在独立 tempdir 中运行，互不干扰
- **Console 静默** — Agent 运行期间禁用所有终端输出，避免干扰结果采集
- **自动确认** — 危险命令和编辑操作在评测模式下自动确认
- **非确定性容错** — 通过重试机制应对 LLM 响应的随机性
