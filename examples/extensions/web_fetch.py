"""Shipped extension — web_fetch: fetch a URL's content into the model's context.
Shipped extension — web_fetch: 抓取 URL 内容进入上下文.

抓取单个 http/https URL 的正文 (HTML 去标签; 其他类型原样), 按 max_chars 截断.
Fetches a single http/https URL's body (HTML stripped of tags; other content types
returned raw), truncated to max_chars.

安全: 仅允许 http/https scheme (拒绝 file:// 等, SSRF 防护); 超时 15s; 响应上限 100KB.
Security: only http/https schemes allowed (rejects file:// etc., SSRF guard); 15s
timeout; response capped at 100KB.

v0.1.51 新增. 按需启用:
  * 复制/软链本文件到 preset 扩展目录:
    ~/.mangocli/presets/<name>/extensions/  (需设 MANGO_PRESET=<name>)
    ~/.mangocli/extensions/  (未设置 MANGO_PRESET 时)

契约: 顶层仅 `from mangopi_cli import ToolBase`; 其余符号一律函数体内延迟导入.
"""
from mangopi_cli import ToolBase

import re

_TIMEOUT = 15
_MAX_BYTES = 100_000
_MAX_CHARS_DEFAULT = 8_000
_MAX_CHARS_LIMIT = 100_000
_ALLOWED_SCHEMES = ("http", "https")


def _strip_html(html: str) -> str:
    """粗略 HTML → 文本: 去 script/style 块, 去标签, 合并空白."""
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"[ \t\r\f\v]+", " ", html).strip()


def _fetch(url: str, max_chars: int) -> str:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "mangopi-cli-web-fetch/0.1"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        ctype = resp.headers.get("Content-Type", "")
        raw = resp.read(_MAX_BYTES + 1)
    truncated = len(raw) > _MAX_BYTES
    raw = raw[:_MAX_BYTES]
    text = raw.decode("utf-8", errors="replace")
    if "html" in ctype.lower():
        text = _strip_html(text)
    if truncated:
        text += f"\n[truncated: response exceeded {_MAX_BYTES} bytes]"
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n[truncated: {len(text) - max_chars} chars omitted]"
    return text


class WebFetchTool(ToolBase):
    name = "web_fetch"
    description = (
        "Fetch a single URL's content into the context: GET the page, strip HTML tags, "
        "and return plain text truncated to max_chars. Use when web_search snippets are "
        "not enough and you need the actual page content. Only http/https URLs are allowed."
    )
    params = {
        "url": {"type": "string", "description": "The http(s) URL to fetch, e.g. 'https://example.com/docs'."},
        "max_chars": {"type": "number?", "description": "Max characters to return (1-100000, default 8000)."},
    }
    guidance = (
        "Use **web_fetch** to read the full text of a page found via web_search. "
        "Only http/https is allowed. Use sparingly — at most 3 times per user query "
        "to avoid excessive network calls."
    )
    preview_lines = 0
    preview_width = 200
    use_spinner = True

    def preview(self, args): return (args.get("url") or "")[:self.preview_width]

    def run(self, args):
        import urllib.parse

        url = (args.get("url") or "").strip()
        if not url:
            return self.fail("web_fetch error: 'url' is required")
        scheme = urllib.parse.urlsplit(url).scheme.lower()
        if scheme not in _ALLOWED_SCHEMES:
            return self.fail(
                f"web_fetch error: scheme {scheme!r} not allowed (only http/https)")

        raw_n = args.get("max_chars")
        try:
            max_chars = int(raw_n) if raw_n not in (None, "") else _MAX_CHARS_DEFAULT
        except (TypeError, ValueError):
            return self.fail(f"web_fetch error: 'max_chars' must be an integer, got {raw_n!r}")
        if not 1 <= max_chars <= _MAX_CHARS_LIMIT:
            return self.fail(
                f"web_fetch error: 'max_chars' must be in [1, {_MAX_CHARS_LIMIT}], got {max_chars}")

        try:
            text = _fetch(url, max_chars)
        except Exception as err:  # noqa: BLE001 HTTPError/URLError/ValueError 统一成明确错误
            return self.fail(f"web_fetch error: {err}")
        return self.ok(text)


tools = [WebFetchTool()]
