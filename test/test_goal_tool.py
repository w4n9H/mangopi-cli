#!/usr/bin/env python3
"""Test GoalTool —— 验证 goal 工具的 plan/step/show/finish 行为。"""

import sys
import os
import json
import tempfile

# 将项目根目录加到 sys.path，以便 import mangopi_cli 中的 GoalTool
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mangopi_cli

# ── 辅助函数 ──────────────────────────────────────────────

def setup_goal_file():
    """创建一个临时 goal 文件路径，并确保 .mangocli 目录存在。"""
    tmpdir = tempfile.mkdtemp(prefix="mangopi_test_goal_")
    persist_dir = os.path.join(tmpdir, ".mangocli")
    os.makedirs(persist_dir, exist_ok=True)
    goal_file = os.path.join(persist_dir, "goal.json")
    # 重写模块级变量
    mangopi_cli.goal_file = goal_file
    return tmpdir, goal_file

def teardown_goal_file(tmpdir):
    """清理临时目录。"""
    import shutil
    if os.path.exists(tmpdir):
        shutil.rmtree(tmpdir)

def tool():
    """返回一个新的 GoalTool 实例。"""
    return mangopi_cli.GoalTool()

# ── 测试用例 ──────────────────────────────────────────────

passed = 0
failed = 0

def t(name, fn):
    """运行一个测试用例。fn 无参，返回 True/False 或 assert。"""
    global passed, failed
    try:
        fn()
        passed += 1
        print(f"  ✓ {name}")
    except AssertionError as e:
        failed += 1
        print(f"  ✗ {name}  FAIL: {e}")
    except Exception as e:
        failed += 1
        import traceback
        print(f"  ✗ {name}  ERROR: {e}")
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════
#  1. action='plan' — 创建新计划
# ═══════════════════════════════════════════════════════════

def test_01_plan_creates_goal():
    """action='plan' 创建新 goal 并写入文件"""
    tmpdir, gf = setup_goal_file()
    try:
        r = tool().run({
            "action": "plan",
            "goal": "写一个完整的测试",
            "steps": json.dumps(["第一步", "第二步", "第三步"])
        })
        assert r["success"], f"plan 应该成功: {r}"
        assert "plan: 3 steps" in r["content"]
        # 验证文件已写入
        assert os.path.exists(gf), "goal.json 应该存在"
        g = json.load(open(gf))
        assert g["goal"] == "写一个完整的测试"
        assert len(g["steps"]) == 3
        assert g["current"] == 0
        assert all(s["status"] == "pending" for s in g["steps"])
    finally:
        teardown_goal_file(tmpdir)


def test_02_plan_overwrites_existing():
    """创建新 plan 会覆盖旧 goal"""
    tmpdir, gf = setup_goal_file()
    try:
        tool().run({
            "action": "plan",
            "goal": "旧目标",
            "steps": json.dumps(["旧步骤"])
        })
        tool().run({
            "action": "plan",
            "goal": "新目标",
            "steps": json.dumps(["新步骤A", "新步骤B"])
        })
        g = json.load(open(gf))
        assert g["goal"] == "新目标"
        assert len(g["steps"]) == 2
    finally:
        teardown_goal_file(tmpdir)


def test_03_plan_requires_goal():
    """plan 缺少 goal 参数 → 失败"""
    tmpdir, gf = setup_goal_file()
    try:
        r = tool().run({
            "action": "plan",
            "steps": json.dumps(["step1"])
        })
        assert not r["success"], "缺少 goal 应该失败"
        assert "requires 'goal'" in r["content"]
    finally:
        teardown_goal_file(tmpdir)


def test_04_plan_requires_steps():
    """plan 缺少 steps 参数 → 失败"""
    tmpdir, gf = setup_goal_file()
    try:
        r = tool().run({
            "action": "plan",
            "goal": "测试目标"
        })
        assert not r["success"], "缺少 steps 应该失败"
        assert "requires 'goal'" in r["content"]
    finally:
        teardown_goal_file(tmpdir)


