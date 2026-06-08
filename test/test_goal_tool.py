"""Tests for GoalTool — covers plan / step / show / finish actions.

Covers:
    * action='plan' — create / refuse-to-overwrite / validation errors
    * action='step' — mark done/failed, sequential vs non-sequential advance,
      last-step prompt wording, edge cases (no active goal, bad number,
      bad status)
    * action='show' — view current goal / default action
    * action='finish' — clear the goal file / idempotent re-finish
    * unknown action rejection
    * Full plan→show→step→step→step→show→finish workflow
    * Edge cases: special-character step text, corrupted goal.json
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

# Add parent dir to sys.path so we can import mangopi_cli.
# This file lives at <project>/test/test_goal_tool.py,
# so the project root is one level up from __file__'s directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mangopi_cli  # noqa: E402


# ── Shared base: each test gets a fresh temp goal.json ─────────────────────


class _GoalToolBase(unittest.TestCase):
    """Base class: each test gets its own tmpdir-based goal.json.

    setUp creates the dir + sets `mangopi_cli.goal_file` to a fresh
    per-test path. tearDown restores the original path and removes the
    tmpdir tree.
    """

    def setUp(self):
        self._orig_goal_file = mangopi_cli.goal_file
        self.tmpdir = tempfile.mkdtemp(prefix="mangopi_test_goal_")
        persist_dir = os.path.join(self.tmpdir, ".mangocli")
        os.makedirs(persist_dir, exist_ok=True)
        self.goal_file = os.path.join(persist_dir, "goal.json")
        mangopi_cli.goal_file = self.goal_file

    def tearDown(self):
        mangopi_cli.goal_file = self._orig_goal_file
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _tool(self):
        return mangopi_cli.GoalTool()

    def _plan(self, goal, steps_desc, action="plan"):
        return self._tool().run({
            "action": action,
            "goal": goal,
            "steps": json.dumps(steps_desc),
        })

    def _step(self, step, status="done", note=None):
        args = {"action": "step", "step": step, "status": status}
        if note is not None:
            args["note"] = note
        return self._tool().run(args)

    def _load(self):
        with open(self.goal_file, "r", encoding="utf-8") as f:
            return json.load(f)


# ── 1. action='plan' ───────────────────────────────────────────────────────


class TestPlanAction(_GoalToolBase):
    """GoalTool.run({action: 'plan', ...}) creates a new goal file."""

    def test_01_plan_creates_goal(self):
        r = self._plan("写一个完整的测试", ["第一步", "第二步", "第三步"])
        self.assertTrue(r["success"], r)
        self.assertIn("plan: 3 steps", r["content"])
        # File is written, and shape matches the documented structure.
        self.assertTrue(os.path.exists(self.goal_file))
        g = self._load()
        self.assertEqual(g["goal"], "写一个完整的测试")
        self.assertEqual(len(g["steps"]), 3)
        self.assertEqual(g["current"], 0)
        self.assertTrue(all(s["status"] == "pending" for s in g["steps"]))

    def test_02_plan_refuses_to_overwrite_active_goal(self):
        """An active (not-yet-finished) goal must NOT be silently overwritten
        by a new plan. The new plan must be refused with a clear message."""
        # First plan: succeeds.
        self._plan("旧目标", ["旧步骤"])
        # Second plan: refused because the first goal is still active.
        r = self._plan("新目标", ["新步骤A", "新步骤B"])
        self.assertFalse(r["success"], r)
        self.assertIn("refused", r["content"])
        self.assertIn("active goal", r["content"])
        # And the original goal on disk is unchanged.
        g = self._load()
        self.assertEqual(g["goal"], "旧目标")

    def test_03_plan_requires_goal(self):
        r = self._tool().run({"action": "plan", "steps": json.dumps(["step1"])})
        self.assertFalse(r["success"])
        self.assertIn("requires 'goal'", r["content"])

    def test_04_plan_requires_steps(self):
        r = self._tool().run({"action": "plan", "goal": "测试目标"})
        self.assertFalse(r["success"])
        self.assertIn("requires 'goal'", r["content"])

    def test_05_plan_rejects_invalid_json_steps(self):
        r = self._plan("目标", ["ignored"])  # overwritten below
        r = self._tool().run({
            "action": "plan",
            "goal": "目标",
            "steps": "这不是json",
        })
        self.assertFalse(r["success"], r)
        self.assertIn("invalid steps", r["content"].lower())

    def test_06_plan_rejects_non_array_steps(self):
        r = self._tool().run({
            "action": "plan",
            "goal": "目标",
            "steps": json.dumps({"a": 1}),
        })
        self.assertFalse(r["success"], r)
        self.assertIn("must be non-empty JSON array", r["content"])

    def test_07_plan_rejects_empty_array_steps(self):
        r = self._tool().run({
            "action": "plan",
            "goal": "目标",
            "steps": "[]",
        })
        self.assertFalse(r["success"], r)
        self.assertIn("must be non-empty JSON array", r["content"])

    def test_08_plan_with_single_step(self):
        r = self._plan("单步任务", ["唯一步骤"])
        self.assertTrue(r["success"], r)
        g = self._load()
        self.assertEqual(len(g["steps"]), 1)


# ── 2. action='step' ───────────────────────────────────────────────────────


class TestStepAction(_GoalToolBase):
    """GoalTool.run({action: 'step', ...}) updates one step's status."""

    def test_09_step_mark_done(self):
        self._plan("测试", ["s1", "s2", "s3"])
        r = self._step(1, "done")
        self.assertTrue(r["success"], r)
        self.assertIn("step 1 done", r["content"])
        g = self._load()
        self.assertEqual(g["steps"][0]["status"], "done")
        self.assertEqual(g["current"], 1)  # sequential → advanced

    def test_10_step_mark_failed(self):
        self._plan("测试", ["s1", "s2"])
        r = self._step(1, "failed")
        self.assertTrue(r["success"], r)
        self.assertIn("step 1 failed", r["content"])
        g = self._load()
        self.assertEqual(g["steps"][0]["status"], "failed")
        # failed does NOT advance current.
        self.assertEqual(g["current"], 0)

    def test_11_step_with_note(self):
        self._plan("测试", ["s1"])
        r = self._step(1, "done", note="pytest 5/5 passed")
        self.assertTrue(r["success"], r)
        g = self._load()
        self.assertEqual(g["steps"][0]["note"], "pytest 5/5 passed")

    def test_12_step_default_status_done(self):
        self._plan("测试", ["s1"])
        r = self._tool().run({"action": "step", "step": 1})  # no status
        self.assertTrue(r["success"], r)
        self.assertIn("step 1 done", r["content"])

    def test_13_step_invalid_status(self):
        self._plan("测试", ["s1"])
        r = self._step(1, "skipped")
        self.assertFalse(r["success"])
        self.assertIn("invalid status", r["content"])

    def test_14_step_no_active_goal(self):
        r = self._tool().run({"action": "step", "step": 1, "status": "done"})
        self.assertFalse(r["success"])
        self.assertIn("no active goal", r["content"].lower())

    def test_15_step_invalid_number(self):
        self._plan("测试", ["s1", "s2"])
        # step 0 invalid (1-indexed).
        r = self._step(0, "done")
        self.assertFalse(r["success"], r)
        # step 3 out of range.
        r = self._step(3, "done")
        self.assertFalse(r["success"], r)

    def test_16_step_sequential_advance(self):
        """Completing all 4 steps in order advances `current` to 4, and
        the final response announces completion with the documented
        'ALL STEPS DONE' marker (case-insensitive)."""
        self._plan("顺序任务", ["s1", "s2", "s3", "s4"])
        last_response = None
        for i in range(1, 5):
            last_response = self._step(i, "done")
            self.assertTrue(last_response["success"], last_response)
        g = self._load()
        self.assertEqual(g["current"], 4)
        # Implementation uses "ALL STEPS DONE"; we match it case-insensitively.
        self.assertIn("all steps done", last_response["content"].lower())

    def test_17_step_non_sequential_no_advance(self):
        """Skipping ahead (e.g. completing step 2 while step 1 is still
        pending) must NOT advance `current`."""
        self._plan("测试", ["s1", "s2", "s3"])
        r = self._step(2, "done")
        self.assertTrue(r["success"], r)
        g = self._load()
        self.assertEqual(g["steps"][1]["status"], "done")
        self.assertEqual(g["current"], 0)

    def test_18_step_last_step_prompt_finish(self):
        """The last step's response must prompt the agent to call
        action='finish' (case-insensitive substring match)."""
        self._plan("测试", ["s1", "s2"])
        self._step(1, "done")
        r = self._step(2, "done")
        self.assertIn("all steps done", r["content"].lower())
        self.assertIn("finish", r["content"].lower())

    def test_19_step_not_last_prompt_next(self):
        """Non-last step response must mention the next step number."""
        self._plan("测试", ["s1", "s2", "s3"])
        r = self._step(1, "done")
        self.assertIn("next: step 2", r["content"])


