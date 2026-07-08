"""Tests for the PocketFlow Lite framework (Step, _Edge, Pipeline).

Covers:
    * DSL operators: connect, >>, -
    * Step hooks: prep / exec / post call order and return values
    * Pipeline linear traversal
    * Pipeline action-based conditional routing
    * Pipeline stop (None next)
    * Custom Step subclasses
    * Edge cases: missing methods (NotImplementedError), invalid action type
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mangopi_cli as m


class _AddStep(m.Step):
    """在 ctx['val'] 上加 exec 返回值的 Step"""
    def prep(self, ctx): return ctx.get("val", 0)

    def execute(self, prep_res): return prep_res + 1

    def post(self, ctx, prep_res, exec_res):
        ctx["val"] = exec_res
        return "ok"


class _FailStep(m.Step):
    def prep(self, ctx): return None
    def execute(self, prep_res): return "fail"
    def post(self, ctx, prep_res, exec_res): return "fail"


class _ActionStep(m.Step):
    """根据参数返回不同的 action 字符串，测试条件路由"""
    def __init__(self, action="a"):
        super().__init__()
        self._action = action

    def prep(self, ctx): return None
    def execute(self, prep_res): return None
    def post(self, ctx, prep_res, exec_res): return self._action


class _WriteStep(m.Step):
    """写入固定值的 Step, post 返回 None 触发 default 边"""
    def __init__(self, key, value):
        super().__init__()
        self._key = key
        self._value = value

    def prep(self, ctx): return None
    def execute(self, prep_res): return None
    def post(self, ctx, prep_res, exec_res):
        ctx[self._key] = self._value
        return None


class _LoopStep(m.Step):
    """exec 被执行时调用回调，用于计数"""
    def __init__(self, cb):
        super().__init__()
        self._cb = cb

    def prep(self, ctx): return None
    def execute(self, p): self._cb(); return None
    def post(self, ctx, p, e): return None


# ── DSL operators ────────────────────────────────────────────────────

class TestDSLOperators(unittest.TestCase):

    def test_connect_returns_target(self):
        a, b = _AddStep(), _AddStep()
        ret = a.connect(b)
        self.assertIs(ret, b)

    def test_connect_sets_next_default(self):
        a, b = _AddStep(), _AddStep()
        a.connect(b)
        self.assertIs(a.next["default"], b)

    def test_connect_sets_named_action(self):
        a, b = _AddStep(), _AddStep()
        a.connect(b, action="fail")
        self.assertIs(a.next["fail"], b)

    def test_rshift_default_action(self):
        a, b = _AddStep(), _AddStep()
        a >> b
        self.assertIs(a.next["default"], b)

    def test_rshift_chaining(self):
        a, b, c = _AddStep(), _AddStep(), _AddStep()
        a >> b >> c
        self.assertIs(a.next["default"], b)
        self.assertIs(b.next["default"], c)

    def test_sub_creates_edge(self):
        a = _AddStep()
        edge = a - "custom"
        self.assertIsInstance(edge, m._Edge)
        self.assertIs(edge.src, a)
        self.assertEqual(edge.action, "custom")

    def test_sub_with_non_string_raises(self):
        a = _AddStep()
        with self.assertRaises(TypeError):
            a - 42

    def test_edge_rshift_sets_connection(self):
        a, b = _AddStep(), _AddStep()
        a - "x" >> b
        self.assertIs(a.next["x"], b)


# ── Step hooks ───────────────────────────────────────────────────────

class TestStepHooks(unittest.TestCase):

    def test_run_calls_prep_execute_post(self):
        log = []

        class LogStep(m.Step):
            def prep(self, ctx): log.append("prep"); return "p"
            def execute(self, prep_res): log.append(f"execute({prep_res})"); return "e"
            def post(self, ctx, prep_res, exec_res): log.append(f"post({prep_res},{exec_res})"); return None

        s = LogStep()
        s.run({})
        self.assertEqual(log, ["prep", "execute(p)", "post(p,e)"])

    def test_prep_default_returns_none(self):
        self.assertIsNone(m.Step().prep({}))

    def test_execute_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            m.Step().execute(None)

    def test_post_default_returns_none(self):
        self.assertIsNone(m.Step().post({}, None, None))

    def test_run_returns_action(self):
        action = _AddStep().run({"val": 0})
        self.assertEqual(action, "ok")

    def test_run_mutates_ctx(self):
        ctx = {"val": 0}
        _AddStep().run(ctx)
        self.assertEqual(ctx["val"], 1)


# ── Pipeline traversal ───────────────────────────────────────────────

class TestPipelineTraversal(unittest.TestCase):

    def test_linear_chain(self):
        ctx = {}
        a, b = _WriteStep("step", "a"), _WriteStep("step", "b")
        a >> b
        p = m.Pipeline(a)
        p.run(ctx)
        self.assertEqual(ctx["step"], "b")

    def test_stop_when_no_next(self):
        ctx = {"val": 0}
        a = _AddStep()
        p = m.Pipeline(a)
        ctx = p.run(ctx)
        self.assertEqual(ctx["val"], 1)

    def test_conditional_routing(self):
        """fail action 走右分支，other 走左分支"""
        a = _ActionStep("fail")
        left, right = _WriteStep("branch", "left"), _WriteStep("branch", "right")
        a - "fail" >> right
        a - "ok" >> left
        p = m.Pipeline(a)
        ctx = p.run({})
        self.assertEqual(ctx["branch"], "right")

    def test_default_fallback_when_no_action_match(self):
        """post 返回 None 触发 default 边"""
        a = _ActionStep(None)
        b = _WriteStep("reached", True)
        a >> b
        p = m.Pipeline(a)
        ctx = p.run({})
        self.assertTrue(ctx.get("reached"))

    def test_conditional_via_default_edge(self):
        """post 返回 '' 也触发 default 边"""
        a = _ActionStep("")
        b = _WriteStep("reached", True)
        a >> b
        p = m.Pipeline(a)
        ctx = p.run({})
        self.assertTrue(ctx.get("reached"))

    def test_multiple_iterations(self):
        """模拟循环：通过 action 路由回跳"""
        counts = {"a": 0, "b": 0}
        class LoopA(m.Step):
            def prep(self, ctx): return None
            def execute(self, p): counts["a"] += 1; return None
            def post(self, ctx, p, e): return "to_b"
        class LoopB(m.Step):
            def prep(self, ctx): return None
            def execute(self, p): counts["b"] += 1; return None
            def post(self, ctx, p, e):
                return "to_a" if counts["b"] < 3 else None

        a, b = LoopA(), LoopB()
        a - "to_b" >> b
        b - "to_a" >> a
        p = m.Pipeline(a)
        p.run({})
        self.assertEqual(counts["a"], 3)
        self.assertEqual(counts["b"], 3)


# ── Edge cases ───────────────────────────────────────────────────────

class TestPipelineEdgeCases(unittest.TestCase):

    def test_empty_pipeline(self):
        p = m.Pipeline(None)
        ctx = p.run({})
        self.assertEqual(ctx, {})

    def test_shared_ctx_accumulates(self):
        a, b, c = _WriteStep("a", 1), _WriteStep("b", 2), _WriteStep("c", 3)
        a >> b >> c
        ctx = m.Pipeline(a).run({})
        self.assertEqual(ctx, {"a": 1, "b": 2, "c": 3})


if __name__ == "__main__":
    unittest.main()