def test_05_plan_rejects_invalid_json_steps():
    """steps 不是合法 JSON 数组 → 失败"""
    tmpdir, gf = setup_goal_file()
    try:
        r = tool().run({
            "action": "plan",
            "goal": "目标",
            "steps": "这不是json"
        })
        assert not r["success"], "非法 JSON 应该失败"
        assert "invalid steps" in r["content"].lower()
    finally:
        teardown_goal_file(tmpdir)


def test_06_plan_rejects_non_array_steps():
    """steps 是 JSON 但不是数组 → 失败"""
    tmpdir, gf = setup_goal_file()
    try:
        r = tool().run({
            "action": "plan",
            "goal": "目标",
            "steps": json.dumps({"a": 1})
        })
        assert not r["success"], "非数组 steps 应该失败"
        assert "must be non-empty JSON array" in r["content"]
    finally:
        teardown_goal_file(tmpdir)


def test_07_plan_rejects_empty_array_steps():
    """steps 是空数组 → 失败"""
    tmpdir, gf = setup_goal_file()
    try:
        r = tool().run({
            "action": "plan",
            "goal": "目标",
            "steps": "[]"
        })
        assert not r["success"], "空数组 steps 应该失败"
        assert "must be non-empty JSON array" in r["content"]
    finally:
        teardown_goal_file(tmpdir)


def test_08_plan_with_single_step():
    """只有 1 个 step → 成功"""
    tmpdir, gf = setup_goal_file()
    try:
        r = tool().run({
            "action": "plan",
            "goal": "单步任务",
            "steps": json.dumps(["唯一步骤"])
        })
        assert r["success"], f"单步 plan 应该成功: {r}"
        g = json.load(open(gf))
        assert len(g["steps"]) == 1
    finally:
        teardown_goal_file(tmpdir)


# ═══════════════════════════════════════════════════════════
#  2. action='step' — 更新步骤状态
# ═══════════════════════════════════════════════════════════

def test_09_step_mark_done():
    """标记步骤为 done"""
    tmpdir, gf = setup_goal_file()
    try:
        tool().run({
            "action": "plan",
            "goal": "测试",
            "steps": json.dumps(["s1", "s2", "s3"])
        })
        r = tool().run({
            "action": "step",
            "step": 1,
            "status": "done"
        })
        assert r["success"], f"step done 应该成功: {r}"
        assert "step 1 done" in r["content"]
        g = json.load(open(gf))
        assert g["steps"][0]["status"] == "done"
        assert g["current"] == 1  # 顺序完成，current 应推进
    finally:
        teardown_goal_file(tmpdir)


def test_10_step_mark_failed():
    """标记步骤为 failed"""
    tmpdir, gf = setup_goal_file()
    try:
        tool().run({
            "action": "plan",
            "goal": "测试",
            "steps": json.dumps(["s1", "s2"])
        })
        r = tool().run({
            "action": "step",
            "step": 1,
            "status": "failed"
        })
        assert r["success"], f"step failed 应该成功: {r}"
        assert "step 1 failed" in r["content"]
        g = json.load(open(gf))
        assert g["steps"][0]["status"] == "failed"
        # failed 不推进 current
        assert g["current"] == 0
    finally:
        teardown_goal_file(tmpdir)


def test_11_step_with_note():
    """标记步骤时附带备注"""
    tmpdir, gf = setup_goal_file()
    try:
        tool().run({
            "action": "plan",
            "goal": "测试",
            "steps": json.dumps(["s1"])
        })
        r = tool().run({
            "action": "step",
            "step": 1,
            "status": "done",
            "note": "pytest 5/5 passed"
        })
        assert r["success"], f"step with note 应该成功: {r}"
        g = json.load(open(gf))
        assert g["steps"][0]["note"] == "pytest 5/5 passed"
    finally:
        teardown_goal_file(tmpdir)


