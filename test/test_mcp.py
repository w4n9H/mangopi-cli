"""Tests for the MCP client extension (shipped: examples/extensions/mcp.py).

Covers:
    * stdio handshake + tools/list discovery (incl. cursor pagination)
    * schema() passthrough of arbitrary/nested inputSchema (ToolBase.params 表达不了)
    * tools/call: text, isError, image, image+text, nested args round-trip
    * self-healing: unknown tool / server death → reconnect + retry once; timeout → fail
    * manifest cache: written with cfg fingerprint on first connect, reused on next
      bootstrap (no subprocess); config change → fingerprint mismatch → force refresh;
      removed servers pruned; lazy connect on first call when MANGO_MCP_EAGER=0
    * config filtering (disabled / unnamed), MANGO_MCP_EAGER=0 short-circuit
    * HTTP transport: SSE response parsing (incl. CRLF multi-event), session-id header,
      404 expiry → re-initialize
    * naming: mcp_<server>_<tool>, long names truncated with sha1 suffix, sanitized
      collisions disambiguated with hash suffix
    * prompt_sections dynamic segment; shutdown closes transports; log rotation

A real fake MCP server runs as a subprocess (mode via FAKE_MCP_MODE) so process
death, pagination and framing are exercised for real rather than mocked.
"""
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

os.environ.setdefault("MANGO_KEY", "test-key-not-used")
os.environ["MANGO_MCP_EAGER"] = "0"          # 导入期不要连接真实配置

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mangopi_cli  # noqa: E402,F401  确保 ToolBase 可用

# ── Load the shipped extension module ────────────────────────────────────────
EXT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "examples", "extensions", "mcp.py")
_spec = importlib.util.spec_from_file_location("mango_mcp_ext", EXT_PATH)
mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mcp)

# ── Fake MCP server (real subprocess, newline-delimited JSON-RPC over stdio) ──
_FAKE = r'''
import json, os, sys, time

MODE = os.environ.get("FAKE_MCP_MODE", "normal")

TOOLS = [
    {"name": "echo", "description": "Echo arguments back",
     "inputSchema": {"type": "object",
                     "properties": {
                         "text": {"type": "string", "description": "text to echo"},
                         "opts": {"type": "object",
                                  "properties": {"loud": {"type": "boolean"},
                                                 "tags": {"type": "array",
                                                          "items": {"type": "string"}}}}},
                     "required": ["text"]}},
    {"name": "boom", "description": "Always fails",
     "inputSchema": {"type": "object", "properties": {}}},
]


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    method, mid = msg.get("method"), msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "fake", "version": "1.0"}}})
    elif method == "tools/list":
        if MODE == "paginated" and not params.get("cursor"):
            send({"jsonrpc": "2.0", "id": mid,
                  "result": {"tools": [TOOLS[0]], "nextCursor": "p2"}})
        elif MODE == "paginated":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [TOOLS[1]]}})
        else:
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if MODE == "slow":
            time.sleep(5)
            send({"jsonrpc": "2.0", "id": mid,
                  "result": {"content": [{"type": "text", "text": "late"}]}})
        elif MODE == "die":
            sys.exit(3)
        elif MODE == "image":
            send({"jsonrpc": "2.0", "id": mid, "result": {"content": [
                {"type": "image", "data": "aGVsbG8=", "mimeType": "image/png"}]}})
        elif MODE == "mixed":
            send({"jsonrpc": "2.0", "id": mid, "result": {"content": [
                {"type": "text", "text": "caption"},
                {"type": "image", "data": "aGVsbG8=", "mimeType": "image/png"}]}})
        elif name == "boom":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "kaboom"}], "isError": True}})
        elif name == "ghost":
            send({"jsonrpc": "2.0", "id": mid,
                  "error": {"code": -32602, "message": "unknown tool: ghost"}})
        else:
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps(args, sort_keys=True)}]}})
'''


