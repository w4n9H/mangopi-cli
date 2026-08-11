"""Tests for ACP (Agent Client Protocol) v1 server — stdio JSON-RPC agent endpoint.

Covers:
    * initialize: protocol version negotiation, capabilities structure, authMethods
    * session/new: required-field validation (cwd, mcpServers), session creation
    * session/prompt: required-field validation, full turn (thinking → tool → permission
      → message → usage), stopReason
    * tool lifecycle: tool_call pending → request_permission → allow/deny/cancelled →
      tool_call_update (toolCallId pairing)
    * session/cancel: releases pending permissions, agent_loop stops early
      (no further LLM/tool calls), stopReason=cancelled
    * messageId aggregation: shared within a turn, new across turns
    * usage_update: official structure (used/size)
    * _prompt_text: rejects non-text ContentBlocks instead of silently dropping
    * concurrency: prompt threads emit events only to their own session
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest

# Add parent dir to sys.path so we can import mangopi_cli.
# This file lives at <project>/test/test_acp.py, so the project
# root is one level up from __file__'s directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MANGO_KEY", "test-key-not-used")

import mangopi_cli as m  # noqa: E402


def _tool_resp(name, args, content="", reasoning=""):
    return {"finish_reason": "tool_calls", "raw_message": {}, "content": content,
            "reasoning_content": reasoning, "model": "fake",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "tool_calls": [{"id": "t1", "name": name, "arguments": args}],
            "has_tool_calls": True}


def _stop_resp(content, reasoning=""):
    return {"finish_reason": "stop", "raw_message": {}, "content": content,
            "reasoning_content": reasoning, "model": "fake",
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            "tool_calls": [], "has_tool_calls": False}


class FakeProvider:
    """Predictable LLM: returns responses in order, repeats the last one."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.api_url = "fake://llm"

    def build_body(self, msgs):
        return {}

    def headers(self):
        return {}

    def parse_response(self, r):
        resp = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return resp


