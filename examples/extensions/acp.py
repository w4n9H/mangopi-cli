"""Shipped extension — ACP (Agent Client Protocol) v1 agent server over stdio.

v0.1.48 从核心移出. 按需启用:
  * 复制/软链本文件到 ~/.mangocli/extensions/, 或
  * MANGO_EXTENSIONS_DIR=examples/extensions
启用后 `mangopi-cli --acp` 分派到本扩展 (entry_points["acp"]); 未安装时报错提示.

契约: 扩展文件顶层只允许 import, 禁止访问 mangopi_cli 属性 (导入期半初始化);
所需符号 (ContextManager/agent_loop/console/... 均晚于扩展扫描点) 一律在函数体内延迟导入.
"""
import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime
from typing import Dict, List, Any, Optional

import mangopi_cli  # noqa: F401  顶层仅 import, 不取属性


class AcpError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _prompt_text(prompt: Any) -> str:
    """提取 session/prompt 文本: 兼容 string 与 text ContentBlock 数组.
    声明的 promptCapabilities 仅 text; 收到非 text block (image/resource/audio 等)即报错, 禁止静默丢弃导致 context 丢失.
    """
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, list):
        parts = []
        for b in prompt:
            if not isinstance(b, dict) or not isinstance(b.get("type"), str):
                raise AcpError(-32602, "Malformed prompt content block: %r" % (b,))
            if b.get("type") != "text":
                raise AcpError(-32602, "Unsupported prompt content type: %s" % b.get("type"))
            parts.append(b.get("text", ""))
        return "".join(parts)
    return str(prompt)


