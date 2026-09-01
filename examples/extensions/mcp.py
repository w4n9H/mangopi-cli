"""Shipped-style extension — MCP client: JSON-RPC 2.0 over stdio / Streamable HTTP.

按需启用:
  * 复制/软链本文件到扩展目录:
      ~/.mangocli/extensions/                  (无 MANGO_PRESET)
      ~/.mangocli/presets/<name>/extensions/   (需设 MANGO_PRESET=<name>)
  * 配置 ~/.mangocli/mcp_servers.json:

        {"servers": [
          {"name": "filesystem", "command": "uvx",
           "args": ["mcp-server-filesystem", "/tmp"]},
          {"name": "internal", "url": "https://mcp.internal.example.com/mcp",
           "auth": {"type": "bearer", "token_env": "MCP_INTERNAL_TOKEN"}}
        ]}

    每个 server 条目的配置键:
      name          必填, 唯一标识 (工具前缀 / manifest 键 / 日志名)
      command/args  stdio 传输: 子进程命令与参数
      url           Streamable HTTP 传输 (与 command 二选一)
      env           stdio 子进程附加环境变量 {"K": "V"}
      auth          HTTP 鉴权: {"type": "bearer", "token_env": "ENV_NAME"}
                    (或 "token": 明文, 不推荐)
      enabled       false 跳过该 server (默认 true)
      confirm       true 时每次调用前询问 y/n (默认 false 直接执行;
                    仅对可信 server 保持默认)
      prefix        工具名加前缀 mcp_<server>_ (默认 true; 关闭后若与内置
                    工具重名会覆盖内置工具, 慎用)
      timeout       tools/call 超时秒数 (默认 60)
      init_timeout  initialize 握手超时秒数 (默认 20)

行为:
  * tools           — 每个 MCP 工具一个 McpProxyTool, 命名 mcp_<server>_<tool>;
                      原生 inputSchema 透传 (override schema(), 绕过 ToolBase.params 的
                      扁平标量限制), 核心 tool_schema() 无需改动
  * prompt_sections — callable 动态段 "mcp_tools", 列出已配置 server 与工具清单

设计说明:
  * 传输无关: _Transport 统一 start/request/notify/close, _StdioTransport (subprocess
    + 读线程) 与 _HttpTransport (urllib POST + SSE 解析) 共享同一套 JSON-RPC 层.
  * 启动快: 导入期优先用清单缓存 (~/.mangocli/mcp_manifest.json, 按配置指纹校验)
    直接建工具, 不连接; 缓存缺失或配置变更才连接一次并写回缓存.
    首次 tools/call 时确保连接, 之后长连接复用.
  * 自愈: 子进程死亡 / 会话过期 / unknown tool → 自动重连并刷新清单, 重试一次.
  * server stderr 重定向到 ~/.mangocli/mcp_logs/<name>.log (不接走会写满管道卡死
    子进程; 启动时超过 5MB 轮转为 <name>.log.1).
  * OAuth 2.0 / 遗留 SSE 传输 / GET 长连接推送不在 v1 范围.

契约: 顶层仅 import; core 符号 (console/MANGO_YOLO) 在函数体内延迟导入.
"""
import atexit
import hashlib
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request

from mangopi_cli import ToolBase

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "mangopi-cli", "version": "0.1"}
MAX_TOOL_NAME = 64
_LOG_MAX_BYTES = 5 * 1024 * 1024

_BASE = os.path.expanduser("~/.mangocli")
CONFIG_PATH = os.path.join(_BASE, "mcp_servers.json")
MANIFEST_PATH = os.path.join(_BASE, "mcp_manifest.json")
LOG_DIR = os.path.join(_BASE, "mcp_logs")


# --- errors ---
class _McpError(Exception):
    pass


class _Disconnected(_McpError):      # stdio 子进程已退出
    pass


class _SessionExpired(_McpError):    # HTTP 会话 404, 需重新 initialize
    pass


class _Waiter:
    """stdio 读线程与请求方的交接点: 响应消息或异常二选一."""
    __slots__ = ("event", "msg", "exc")

    def __init__(self):
        self.event = threading.Event()
        self.msg = None
        self.exc = None


def _log(msg):
    print(f"[mcp] {msg}", file=sys.stderr, flush=True)


