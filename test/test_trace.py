"""Tests for the agent-level events (agent:user_input / agent:assistant /
agent:compact / agent:end) and the trace.py shipped extension that replaces
the removed MANGO_TRACE core feature (v0.1.49 pluginization).
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock
import mangopi_cli as m

# Force a fake MANGO_KEY so the module-level create_provider() doesn't choke
os.environ.setdefault("MANGO_KEY", "test-key-not-used")

RESP = {
    "raw_message": {"role": "assistant", "content": "hi"},
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    "finish_reason": "stop",
    "has_tool_calls": False,
    "tool_calls": [],
    "reasoning_content": "",
    "content": "hi",
    "model": "test-model",
}


class TestAgentEvents(unittest.TestCase):
    """agent_loop 会话级事件: 一轮即停的会话触发 user_input/assistant/end."""

    def setUp(self):
        self.orig_listeners = m._mango_events._listeners
        m._mango_events._listeners = {}
        self.tmp = tempfile.mkdtemp()
        self.ctx = m.ContextManager()
        self.path = os.path.join(self.tmp, "session.json")

    def tearDown(self):
        m._mango_events._listeners = self.orig_listeners
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_session_events_emitted(self):
        events = []
        m.on("agent:user_input", lambda *a: events.append(("user_input", a)))
        m.on("agent:assistant", lambda *a: events.append(("assistant", a)))
        m.on("agent:end", lambda *a: events.append(("end", a)))
        with mock.patch.object(m, "chat_completion", return_value={}), \
                mock.patch.object(m.provider, "parse_response", return_value=dict(RESP)):
            m.agent_loop(self.ctx, self.path, "goal")
        self.assertEqual([e[0] for e in events], ["user_input", "assistant", "end"])
        self.assertEqual(events[0][1], ("chat", "goal", self.path, 4))
        self.assertEqual(events[1][1][:2], (1, "stop"))  # round, finish_reason
        self.assertEqual(events[2][1], (1,))             # total_rounds

    def test_compact_event_emitted(self):
        # prepare_for_api 在 compact 生效时触发 agent:compact
        events = []
        m.on("agent:compact", lambda *a: events.append(a))
        ctx = m.ContextManager()
        ctx.auto_compact_threshold = 0  # 任何内容都触发 auto compact
        ctx.append_user("x" * 100)

        def _shrink():
            ctx.messages.clear()  # 模拟压缩: 大幅减 token

        with mock.patch.object(ctx, "session_memory_compact", side_effect=_shrink), \
                mock.patch.object(ctx, "full_compact", side_effect=lambda: None), \
                mock.patch.object(m.console, "compact_status"):
            ctx.prepare_for_api()
        self.assertEqual(len(events), 1)
        before, after, saved = events[0]
        self.assertGreater(before, after)
        self.assertEqual(saved, before - after)

    def test_trace_fields_removed_from_core(self):
        # v0.1.49: MANGO_TRACE 插件化, 核心不再持有 trace 状态
        ctx = m.ContextManager()
        self.assertFalse(hasattr(ctx, "trace_list"))
        self.assertFalse(hasattr(ctx, "trace_meta"))


class TestTraceExtension(unittest.TestCase):
    """trace.py 扩展: 会话事件序列 -> JSON 落盘 (替代核心 MANGO_TRACE)."""

    def setUp(self):
        self.orig_listeners = m._mango_events._listeners
        m._mango_events._listeners = {}
        self.tmp = tempfile.mkdtemp()
        self.mod = m.ExtensionRegistry.load_file(os.path.join("examples", "extensions", "trace.py"))
        self.mod._TRACES_DIR = os.path.join(self.tmp, "traces")

    def tearDown(self):
        m._mango_events._listeners = self.orig_listeners
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_trace_writes_run_json(self):
        m._mango_events.emit("agent:user_input", "chat", "goal", "/s.json", 4)
        m._mango_events.emit("agent:assistant", 1, "stop", False, 0, False, 0, 2, "m", 10, 5)
        m._mango_events.emit("tool:before", "bash", {"cmd": "echo hi"})
        m._mango_events.emit("tool:after", "bash", {"success": True, "content": "hi"})
        m._mango_events.emit("agent:end", 1)
        files = os.listdir(self.mod._TRACES_DIR)
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.mod._TRACES_DIR, files[0]), encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual([e["kind"] for e in data],
                         ["user_input", "assistant", "tool_call", "tool_result", "end"])
        self.assertEqual(data[0]["goal"], "goal")
        self.assertEqual(data[1]["round"], 1)
        self.assertEqual(data[2]["args_preview"], "{'cmd': 'echo hi'}")
        self.assertEqual(data[4]["total_rounds"], 1)

    def test_no_events_no_file(self):
        # 无 agent:end 不落盘 (会话未结束)
        m._mango_events.emit("agent:user_input", "chat", "goal", "/s.json", 4)
        self.assertFalse(os.path.exists(self.mod._TRACES_DIR))


if __name__ == "__main__":
    unittest.main()