# ── 3. action='show' ───────────────────────────────────────────────────────


class TestShowAction(_GoalToolBase):
    """GoalTool.run({action: 'show'}) returns the current goal JSON."""

    def test_20_show_active_goal(self):
        self._plan("查看测试", ["a", "b"])
        r = self._tool().run({"action": "show"})
        self.assertTrue(r["success"], r)
        g = json.loads(r["content"])
        self.assertEqual(g["goal"], "查看测试")
        self.assertEqual(len(g["steps"]), 2)

    def test_21_show_no_active_goal(self):
        r = self._tool().run({"action": "show"})
        self.assertFalse(r["success"], r)
        self.assertIn("no active goal", r["content"].lower())

    def test_22_default_action_is_show(self):
        self._plan("默认测试", ["x"])
        r = self._tool().run({})
        self.assertTrue(r["success"], r)
        g = json.loads(r["content"])
        self.assertEqual(g["goal"], "默认测试")


# ── 4. action='finish' ─────────────────────────────────────────────────────


class TestFinishAction(_GoalToolBase):
    """GoalTool.run({action: 'finish'}) clears the goal file."""

    def test_23_finish_clears_goal(self):
        self._plan("结束测试", ["s1"])
        self.assertTrue(os.path.exists(self.goal_file))
        r = self._tool().run({"action": "finish"})
        self.assertTrue(r["success"], r)
        self.assertIn("goal cleared", r["content"].lower())
        self.assertFalse(os.path.exists(self.goal_file))

    def test_24_finish_after_finish(self):
        """Repeat finish must succeed even with no goal file (idempotent)."""
        self._plan("测试", ["s1"])
        self._tool().run({"action": "finish"})
        r = self._tool().run({"action": "finish"})
        self.assertTrue(r["success"], r)