def test_12_step_default_status_done():
    """不传 status 时默认为 done"""
    tmpdir, gf = setup_goal_file()
    try:
        tool().run({
            "action": "plan",
            "goal": "测试",
            "steps": json.dumps(["s1"])
        })
        r = tool().run({
            "action": "step",
            "step": 1
        })
        assert r["success"], f"默认 status 应该成功: {r}"
        assert "step 1 done" in r["content"]
    finally:
        teardown_goal_file(tmpdir)


def test_13_step_invalid_status():
    """非法 status → 失败"""
    tmpdir, gf = setup_goal_file()
    try:
        tool().run({
            "action": "plan",
            "goal": "测试",
            "steps": json.dumps(["s1"])
        })
        r = tool().run({
            "action": "step",
            "step": 1,
            "status": "skipped"
        })
        assert not r["success"], "非法 status 应该失败"
        assert "invalid status" in r["content"]
    finally:
        teardown_goal_file(tmpdir)


def test_14_step_no_active_goal():
    """没有活跃 goal → step 失败"""
    tmpdir, gf = setup_goal_file()
    try:
        r = tool().run({
            "action": "step",
            "step": 1,
            "status": "done"
        })
        assert not r["success"], "无活跃 goal 应该失败"
        assert "no active goal" in r["content"].lower()
    finally:
        teardown_goal_file(tmpdir)


def test_15_step_invalid_number():
    """步骤号超出范围 → 失败"""
    tmpdir, gf = setup_goal_file()
    try:
        tool().run({
            "action": "plan",
            "goal": "测试",
            "steps": json.dumps(["s1", "s2"])
        })
        # step 0 无效 (1-indexed)
        r = tool().run({
            "action": "step",
            "step": 0,
            "status": "done"
        })
        assert not r["success"], "step 0 应该失败"
        # step 3 超出范围
        r = tool().run({
            "action": "step",
            "step": 3,
            "status": "done"
        })
        assert not r["success"], "step 3 超出范围应该失败"
    finally:
        teardown_goal_file(tmpdir)


def test_16_step_sequential_advance():
    """顺序完成步骤 → current 逐次推进"""
    tmpdir, gf = setup_goal_file()
    try:
        tool().run({
            "action": "plan",
            "goal": "顺序任务",
            "steps": json.dumps(["s1", "s2", "s3", "s4"])
        })
        # 依次完成
        for i in range(1, 5):
            r = tool().run({
                "action": "step",
                "step": i,
                "status": "done"
            })
            assert r["success"], f"step {i} 应该成功: {r}"
        g = json.load(open(gf))
        assert g["current"] == 4
        # 最后一步完成提示
        assert "all done" in r["content"].lower()
    finally:
        teardown_goal_file(tmpdir)


def test_17_step_non_sequential_no_advance():
    """非顺序完成（跳过）→ current 不推进"""
    tmpdir, gf = setup_goal_file()
    try:
        tool().run({
            "action": "plan",
            "goal": "测试",
            "steps": json.dumps(["s1", "s2", "s3"])
        })
        # 跳过 s1，直接完成 s2
        r = tool().run({
            "action": "step",
            "step": 2,
            "status": "done"
        })
        assert r["success"], f"step 2 应该成功: {r}"
        g = json.load(open(gf))
        assert g["steps"][1]["status"] == "done"
        # current 不应推进（因为 s1 还是 pending）
        assert g["current"] == 0
    finally:
        teardown_goal_file(tmpdir)


def test_18_step_last_step_prompt():
    """最后一步完成时提示 finish"""
    tmpdir, gf = setup_goal_file()
    try:
        tool().run({
            "action": "plan",
            "goal": "测试",
            "steps": json.dumps(["s1", "s2"])
        })
        tool().run({"action": "step", "step": 1, "status": "done"})
        r = tool().run({"action": "step", "step": 2, "status": "done"})
        assert "all done" in r["content"].lower()
        assert "finish" in r["content"].lower()
    finally:
        teardown_goal_file(tmpdir)