class AcpServer:
    def __init__(self):
        from mangopi_cli import ContextManager  # 函数体延迟导入: 执行时模块已完整初始化
        self.sessions: Dict[str, ContextManager] = {}     # sessionId -> ctx
        self.cancel_flags: Dict[str, threading.Event] = {}   # sessionId -> cancel 事件
        self._perm: Dict[str, Dict[str, Any]] = {}           # requestId -> {event, decision}
        self._lock = threading.RLock()
        self._local = threading.local()  # prompt 线程本地状态: sid / msg_id / tool_id (并发隔离)
        self._seq = 0

    # --- 线程本地状态访问 (每个 session/prompt 在独立线程处理, 事件发射必属本线程的会话) ---
    @property
    def _cur_sid(self) -> Optional[str]: return getattr(self._local, "sid", None)

    @_cur_sid.setter
    def _cur_sid(self, value: Optional[str]) -> None: self._local.sid = value

    @property
    def _msg_id(self) -> Optional[str]: return getattr(self._local, "msg_id", None)

    @_msg_id.setter
    def _msg_id(self, value: Optional[str]) -> None: self._local.msg_id = value

    def _tool_id(self) -> Optional[str]: return getattr(self._local, "tool_id", None)

    def _set_tool_id(self, value: Optional[str]) -> None: self._local.tool_id = value

    # ---------- JSON-RPC 底层 ----------
    def _send(self, obj: dict) -> None:
        with self._lock:
            print(json.dumps(obj, ensure_ascii=False), flush=True)

    def _respond(self, msg_id: Any, result: Any) -> None: self._send({"jsonrpc": "2.0", "id": msg_id, "result": result})

    def _error(self, msg_id: Any, code: int, message: str) -> None:
        self._send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})

    def _notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _emit(self, sid: str, update: dict) -> None:
        self._notify("session/update", {"sessionId": sid, "update": update})

    def _next_id(self) -> str:
        self._seq += 1
        return str(self._seq)

    # ---------- 方法分发 ----------
    def dispatch(self, msg: dict) -> None:
        method, msg_id = msg.get("method"), msg.get("id")
        if not isinstance(method, str):  # JSON-RPC 响应 (无 method): 匹配 pending 权限请求 (id 关联)
            if "result" in msg or "error" in msg:
                self._on_response(msg_id, msg.get("result"))
                return
            if msg_id is not None:
                self._error(msg_id, -32600, "Invalid Request")
            return
        handler = getattr(self, "_m_" + method.replace("/", "_"), None)
        if handler is None:
            if msg_id is not None:
                self._error(msg_id, -32601, "Method not found: %s" % method)
            return
        try:
            result = handler(msg.get("params") or {})
            if msg_id is not None:
                self._respond(msg_id, result)
        except AcpError as e:
            self._error(msg_id, e.code, e.message)
        except Exception as e:  # noqa: BLE001 协议边界兜底
            traceback.print_exc()  # 完整堆栈落 stderr, 主循环不可见但可诊断
            self._error(msg_id, -32603, "Internal error: %s" % e)

    def _on_response(self, msg_id: Any, result: Any) -> None:  # 处理client对session/request_permission的响应(同id关联).
        if msg_id is None:
            return
        with self._lock:
            rec = self._perm.get(str(msg_id))
            if rec is None:
                return  # 未知/过期响应, 忽略
            outcome = ((result or {}).get("outcome") or {})
            oc = outcome.get("outcome", "")
            if oc == "selected" and outcome.get("optionId", "") == "allow-once":
                rec["decision"] = "allow"
            elif oc == "cancelled":
                rec["decision"] = "cancelled"  # RequestPermissionOutcome::Cancelled: client 已取消 turn
            else:
                rec["decision"] = "deny"
            rec["event"].set()

    # ---------- 协议方法 ----------
    def _m_initialize(self, p: dict) -> dict:
        from mangopi_cli import __version__
        version = p.get("protocolVersion")
        if version is not None and int(version) != 1:
            raise AcpError(-32602, "Unsupported protocol version: %s" % version)
        return {
            "protocolVersion": 1,
            "agentCapabilities": {  # 官方 v1 结构: 支持 session/load + session/list, 不支持 MCP, prompt 仅纯文本
                "loadSession": True,
                "sessionCapabilities": {"list": {}},
                "promptCapabilities": {"image": False, "audio": False, "embeddedContext": False},
                "mcpCapabilities": {"http": False, "sse": False}},
            "agentInfo": {"name": "mangopi-cli", "title": "Mangopi CLI", "version": __version__},
            "authMethods": []}

    def _m_session_new(self, p: dict) -> dict:  # NewSessionRequest required: ["cwd", "mcpServers"]
        from mangopi_cli import ContextManager, session_dir
        cwd = p.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            raise AcpError(-32602, "Missing required field: cwd")
        if not isinstance(p.get("mcpServers"), list):
            raise AcpError(-32602, "Missing required field: mcpServers")
        # 官方 params: {cwd, mcpServers?}; sessionId 由 agent 生成并返回, 无 id 字段
        # 确定性命名: name = acp_<epoch>_<hex> => 文件 session_dir/<name>.json, sid = sess_<name>,
        # 重启后 session/list 仍可发现并恢复 (旧随机 sid 无法跨进程恢复)
        name = "acp_" + str(int(time.time())) + "_" + os.urandom(4).hex()
        sid = "sess_" + name
        ctx = ContextManager()
        ctx.load(self._ctx_file(sid))
        self.sessions[sid] = ctx
        self.cancel_flags[sid] = threading.Event()
        return {"sessionId": sid}

    def _m_session_prompt(self, p: dict) -> Optional[dict]:  # PromptRequest required: ["prompt", "sessionId"]
        from mangopi_cli import agent_loop
        sid = p.get("sessionId")
        ctx = self.sessions.get(sid)
        if ctx is None:
            raise AcpError(-32602, "Unknown session: %s" % sid)
        if p.get("prompt") is None:
            raise AcpError(-32602, "Missing required field: prompt")
        cancel = self.cancel_flags[sid]
        cancel.clear()
        text = _prompt_text(p.get("prompt"))
        self._cur_sid = sid
        self._msg_id = None  # 新 turn: 重置消息身份, 本 turn 所有 chunk 聚合为一条消息
        try:
            agent_loop(ctx, self._ctx_file(sid), text, cancel_event=cancel)
        finally:
            if self._cur_sid == sid:
                self._cur_sid = None
        return {"stopReason": "cancelled" if cancel.is_set() else "end_turn"}

    def _m_session_cancel(self, p: dict) -> None:
        sid = p.get("sessionId")
        ev = self.cancel_flags.get(sid)
        if ev is not None:
            ev.set()  # 软取消: 当前 LLM 调用返回后结束本轮
        # 协议要求 abort 进行中的工具调用: 解除本 session 所有 pending 权限请求,
        # 否则 client 取消后不再裁决, prompt 线程会卡满权限超时
        with self._lock:
            for rid, rec in list(self._perm.items()):
                if rec.get("sid") == sid:
                    rec["decision"] = "deny"  # 取消 => 工具不执行
                    rec["event"].set()
        return None

    def _m_session_list(self, p: dict) -> dict:  # session/list: 客户端据此展示会话历史并切换.
        from mangopi_cli import session_dir, project_root
        try:
            names = os.listdir(session_dir)
        except OSError:
            names = []
        sessions = []
        for f in sorted(names):
            if not f.endswith(".json") or not f.startswith("acp_"):  # 只关注 ACP 会话, CLI 会话不混入
                continue
            fpath = os.path.join(session_dir, f)
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    msgs = json.load(fh)
            except (json.JSONDecodeError, IOError):
                msgs = []
            title = next((m.get("content", "")[:80] for m in msgs if m.get("role") == "user"), None)
            sessions.append({
                "sessionId": "sess_" + f[:-5], "cwd": project_root, "title": title,
                "updatedAt": datetime.fromtimestamp(os.path.getmtime(fpath)).isoformat(),
                "_meta": {"messageCount": len(msgs)}})
        return {"sessions": sessions}

    def _m_session_load(self, p: dict) -> None:  # session/load: 恢复指定会话并回放历史 (session/update 通知) 后响应 null."""
        from mangopi_cli import ContextManager
        sid = p.get("sessionId")
        if not isinstance(sid, str) or not sid.startswith("sess_"):
            raise AcpError(-32602, "Invalid session id")
        name = sid[5:]  # 与 session/list 同一判断: 按 name 前缀过滤 CLI 会话
        if not name.startswith("acp_"):
            raise AcpError(-32602, "Invalid session id")
        fpath = self._ctx_file(sid)
        if not os.path.isfile(fpath):
            raise AcpError(-32602, "Unknown session: %s" % sid)
        ctx = ContextManager()
        ctx.load(fpath)
        self.sessions[sid] = ctx
        self.cancel_flags[sid] = threading.Event()
        for i, msg in enumerate(ctx.messages):
            mid = "mr_" + str(i)
            role = msg.get("role")
            if role == "user":
                self._emit(sid, {"sessionUpdate": "user_message_chunk", "messageId": mid,
                                 "content": {"type": "text", "text": msg.get("content", "")}})
            elif role == "assistant":
                text = msg.get("content") or ""
                if text:
                    self._emit(sid, {"sessionUpdate": "agent_message_chunk", "messageId": mid,
                                     "content": {"type": "text", "text": text}})
                for tc in msg.get("tool_calls") or []:
                    tid = tc.get("id", "")
                    self._emit(sid, {"sessionUpdate": "tool_call", "toolCallId": tid,
                                     "title": tc.get("function", {}).get("name", ""), "status": "pending"})
                    self._emit(sid, {"sessionUpdate": "tool_call_update", "toolCallId": tid,
                                     "status": "completed"})
                reasoning = msg.get("reasoning_content") or ""
                if reasoning:
                    self._emit(sid, {"sessionUpdate": "agent_thought_chunk", "messageId": mid,
                                     "content": {"type": "text", "text": reasoning}})
            elif role == "tool":
                self._emit(sid, {"sessionUpdate": "tool_call_update",
                                 "toolCallId": msg.get("tool_call_id", ""), "status": "completed"})
        return None

    # ---------- Printer.emitter 回调 ----------
    def emit(self, d: dict) -> None:
        """Printer.emitter 回调: 事件 dict → session/update 通知 (tool/tool_result/thinking/output/usage)."""
        sid = self._cur_sid
        if sid is None:
            return
        t = d.get("type")
        if t == "tool":
            tid = "%s:%s" % (d.get("name", "tool"), self._next_id())
            self._set_tool_id(tid)
            self._emit(sid, {"sessionUpdate": "tool_call", "toolCallId": tid,
                             "title": "%s %s" % (d.get("name", "tool"), str(d.get("args_preview", ""))[:80]),
                             "status": "pending"})
        elif t == "tool_result":
            tid = self._tool_id() or ("%s:0" % d.get("name", "tool"))
            self._set_tool_id(None)  # 配对消费
            self._emit(sid, {"sessionUpdate": "tool_call_update", "toolCallId": tid,
                             "status": "completed" if d.get("ok") else "failed"})
        elif t == "thinking":
            if self._msg_id is None:
                self._msg_id = "msg_" + self._next_id()
            self._emit(sid, {"sessionUpdate": "agent_thought_chunk", "messageId": self._msg_id,
                             "content": {"type": "text", "text": str(d.get("content", ""))}})
        elif t == "output":
            if self._msg_id is None:
                self._msg_id = "msg_" + self._next_id()  # turn 内首个 chunk 时生成, 后续复用
            self._emit(sid, {"sessionUpdate": "agent_message_chunk", "messageId": self._msg_id,
                             "content": {"type": "text", "text": str(d.get("content", ""))}})
        elif t == "usage":
            self._emit(sid, {"sessionUpdate": "usage_update",
                             "used": d.get("context_tokens", 0), "size": d.get("max_context", 0)})

    def _h_permission(self, message: str) -> bool:
        sid = self._cur_sid
        if sid is None:
            return False
        req_id = "perm_" + self._next_id()
        ev = threading.Event()
        with self._lock:
            self._perm[req_id] = {"event": ev, "decision": "", "sid": sid}
        self._send({"jsonrpc": "2.0", "id": req_id, "method": "session/request_permission",
                    "params": {"sessionId": sid,
                               "toolCall": {"toolCallId": self._tool_id() or "", "title": message[:120]},
                               "options": [
                                   {"optionId": "allow-once", "name": "Allow once", "kind": "allow_once"},
                                   {"optionId": "reject-once", "name": "Reject", "kind": "reject_once"}]}})
        ev.wait(timeout=300)
        with self._lock:
            decision = self._perm.pop(req_id, {}).get("decision", "")
        if decision == "cancelled":
            ev2 = self.cancel_flags.get(sid)
            if ev2 is not None:
                ev2.set()  # 协议: client 取消 turn 时以 Cancelled 裁决权限 => 同步终止本轮
            return False
        return decision == "allow"

    # ---------- 会话文件与主循环 ----------
    def _ctx_file(self, sid: str) -> str:
        from mangopi_cli import session_dir
        # sid 与文件名确定性映射: sid = "sess_<name>" => session_dir/<name>.json
        name = sid[5:] if sid.startswith("sess_") else sid
        if not name or ".." in name or "/" in name:
            raise AcpError(-32602, "Invalid session id")
        return os.path.join(session_dir, name + ".json")

    # ---------- 主循环 ----------
    def serve(self) -> None:
        from mangopi_cli import console
        # 原生注册 (Printer 扩展点): acp 模式文本静默, 事件经 emitter, 权限经 handler
        console.mode = "acp"
        console.emitter = self.emit
        console.permission_handler = self._h_permission
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("method") == "session/prompt":  # prompt 在独立线程处理, 主循环继续读 stdin 以接收 cancel 通知
                threading.Thread(target=self._run_prompt_thread, args=(msg,), daemon=True, name="acp-prompt").start()
            else:
                self.dispatch(msg)

    def _run_prompt_thread(self, msg: dict) -> None:
        """prompt 线程边界兜底: 线程内未捕获异常(含 _error 自身失败, 如 client 断连的BrokenPipeError)不会传播到主循环, 必须打印 traceback 并尽力回执, 避免静默吞掉."""
        try:
            self.dispatch(msg)
        except Exception:  # noqa: BLE001 线程边界
            traceback.print_exc()
            try:
                self._error(msg.get("id"), -32603, "Internal error: %s" % sys.exc_info()[1])
            except Exception:  # noqa: BLE001 回执也失败(client 已断连), 放弃
                pass


def acp_main() -> int:
    from mangopi_cli import MANGO_KEY, console, initialize_system
    if not MANGO_KEY:
        console.error("MANGO_KEY env var is required for ACP mode")
        return 1
    initialize_system()  # 确保 .mangocli/session 等目录存在
    AcpServer().serve()
    return 0


# 导出约定: entry_points 字典 (name -> Callable[[], int]); 同名首个生效
entry_points = {"acp": acp_main}