# ── 5. Unknown action ─────────────────────────────────────────────────────


class TestUnknownAction(_GoalToolBase):
    def test_25_unknown_action(self):
        r = self._tool().run({"action": "delete"})
        self.assertFalse(r["success"])
        self.assertIn("unknown action", r["content"])


# ── 6. Full workflow & edge cases ──────────────────────────────────────────


class TestFullWorkflowAndEdges(_GoalToolBase):
    """End-to-end plan → step → step → step → show → finish plus
    a couple of edge cases (special characters, corrupted goal.json).
    """

    def test_26_full_workflow(self):
        t = self._tool()

        # 1. plan
        r = t.run({
            "action": "plan",
            "goal": "完整流程测试",
            "steps": json.dumps(["步骤A", "步骤B", "步骤C"]),
        })
        self.assertTrue(r["success"], r)

        # 2. show
        r = t.run({"action": "show"})
        self.assertTrue(r["success"], r)
        g = json.loads(r["content"])
        self.assertEqual(g["goal"], "完整流程测试")
        self.assertEqual(g["current"], 0)

        # 3. step 1 done
        r = t.run({"action": "step", "step": 1, "status": "done", "note": "第一步完成"})
        self.assertTrue(r["success"], r)
        self.assertIn("step 1 done", r["content"])
        self.assertIn("next: step 2", r["content"])

        # 4. step 2 failed
        r = t.run({"action": "step", "step": 2, "status": "failed", "note": "编译错误"})
        self.assertTrue(r["success"], r)
        self.assertIn("step 2 failed", r["content"])

        # 5. step 3 done
        r = t.run({"action": "step", "step": 3, "status": "done"})
        self.assertTrue(r["success"], r)

        # 6. show final state
        r = t.run({"action": "show"})
        self.assertTrue(r["success"], r)
        g = json.loads(r["content"])
        self.assertEqual(g["steps"][0]["status"], "done")
        self.assertEqual(g["steps"][0]["note"], "第一步完成")
        self.assertEqual(g["steps"][1]["status"], "failed")
        self.assertEqual(g["steps"][1]["note"], "编译错误")
        self.assertEqual(g["steps"][2]["status"], "done")
        # Only step 1 was sequential, so current=1.
        self.assertEqual(g["current"], 1)

        # 7. finish
        r = t.run({"action": "finish"})
        self.assertTrue(r["success"], r)
        self.assertFalse(os.path.exists(self.goal_file))

        # 8. show after finish must fail
        r = t.run({"action": "show"})
        self.assertFalse(r["success"])

    def test_27_steps_with_special_characters(self):
        """Step text with Chinese, emoji, and special punctuation must
        round-trip through the JSON file."""
        r = self._tool().run({
            "action": "plan",
            "goal": "特殊字符测试 🎯",
            "steps": json.dumps([
                "读取 mangopi_cli.py，定位 GoalTool",
                "编写 ✅ 测试",
                "运行 & 验证",
            ]),
        })
        self.assertTrue(r["success"], r)
        g = self._load()
        self.assertIn("🎯", g["goal"])
        self.assertIn("✅", g["steps"][1]["desc"])

    def test_28_step_number_missing_is_failure(self):
        """Omitting the `step` parameter must fail gracefully."""
        self._plan("测试", ["s1", "s2"])
        r = self._tool().run({"action": "step", "status": "done"})
        self.assertFalse(r["success"], r)
        self.assertIn("no active goal or invalid step", r["content"].lower())

    def test_29_goal_file_corrupted(self):
        """A goal.json with invalid JSON must surface as 'no active goal'."""
        with open(self.goal_file, "w") as f:
            f.write("这不是合法的 JSON {{{")
        r = self._tool().run({"action": "show"})
        self.assertFalse(r["success"], r)
        self.assertIn("no active goal", r["content"].lower())


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)