def _http_response(payload=None, ctype="application/json", headers=None, raw=None):
    hdrs = dict(headers or {})
    hdrs.setdefault("Content-Type", ctype)
    resp = mock.MagicMock()
    resp.read.return_value = raw if raw is not None else json.dumps(payload).encode()
    resp.headers.get.side_effect = lambda k, d=None: hdrs.get(k, d)
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)
    resp._ctype = ctype
    return resp


class McpTestBase(unittest.TestCase):
    """隔离加载扩展并重定向配置/清单/日志到临时目录, 用完恢复."""

    def setUp(self):
        self._orig = (mcp.CONFIG_PATH, mcp.MANIFEST_PATH, mcp.LOG_DIR,
                      dict(mcp._SERVERS), list(mcp.tools))
        self.tmp = tempfile.TemporaryDirectory()
        mcp.CONFIG_PATH = os.path.join(self.tmp.name, "mcp_servers.json")
        mcp.MANIFEST_PATH = os.path.join(self.tmp.name, "manifest.json")
        mcp.LOG_DIR = os.path.join(self.tmp.name, "logs")
        mcp._SERVERS.clear()
        mcp.tools.clear()
        self.fake = os.path.join(self.tmp.name, "fake_mcp_server.py")
        with open(self.fake, "w", encoding="utf-8") as f:
            f.write(_FAKE)

    def tearDown(self):
        mcp._shutdown()
        (mcp.CONFIG_PATH, mcp.MANIFEST_PATH, mcp.LOG_DIR) = self._orig[:3]
        mcp._SERVERS.clear()
        mcp._SERVERS.update(self._orig[3])
        mcp.tools.clear()
        mcp.tools.extend(self._orig[4])
        self.tmp.cleanup()

    def _bootstrap(self, servers, eager="1", manifest=None):
        with open(mcp.CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"servers": servers}, f)
        if manifest is not None:
            with open(mcp.MANIFEST_PATH, "w", encoding="utf-8") as f:
                json.dump(manifest, f)
        with mock.patch.dict(os.environ, {"MANGO_MCP_EAGER": eager}):
            mcp._bootstrap()

    def _cfg(self, name="fake", **extra):
        cfg = {"name": name, "command": sys.executable, "args": [self.fake],
               "timeout": 5, "init_timeout": 10}
        cfg.update(extra)
        return cfg

    def _tool(self, remote="echo"):
        return next(t for t in mcp.tools if t._remote == remote)