# --- transports ---
class _StdioTransport:
    """JSON-RPC over 子进程 stdin/stdout, 换行分隔; 读线程按 id 分发响应."""

    def __init__(self, command, args=None, env=None, log_path=None, timeout=60.0):
        self.command = command
        self.args = list(args or [])
        self.env = env or {}
        self.log_path = log_path
        self.timeout = timeout
        self._proc = None
        self._logf = None
        self._pending = {}
        self._id = 0
        self._lock = threading.Lock()

    @property
    def alive(self):
        return self._proc is not None and self._proc.poll() is None

    def start(self):
        env = dict(os.environ)
        env.update({str(k): str(v) for k, v in self.env.items()})
        if self.log_path:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            try:
                if os.path.getsize(self.log_path) > _LOG_MAX_BYTES:  # 简单轮转: 保留一份旧日志
                    os.replace(self.log_path, self.log_path + ".1")
            except OSError:
                pass
            self._logf = open(self.log_path, "ab", buffering=0)
        self._proc = subprocess.Popen(
            [self.command] + self.args,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self._logf or subprocess.DEVNULL,
            env=env, bufsize=0)
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _read_loop(self):
        try:
            for raw in self._proc.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                mid = msg.get("id")
                waiter = self._pending.get(mid) if mid is not None else None
                if waiter is not None:
                    waiter.msg = msg
                    waiter.event.set()
        except (OSError, ValueError):
            pass
        finally:
            # 进程退出: 唤醒所有等待方, 否则请求方会卡到超时
            for waiter in list(self._pending.values()):
                waiter.exc = _Disconnected("server process exited")
                waiter.event.set()

    def _write(self, payload):
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        with self._lock:  # 串行化写入, 防并发线程交错帧
            self._proc.stdin.write(data)
            self._proc.stdin.flush()

    def request(self, method, params=None, timeout=None):
        if self._proc is None or not self.alive:
            raise _Disconnected("server not running")
        with self._lock:
            self._id += 1
            mid = self._id
        waiter = _Waiter()
        self._pending[mid] = waiter
        payload = {"jsonrpc": "2.0", "id": mid, "method": method}
        if params is not None:
            payload["params"] = params
        try:
            self._write(payload)
        except (OSError, ValueError, BrokenPipeError) as err:
            self._pending.pop(mid, None)
            raise _Disconnected(f"send failed: {err}")
        if not waiter.event.wait(timeout or self.timeout):
            self._pending.pop(mid, None)
            raise _McpError(f"timeout after {timeout or self.timeout}s on {method}")
        self._pending.pop(mid, None)
        if waiter.exc:
            raise waiter.exc
        return _unwrap(waiter.msg, method)

    def notify(self, method, params=None):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        try:
            self._write(payload)
        except (OSError, ValueError, BrokenPipeError):
            pass

    def close(self):
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    self._proc.kill()
                except OSError:
                    pass
        if self._logf is not None:
            try:
                self._logf.close()
            except OSError:
                pass
            self._logf = None
        self._proc = None


