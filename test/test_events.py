"""Tests for the run_tool event bus — _EventBus / on() / emit() and the
tool:before / tool:after / tool:error events emitted by run_tool.

Contract: emit only (no bail/serial/waterfall); listener exceptions are
isolated (diagnostic only); the bus singleton is defined before the extension
scan point so extensions can `from mangopi_cli import on` at top level.
"""
import os
import unittest
from unittest import mock
import mangopi_cli as m

# Force a fake MANGO_KEY so the module-level create_provider() doesn't choke
os.environ.setdefault("MANGO_KEY", "test-key-not-used")


class TestEventBus(unittest.TestCase):
    def setUp(self):
        self.orig_listeners = m._mango_events._listeners
        m._mango_events._listeners = {}

    def tearDown(self):
        m._mango_events._listeners = self.orig_listeners

    def test_on_emit_basic(self):
        got = []
        m.on("ev", lambda *a: got.append(a))
        n = m._mango_events.emit("ev", 1, "x")
        self.assertEqual(n, 1)
        self.assertEqual(got, [(1, "x")])

    def test_emit_unknown_event_returns_zero(self):
        self.assertEqual(m._mango_events.emit("nope", 1), 0)

    def test_emit_returns_listener_count(self):
        m.on("ev", lambda: None)
        m.on("ev", lambda: None)
        self.assertEqual(m._mango_events.emit("ev"), 2)

    def test_unsub(self):
        got = []
        unsub = m.on("ev", lambda: got.append(1))
        m._mango_events.emit("ev")
        self.assertTrue(unsub())
        m._mango_events.emit("ev")
        self.assertFalse(unsub())  # 重复退订返回 False
        self.assertEqual(got, [1])

    def test_listener_exception_isolated(self):
        got = []

        def bad(*a):
            raise RuntimeError("boom")

        m.on("ev", bad)
        m.on("ev", lambda: got.append(1))
        with mock.patch.object(m.console, "error") as err:
            n = m._mango_events.emit("ev")
        err.assert_called_once()
        self.assertIn("boom", str(err.call_args))
        self.assertEqual(n, 2)  # listener 数不变, 坏的仍注册
        self.assertEqual(got, [1])  # 其余 listener 正常执行

    def test_unregister_inside_listener(self):
        # 复制列表语义: listener 循环内退订不影响本轮遍历
        got = []

        def inner():
            got.append("inner")
            unsub2()

        m.on("ev", inner)  # 先注册 inner
        unsub2 = m.on("ev", lambda: got.append("outer"))
        m._mango_events.emit("ev")
        self.assertEqual(got, ["inner", "outer"])  # 复制列表: 本轮 outer 仍执行
        m._mango_events.emit("ev")
        self.assertEqual(got.count("outer"), 1)  # 之后退订生效, outer 不再执行


class TestRunToolEvents(unittest.TestCase):
    """run_tool 三事件集成."""

    def setUp(self):
        self.orig_listeners = m._mango_events._listeners
        m._mango_events._listeners = {}
        self.orig_tools = dict(m.TOOLS)
        self.orig_yolo = m.MANGO_YOLO
        m.MANGO_YOLO = True  # 跳过 confirm 阻塞

        class BoomTool(m.ToolBase):
            name = "boom"
            description = "boom"
            params = {}

            def run(self, args):
                raise RuntimeError("kaboom")

        m.TOOLS["boom"] = BoomTool()

    def tearDown(self):
        m.TOOLS.clear()
        m.TOOLS.update(self.orig_tools)
        m.MANGO_YOLO = self.orig_yolo
        m._mango_events._listeners = self.orig_listeners

    def test_before_after_events(self):
        events = []
        m.on("tool:before", lambda n, a: events.append(("before", n, a)))
        m.on("tool:after", lambda n, r: events.append(("after", n, r.get("success"))))
        r = m.run_tool("bash", {"cmd": "echo hi"})
        self.assertTrue(r["success"])
        self.assertEqual(events, [("before", "bash", {"cmd": "echo hi"}),
                                  ("after", "bash", True)])

    def test_error_event(self):
        events = []
        m.on("tool:error", lambda n, e: events.append((n, str(e))))
        r = m.run_tool("boom", {})
        self.assertFalse(r["success"])
        self.assertEqual(events, [("boom", "kaboom")])

    def test_before_fires_even_if_tool_fails(self):
        # before 在 try 之外: 工具失败时 before 仍触发
        events = []
        m.on("tool:before", lambda n, a: events.append(n))
        m.on("tool:error", lambda n, e: events.append("err:" + n))
        m.run_tool("boom", {})
        self.assertEqual(events, ["boom", "err:boom"])

    def test_unknown_tool_no_events(self):
        # TOOLS 查找在 before 之前: 未知工具不触发任何事件
        events = []
        m.on("tool:before", lambda n, a: events.append(n))
        m.on("tool:error", lambda n, e: events.append(n))
        with self.assertRaises(KeyError):
            m.run_tool("nope", {})
        self.assertEqual(events, [])

    def test_denied_path_before_only(self):
        # confirm 拒绝路径: before 触发 (try 外, confirm 前), after/error 不触发
        events = []
        m.on("tool:before", lambda n, a: events.append(n))
        m.on("tool:after", lambda n, r: events.append(n))
        m.on("tool:error", lambda n, e: events.append(n))
        with mock.patch.object(m.console, "prompt_apply", return_value=False), \
                mock.patch.object(m, "MANGO_YOLO", False):
            r = m.run_tool("bash", {"cmd": "rm -rf /"})
        self.assertFalse(r["success"])
        self.assertEqual(events, ["bash"])

    def test_listener_exception_does_not_break_tool(self):
        # listener 抛异常只记录诊断, run_tool 正常返回
        def bad(n, a):
            raise RuntimeError("listener boom")

        m.on("tool:before", bad)
        with mock.patch.object(m.console, "error"):
            r = m.run_tool("bash", {"cmd": "echo hi"})
        self.assertTrue(r["success"])


if __name__ == "__main__":
    unittest.main()