class StdioDiscoveryTest(McpTestBase):

    def test_01_handshake_registers_prefixed_tools(self):
        self._bootstrap([self._cfg()])
        self.assertEqual(sorted(t.name for t in mcp.tools),
                         ["mcp_fake_boom", "mcp_fake_echo"])
        self.assertTrue(mcp._SERVERS["fake"].is_connected)
        self.assertEqual(mcp._SERVERS["fake"].tools[0]["name"], "echo")

    def test_02_schema_passes_native_input_schema(self):
        self._bootstrap([self._cfg()])
        schema = self._tool("echo").schema()
        params = schema["function"]["parameters"]
        self.assertEqual(schema["type"], "function")
        self.assertEqual(schema["function"]["name"], "mcp_fake_echo")
        self.assertEqual(params["required"], ["text"])
        self.assertEqual(params["properties"]["opts"]["type"], "object")
        self.assertEqual(params["properties"]["opts"]["properties"]["tags"]["items"],
                         {"type": "string"})

    def test_03_manifest_written_and_reused_without_subprocess(self):
        self._bootstrap([self._cfg()])
        with open(mcp.MANIFEST_PATH, encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual([s["name"] for s in manifest["fake"]["tools"]], ["echo", "boom"])
        self.assertEqual(manifest["fake"]["fp"], mcp._cfg_fp(self._cfg()))
        os.remove(self.fake)                      # 缓存命中(指纹匹配), 不该再拉起子进程
        mcp._SERVERS.clear()
        mcp.tools.clear()
        self._bootstrap([self._cfg()])
        self.assertEqual(sorted(t.name for t in mcp.tools),
                         ["mcp_fake_boom", "mcp_fake_echo"])

    def test_04_pagination_collects_all_pages(self):
        with mock.patch.dict(os.environ, {"FAKE_MCP_MODE": "paginated"}):
            self._bootstrap([self._cfg()])
        self.assertEqual(sorted(s["name"] for s in mcp._SERVERS["fake"].tools),
                         ["boom", "echo"])

    def test_05_eager_disabled_skips_connect(self):
        self._bootstrap([self._cfg()], eager="0")
        self.assertEqual(mcp.tools, [])
        self.assertFalse(mcp._SERVERS["fake"].is_connected)

    def test_06_config_skips_disabled_and_unnamed(self):
        self._bootstrap([{"name": "off", "enabled": False, "command": "false"},
                         {"command": "false"},
                         self._cfg()])
        self.assertEqual(list(mcp._SERVERS), ["fake"])

    def test_07_unavailable_server_is_isolated(self):
        self._bootstrap([{"name": "broken", "command": sys.executable,
                          "args": ["-c", "raise SystemExit(1)"], "init_timeout": 5},
                         self._cfg()])
        self.assertIn("mcp_fake_echo", [t.name for t in mcp.tools])
        self.assertNotIn("broken", [t.name for t in mcp.tools])


class StdioCallTest(McpTestBase):

    def test_10_text_result(self):
        self._bootstrap([self._cfg()])
        res = self._tool().run({"text": "hi"})
        self.assertTrue(res["success"])
        self.assertEqual(json.loads(res["content"]), {"text": "hi"})

    def test_11_nested_args_survive_round_trip(self):
        self._bootstrap([self._cfg()])
        args = {"text": "x", "opts": {"loud": True, "tags": ["a", "b"]}}
        res = self._tool().run(args)
        self.assertTrue(res["success"])
        self.assertEqual(json.loads(res["content"]), args)

    def test_12_is_error_maps_to_fail(self):
        self._bootstrap([self._cfg()])
        res = self._tool("boom").run({})
        self.assertFalse(res["success"])
        self.assertEqual(res["content"], "kaboom")

    def test_13_image_result_uses_core_multimodal_shape(self):
        with mock.patch.dict(os.environ, {"FAKE_MCP_MODE": "image"}):
            self._bootstrap([self._cfg()])
            res = self._tool().run({"text": "x"})
        self.assertTrue(res["success"])
        self.assertEqual(res["content"]["type"], "image")
        self.assertEqual(res["content"]["image_url"], "data:image/png;base64,aGVsbG8=")

    def test_14_image_with_caption_keeps_text(self):
        with mock.patch.dict(os.environ, {"FAKE_MCP_MODE": "mixed"}):
            self._bootstrap([self._cfg()])
            res = self._tool().run({"text": "x"})
        self.assertTrue(res["success"])
        self.assertEqual(res["content"]["text"], "caption")

    def test_15_unknown_tool_reconnects_then_fails(self):
        self._bootstrap([self._cfg()])
        ghost = mcp.McpProxyTool(mcp._SERVERS["fake"], {"name": "ghost"})
        res = ghost.run({})
        self.assertFalse(res["success"])
        self.assertIn("unknown tool", res["content"])

    def test_16_server_death_does_not_hang(self):
        with mock.patch.dict(os.environ, {"FAKE_MCP_MODE": "die"}):
            self._bootstrap([self._cfg()])
            started = time.time()
            res = self._tool().run({"text": "x"})
        self.assertFalse(res["success"])
        self.assertLess(time.time() - started, 20)

    def test_17_timeout_returns_fail(self):
        with mock.patch.dict(os.environ, {"FAKE_MCP_MODE": "slow"}):
            self._bootstrap([self._cfg(timeout=1)])
            started = time.time()
            res = self._tool().run({"text": "x"})
        self.assertFalse(res["success"])
        self.assertIn("timeout", res["content"])
        self.assertLess(time.time() - started, 10)

    def test_18_preview_renders_json(self):
        self._bootstrap([self._cfg()])
        self.assertEqual(self._tool().preview({"text": "hi"}), '{"text": "hi"}')

    def test_19_confirm_defaults_to_no_prompt(self):
        self._bootstrap([self._cfg()])
        self.assertTrue(self._tool().confirm({}))

    def test_20_shutdown_closes_transports(self):
        self._bootstrap([self._cfg()])
        self.assertTrue(mcp._SERVERS["fake"].is_connected)
        mcp._shutdown()
        self.assertFalse(mcp._SERVERS["fake"].is_connected)

    def test_21_stale_manifest_refreshed_after_reconnect(self):
        """缓存声称有 ghost(指纹匹配), 服务端没有 → 重连后清单被就地改写为真实清单."""
        cfg = self._cfg()
        self._bootstrap([cfg],
                        manifest={"fake": {"fp": mcp._cfg_fp(cfg),
                                           "tools": [{"name": "ghost"}]}})
        self.assertEqual([t.name for t in mcp.tools], ["mcp_fake_ghost"])
        res = mcp.tools[0].run({})
        self.assertFalse(res["success"])
        with open(mcp.MANIFEST_PATH, encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(sorted(s["name"] for s in manifest["fake"]["tools"]),
                         ["boom", "echo"])

    def test_22_config_change_invalidates_manifest(self):
        """配置变更 → 指纹失配 → 强制重连 (脚本已删, 连接失败则无工具注册)."""
        self._bootstrap([self._cfg()])
        mcp._SERVERS.clear()
        mcp.tools.clear()
        os.remove(self.fake)                      # 若仍走缓存, 不拉子进程即通过
        self._bootstrap([self._cfg(args=[self.fake, "--changed"])])
        self.assertEqual(mcp.tools, [])

    def test_23_removed_server_pruned_from_manifest(self):
        self._bootstrap([self._cfg(), self._cfg(name="fake2")])
        with open(mcp.MANIFEST_PATH, encoding="utf-8") as f:
            self.assertEqual(sorted(json.load(f)), ["fake", "fake2"])
        mcp._SERVERS.clear()
        mcp.tools.clear()
        self._bootstrap([self._cfg(name="fake2")])   # fake 从配置中移除
        with open(mcp.MANIFEST_PATH, encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(list(manifest), ["fake2"])

    def test_24_tool_name_collision_gets_hash_suffix(self):
        """消毒后重名 (x.y 与 x_y) → 碰撞者追加 4 位 hash, 不静默覆盖."""
        specs = [{"name": "x.y"}, {"name": "x_y"}]
        self._bootstrap([self._cfg()],
                        manifest={"fake": {"fp": mcp._cfg_fp(self._cfg()),
                                           "tools": specs}})
        names = sorted(t.name for t in mcp.tools)
        self.assertEqual(len(names), len(set(names)), names)
        self.assertEqual(names[0], "mcp_fake_x_y")
        self.assertRegex(names[1], r"^mcp_fake_x_y_[0-9a-f]{4}$")

    def test_25_lazy_connect_on_first_call(self):
        """eager=0 + 有效缓存 → 导入期零连接; 首次 run() 才连并成功."""
        self._bootstrap([self._cfg()])            # 先生成带指纹的缓存
        mcp._SERVERS.clear()
        mcp.tools.clear()
        self._bootstrap([self._cfg()], eager="0")
        self.assertFalse(mcp._SERVERS["fake"].is_connected)
        self.assertEqual(len(mcp.tools), 2)
        res = self._tool().run({"text": "hi"})
        self.assertTrue(res["success"])
        self.assertTrue(mcp._SERVERS["fake"].is_connected)


class HttpTransportTest(McpTestBase):

    INIT = {"jsonrpc": "2.0", "id": 1, "result": {
        "protocolVersion": "2025-06-18",
        "capabilities": {"tools": {"listChanged": False}}}}
    LIST = {"jsonrpc": "2.0", "id": 2, "result": {
        "tools": [{"name": "t", "inputSchema": {"type": "object"}}]}}
    CALL = {"jsonrpc": "2.0", "id": 3, "result": {
        "content": [{"type": "text", "text": "done"}]}}

    def _connect(self, responses):
        srv = mcp._McpServer({"name": "h", "url": "https://x/mcp"})
        with mock.patch.object(mcp.urllib.request, "urlopen") as uo:
            uo.side_effect = responses
            srv.connect()
        return srv, uo

    def test_30_handshake_sends_accept_and_captures_session(self):
        srv, uo = self._connect([
            _http_response(self.INIT, headers={"Mcp-Session-Id": "s1"}),
            _http_response(raw=b""),
            _http_response(self.LIST)])
        self.assertEqual([s["name"] for s in srv.tools], ["t"])
        first = uo.call_args_list[0][0][0]
        self.assertEqual(first.get_header("Content-type"), "application/json")
        self.assertEqual(first.get_header("Accept"),
                         "application/json, text/event-stream")

    def test_31_session_id_echoed_on_later_requests(self):
        srv, uo = self._connect([
            _http_response(self.INIT, headers={"Mcp-Session-Id": "s1"}),
            _http_response(raw=b""),
            _http_response(self.LIST)])
        listing = uo.call_args_list[2][0][0]
        self.assertEqual(listing.get_header("Mcp-session-id"), "s1")
        self.assertEqual(listing.get_header("Mcp-protocol-version"), "2025-06-18")

    def test_32_sse_stream_response_is_parsed(self):
        sse = b"event: message\ndata: " + json.dumps(self.LIST).encode() + b"\n\n"
        srv, _ = self._connect([
            _http_response(self.INIT, headers={"Mcp-Session-Id": "s1"}),
            _http_response(raw=b""),
            _http_response(raw=sse, ctype="text/event-stream")])
        self.assertEqual([s["name"] for s in srv.tools], ["t"])

    def test_33_sse_ignores_leading_notifications(self):
        notify = b'data: {"jsonrpc":"2.0","method":"notifications/message"}\n\n'
        sse = notify + b"data: " + json.dumps(self.LIST).encode() + b"\n\n"
        srv, _ = self._connect([
            _http_response(self.INIT, headers={"Mcp-Session-Id": "s1"}),
            _http_response(raw=b""),
            _http_response(raw=sse, ctype="text/event-stream")])
        self.assertEqual([s["name"] for s in srv.tools], ["t"])

    def test_33b_sse_crlf_multievent_is_parsed(self):
        """CRLF 行尾 + 多事件流: 归一化后正确分块, 不把两个 data 行并成一个 JSON."""
        payload = json.dumps(self.LIST).encode()
        sse = (b"event: message\r\ndata: "
               b'{"jsonrpc":"2.0","method":"notifications/message"}'
               b"\r\n\r\nevent: message\r\ndata: " + payload + b"\r\n\r\n")
        parsed = mcp._HttpTransport._from_sse(sse)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["result"]["tools"][0]["name"], "t")

    def test_34_session_expiry_reinitializes_and_retries(self):
        expired = urllib.error.HTTPError("https://x/mcp", 404, "Not Found", None, None)
        srv, uo = self._connect([
            _http_response(self.INIT, headers={"Mcp-Session-Id": "s1"}),
            _http_response(raw=b""),
            _http_response(self.LIST)])
        with mock.patch.object(mcp.urllib.request, "urlopen") as uo2:
            uo2.side_effect = [expired,
                               _http_response(self.INIT, headers={"Mcp-Session-Id": "s2"}),
                               _http_response(raw=b""),
                               _http_response(self.LIST),
                               _http_response(self.CALL)]
            ok, content = srv.call("t", {})
        self.assertTrue(ok)
        self.assertEqual(content, "done")
        self.assertEqual(uo2.call_count, 5)

    def test_35_bearer_token_from_env(self):
        with mock.patch.dict(os.environ, {"MCP_TOK": "secret"}):
            srv = mcp._McpServer({"name": "h", "url": "https://x/mcp",
                                  "auth": {"type": "bearer", "token_env": "MCP_TOK"}})
            self.assertEqual(srv._auth_headers(), {"Authorization": "Bearer secret"})

    def test_36_close_sends_delete(self):
        srv, _ = self._connect([
            _http_response(self.INIT, headers={"Mcp-Session-Id": "s1"}),
            _http_response(raw=b""),
            _http_response(self.LIST)])
        with mock.patch.object(mcp.urllib.request, "urlopen") as uo:
            uo.return_value = _http_response(raw=b"")
            srv.close()
        self.assertEqual(uo.call_args[0][0].get_method(), "DELETE")

    def test_37_transport_alive_false_after_close(self):
        transport = mcp._HttpTransport("https://x/mcp")
        self.assertTrue(transport.alive)
        transport.close()
        self.assertFalse(transport.alive)


class NamingAndPromptTest(McpTestBase):

    def test_40_prefix_and_sanitize(self):
        self.assertEqual(mcp._tool_name("srv", "read_file"), "mcp_srv_read_file")
        self.assertEqual(mcp._tool_name("srv", "a.b/c"), "mcp_srv_a_b_c")
        self.assertEqual(mcp._tool_name("srv", "x", prefix=False), "x")

    def test_41_long_name_truncated_with_hash(self):
        name = mcp._tool_name("server", "t" * 80)
        self.assertLessEqual(len(name), 64)
        self.assertRegex(name, r"^mcp_server_t+_[0-9a-f]{8}$")

    def test_42_prompt_section_lists_servers(self):
        self._bootstrap([self._cfg()])
        sections = mcp.prompt_sections()
        self.assertEqual(len(sections), 1)
        name, body = sections[0]
        self.assertEqual(name, "mcp_tools")
        self.assertIn("**fake**", body)
        self.assertIn("echo", body)

    def test_43_prompt_section_empty_without_servers(self):
        self.assertEqual(mcp.prompt_sections(), [])


class StdioHousekeepingTest(McpTestBase):
    """日志轮转 / cfg 指纹."""

    def test_50_cfg_fp_stable_and_sensitive(self):
        cfg = self._cfg()
        self.assertEqual(mcp._cfg_fp(cfg), mcp._cfg_fp(self._cfg()))
        self.assertNotEqual(mcp._cfg_fp(cfg), mcp._cfg_fp(self._cfg(args=["x"])))
        self.assertEqual(mcp._cfg_fp({"name": "s", "_specs": [1]}),
                         mcp._cfg_fp({"name": "s"}))      # _specs 不参与指纹

    def test_51_log_rotated_when_oversized(self):
        log_path = os.path.join(mcp.LOG_DIR, "rot.log")
        os.makedirs(mcp.LOG_DIR, exist_ok=True)
        with mock.patch.object(mcp, "_LOG_MAX_BYTES", 16):
            t = mcp._StdioTransport(sys.executable, ["-c", "pass"],
                                    log_path=log_path, timeout=5)
            with open(log_path, "wb") as f:
                f.write(b"x" * 32)
            t.start()
            t.close()
        self.assertFalse(os.path.exists(log_path) and
                         os.path.getsize(log_path) > 16)
        self.assertTrue(os.path.exists(log_path + ".1"))
        with open(log_path + ".1", "rb") as f:
            self.assertEqual(f.read(), b"x" * 32)

    def test_52_log_reused_when_small(self):
        log_path = os.path.join(mcp.LOG_DIR, "keep.log")
        os.makedirs(mcp.LOG_DIR, exist_ok=True)
        with open(log_path, "wb") as f:
            f.write(b"old")
        t = mcp._StdioTransport(sys.executable, ["-c", "pass"],
                                log_path=log_path, timeout=5)
        t.start()
        t.close()
        self.assertFalse(os.path.exists(log_path + ".1"))
        with open(log_path, "rb") as f:
            self.assertIn(b"old", f.read())


if __name__ == "__main__":
    unittest.main()
