"""Shipped preset — codemode: Code Mode / 程序化工具调用 (PTC).
Shipped preset — codemode: Code Mode / Programmatic Tool Calling (PTC).

标准工具集 + run_code 扩展. 模型编写一段 Python 脚本, 将多步工具操作编排进
一次执行, 减少模型往返次数与 token 消耗 (中间工具结果不进对话, 只有
print 输出回流). 对齐 DeepSeek Harness Code Mode, 适配 Mangopi 的 Python
exec() 运行时.
Standard tools + run_code extension. The model writes a Python script that
orchestrates multiple tool calls in one execution, reducing round-trips and
token usage (intermediate tool results stay out of the conversation; only
print output flows back). Mirrors DeepSeek Harness Code Mode, adapted for
Mangopi's Python exec() runtime.

目录结构 / Layout:
  ~/.mangocli/presets/codemode/
  ├── conf.py              # 本文件: 总配置 (keep_tools 白名单 + prompt_overrides)
  └── extensions/
      └── run_code.py      # PTC 工具扩展

启用 / Enable: 将本目录复制到 ~/.mangocli/presets/ 后, 以 `MANGO_PRESET=codemode` 启动
mangopi-cli (需同时复制 examples/extensions/run_code.py).
Copy this directory into ~/.mangocli/presets/ and start with `MANGO_PRESET=codemode`
(also copy examples/extensions/run_code.py into its extensions/ dir).

字段 / Fields:
  * keep_tools  — 白名单: TOOLS 只剩名单内工具 (内置 + 扩展统一过滤);
                  whitelist: TOOLS keeps only listed tools (built-in + extensions).
  * prompt_overrides.append_sections — 追加 Code Mode 专用 prompt 段:
                  code_only_instruction (CODE_ONLY_INSTRUCTION) + tools_sdk
                  (CODE_MODE_SDK); 文本参考 code-mode-full-system-prompt.md;
                  appends Code-Mode prompt sections: usage instruction + SDK
                  declarations (see code-mode-full-system-prompt.md).
"""

_CODE_ONLY_INSTRUCTION = (
    "`run_code` is the only tool you can call directly — a tool call naming "
    "any other tool fails. Reach every tool the API declares below from "
    "inside the program."
)

_CODE_MODE_SDK = """## Writing code for run_code

`run_code` takes two required arguments: `code` — a Python script (top-level statements; top-level `return` is not supported) — and `description`, a short summary of what the program does. At run time the following functions are bound in the execution scope. Everything else is standard Python. Inside the program:

- Call tools directly: `read(path)`, `write(path, content)`, `edit(path, old, new)`, `search(pat)`, `grep(pat)`, `bash(cmd)`. Every call returns a string result. Tool arguments must be valid Python values.
- A FAILED tool call raises `ToolError` with a human-readable message — wrap in `try/except ToolError` to handle and continue.
- Emit results with `print(...)`. ONLY what you print comes back to you — intermediate tool results never enter the conversation, so extract just what you need.

Available API:

```python
def read(path: str) -> str
    \"\"\"Read a text file and return its content.\"\"\"

def write(path: str, content: str) -> str
    \"\"\"Write content to a file (overwrite or create).\"\"\"

def edit(path: str, old: str, new: str) -> str
    \"\"\"Replace old string with new string in the file at path.\"\"\"

def search(pat: str) -> str
    \"\"\"Search files matching a glob pattern, sorted by modification time.\"\"\"

def grep(pat: str, path: str = ".") -> str
    \"\"\"Search for pattern in file contents recursively.\"\"\"

def bash(cmd: str) -> str
    \"\"\"Execute a shell command (60s timeout, output filtered).\"\"\"
```
"""

preset = {
    "name": "codemode",
    "description": "PTC mode: run_code as the only directly callable tool, others via script SDK",
    "keep_tools": [
        "run_code",
        "attempt_completion",
    ],
    "prompt_overrides": {
        "append_sections": [
            {"name": "code_only_instruction", "content": _CODE_ONLY_INSTRUCTION},
            {"name": "tools_sdk", "content": _CODE_MODE_SDK},
        ],
    },
}