def test_19_step_not_last_prompt_next():
    """非最后一步提示 next step"""
    tmpdir, gf = setup_goal_file()
    try:
        tool().run({
            "action": "plan",
            "goal": "测试",
            "steps": json.dumps(["s1", "s2", "s3"])
        })
        r = tool().run({"action": "step", "step": 1, "status": "done"})
        assert "next: step 2" in r["content"]
    finally:
        teardown_goal_file(tmpdir)


# ═══════════════════════════════════════════════════════════
#  3. action='show' — 查看当前计划
# ═══════════════════════════════════════════════════════════

def test_20_show_active_goal():
    """show 返回当前 goal JSON"""
    tmpdir, gf = setup_goal_file()
    try:
        tool().run({
            "action": "plan",
            "goal": "查看测试",
            "steps": json.dumps(["a", "b"])
        })
        r = tool().run({"action": "show"})
        assert r["success"], f"show 应该成功: {r}"
        g = json.loads(r["content"])
        assert g["goal"] == "查看测试"
        assert len(g["steps"]) == 2
    finally:
        teardown_goal_file(tmpdir)


def test_21_show_no_active_goal():
    """没有活跃 goal → show 失败"""
    tmpdir, gf = setup_goal_file()
    try:
        r = tool().run({"action": "show"})
        assert not r["success"], "无活跃 goal 应该失败"
        assert "no active goal" in r["content"].lower()
    finally:
        teardown_goal_file(tmpdir)


def test_22_default_action_is_show():
    """不传 action 时默认为 show"""
    tmpdir, gf = setup_goal_file()
    try:
        tool().run({
            "action": "plan",
            "goal": "默认测试",
            "steps": json.dumps(["x"])
        })
        r = tool().run({})
        assert r["success"], f"默认 show 应该成功: {r}"
        g = json.loads(r["content"])
        assert g["goal"] == "默认测试"
    finally:
        teardown_goal_file(tmpdir)


# ═══════════════════════════════════════════════════════════
#  4. action='finish' — 结束计划
# ═══════════════════════════════════════════════════════════

def test_23_finish_clears_goal():
    """finish 清除 goal 文件"""
    tmpdir, gf = setup_goal_file()
    try:
        tool().run({
            "action": "plan",
            "goal": "结束测试",
            "steps": json.dumps(["s1"])
        })
        assert os.path.exists(gf), "goal.json 应该存在"
        r = tool().run({"action": "finish"})
        assert r["success"], f"finish 应该成功: {r}"
        assert "goal cleared" in r["content"].lower()
        assert not os.path.exists(gf), "goal.json 应该被删除"
    finally:
        teardown_goal_file(tmpdir)


def test_24_finish_after_finish():
    """重复 finish 不报错"""
    tmpdir, gf = setup_goal_file()
    try:
        tool().run({
            "action": "plan",
            "goal": "测试",
            "steps": json.dumps(["s1"])
        })
        tool().run({"action": "finish"})
        r = tool().run({"action": "finish"})
        assert r["success"], f"重复 finish 应该成功: {r}"
    finally:
        teardown_goal_file(tmpdir)


# ═══════════════════════════════════════════════════════════
#  5. 未知 action
# ═══════════════════════════════════════════════════════════

def test_25_unknown_action():
    """非法 action → 失败"""
    tmpdir, gf = setup_goal_file()
    try:
        r = tool().run({"action": "delete"})
        assert not r["success"], "未知 action 应该失败"
        assert "unknown action" in r["content"]
    finally:
        teardown_goal_file(tmpdir)


# ═══════════════════════════════════════════════════════════
#  6. 综合场景：完整 workflow
# ═══════════════════════════════════════════════════════════