class _HttpTransport:
    """Streamable HTTP: 每条 JSON-RPC 一个 POST; 响应可为 JSON 单对象或 SSE 流."""

    def __init__(self, url, headers=None, timeout=60.0):
        self.url = url
        self._headers = {str(k): str(v) for k, v in (headers or {}).items()}
        self.timeout = timeout
        self._session_id = None
        self._closed = False
        self._id = 0
        self._lock = threading.Lock()

    @property
    def alive(self):
        return not self._closed

    def start(self):
        pass

    def _post(self, payload, timeout):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        hdrs = {"Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"}
        if self._session_id:
            hdrs["Mcp-Session-Id"] = self._session_id
            hdrs["MCP-Protocol-Version"] = PROTOCOL_VERSION
        hdrs.update(self._headers)
        req = urllib.request.Request(self.url, data=body, headers=hdrs, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self._session_id = sid
                ctype = (resp.headers.get("Content-Type") or "").lower()
                raw = resp.read()
        except urllib.error.HTTPError as err:
            if err.code == 404 and self._session_id:
                self._session_id = None
                raise _SessionExpired("session expired")
            raise _McpError(f"http {err.code}: {err.reason}")
        except urllib.error.URLError as err:
            raise _McpError(f"http error: {err.reason}")
        if not raw:
            return None
        if "text/event-stream" in ctype:
            return self._from_sse(raw)
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            raise _McpError("invalid json in response")

    @staticmethod
    def _from_sse(raw):
        """SSE 流里第一条 response (含 result/error) 即所求; 其余为通知, v1 忽略.
        兼容 LF/CRLF 行尾 (先归一化再按空行分块, 否则 CRLF 多事件流会并成一个块)."""
        for block in raw.decode("utf-8", "replace").replace("\r\n", "\n").split("\n\n"):
            data = [ln[5:].strip() for ln in block.splitlines() if ln.startswith("data:")]
            if not data:
                continue
            try:
                msg = json.loads("\n".join(data))
            except ValueError:
                continue
            if "result" in msg or "error" in msg:
                return msg
        return None

    def request(self, method, params=None, timeout=None):
        with self._lock:
            self._id += 1
            mid = self._id
        payload = {"jsonrpc": "2.0", "id": mid, "method": method}
        if params is not None:
            payload["params"] = params
        msg = self._post(payload, timeout or self.timeout)
        if msg is None:
            raise _McpError(f"empty response for {method}")
        return _unwrap(msg, method)

    def notify(self, method, params=None):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        try:
            self._post(payload, self.timeout)
        except _McpError:
            pass

    def close(self):
        self._closed = True
        if not self._session_id:
            return
        req = urllib.request.Request(
            self.url, data=b"", method="DELETE",
            headers={"Mcp-Session-Id": self._session_id, **self._headers})
        try:
            urllib.request.urlopen(req, timeout=5).close()
        except (urllib.error.HTTPError, urllib.error.URLError, OSError):
            pass
        self._session_id = None


def _unwrap(msg, method):
    if not isinstance(msg, dict):
        raise _McpError(f"malformed response for {method}")
    if "error" in msg:
        err = msg["error"] or {}
        raise _McpError(f"{err.get('message', 'json-rpc error')} (code {err.get('code')})")
    return msg.get("result") or {}


# --- server session ---
class _McpServer:
    """一个 MCP server 的会话: 握手 / 工具清单 / 调用 / 自愈重连."""

    def __init__(self, cfg):
        self.name = str(cfg.get("name") or "mcp")
        self.cfg = cfg
        self._transport = None
        self._specs = list(cfg.get("_specs") or [])
        self._lock = threading.RLock()
        self._dead = False

    @property
    def tools(self):
        return self._specs

    @property
    def is_connected(self):
        return self._transport is not None and self._transport.alive

    def _auth_headers(self):
        auth = self.cfg.get("auth") or {}
        if not isinstance(auth, dict) or auth.get("type") != "bearer":
            return {}
        token = auth.get("token") or ""
        if not token and auth.get("token_env"):
            token = os.environ.get(str(auth["token_env"]), "")
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _make_transport(self):
        timeout = float(self.cfg.get("timeout") or 60)
        url = self.cfg.get("url")
        if url:
            return _HttpTransport(str(url), headers=self._auth_headers(), timeout=timeout)
        command = self.cfg.get("command")
        if not command:
            raise _McpError("server config needs 'command' or 'url'")
        return _StdioTransport(str(command), self.cfg.get("args"),
                               env=self.cfg.get("env"),
                               log_path=os.path.join(LOG_DIR, f"{self.name}.log"),
                               timeout=timeout)

    def connect(self):
        with self._lock:
            self._close_transport()
            transport = self._make_transport()
            transport.start()
            try:
                result = transport.request("initialize", {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                }, timeout=float(self.cfg.get("init_timeout") or 20))
                transport.notify("notifications/initialized")
                self._specs = self._list_tools(transport)
            except _McpError:
                try:
                    transport.close()      # 清理失败不得掩盖握手失败的原始错误
                except Exception:          # noqa: BLE001
                    pass
                raise
            self._transport = transport
            self._dead = False
            return self._specs

    @staticmethod
    def _list_tools(transport):
        specs, cursor = [], None
        for _ in range(50):                      # 防御: 服务端游标死循环
            result = transport.request("tools/list", {"cursor": cursor} if cursor else None)
            specs.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return specs

    def call(self, tool_name, arguments=None, timeout=None):
        last = None
        for attempt in (1, 2):
            try:
                with self._lock:
                    if self._transport is None or not self._transport.alive:
                        self.connect()
                    result = self._transport.request(
                        "tools/call", {"name": tool_name, "arguments": arguments or {}},
                        timeout=timeout)
                return _flatten(result)
            except _McpError as err:
                last = err
                if attempt == 1 and self._should_retry(err):
                    try:
                        self.connect()
                        _MANIFEST[self.name] = {"fp": _cfg_fp(self.cfg),   # 自愈: 陈旧清单就地刷新
                                                "tools": self.tools}
                        _save_manifest(_MANIFEST)
                    except _McpError:
                        pass
                    continue
                break
        return False, f"mcp {self.name}/{tool_name}: {last}"

    @staticmethod
    def _should_retry(err):
        if isinstance(err, (_Disconnected, _SessionExpired)):
            return True
        text = str(err).lower()
        return "unknown tool" in text or "not found" in text

    def _close_transport(self):
        if self._transport is not None:
            try:
                self._transport.close()
            except Exception:      # noqa: BLE001 清理失败不影响后续
                pass
            self._transport = None

    def close(self):
        with self._lock:
            self._close_transport()


def _flatten(result):
    """MCP content[] → (ok, content); image 复用核心多模态形状 {"type":"image", ...}."""
    is_error = bool(result.get("isError"))
    texts, images = [], []
    for item in result.get("content") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text":
            texts.append(item.get("text") or "")
        elif kind == "image":
            mime = item.get("mimeType") or "image/png"
            images.append(f"data:{mime};base64,{item.get('data') or ''}")
        elif kind == "resource":
            res = item.get("resource") or {}
            texts.append(res.get("text") or f"[resource {res.get('uri', '')}]")
        elif kind == "resource_link":
            texts.append(f"[resource_link {item.get('uri', '')}]")
        elif kind == "audio":
            texts.append(f"[audio {item.get('mimeType') or 'audio'}]")
        else:
            texts.append(json.dumps(item, ensure_ascii=False)[:500])
    text = "\n".join(t for t in texts if t).strip()
    if not text and result.get("structuredContent"):
        text = json.dumps(result["structuredContent"], ensure_ascii=False)
    if images:
        payload = {"type": "image", "image_url": images[0]}
        if text:
            payload["text"] = text
        if len(images) > 1:
            note = f"[{len(images) - 1} more image(s) not shown]"
            payload["text"] = f"{payload.get('text', '')}\n{note}".strip()
        return (not is_error), payload
    return (not is_error), text


# --- config / manifest ---
def _load_config():
    if not os.path.isfile(CONFIG_PATH):
        return []
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError) as err:
        _log(f"bad config {CONFIG_PATH}: {err}")
        return []
    out = []
    for entry in (data.get("servers") if isinstance(data, dict) else None) or []:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        if entry.get("enabled") is False:
            continue
        out.append(entry)
    return out


