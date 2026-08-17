"""Shipped extension — web_search: Bocha (博查) AI Search API 实时搜索.
Shipped extension — web_search: live web search via the Bocha AI Search API.

v0.1.49 从核心移出 (插件化). 按需启用:
  * 复制/软链本文件到 preset 扩展目录: ~/.mangocli/presets/<name>/extensions/ (需设 MANGO_PRESET=<name>)

需要 MANGO_SEARCH_API_KEY 环境变量; 未设置时返回明确错误.
Requires the MANGO_SEARCH_API_KEY env var; returns a clear error otherwise.

契约: 顶层仅 `from mangopi_cli import ToolBase`; 核心符号 (_request) 晚于扩展扫描点,
在函数体内延迟导入 (导入期半初始化契约).
"""
from mangopi_cli import ToolBase

import os


def _bocha_search_api(query=None, freshness="noLimit", summary=True,
                      include="", exclude="", count=10,
                      bocha_key=None, bocha_url="https://api.bocha.cn/v1/web-search"):
    import mangopi_cli as m  # 延迟导入: _request 定义晚于扩展扫描点
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "Authorization": f"Bearer {bocha_key}"}
    payload = {"query": query, "freshness": freshness, "summary": summary,
               "include": include, "exclude": exclude, "count": count}
    data = m._request(bocha_url, payload, headers).get("data", {})
    pages = data.get("webPages", {}) if isinstance(data, dict) else {}
    return [{"date": x.get("dateLastCrawled", ""), "title": x.get("name", ""),
             "link": x.get("url", ""), "summary": x.get("summary", ""),
             "content": x.get("content", "")}
            for x in pages.get("value", [])] if isinstance(pages, dict) else []


class WebSearchTool(ToolBase):
    name = "web_search"
    description = (
        "Search the live web via the Bocha (博查) AI Search API and return a list of results with "
        "per-page AI summaries. Use this when the user asks for the latest docs, news, blog posts, "
        "or any information that requires looking up something beyond the local filesystem. "
        "Requires the MANGO_SEARCH_API_KEY env var to be set; returns a clear error otherwise.")
    params = {
        "query": {"type": "string", "description": "Natural-language search query, e.g. 'FastAPI vs Flask in 2026'."},
        "top_k": {"type": "number?", "description": "How many results to return (1-50, default 10)."},
        "freshness": {"type": "string?",
                      "description": "Time filter for results: 'noLimit' (default), "
                                     "'oneDay', 'oneWeek', 'oneMonth', 'oneYear'."}}
    guidance = (
        "Use **web_search** for the latest docs, news, or anything that requires the live web "
        "beyond the local filesystem. Requires the `MANGO_SEARCH_API_KEY` env var. "
        "Use sparingly — at most 3 times per user query to avoid excessive API calls.")
    preview_lines = 0
    preview_width = 200
    use_spinner = True
    _VALID_FRESHNESS = ("noLimit", "oneDay", "oneWeek", "oneMonth", "oneYear")

    def preview(self, args): return (args.get("query") or "")[:self.preview_width]

    def run(self, args):
        query = (args.get("query") or "").strip()
        if not query:
            return self.fail("web_search error: 'query' is required")
        api_key = os.environ.get("MANGO_SEARCH_API_KEY")
        if not api_key:
            return self.fail("web_search error: MANGO_SEARCH_API_KEY env var is not set")
        raw_k = args.get("top_k")
        try:
            top_k = int(raw_k) if raw_k not in (None, "") else 10
        except (TypeError, ValueError):
            return self.fail(f"web_search error: 'top_k' must be an integer in [1, 50], got {raw_k!r}")
        if not 1 <= top_k <= 50:
            return self.fail(f"web_search error: 'top_k' must be in [1, 50], got {top_k}")
        freshness = (args.get("freshness") or "noLimit").strip()
        if freshness not in self._VALID_FRESHNESS:
            return self.fail(f"web_search error: 'freshness' must be one of "
                             f"{'/'.join(self._VALID_FRESHNESS)}, got {freshness!r}")

        try:
            results = _bocha_search_api(query=query, count=top_k, freshness=freshness, bocha_key=api_key)
        except Exception as err:
            return self.fail(f"web_search error: Bocha API call failed: {err}")
        if not results:
            return self.ok(f"(no results for query: {query})")

        lines = [f"## Answer (Bocha · {len(results)} result(s) for: {query})", ""]
        sources = []
        for i, r in enumerate(results, 1):
            title = (r.get("title") or "(untitled)").strip()
            link = (r.get("link") or "").strip()
            date = (r.get("date") or "").strip()
            summary = (r.get("summary") or "").strip()
            content = (r.get("content") or "").strip()

            header = f"### {i}. [{title}]({link})" if link else f"### {i}. {title}"
            lines.append(header)
            if date:
                lines.append(f"*Date: {date}*")
            lines.append("")
            if summary:
                lines.append(f"> {summary}")
                lines.append("")
            if content and content != summary:
                snippet = content if len(content) <= 500 else content[:500] + "..."
                lines.append(snippet)
                lines.append("")

            sources.append(f"{i}. [{title}]({link})" if link else f"{i}. {title}")

        lines.append("## Sources")
        lines.extend(sources)
        return self.ok("\n".join(lines).rstrip())


tools = [WebSearchTool()]