def test_26_full_workflow():
    """完整的 plan → show → step → step → show → finish 流程"""
    tmpdir, gf = setup_goal_file()
    try:
        t = tool()

        # 1. plan
        r = t.run({
            "action": "plan",
            "goal": "完整流程测试",
            "steps": json.dumps(["步骤A", "步骤B", "步骤C"])
        })
        assert r["success"], f"plan 失败: {r}"

        # 2. show
        r = t.run({"action": "show"})
        assert r["success"], f"show 失败: {r}"
        g = json.loads(r["content"])
        assert g["goal"] == "完整流程测试"
        assert g["current"] == 0

        # 3. step 1 done
        r = t.run({"action": "step", "step": 1, "status": "done", "note": "第一步完成"})
        assert r["success"], f"step1 失败: {r}"
        assert "step 1 done" in r["content"]
        assert "next: step 2" in r["content"]

        # 4. step 2 failed
        r = t.run({"action": "step", "step": 2, "status": "failed", "note": "编译错误"})
        assert r["success"], f"step2 失败: {r}"
        assert "step 2 failed" in r["content"]

        # 5. step 3 done
        r = t.run({"action": "step", "step": 3, "status": "done"})
        assert r["success"], f"step3 失败: {r}"

        # 6. show 最终状态
        r = t.run({"action": "show"})
        assert r["success"]
        g = json.loads(r["content"])
        assert g["steps"][0]["status"] == "done"
        assert g["steps"][0]["note"] == "第一步完成"
        assert g["steps"][1]["status"] == "failed"
        assert g["steps"][1]["note"] == "编译错误"
        assert g["steps"][2]["status"] == "done"
        # current 应为 1（只顺序推进了第一步）
        assert g["current"] == 1

        # 7. finish
        r = t.run({"action": "finish"})
        assert r["success"], f"finish 失败: {r}"
        assert not os.path.exists(gf)

        # 8. finish 后 show 应失败
        r = t.run({"action": "show"})
        assert not r["success"], "finish 后 show 应该失败"
    finally:
        teardown_goal_file(tmpdir)


def test_27_steps_with_special_characters():
    """步骤描述含特殊字符（中文、emoji、换行）→ 正常存储"""
    tmpdir, gf = setup_goal_file()
    try:
        r = tool().run({
            "action": "plan",
            "goal": "特殊字符测试 🎯",
            "steps": json.dumps(["读取 mangopi_cli.py，定位 GoalTool", "编写 ✅ 测试", "运行 & 验证"])
        })
        assert r["success"], f"plan 失败: {r}"
        g = json.load(open(gf))
        assert "🎯" in g["goal"]
        assert "✅" in g["steps"][1]["desc"]
    finally:
        teardown_goal_file(tmpdir)


# ═══════════════════════════════════════════════════════════
#  7. 边界情况
# ═══════════════════════════════════════════════════════════

def test_28_step_number_as_string():
    """step 参数为缺失或 None → 应优雅失败"""
    tmpdir, gf = setup_goal_file()
    try:
        tool().run({
            "action": "plan",
            "goal": "测试",
            "steps": json.dumps(["s1", "s2"])
        })
        # 不传 step 参数
        r = tool().run({
            "action": "step",
            "status": "done"
        })
        assert not r["success"], "缺少 step 参数应该失败"
        assert "no active goal or invalid step" in r["content"].lower()
    finally:
        teardown_goal_file(tmpdir)


def test_29_goal_file_corrupted():
    """goal.json 内容损坏 → _goal_load 返回 None"""
    tmpdir, gf = setup_goal_file()
    try:
        # 写入非法 JSON
        with open(gf, "w") as f:
            f.write("这不是合法的 JSON {{{")
        r = tool().run({"action": "show"})
        assert not r["success"], "损坏的 goal 文件应该导致失败"
        assert "no active goal" in r["content"].lower()
    finally:
        teardown_goal_file(tmpdir)


# ── 入口 ──────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== GoalTool 单元测试 ===\n")
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                print(f"  ✓ {name}")
            except AssertionError as e:
                failed += 1
                print(f"  ✗ {name}  FAIL: {e}")
            except Exception as e:
                failed += 1
                import traceback
                print(f"  ✗ {name}  ERROR: {e}")
                traceback.print_exc()

    print(f"\n{'='*40}")
    print(f"通过: {passed}  失败: {failed}  总计: {passed+failed}")
    if failed:
        sys.exit(1)