def _load_manifest():
    if not os.path.isfile(MANIFEST_PATH):
        return {}
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_manifest(manifest):
    try:
        os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
        tmp = MANIFEST_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        os.replace(tmp, MANIFEST_PATH)
    except OSError as err:
        _log(f"save manifest err: {err}")


def _cfg_fp(cfg):
    """配置指纹: cfg 规范化 JSON 的 sha1 (剔除测试注入的 _specs).
    manifest 记录指纹, 配置变更即失效, 避免 server 新增工具永远不可见."""
    payload = {k: v for k, v in cfg.items() if k != "_specs"}
    return hashlib.sha1(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _tool_name(server_name, tool_name, prefix=True):
    raw = tool_name if not prefix else f"mcp_{server_name}_{tool_name}"
    safe = "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in str(raw))
    if len(safe) <= MAX_TOOL_NAME:
        return safe
    digest = hashlib.sha1(str(raw).encode("utf-8")).hexdigest()[:8]
    return f"{safe[:MAX_TOOL_NAME - 9]}_{digest}"


class McpProxyTool(ToolBase):
    """一个 MCP 工具的本地代理: 原生 inputSchema 透传, 参数原样转发."""

    use_spinner = True
    preview_lines = 12

    def __init__(self, server, spec, prefix=True):
        self._server = server
        self._spec = spec
        self._remote = str(spec.get("name") or "")
        self.name = _tool_name(server.name, self._remote, prefix)
        self.description = (str(spec.get("description") or "").strip()
                            or f"MCP tool '{self._remote}' on server '{server.name}'")
        self.params = {}          # schema() 被 override, params 不参与
        self.guidance = ""

    def schema(self):
        params = self._spec.get("inputSchema")
        if not isinstance(params, dict) or not params:
            params = {"type": "object", "properties": {}}
        params = dict(params)
        params.setdefault("type", "object")
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": params}}

    def preview(self, args):
        try:
            return json.dumps(args, ensure_ascii=False)[:self.preview_width]
        except (TypeError, ValueError):
            return str(args)[:self.preview_width]

    def confirm(self, args):
        if not self._server.cfg.get("confirm"):
            return True
        from mangopi_cli import console, MANGO_YOLO   # 函数体内延迟导入
        return MANGO_YOLO or console.prompt_apply(
            f"Call MCP tool '{self._remote}' on server '{self._server.name}' (y or n)?")

    def run(self, args):
        ok, content = self._server.call(self._remote, args or {})
        return self.ok(content) if ok else self.fail(content)


# --- bootstrap ---
_SERVERS = {}
_MANIFEST = {}
tools = []


def _bootstrap():
    """建工具: 清单缓存 (配置指纹匹配) 命中则零延迟; 指纹不匹配/缓存缺失才连接
    一次并写回缓存. 已删除 server 的清单条目被 prune. MANGO_MCP_EAGER=0 可完全
    跳过导入期连接 (仅用缓存, 首次 tools/call 再连)."""
    global _MANIFEST
    _MANIFEST = _load_manifest()
    eager = os.environ.get("MANGO_MCP_EAGER", "1") != "0"
    changed = False
    used = set()                                # 已占用工具名, 消毒后重名消歧
    for cfg in _load_config():
        name = str(cfg["name"])
        server = _McpServer(cfg)
        _SERVERS[name] = server
        entry = _MANIFEST.get(name)
        entry = entry if isinstance(entry, dict) else {}   # 旧格式 list / 坏条目 → 视为缺失
        specs = entry.get("tools")
        if entry.get("fp") != _cfg_fp(cfg) or not isinstance(specs, list):
            specs = None                        # 配置变更或缓存缺失 → 强制刷新
        if specs is None and eager:
            try:
                server.connect()
                specs = server.tools
                _MANIFEST[name] = {"fp": _cfg_fp(cfg), "tools": specs}
                changed = True
            except Exception as err:      # noqa: BLE001 单个 server 不可用不影响其余
                _log(f"server '{name}' unavailable: {err}")
                continue
        for spec in specs or []:
            if not isinstance(spec, dict) or not spec.get("name"):
                continue
            tool = McpProxyTool(server, spec, prefix=cfg.get("prefix", True))
            if tool.name in used:         # 消毒后碰撞 (如 a.b 与 a_b): 追加短 hash 消歧
                digest = hashlib.sha1(tool.name.encode("utf-8")).hexdigest()[:4]
                tool.name = f"{tool.name[:MAX_TOOL_NAME - 5]}_{digest}"
            used.add(tool.name)
            tools.append(tool)
    pruned = {n: m for n, m in _MANIFEST.items() if n in _SERVERS and isinstance(m, dict)}
    changed = changed or len(pruned) != len(_MANIFEST)
    _MANIFEST = pruned
    if changed:
        _save_manifest(_MANIFEST)


def _shutdown():
    for server in list(_SERVERS.values()):
        try:
            server.close()
        except Exception:      # noqa: BLE001 退出期清理
            pass


def prompt_sections():
    """动态段: 每次 SystemPrompt 构建时输出已配置 server 与工具清单."""
    if not _SERVERS:
        return []
    lines = ["## MCP Servers", "",
             "Tools from configured MCP servers are exposed as `mcp_<server>_<tool>` "
             "and behave like built-in tools — call them directly with JSON arguments."]
    for name in sorted(_SERVERS):
        server = _SERVERS[name]
        entry = _MANIFEST.get(name)
        specs = server.tools or (entry.get("tools") if isinstance(entry, dict) else None) or []
        state = "connected" if server.is_connected else "on demand"
        names = ", ".join(str(s.get("name", "")) for s in specs) or "no tools"
        lines.append(f"- **{name}** ({state}): {names}")
    return [("mcp_tools", "\n".join(lines) + "\n")]


_bootstrap()
atexit.register(_shutdown)
