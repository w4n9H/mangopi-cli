"""Benchmark task definitions — end-to-end scenarios that evaluate the AI agent.

Each task:
    - Sets up initial files in the workspace
    - Sends a natural-language prompt to the agent
    - Verifies the workspace state after agent completion

Task levels:
    L1 — single-tool, trivial (1-2 tool calls)
    L2 — two-tool, simple (2-4 tool calls)
    L3 — multi-step (4-8 tool calls)
    L4 — complex workflow (8+ tool calls)
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Tuple

from benchmark.base import BenchmarkTask


# ═══════════════════════════════════════════════════════════════════════════════
# Helper task subclasses
# ═══════════════════════════════════════════════════════════════════════════════


class _FileContentTask(BenchmarkTask):
    """Task that verifies a file exists with expected content."""
    expected_file: str = ""
    expected_contains: str = ""
    expected_not_contains: str = ""

    def verify(self, workspace: str) -> Tuple[bool, str]:
        path = os.path.join(workspace, self.expected_file)
        if not os.path.isfile(path):
            return False, f"expected file '{self.expected_file}' not found"
        content = open(path, encoding="utf-8").read()
        if self.expected_contains and self.expected_contains not in content:
            return False, f"'{self.expected_file}' missing expected content: '{self.expected_contains[:80]}'"
        if self.expected_not_contains and self.expected_not_contains in content:
            return False, f"'{self.expected_file}' still contains forbidden: '{self.expected_not_contains[:80]}'"
        return True, ""


class _FileCountTask(BenchmarkTask):
    """Task that verifies a file contains an expected count."""
    result_file: str = ""
    min_count: int = 0

    def verify(self, workspace: str) -> Tuple[bool, str]:
        path = os.path.join(workspace, self.result_file)
        if not os.path.isfile(path):
            return False, f"result file '{self.result_file}' not found"
        content = open(path, encoding="utf-8").read()
        numbers = re.findall(r'\d+', content)
        if not numbers:
            return False, f"no number found in '{self.result_file}'"
        count = int(numbers[0])
        if count < self.min_count:
            return False, f"count {count} < expected min {self.min_count}"
        return True, ""


# ═══════════════════════════════════════════════════════════════════════════════
# Level 1 — single-tool tasks
# ═══════════════════════════════════════════════════════════════════════════════


class ReadFileTask(_FileContentTask):
    name = "L1_read_file"
    description = "Read an existing file and report its content"
    level = 1
    max_tool_calls = 3
    prompt = "Read the file named 'data.txt' and tell me what it says."
    setup_files = {"data.txt": "Hello, this is the content of data.txt.\nIt has two lines."}
    expected_file = "data.txt"

    def verify(self, workspace: str) -> Tuple[bool, str]:
        # For read tasks, we check that the file was NOT modified
        path = os.path.join(workspace, "data.txt")
        if not os.path.isfile(path):
            return False, "data.txt was deleted"
        content = open(path, encoding="utf-8").read()
        if "Hello, this is the content" not in content:
            return False, "data.txt content was modified"
        return True, ""


class SearchPythonFilesTask(_FileContentTask):
    name = "L1_search_python_files"
    description = "Glob-search for all Python files"
    level = 1
    max_tool_calls = 3
    prompt = "Find all Python (.py) files in the current project directory."
    setup_files = {
        "src/main.py": "print('hello')",
        "src/utils/helpers.py": "def add(a, b): return a + b",
        "tests/test_main.py": "import unittest",
        "README.md": "# Project",
        "config.json": "{}",
    }
    expected_file = "README.md"  # just verify no files were modified

    def verify(self, workspace: str) -> Tuple[bool, str]:
        for path in ["src/main.py", "src/utils/helpers.py", "tests/test_main.py", "README.md", "config.json"]:
            if not os.path.isfile(os.path.join(workspace, path)):
                return False, f"'{path}' was deleted"
        return True, ""


class GrepTodoTask(_FileContentTask):
    name = "L1_grep_todo"
    description = "Grep for TODO comments in source files"
    level = 1
    max_tool_calls = 3
    prompt = "Find all lines containing 'TODO' in the Python files in this project."
    setup_files = {
        "src/app.py": "# TODO: implement login\nprint('app')\n# TODO: add logging",
        "src/utils.py": "def process():\n    # FIXME: optimize\n    pass",
        "src/models.py": "# NOTE: this is fine\nclass User:\n    pass",
    }
    expected_file = "src/app.py"

    def verify(self, workspace: str) -> Tuple[bool, str]:
        for path in ["src/app.py", "src/utils.py", "src/models.py"]:
            if not os.path.isfile(os.path.join(workspace, path)):
                return False, f"'{path}' was deleted"
        return True, ""


# ═══════════════════════════════════════════════════════════════════════════════
# Level 2 — two-tool tasks
# ═══════════════════════════════════════════════════════════════════════════════


class ReadAndWriteTask(_FileContentTask):
    name = "L2_read_and_write"
    description = "Read a file, extract content, write to new file"
    level = 2
    max_tool_calls = 6
    prompt = (
        "Read the file 'source.txt', then create a new file called 'target.txt' "
        "that contains only the line(s) from source.txt that start with 'IMPORTANT:'."
    )
    setup_files = {"source.txt": "SKIP: this line\nIMPORTANT: this is critical\nSKIP: another\nIMPORTANT: also important\nordinary line"}
    expected_file = "target.txt"
    expected_contains = "IMPORTANT:"

    def verify(self, workspace: str) -> Tuple[bool, str]:
        ok, detail = super().verify(workspace)
        if not ok:
            return ok, detail
        content = open(os.path.join(workspace, "target.txt"), encoding="utf-8").read()
        if "SKIP:" in content:
            return False, "target.txt contains lines that should have been filtered (SKIP:)"
        if "ordinary" in content:
            return False, "target.txt contains unfiltered lines"
        return True, ""


class SearchAndCountTask(_FileCountTask):
    name = "L2_search_and_count"
    description = "Search for files matching a pattern, count them, write result"
    level = 2
    max_tool_calls = 6
    min_count = 3
    result_file = "count.txt"
    prompt = (
        "Count how many Python files (.py) exist in this project, "
        "and write the exact number to a file called 'count.txt'."
    )
    setup_files = {
        "a.py": "", "b.py": "", "c.py": "",
        "d.txt": "", "e.md": "",
        "sub/f.py": "", "sub/g.py": "",
    }


class SimpleEditTask(_FileContentTask):
    name = "L2_simple_edit"
    description = "Edit a file to replace a specific string"
    level = 2
    max_tool_calls = 5
    prompt = (
        "In the file 'config.json', change the value of 'debug' from 'false' to 'true'."
    )
    setup_files = {"config.json": '{\n  "debug": false,\n  "port": 8080\n}'}
    expected_file = "config.json"
    expected_contains = '"debug": true'
    expected_not_contains = '"debug": false'


class BashListAndWriteTask(_FileContentTask):
    name = "L2_bash_list_and_write"
    description = "Use bash to list files and write to a file"
    level = 2
    max_tool_calls = 5
    prompt = (
        "Run 'ls -la' to list all files in the current directory, "
        "then save the output to 'listing.txt'."
    )
    setup_files = {"file1.txt": "a", "file2.txt": "b"}
    expected_file = "listing.txt"
    expected_contains = "file1.txt"


# ═══════════════════════════════════════════════════════════════════════════════
# Level 3 — multi-step tasks
# ═══════════════════════════════════════════════════════════════════════════════


class CreatePythonModuleTask(_FileContentTask):
    name = "L3_create_python_module"
    description = "Create a Python module with two functions"
    level = 3
    max_tool_calls = 10
    prompt = (
        "Create a file called 'calculator.py' with two functions: "
        "add(a, b) that returns a+b, and multiply(a, b) that returns a*b. "
        "Include type hints and a docstring for the module."
    )
    setup_files = {}
    expected_file = "calculator.py"
    expected_contains = "def add"

    def verify(self, workspace: str) -> Tuple[bool, str]:
        ok, detail = super().verify(workspace)
        if not ok:
            return ok, detail
        path = os.path.join(workspace, "calculator.py")
        content = open(path, encoding="utf-8").read()
        if "def multiply" not in content:
            return False, "calculator.py missing multiply function"
        if "def add" not in content:
            return False, "calculator.py missing add function"
        # Try to import and use it
        sys.path.insert(0, workspace)
        try:
            import calculator  # noqa: F811
            import importlib
            importlib.reload(calculator)
            if calculator.add(2, 3) != 5:
                return False, "add(2,3) != 5"
            if calculator.multiply(4, 5) != 20:
                return False, "multiply(4,5) != 20"
        except Exception as e:
            return False, f"calculator.py import/execution error: {e}"
        finally:
            sys.path.remove(workspace)
        return True, ""


class MultiFileEditTask(_FileContentTask):
    name = "L3_multi_file_edit"
    description = "Edit multiple files to replace a common pattern"
    level = 3
    max_tool_calls = 12
    prompt = (
        "In ALL Python files in the 'src/' directory, replace the string "
        "'OLD_API_KEY' with 'NEW_API_KEY'. Do NOT modify files outside src/."
    )
    setup_files = {
        "src/config.py": "API_KEY = 'OLD_API_KEY'\nSECRET = 'OLD_API_KEY'",
        "src/auth.py": "key = 'OLD_API_KEY'\n# use OLD_API_KEY here",
        "src/utils/helpers.py": "# placeholder: OLD_API_KEY",
        "tests/test_config.py": "# test with OLD_API_KEY (should NOT be changed)",
    }
    expected_file = "src/config.py"
    expected_contains = "NEW_API_KEY"
    expected_not_contains = "OLD_API_KEY"

    def verify(self, workspace: str) -> Tuple[bool, str]:
        # src files should NOT contain OLD_API_KEY
        for path in ["src/config.py", "src/auth.py", "src/utils/helpers.py"]:
            full = os.path.join(workspace, path)
            if not os.path.isfile(full):
                return False, f"'{path}' missing"
            content = open(full, encoding="utf-8").read()
            if "OLD_API_KEY" in content:
                return False, f"'{path}' still contains OLD_API_KEY"
            if "NEW_API_KEY" not in content:
                return False, f"'{path}' missing NEW_API_KEY"
        # tests/test_config.py should NOT be modified
        test_path = os.path.join(workspace, "tests/test_config.py")
        if not os.path.isfile(test_path):
            return False, "tests/test_config.py missing"
        test_content = open(test_path, encoding="utf-8").read()
        if "OLD_API_KEY" not in test_content:
            return False, "tests/test_config.py was incorrectly modified (OLD_API_KEY removed)"
        if "NEW_API_KEY" in test_content:
            return False, "tests/test_config.py was incorrectly modified (NEW_API_KEY added)"
        return True, ""


class DataProcessingTask(_FileContentTask):
    name = "L3_data_processing"
    description = "Extract and format data from JSON, write CSV"
    level = 3
    max_tool_calls = 10
    prompt = (
        "Read 'users.json', extract the email addresses of all users who are "
        "'active', sort them alphabetically, and write them one per line to "
        "'active_emails.txt'."
    )
    setup_files = {
        "users.json": json.dumps([
            {"name": "Alice", "email": "alice@example.com", "status": "active"},
            {"name": "Bob", "email": "bob@test.com", "status": "inactive"},
            {"name": "Charlie", "email": "charlie@example.com", "status": "active"},
            {"name": "Diana", "email": "diana@test.com", "status": "active"},
            {"name": "Eve", "email": "eve@example.com", "status": "inactive"},
        ], indent=2),
    }
    expected_file = "active_emails.txt"
    expected_contains = "alice@example.com"

    def verify(self, workspace: str) -> Tuple[bool, str]:
        path = os.path.join(workspace, "active_emails.txt")
        if not os.path.isfile(path):
            return False, "active_emails.txt not found"
        lines = [l.strip() for l in open(path, encoding="utf-8").readlines() if l.strip()]
        if len(lines) != 3:
            return False, f"expected 3 emails, got {len(lines)}: {lines}"
        expected = sorted(["alice@example.com", "charlie@example.com", "diana@test.com"])
        actual = sorted(lines)
        if actual != expected:
            return False, f"expected {expected}, got {actual}"
        # Verify sorted order
        if lines != sorted(lines):
            return False, "emails not sorted alphabetically"
        return True, ""


class BashPipelineTask(_FileContentTask):
    name = "L3_bash_pipeline"
    description = "Use bash pipeline to find and process files"
    level = 3
    max_tool_calls = 6
    prompt = (
        "Find all .txt files in the 'logs/' directory, count the total number "
        "of lines across all of them, and write just the number to 'total_lines.txt'."
    )
    setup_files = {
        "logs/a.txt": "line 1\nline 2\nline 3\n",
        "logs/b.txt": "line 4\nline 5\n",
        "logs/c.txt": "",
        "logs/d.log": "not a txt\n",
    }
    expected_file = "total_lines.txt"
    expected_contains = "5"

    def verify(self, workspace: str) -> Tuple[bool, str]:
        ok, detail = super().verify(workspace)
        if not ok:
            return ok, detail
        content = open(os.path.join(workspace, "total_lines.txt"), encoding="utf-8").read().strip()
        if content != "5":
            return False, f"expected total_lines.txt to contain '5', got '{content}'"
        return True, ""


# ═══════════════════════════════════════════════════════════════════════════════
# Level 4 — complex workflow tasks
# ═══════════════════════════════════════════════════════════════════════════════


class CreateAndTestModuleTask(_FileContentTask):
    name = "L4_create_and_test"
    description = "Create a Python module, write tests, and run them"
    level = 4
    max_tool_calls = 16
    timeout = 180
    prompt = (
        "1. Create a file 'mathlib.py' with functions: factorial(n), is_prime(n), gcd(a, b). "
        "Include docstrings and type hints.\n"
        "2. Create a test file 'test_mathlib.py' with unittest cases for all three functions.\n"
        "3. Run the tests with 'python -m unittest test_mathlib.py' and confirm they pass.\n"
        "Fix any test failures before reporting completion."
    )
    setup_files = {}
    expected_file = "mathlib.py"
    expected_contains = "def factorial"

    def verify(self, workspace: str) -> Tuple[bool, str]:
        path = os.path.join(workspace, "mathlib.py")
        if not os.path.isfile(path):
            return False, "mathlib.py not found"
        test_path = os.path.join(workspace, "test_mathlib.py")
        if not os.path.isfile(test_path):
            return False, "test_mathlib.py not found"

        content = open(path, encoding="utf-8").read()
        for fn in ["factorial", "is_prime", "gcd"]:
            if f"def {fn}" not in content:
                return False, f"mathlib.py missing function '{fn}'"

        sys.path.insert(0, workspace)
        try:
            import mathlib  # noqa: F811
            import importlib
            importlib.reload(mathlib)
            assert mathlib.factorial(5) == 120, "factorial(5) != 120"
            assert mathlib.is_prime(7) is True, "is_prime(7) != True"
            assert mathlib.is_prime(4) is False, "is_prime(4) != False"
            assert mathlib.gcd(12, 8) == 4, "gcd(12,8) != 4"
        except Exception as e:
            return False, f"mathlib import/execution error: {e}"
        finally:
            sys.path.remove(workspace)
        return True, ""


class RefactorTask(_FileContentTask):
    name = "L4_refactor_module"
    description = "Refactor a Python file to use modern patterns"
    level = 4
    max_tool_calls = 12
    timeout = 180
    prompt = (
        "The file 'old_utils.py' uses outdated patterns. Refactor it:\n"
        "1. Replace string concatenation with f-strings.\n"
        "2. Replace the manual loop in 'find_even' with a list comprehension.\n"
        "3. Add type hints to all function signatures.\n"
        "Do NOT change any function names or signatures beyond adding type hints."
    )
    setup_files = {
        "old_utils.py": (
            "def greet(name):\n"
            "    return 'Hello, ' + name + '!'\n\n"
            "def find_even(numbers):\n"
            "    result = []\n"
            "    for n in numbers:\n"
            "        if n % 2 == 0:\n"
            "            result.append(n)\n"
            "    return result\n\n"
            "def format_price(amount):\n"
            "    return '$' + str(amount)\n"
        ),
    }
    expected_file = "old_utils.py"
    expected_contains = "def greet(name:"
    expected_not_contains = "+ name +"

    def verify(self, workspace: str) -> Tuple[bool, str]:
        path = os.path.join(workspace, "old_utils.py")
        if not os.path.isfile(path):
            return False, "old_utils.py not found"
        content = open(path, encoding="utf-8").read()
        # Must NOT have old patterns
        if "'Hello, ' + name" in content or '"Hello, " + name' in content:
            return False, "old_utils.py still uses string concatenation in greet()"
        if "result = []" in content and "result.append" in content:
            return False, "old_utils.py still uses manual loop in find_even()"
        # Must have new patterns
        if "def find_even" not in content:
            return False, "old_utils.py missing find_even function"
        if "def greet" not in content:
            return False, "old_utils.py missing greet function"
        if "def format_price" not in content:
            return False, "old_utils.py missing format_price function"
        # Should have type hints
        if "def greet(name:" not in content:
            return False, "old_utils.py missing type hints (or greet was deleted)"
        # Verify it still runs
        sys.path.insert(0, workspace)
        try:
            import old_utils  # noqa: F811
            import importlib
            importlib.reload(old_utils)
            assert old_utils.greet("World") == "Hello, World!"
            assert old_utils.find_even([1, 2, 3, 4]) == [2, 4]
            assert old_utils.format_price(42) == "$42"
        except Exception as e:
            return False, f"old_utils.py execution error: {e}"
        finally:
            sys.path.remove(workspace)
        return True, ""


class ProjectScaffoldTask(_FileContentTask):
    name = "L4_project_scaffold"
    description = "Scaffold a minimal Python package structure"
    level = 4
    max_tool_calls = 14
    timeout = 180
    prompt = (
        "Create a minimal Python package called 'mypkg' with the following structure:\n"
        "  mypkg/__init__.py  — exports a 'version' string\n"
        "  mypkg/core.py      — has a function 'hello()' that returns 'Hello from mypkg!'\n"
        "  setup.py           — minimal setup script with name='mypkg', version from mypkg.__version__\n"
        "After creating the files, verify the package can be imported."
    )
    setup_files = {}
    expected_file = "mypkg/__init__.py"
    expected_contains = "version"

    def verify(self, workspace: str) -> Tuple[bool, str]:
        for path in ["mypkg/__init__.py", "mypkg/core.py", "setup.py"]:
            if not os.path.isfile(os.path.join(workspace, path)):
                return False, f"'{path}' not found"

        # Verify mypkg can be imported
        sys.path.insert(0, workspace)
        try:
            import mypkg  # noqa: F811
            import importlib
            importlib.reload(mypkg)
            assert hasattr(mypkg, "version"), "mypkg missing 'version'"
            assert isinstance(mypkg.version, str), "mypkg.version is not a string"
            from mypkg.core import hello
            assert hello() == "Hello from mypkg!", f"hello() returned '{hello()}'"
        except Exception as e:
            return False, f"mypkg import error: {e}"
        finally:
            sys.path.remove(workspace)
        return True, ""


# ═══════════════════════════════════════════════════════════════════════════════
# Task registry
# ═══════════════════════════════════════════════════════════════════════════════

ALL_TASKS: list = [
    # L1 — single tool
    ReadFileTask(),
    SearchPythonFilesTask(),
    GrepTodoTask(),
    # L2 — two tools
    ReadAndWriteTask(),
    SearchAndCountTask(),
    SimpleEditTask(),
    BashListAndWriteTask(),
    # L3 — multi-step
    CreatePythonModuleTask(),
    MultiFileEditTask(),
    DataProcessingTask(),
    BashPipelineTask(),
    # L4 — complex
    CreateAndTestModuleTask(),
    RefactorTask(),
    ProjectScaffoldTask(),
]

TASKS_BY_NAME = {t.name: t for t in ALL_TASKS}
TASKS_BY_LEVEL = {lv: [t for t in ALL_TASKS if t.level == lv] for lv in [1, 2, 3, 4]}