class AcpTestBase(unittest.TestCase):
    """In-process ACP server harness: pipe-based stdin/stdout, JSON-RPC helpers."""

    def setUp(self):
        self.orig_mode = m.console.mode
        self.orig_emitter = m.console.emitter
        self.orig_perm = m.console.permission_handler
        self.orig_stdin, self.orig_stdout = sys.stdin, sys.stdout
        self.orig_provider, self.orig_chat = m.provider, m.chat_completion
        self.orig_cwd = os.getcwd()
        self.orig_root, self.orig_session_dir = m.project_root, m.session_dir

        self.workdir = tempfile.mkdtemp()
        # 工具路径校验基准 + 会话持久化目录都指向临时目录 (避免污染仓库 .mangocli)
        m.project_root = self.workdir
        m.session_dir = os.path.join(self.workdir, ".mangocli", "session")
        os.makedirs(m.session_dir, exist_ok=True)
        os.chdir(self.workdir)

        r_in, w_in = os.pipe()
        self.in_r, self.in_w = os.fdopen(r_in), os.fdopen(w_in, "w")
        r_out, w_out = os.pipe()
        self.out_r, self.out_w = os.fdopen(r_out), os.fdopen(w_out, "w")
        sys.stdin, sys.stdout = self.in_r, self.out_w

        self.out, self.out_lock = [], threading.Lock()
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

        self.server = m.AcpServer()
        # serve() 的前 3 行注册 (原生钩子), 不启动 stdin 主循环
        m.console.mode = "acp"
        m.console.emitter = self.server.emit
        m.console.permission_handler = self.server._h_permission
        m.chat_completion = lambda msgs: {}  # 占位: parse_response 按序列返回, 不解析原始响应

    def tearDown(self):
        self.out_w.close()           # 关写端 → read_loop 收到 EOF
        self.reader.join(timeout=2)  # 等读线程退出, 避免与 close 读端争抢文件锁
        self.in_w.close()
        self.in_r.close()
        self.out_r.close()
        m.console.mode = self.orig_mode
        m.console.emitter = self.orig_emitter
        m.console.permission_handler = self.orig_perm
        m.provider, m.chat_completion = self.orig_provider, self.orig_chat
        m.project_root, m.session_dir = self.orig_root, self.orig_session_dir
        sys.stdin, sys.stdout = self.orig_stdin, self.orig_stdout
        os.chdir(self.orig_cwd)

    def _read_loop(self):
        for line in self.out_r:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            with self.out_lock:
                self.out.append(msg)

    # ---- JSON-RPC helpers ----

    def send(self, method, params, msg_id=None):
        obj = {"jsonrpc": "2.0", "method": method, "params": params}
        if msg_id is not None:
            obj["id"] = msg_id
        if method == "session/prompt":
            # 与 serve() 一致: prompt 独立线程处理, 主循环可继续收 cancel/权限响应
            threading.Thread(target=self.server.dispatch, args=(obj,), daemon=True).start()
        else:
            self.server.dispatch(obj)

    def send_response(self, msg_id, result):
        self.server.dispatch({"jsonrpc": "2.0", "id": msg_id, "result": result})

    def wait_for(self, pred, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.out_lock:
                for msg in self.out:
                    if pred(msg):
                        return msg
            time.sleep(0.01)
        self.fail("timeout waiting, got: %s" % self.out)

    def updates(self):
        with self.out_lock:
            return [x["params"]["update"] for x in self.out
                    if x.get("method") == "session/update"]

    def wait_update(self, update_type, timeout=5):
        return self.wait_for(lambda x: x.get("method") == "session/update"
                             and x["params"]["update"].get("sessionUpdate") == update_type,
                             timeout)["params"]["update"]

    def wait_permission(self, timeout=5):
        return self.wait_for(lambda x: x.get("method") == "session/request_permission", timeout)

    def new_session(self, msg_id=100):
        self.send("session/new", {"cwd": self.workdir, "mcpServers": []}, msg_id)
        return self.wait_for(lambda x: x.get("id") == msg_id)["result"]["sessionId"]

    def set_provider(self, responses):
        m.provider = FakeProvider(responses)


# ── initialize ────────────────────────────────────────────────────────

class TestInitialize(AcpTestBase):
    def test_negotiation_success(self):
        self.send("initialize", {"protocolVersion": 1}, 1)
        r = self.wait_for(lambda x: x.get("id") == 1)["result"]
        self.assertEqual(r["protocolVersion"], 1)
        self.assertEqual(r["agentInfo"]["name"], "mangopi-cli")
        self.assertEqual(r["authMethods"], [])

    def test_agent_capabilities_structure(self):
        self.send("initialize", {"protocolVersion": 1}, 1)
        caps = self.wait_for(lambda x: x.get("id") == 1)["result"]["agentCapabilities"]
        self.assertEqual(caps, {"loadSession": True,
                                "sessionCapabilities": {"list": {}},
                                "promptCapabilities": {"image": False, "audio": False,
                                                       "embeddedContext": False},
                                "mcpCapabilities": {"http": False, "sse": False}})

    def test_unsupported_version_rejected(self):
        self.send("initialize", {"protocolVersion": 2}, 1)
        r = self.wait_for(lambda x: x.get("id") == 1)
        self.assertEqual(r["error"]["code"], -32602)


# ── session/new ───────────────────────────────────────────────────────

class TestSessionNew(AcpTestBase):
    def test_missing_cwd_rejected(self):
        self.send("session/new", {"mcpServers": []}, 1)
        r = self.wait_for(lambda x: x.get("id") == 1)
        self.assertEqual(r["error"]["code"], -32602)
        self.assertIn("cwd", r["error"]["message"])

    def test_missing_mcp_servers_rejected(self):
        self.send("session/new", {"cwd": self.workdir}, 1)
        r = self.wait_for(lambda x: x.get("id") == 1)
        self.assertEqual(r["error"]["code"], -32602)
        self.assertIn("mcpServers", r["error"]["message"])

    def test_creates_session(self):
        sid = self.new_session()
        self.assertTrue(sid.startswith("sess_"))
        self.assertIn(sid, self.server.sessions)


# ── session/prompt: full turn ─────────────────────────────────────────

class TestPrompt(AcpTestBase):
    def test_missing_prompt_rejected(self):
        sid = self.new_session()
        self.send("session/prompt", {"sessionId": sid}, 1)
        r = self.wait_for(lambda x: x.get("id") == 1)
        self.assertEqual(r["error"]["code"], -32602)
        self.assertIn("prompt", r["error"]["message"])

    def test_full_turn_with_tool_and_permission(self):
        with open("x.py", "w") as f:
            f.write("a")
        self.set_provider([_tool_resp("edit", {"path": "x.py", "old": "a", "new": "b"},
                                      reasoning="thinking-1"),
                           _stop_resp("done")])
        sid = self.new_session()
        self.send("session/prompt", {"sessionId": sid, "prompt": "edit x.py"}, 3)

        # 全链路: thinking → usage → tool_call → permission → tool_call_update → message
        thought = self.wait_update("agent_thought_chunk")
        self.assertEqual(thought["content"], {"type": "text", "text": "thinking-1"})
        usage = self.wait_update("usage_update")
        self.assertEqual(set(usage.keys()), {"sessionUpdate", "used", "size"})
        self.assertGreater(usage["size"], 0)

        tc = self.wait_update("tool_call")
        self.assertEqual(tc["status"], "pending")
        tid = tc["toolCallId"]

        pm = self.wait_permission()
        self.assertEqual(pm["params"]["toolCall"]["toolCallId"], tid)
        self.assertIn("allow-once", [o["optionId"] for o in pm["params"]["options"]])
        self.send_response(pm["id"], {"outcome": {"outcome": "selected", "optionId": "allow-once"}})

        tcu = self.wait_update("tool_call_update")
        self.assertEqual(tcu["toolCallId"], tid)  # 配对
        self.assertEqual(tcu["status"], "completed")

        msg = self.wait_update("agent_message_chunk")
        self.assertEqual(msg["content"]["text"], "done")
        self.assertEqual(msg["messageId"], thought["messageId"])  # 共享 turn 内 messageId

        r = self.wait_for(lambda x: x.get("id") == 3)
        self.assertEqual(r["result"]["stopReason"], "end_turn")
        with open("x.py") as f:
            self.assertEqual(f.read(), "b")  # 工具真实执行


# ── permission outcomes ───────────────────────────────────────────────

class TestPermission(AcpTestBase):
    def _deny_flow(self, outcome_obj):
        with open("x.py", "w") as f:
            f.write("a")
        self.set_provider([_tool_resp("edit", {"path": "x.py", "old": "a", "new": "b"}),
                           _stop_resp("done")])
        sid = self.new_session()
        self.send("session/prompt", {"sessionId": sid, "prompt": "edit"}, 3)
        pm = self.wait_permission()
        self.send_response(pm["id"], {"outcome": outcome_obj})
        r = self.wait_for(lambda x: x.get("id") == 3)
        self.assertEqual(r["result"]["stopReason"], "end_turn")
        with open("x.py") as f:
            self.assertEqual(f.read(), "a")  # 工具未执行

    def test_reject_once_skips_tool(self):
        self._deny_flow({"outcome": "selected", "optionId": "reject-once"})

    def test_cancelled_outcome_terminates_turn(self):
        """RequestPermissionOutcome::Cancelled 裁决 → 工具跳过, 且 turn 终止 (stopReason=cancelled, 无第二轮 LLM)."""
        with open("x.py", "w") as f:
            f.write("a")
        self.set_provider([_tool_resp("edit", {"path": "x.py", "old": "a", "new": "b"}),
                           _stop_resp("done")])
        sid = self.new_session()
        self.send("session/prompt", {"sessionId": sid, "prompt": "edit"}, 3)
        pm = self.wait_permission()
        self.send_response(pm["id"], {"outcome": {"outcome": "cancelled"}})
        r = self.wait_for(lambda x: x.get("id") == 3)
        self.assertEqual(r["result"]["stopReason"], "cancelled")
        self.assertEqual(m.provider.calls, 1, "cancelled 裁决应终止 turn, 不再发起新 LLM 调用")
        with open("x.py") as f:
            self.assertEqual(f.read(), "a")


# ── session/cancel ────────────────────────────────────────────────────

class TestCancel(AcpTestBase):
    def test_cancel_releases_pending_permission(self):
        """cancel 后 prompt 快速返回 cancelled: 不卡权限超时, 工具不执行,
        agent_loop 提前终止 (不再发起新的 LLM 调用, calls==1)."""
        with open("x.py", "w") as f:
            f.write("a")
        self.set_provider([_tool_resp("edit", {"path": "x.py", "old": "a", "new": "b"}),
                           _stop_resp("done")])
        sid = self.new_session()
        self.send("session/prompt", {"sessionId": sid, "prompt": "edit"}, 3)
        self.wait_permission()

        t0 = time.time()
        self.send("session/cancel", {"sessionId": sid})
        r = self.wait_for(lambda x: x.get("id") == 3, timeout=8)
        self.assertLess(time.time() - t0, 5)  # 未卡权限超时
        self.assertEqual(r["result"]["stopReason"], "cancelled")
        self.assertEqual(m.provider.calls, 1, "cancel 后 agent_loop 不应再发起新的 LLM 调用")
        with open("x.py") as f:
            self.assertEqual(f.read(), "a")


# ── messageId aggregation ─────────────────────────────────────────────

class TestMessageId(AcpTestBase):
    def test_shared_within_turn_new_across_turns(self):
        """turn 内多次输出 (工具循环) 共享 messageId; 跨 turn 生成新 id."""
        # turn1: 两次 LLM 响应都带 content (read 无权限确认, 不触发权限桥)
        self.set_provider([_tool_resp("read", {"path": "x.py"}, content="part-A"),
                           _stop_resp("part-B")])
        sid = self.new_session()
        self.send("session/prompt", {"sessionId": sid, "prompt": "hi"}, 3)
        self.wait_for(lambda x: x.get("id") == 3)

        chunks1 = [u for u in self.updates() if u.get("sessionUpdate") == "agent_message_chunk"]
        self.assertEqual([c["content"]["text"] for c in chunks1], ["part-A", "part-B"])
        self.assertEqual(chunks1[0]["messageId"], chunks1[1]["messageId"], "同 turn 共享")

        # turn2: 新消息身份
        self.send("session/prompt", {"sessionId": sid, "prompt": "again"}, 4)
        self.wait_for(lambda x: x.get("id") == 4)
        chunks2 = [u for u in self.updates() if u.get("sessionUpdate") == "agent_message_chunk"]
        self.assertEqual(len(chunks2), 3)
        self.assertNotEqual(chunks2[2]["messageId"], chunks1[0]["messageId"], "跨 turn 独立")


# ── _prompt_text strictness ───────────────────────────────────────────

class TestPromptText(AcpTestBase):
    def _prompt_error(self, prompt):
        sid = self.new_session()
        self.send("session/prompt", {"sessionId": sid, "prompt": prompt}, 1)
        return self.wait_for(lambda x: x.get("id") == 1)

    def test_unsupported_content_block_rejected(self):
        r = self._prompt_error([{"type": "text", "text": "keep"},
                                {"type": "image", "data": "base64"}])
        self.assertEqual(r["error"]["code"], -32602)
        self.assertIn("image", r["error"]["message"])

    def test_malformed_block_rejected(self):
        r = self._prompt_error(["not-a-dict"])
        self.assertEqual(r["error"]["code"], -32602)
        self.assertIn("Malformed", r["error"]["message"])


# ── concurrency ───────────────────────────────────────────────────────

class TestConcurrency(AcpTestBase):
    def test_events_isolated_across_concurrent_prompts(self):
        """两个 session 交错处理时, 事件必须发回各自会话 (threading.local 隔离)."""
        def slow_resp(content):
            def parse(r):
                time.sleep(0.5)
                return _stop_resp(content)
            return parse

        fp = FakeProvider([_stop_resp("msg-1")])
        fp.parse_response = slow_resp("msg-1")
        m.provider = fp

        sid_a, sid_b = self.new_session(101), self.new_session(102)
        self.send("session/prompt", {"sessionId": sid_a, "prompt": "q1"}, 3)
        time.sleep(0.1)
        self.send("session/prompt", {"sessionId": sid_b, "prompt": "q2"}, 4)
        self.wait_for(lambda x: x.get("id") == 3)
        self.wait_for(lambda x: x.get("id") == 4)

        with self.out_lock:
            updates = [x for x in self.out if x.get("method") == "session/update"]
        by_sid = {}
        for u in updates:
            by_sid.setdefault(u["params"]["sessionId"], []).append(u)
        # 只取 agent_message_chunk (usage_update 无 content 字段)
        def texts(sid):
            return [u["params"]["update"]["content"]["text"] for u in by_sid[sid]
                    if u["params"]["update"].get("sessionUpdate") == "agent_message_chunk"]
        self.assertEqual(texts(sid_a), ["msg-1"])
        self.assertEqual(texts(sid_b), ["msg-1"])
        mid_a = [u["params"]["update"]["messageId"] for u in by_sid[sid_a]
                 if u["params"]["update"].get("sessionUpdate") == "agent_message_chunk"][0]
        mid_b = [u["params"]["update"]["messageId"] for u in by_sid[sid_b]
                 if u["params"]["update"].get("sessionUpdate") == "agent_message_chunk"][0]
        self.assertNotEqual(mid_a, mid_b)


# ── session/list & session/load ───────────────────────────────────────

def _write_session(name, msgs):
    with open(os.path.join(m.session_dir, name + ".json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(msgs, ensure_ascii=False))


class TestSessionList(AcpTestBase):
    def test_list_returns_all_sessions(self):
        _write_session("acp_1_ab", [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello world", "ts": 1}])
        _write_session("acp_2_cd", [])
        _write_session("feature-x", [{"role": "user", "content": "cli session", "ts": 1}])  # CLI 会话不混入
        # backup 真实命名: <name>.json.<ts>.backup, 不以 .json 结尾 => 排除
        with open(os.path.join(m.session_dir, "skip.json.123.backup"), "w", encoding="utf-8") as f:
            f.write(json.dumps([{"role": "user", "content": "x", "ts": 1}], ensure_ascii=False))

        self.send("session/list", {}, 1)
        r = self.wait_for(lambda x: x.get("id") == 1)["result"]
        sids = [s["sessionId"] for s in r["sessions"]]
        self.assertEqual(sids, ["sess_acp_1_ab", "sess_acp_2_cd"])  # CLI 会话与 backup 文件排除
        s1 = next(s for s in r["sessions"] if s["sessionId"] == "sess_acp_1_ab")
        self.assertEqual(s1["title"], "hello world")
        self.assertEqual(s1["_meta"]["messageCount"], 2)
        self.assertEqual(s1["cwd"], m.project_root)
        self.assertIn("T", s1["updatedAt"])  # ISO 8601


class TestSessionLoad(AcpTestBase):
    def _msgs(self):
        return [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello", "ts": 1},
            {"role": "assistant", "content": "hi there", "reasoning_content": "think", "ts": 2},
            {"role": "assistant", "content": None, "ts": 3,
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "read", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "file content", "ts": 4}]

    def test_load_restores_ctx_and_replays(self):
        _write_session("acp_9_ef", self._msgs())
        self.send("session/load", {"sessionId": "sess_acp_9_ef"}, 1)
        r = self.wait_for(lambda x: x.get("id") == 1)
        self.assertEqual(r["result"], None)  # 官方: 回放后响应 null
        # ctx 已恢复并可继续 prompt
        self.assertEqual(len(self.server.sessions["sess_acp_9_ef"]), 5)
        # 回放序列: user → assistant(text+reasoning) → tool_call → tool_call_update → tool result
        updates = self.updates()
        seq = [u.get("sessionUpdate") for u in updates]
        self.assertIn("user_message_chunk", seq)
        self.assertIn("agent_message_chunk", seq)
        self.assertIn("agent_thought_chunk", seq)
        self.assertIn("tool_call", seq)
        self.assertIn("tool_call_update", seq)
        # 回放消息均发往目标 sid
        self.assertTrue(all(u.get("params", {}).get("sessionId") == "sess_acp_9_ef"
                            for u in self.out if u.get("method") == "session/update"))
        # tool_call 与 tool_call_update 配对 (toolCallId 一致)
        by_type = {u["sessionUpdate"]: u for u in updates}
        self.assertEqual(by_type["tool_call"]["toolCallId"], "c1")
        self.assertEqual(by_type["tool_call_update"]["toolCallId"], "c1")
        # 回放 messageId 与 live turn 不同命名空间 (mr_ 前缀), 避免与运行时 msg_ 冲突
        mids = [u["messageId"] for u in updates if u.get("messageId")]
        self.assertTrue(all(m.startswith("mr_") for m in mids))

    def test_load_unknown_session_rejected(self):
        self.send("session/load", {"sessionId": "sess_acp_nonexistent"}, 1)
        r = self.wait_for(lambda x: x.get("id") == 1)
        self.assertEqual(r["error"]["code"], -32602)
        self.assertIn("Unknown session", r["error"]["message"])

    def test_load_invalid_sid_rejected(self):
        for bad in ["sess_..%2F..", "sess_..", "abc", "sess_", None, "sess_feature-x"]:  # 含 CLI 命名空间
            self.send("session/load", {"sessionId": bad}, 1)
            r = self.wait_for(lambda x: x.get("id") == 1)
            self.assertEqual(r["error"]["code"], -32602)


class TestSessionNewNaming(AcpTestBase):
    def test_sid_maps_to_session_file(self):
        sid = self.new_session(101)
        self.assertTrue(sid.startswith("sess_acp_"))  # 确定性前缀: 文件名可推导
        name = sid[5:]
        fpath = os.path.join(m.session_dir, name + ".json")
        # session/new 尚不写盘 (首次 turn 后落盘), 但 sid 必须能推导出合法路径
        self.assertNotIn("..", name)
        self.assertNotIn("/", name)


if __name__ == "__main__":
    unittest.main()
