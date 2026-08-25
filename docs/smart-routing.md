# Smart Provider Routing 与 FlashThinking 归档 / Archived: Smart Provider Routing & FlashThinking

> 本文档归档 mangopi-cli 的 Smart Provider Routing（`RoutedProvider`）与 FlashThinking 功能知识，
> 代码于 **v0.1.52** 从核心移除（低使用频率）。配置样例 `providers.json.example` 保留于仓库根目录。
> This document archives the Smart Provider Routing (`RoutedProvider`) and FlashThinking
> knowledge of mangopi-cli. The code was removed from the core in **v0.1.52** (low usage).
> The sample config `providers.json.example` stays in the repo root.

---

## 1. 背景与演进 / Background & Evolution

- **v0.1.29** — 引入 Smart Provider Routing：同一会话内 "read me this file" 与 "design me a distributed system"
  对模型能力的需求差异巨大，`MANGO_ROUTING=on` 按任务复杂度在 low/medium/high 三档模型间路由，
  配置位于 `.mangocli/providers.json`。`RoutedProvider` 不继承 `BaseProvider`，仅实现相同接口
  （鸭子类型），将 API 调用委托给当轮选中的子 provider。
- **v0.1.30** — 评分重构：关键词评分集中到 `FlashThinking.KEYWORDS`，移除 `RoutedProvider._KEYWORD_RULES`；
  评分公式改为 `keyword × 0.3 + llm × 0.7`，阈值可配置。
- **v0.1.31** — `FlashThinking` 引入（v0.1.29 的 Flash-ext Thinking Framework Server 的简化内核）：
  根据 query 关键词匹配五类思考框架（debug/design/explain/optimize/implement），
  早期为 SystemPrompt 注入思考框架步骤，后期仅作为 `RoutedProvider._keyword_score` 的关键词库。
- **v0.1.47** — `--flash-ext` HTTP 代理入口移除，`FlashThinking` 保留为纯关键词匹配器。
- **v0.1.52** — 整体移除（代码归档于本文档）：`RoutedProvider`、`FlashThinking` 及其全部集成点。

---

## 2. 架构说明 / Architecture

### 2.1 两阶段评分 / Two-phase scoring

`route(ctx, user_query)` 在每次 `agent_loop` 调用前执行：

```
Phase 1 — Keyword scoring (0 ms, 0 token):
  flash_thinking.match(query) → 命中的框架名列表 → _FRAMEWORK_SCORE 映射
  max(70%) 反映复杂度天花板, avg(30%) 反映多维度密度:
    score = round(max * 0.7 + avg * 0.3), 夹取 [1, 10]
  命中 _FRAMEWORK_ANGER (愤怒词) 直接短路返回 10。
  score ≤ low_max (3) → tier = low;  score > medium_max (7) → tier = high;
  否则进入 Phase 2。

Phase 2 — LLM scoring (~300–500 ms, 少量 token):
  将最近几轮的工具调用指纹 (ContextManager.tool_fingerprint, 如 [read, edit, read, grep])
  + 当前 query 发给 tier=high 模型, 返回 1–10 整数评分。
  final = round(keyword * 0.3 + llm * 0.7)
    ≤ 3 → low;  4–7 → medium;  ≥ 8 → high
```

关键设计决策：
- 每轮（一次 `agent_loop`）只选一个模型，**循环内不切换**、不升级、不降级。
- provider 失败直接报错，无自动 fallback（high 级任务不得静默降级）。
- 三档模型名示例：`deepseek-v4-flash` (low) / `deepseek-v4` (medium) / `deepseek-v4-reasoning` (high)。
- 跨 provider 消息兼容由 `BaseProvider._sanitize_messages`（实例方法）与 `_reasoning_field`
  类属性保证（DeepSeek/OpenAI/kimi/glm/qwen 用 `reasoning_content`，MiniMax 用 `reasoning_details`）。

### 2.2 配置格式 / Config format

`~/.mangocli/providers.json`（样例见仓库根 `providers.json.example`）：

```json
{
  "providers": [
    {"name": "low",    "url": "https://api.deepseek.com", "model": "deepseek-v4-flash",     "tier": "low",    "api_key": "sk-xxx"},
    {"name": "medium", "url": "https://api.deepseek.com", "model": "deepseek-v4",           "tier": "medium", "api_key": "sk-xxx"},
    {"name": "high",   "url": "https://api.deepseek.com", "model": "deepseek-v4-reasoning", "tier": "high",   "api_key": "sk-xxx"}
  ],
  "routing": {
    "default_tier": "medium",
    "score_thresholds": {"low_max": 3, "medium_max": 7}
  }
}
```

- `providers[].tier` 必须是 `low`/`medium`/`high` 之一，否则 `ValueError`。
- `routing.score_thresholds` 可选，缺省 `{"low_max": 3, "medium_max": 7}`。
- `routing.default_tier` 可选，缺省 `medium`；若该档为空自动回退 medium → low → high。

### 2.3 集成点（v0.1.51 核心中的位置）/ Integration points

| 位置 | 内容 |
|---|---|
| 模块级 | `MANGO_ROUTING = os.environ.get("MANGO_ROUTING", "off").lower()` |
| 模块级 | `providers_file = os.path.join(base_persist_dir, "providers.json")` |
| `doctor()` | `MANGO_ROUTING=on` 且 providers.json 缺失时报告错误 |
| `main()` | `MANGO_ROUTING=on` 时 `RoutedProvider.from_file(providers_file)`，失败回退 high-tier 单 provider |
| `main()` | 启动横幅 mode 显示 `smart-routing[N]`（N = total_providers） |
| agent 循环 | 每轮用户输入后、`agent_loop` 前：`provider.route(ctx, user_input)`，失败仅告警 |

---

## 3. 归档代码 / Archived Code

### 3.1 FlashThinking（v0.1.51 行 664–708）

```python
class FlashThinking:  # 思考引导增强系统——根据 query 关键词和 tool call 模式选择和注入结构化思考框架。
    KEYWORDS = {"debug": ["报错", "bug", "error", "失败", "fail", "慢", "slow", "崩溃", "crash", "排查", "debug",
                          "修复", "fix", "test", "修改", "modif", "update", "chang", "issue", "adjust",
                          "patch", "correct", "错误", "问题", "调整", "更正", "改动", "alter",
                          "调试", "debugging", "异常", "exception", "日志", "log", "logging",
                          "堆栈", "stack", "trace", "broken", "挂起", "hang", "leak",
                          "undefined", "null", "复现", "reproduc"],
                "design": ["设计", "design", "架构", "architect", "选型", "规划",
                           "distribut", "microservic", "scalab", "infrastructur",
                           "overall", "可扩展", "高可用", "容灾", "分布式", "framework", "platform",
                           "重构", "refactor", "migrat", "死锁", "deadlock", "并发", "concurren",
                           "async", "multithread", "异步", "迁移",
                           "模式", "pattern", "抽象", "abstraction", "模块化", "modular",
                           "分层", "layered", "安全", "security", "灵活", "flexib", "可靠", "reliab"],
                "explain": ["什么是", "解释", "explain", "区别", "原理", "怎么理解", "what is",
                            "read", "查看", "show", "find", "search", "搜索", "查询", "query",
                            "display", "获取", "了解", "描述", "describe",
                            "文档", "doc", "document", "注释", "comment",
                            "概述", "overview", "总结", "summar",
                            "对比", "compar", "列举", "list", "分析", "analy"],
                "optimize": ["优化", "optimize", "性能", "performance", "加速", "提升",
                             "延迟", "latency", "吞吐", "throughput", "响应", "respons",
                             "内存", "memory", "磁盘", "disk", "缓存", "cache", "索引", "index", "瓶颈", "bottleneck",
                             "profile", "profiling", "benchmark", "压缩", "compress", "减少", "reduc",
                             "预加载", "preload", "懒加载", "lazy", "连接池", "调用量", "负载", "load"],
                "implement": ["实现", "implement", "写", "create", "build", "开发", "生成",
                              "integrat", "multi", "feature", "api", "interfac", "modul",
                              "component", "databas", "config", "集成", "接口", "模块", "组件", "数据库", "存储", "stor",
                              "编写", "write", "添加", "add", "函数", "function", "class", "初始化", "init",
                              "部署", "deploy", "继承", "extend", "导入", "import", "配置", "configure",
                              "模板", "template", "注册", "register"]}

    def __init__(self):
        self.frameworks = {}

    def match(self, query):  # 返回所有命中的 framework 名称（去重），用于综合评分
        q = query.lower()
        matched = []
        for fw, keywords in self.KEYWORDS.items():
            if any(kw in q for kw in keywords):
                matched.append(fw)
        return matched


flash_thinking = FlashThinking()
```

### 3.2 RoutedProvider（v0.1.51 行 1423–1552，含段注释）

```python
# --- Smart Provider Routing ---

class RoutedProvider:  # A provider that scores task complexity and delegates to low/medium/high sub-providers.
    @classmethod
    def from_file(cls, path: str) -> "RoutedProvider":
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    def __init__(self, config: dict):
        self._tiers: Dict[str, List[BaseProvider]] = {"low": [], "medium": [], "high": []}
        for p in config.get("providers", []):
            tier = p.get("tier", "")
            if tier not in self._tiers:
                raise ValueError(f"Invalid provider tier '{tier}'. Must be low/medium/high.")
            self._tiers[tier].append(_new_provider(p["model"], p["url"], p["api_key"]))
        if not any(self._tiers.values()):
            raise ValueError("No providers defined in config")

        routing = config.get("routing", {})
        _defaults_score_thresholds = {"low_max": 3, "medium_max": 7}
        self._thresholds = {**_defaults_score_thresholds, **routing.get("score_thresholds", {})}
        default_tier = routing.get("default_tier", "medium")
        self._default_tier_value = default_tier if self._tiers.get(default_tier) else \
            next((t for t in ("medium", "low", "high") if self._tiers.get(t)), "medium")
        default = self._tiers.get(default_tier) or next((v for v in self._tiers.values() if v), [])
        self._current = default[0]

    # ── delegation to _current ──
    @property
    def api_url(self): return self._current.api_url

    @property
    def api_key(self): return self._current.api_key

    @property
    def model(self): return self._current.model

    @property
    def total_providers(self) -> int: return sum(len(v) for v in self._tiers.values())

    def headers(self) -> dict: return self._current.headers()

    def build_body(self, messages: List[Dict[str, Any]]) -> dict: return self._current.build_body(messages)

    def parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]: return self._current.parse_response(response)

    _FRAMEWORK_ANGER: List[str] = [
        "fuck", "fuxx", "f**k", "shit", "damn", "asshole", "bastard", "傻子", "笨蛋", "蠢货", "白痴", "脑残", "sb", "废物",
        "垃圾", "特么", "卧槽", "我操", "cnm", "tmd", "废物", "傻x"]

    _FRAMEWORK_SCORE: Dict[str, int] = {"design": 9, "implement": 5, "optimize": 5, "debug": 3, "explain": 1}

    _SCORING_PROMPT = """\
Rate this coding task complexity from 1-10 (1=trivial, 10=architectural/system design).
Consider: scope of changes, reasoning depth, debugging difficulty, components involved.

Tool call history (each segment = one user turn):
{tool_patterns}

Current request:
{user_query}

Rubric: 1-3=read/search, 4-6=multi-file/edit/debug, 7-10=design/refactor/complex

Respond with ONLY a single integer."""

    @staticmethod
    def _keyword_score(query: str) -> int:
        q = query.lower()
        for kw in RoutedProvider._FRAMEWORK_ANGER:
            if kw in q:
                return 10
        matched = flash_thinking.match(query)
        if not matched:
            return 4
        scores = [RoutedProvider._FRAMEWORK_SCORE.get(fw, 0) for fw in matched]
        max_s = max(scores)  # 综合加权: max(70%) 反映复杂度天花板, avg(30%) 反映多维度密度
        avg_s = sum(scores) / len(scores)
        return max(1, min(10, round(max_s * 0.7 + avg_s * 0.3)))

    @staticmethod
    def _llm_score(user_query: str, fingerprint: str, high_provider) -> int:
        prompt = RoutedProvider._SCORING_PROMPT.format(
            tool_patterns=fingerprint, user_query=user_query)
        body = high_provider.build_body([{"role": "user", "content": prompt}])
        try:
            console.start_spinner("Smart Routing...")
            resp = _request(high_provider.api_url, body,
                            headers=high_provider.headers(), timeout=15)
            parsed = high_provider.parse_response(resp)
            content = parsed.get("content", "").strip()
            match = re.search(r'\d+', content)
            console.end_spinner()
            if match:
                val = int(match.group())
                return max(1, min(10, val))
        except Exception:
            console.end_spinner()
        return 5

    def route(self, ctx, user_query: str):  # Score task complexity and switch to the appropriate tier provider.
        kw = self._keyword_score(user_query)
        if kw <= self._thresholds["low_max"]:
            tier = "low"
        elif kw > self._thresholds["medium_max"]:
            tier = "high"
        else:
            high = self._tiers.get("high", [])
            if high:
                fp = ctx.tool_fingerprint()
                llm = self._llm_score(user_query, fp, high[0])
                final = round(kw * 0.3 + llm * 0.7)
                if final <= self._thresholds["low_max"]:
                    tier = "low"
                elif final <= self._thresholds["medium_max"]:
                    tier = "medium"
                else:
                    tier = "high"
            else:
                tier = self._default_tier
        providers = self._tiers.get(tier)
        if not providers:
            providers = self._tiers[self._default_tier]
        self._current = providers[0]
        print(f"{DIM}→ {tier}: {self._current.model}{RESET}")

    @property
    def _default_tier(self) -> str: return self._default_tier_value
```

### 3.3 散点集成代码 / Scattered integration code

```python
# 模块级 (v0.1.51 行 40 / 53)
MANGO_ROUTING = os.environ.get("MANGO_ROUTING", "off").lower()
providers_file = os.path.join(base_persist_dir, "providers.json")

# doctor() 内 (行 312–313)
if MANGO_ROUTING == "on" and not os.path.isfile(providers_file):
    results.append((False, "providers.json not found (required when MANGO_ROUTING=on)"))

# main() 内 (行 1824–1833)
if MANGO_ROUTING == "on":
    try:
        provider = RoutedProvider.from_file(providers_file)
    except Exception:
        console.warning(f"Failed to load {providers_file}, forcing high-tier fallback")
        provider = RoutedProvider({
            "providers": [{"name": MANGO_MODEL, "url": MANGO_API_URL, "model": MANGO_MODEL,
                           "tier": "high", "api_key": MANGO_KEY or ""}]})

mode = f"smart-routing[{provider.total_providers}]" if MANGO_ROUTING == "on" else provider.model

# agent 循环内 (行 1908–1912), agent_loop 调用前
if MANGO_ROUTING == "on":
    try:
        provider.route(ctx, user_input)
    except Exception as e:
        console.warning(f"Routing failed ({e})")
```

---

## 4. 测试归档 / Archived Tests

原 `test/test_provider_routing.py`（357 行，41 用例）于 v0.1.52 随功能删除，完整代码归档如下。
**注意**：`ExtractToolFingerprintTests`（`ContextManager.tool_fingerprint`）与 `NewProviderTests`
（`_new_provider`）测试的是**仍保留**的核心功能——若未来恢复路由，这两个测试类可直接复用，
其余 5 个测试类依赖已移除的 `RoutedProvider`/`FlashThinking`。

### 4.1 用例清单 / Case index

| 测试类 / Class | 用例数 | 覆盖点 / Coverage |
|---|---|---|
| `KeywordScoreTests` | 7 | 高/中高/中低/低/琐碎五档关键词评分（design=9, refactor=8, implement=5, debug=3, explain=1）、大小写不敏感、无命中默认 4 分 |
| `MultiFrameworkAggregationTests` | 7 | 单框架（explain→1 / design→9）、双框架（explain+debug→3、design+implement→8）、三框架（optimize+implement+design→8）、四框架（→8）、英文 query |
| `RoutedProviderInitTests` | 6 | providers.json 解析、三档装载、默认档 medium、自定义 `score_thresholds`、文件不存在 `FileNotFoundError`、非法 tier / 空 providers `ValueError`、单档配置回退 |
| `ExtractToolFingerprintTests` | 5 | `ContextManager.tool_fingerprint`：单轮/多轮模式、`n_turns` 截断、空上下文返回 `[]`、无工具轮跳过 |
| `LLMScoreTests` | 4 | `_llm_score`（mock `mangopi_cli._request`）：返回整数、1–10 夹取、从文本提取数字、异常回退 5 分 |
| `RouteMethodTests` | 7 | `route()` 分档：关键词低→low、关键词高→high、LLM 低/中/高→对应档（kw×0.3+llm×0.7）、无 high tier 跳过 LLM 评分、route 后委托属性（model/api_url/headers） |
| `NewProviderTests` | 5 | `_new_provider` 工厂：deepseek/minimax/openai 类选择、URL 规范化（追加 `/chat/completions`、尾斜杠、幂等） |

### 4.2 完整代码 / Full source

```python
"""Unit tests for Smart Provider Routing (refactored — RoutedProvider + _new_provider).

Tests cover:
    1. _keyword_score           – keyword matching → score
    2. RoutedProvider.__init__   – providers.json parsing & validation
    3. _extract_tool_fingerprint – tool-call pattern extraction
    4. RoutedProvider.route()    – two-phase scoring → tier selection
    5. _llm_score               – LLM scoring edge cases
    6. _new_provider            – factory: url normalisation & provider-class selection

No real network calls — LLM scoring is mocked.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mangopi_cli  # noqa: E402
from mangopi_cli import ContextManager, RoutedProvider  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_fake_ctx(tool_sequences):
    """Return a real ContextManager with tool messages matching the given sequences.

    Each inner list is one user turn; a user message is inserted before each turn.
    """
    from mangopi_cli import ContextManager
    ctx = ContextManager()
    ctx.clear()
    for seq in tool_sequences:
        ctx.messages.append({"role": "user", "content": "query"})
        for name in seq:
            ctx.messages.append({"role": "tool", "tool_name": name, "content": "ok"})
    return ctx


def _write_providers_json(providers, routing=None):
    """Write a temporary providers.json and return its path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    config = {"providers": providers}
    if routing:
        config["routing"] = routing
    json.dump(config, tmp)
    tmp.close()
    return tmp.name


def _make_routed_provider(providers, routing=None):
    """Build a RoutedProvider from a temp file."""
    p_file = _write_providers_json(providers, routing)
    return RoutedProvider.from_file(p_file), p_file


# ── Tests ────────────────────────────────────────────────────────────────────

class KeywordScoreTests(unittest.TestCase):
    """_keyword_score returns correct tier-indicative scores."""

    def test_high_complexity_keywords(self):
        self.assertEqual(RoutedProvider._keyword_score("design me a distributed system"), 9)
        self.assertEqual(RoutedProvider._keyword_score("架构重构"), 9)
        self.assertEqual(RoutedProvider._keyword_score("系统设计 for microservice"), 9)

    def test_medium_high_keywords(self):
        self.assertEqual(RoutedProvider._keyword_score("refactor the auth module"), 8)
        self.assertEqual(RoutedProvider._keyword_score("migrate to new API"), 8)

    def test_medium_low_keywords(self):
        self.assertEqual(RoutedProvider._keyword_score("implement a new feature"), 5)
        self.assertEqual(RoutedProvider._keyword_score("integrate with external API"), 5)
        self.assertEqual(RoutedProvider._keyword_score("update config"), 5)

    def test_low_keywords(self):
        self.assertEqual(RoutedProvider._keyword_score("fix the login bug"), 3)
        self.assertEqual(RoutedProvider._keyword_score("修复编译错误"), 3)

    def test_trivial_keywords(self):
        self.assertEqual(RoutedProvider._keyword_score("read main.py"), 1)
        self.assertEqual(RoutedProvider._keyword_score("explain decorator"), 1)
        self.assertEqual(RoutedProvider._keyword_score("show the content"), 1)

    def test_case_insensitive(self):
        self.assertEqual(RoutedProvider._keyword_score("DESIGN a System"), 9)

    def test_no_match_returns_default(self):
        self.assertEqual(RoutedProvider._keyword_score("blah blah blah"), 4)


class MultiFrameworkAggregationTests(unittest.TestCase):
    """多框架命中时聚合加权评分（以中文 query 为主）."""

    def test_single_framework_explain(self):
        """单框架：仅命中 explain → 1 分"""
        self.assertEqual(RoutedProvider._keyword_score("列举目录结构"), 1)

    def test_single_framework_design(self):
        """单框架：仅命中 design → 9 分"""
        self.assertEqual(RoutedProvider._keyword_score("重构整个系统的架构设计"), 9)

    def test_dual_framework_debug_explain(self):
        """双框架：explain + debug → 加权 3 分"""
        score = RoutedProvider._keyword_score("解释一下这个 bug 并修复它")
        self.assertEqual(score, 3)

    def test_triple_framework(self):
        """三框架：optimize + implement + design → 加权 8 分"""
        score = RoutedProvider._keyword_score("优化接口性能并重构数据库")
        self.assertEqual(score, 8)

    def test_quad_framework(self):
        """四框架：debug + design + optimize + implement → 加权 8 分"""
        score = RoutedProvider._keyword_score("修复 bug，重构设计，优化性能，实现新功能")
        self.assertEqual(score, 8)

    def test_design_implement_blend(self):
        """双框架：design + implement → 加权 8 分"""
        self.assertEqual(RoutedProvider._keyword_score("设计并实现一个新模块"), 8)

    def test_english_still_works(self):
        """英文 query 保持正常"""
        self.assertEqual(RoutedProvider._keyword_score("just a read query"), 1)
        self.assertEqual(RoutedProvider._keyword_score("design and implement a new module"), 8)


class RoutedProviderInitTests(unittest.TestCase):
    """RoutedProvider.__init__ parses and validates config."""

    def test_valid_config(self):
        rp, p_file = _make_routed_provider(
            [
                {"name": "lo", "url": "https://lo.com", "model": "lo", "tier": "low",    "api_key": "k-lo"},
                {"name": "md", "url": "https://md.com", "model": "md", "tier": "medium", "api_key": "k-md"},
                {"name": "hi", "url": "https://hi.com", "model": "hi", "tier": "high",   "api_key": "k-hi"},
            ],
        )
        self.assertEqual(len(rp._tiers["low"]), 1)
        self.assertEqual(len(rp._tiers["medium"]), 1)
        self.assertEqual(len(rp._tiers["high"]), 1)
        self.assertEqual(rp.model, "md")  # default tier = medium
        self.assertEqual(rp._thresholds, {"low_max": 3, "medium_max": 7})
        os.unlink(p_file)

    def test_custom_thresholds(self):
        rp, p_file = _make_routed_provider(
            [{"name": "hi", "url": "https://hi.com", "model": "hi", "tier": "high", "api_key": "k"}],
            routing={"score_thresholds": {"low_max": 2, "medium_max": 5}, "default_tier": "high"},
        )
        self.assertEqual(rp._thresholds, {"low_max": 2, "medium_max": 5})
        os.unlink(p_file)

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            RoutedProvider.from_file("/nonexistent/path.json")

    def test_invalid_tier(self):
        p_file = _write_providers_json([
            {"name": "x", "url": "https://x.com", "model": "x", "tier": "super_fast", "api_key": "k"},
        ])
        with self.assertRaises(ValueError):
            RoutedProvider.from_file(p_file)
        os.unlink(p_file)

    def test_empty_providers(self):
        p_file = _write_providers_json([])
        with self.assertRaises(ValueError):
            RoutedProvider.from_file(p_file)
        os.unlink(p_file)

    def test_delegates_to_default_tier(self):
        rp, p_file = _make_routed_provider(
            [{"name": "hi", "url": "https://hi.com", "model": "hi", "tier": "high", "api_key": "k"}],
        )
        # Only high tier is configured, default should fall back to high
        self.assertEqual(rp.model, "hi")
        os.unlink(p_file)


class ExtractToolFingerprintTests(unittest.TestCase):
    """ContextManager.tool_fingerprint() builds compact tool-call patterns."""

    def test_single_turn(self):
        ctx = _make_fake_ctx([["read", "grep", "read"]])
        fp = ctx.tool_fingerprint()
        self.assertIn("read", fp)
        self.assertIn("grep", fp)
        self.assertIn("query", fp)  # user message content

    def test_multiple_turns(self):
        ctx = _make_fake_ctx([["read", "edit"], ["bash", "read"], ["edit", "edit"]])
        fp = ctx.tool_fingerprint()
        self.assertIn("['read', 'edit']", fp)
        self.assertEqual(fp.count("query"), 3)  # three user messages

    def test_truncates_to_n_turns(self):
        ctx = _make_fake_ctx([["a"], ["b"], ["c"], ["d"], ["e"]])
        fp = ctx.tool_fingerprint(n_turns=2)
        self.assertNotIn("'a'", fp)
        self.assertIn("'d'", fp)
        self.assertIn("'e'", fp)

    def test_empty_context(self):
        ctx = _make_fake_ctx([])
        self.assertEqual(ctx.tool_fingerprint(), "[]")

    def test_skips_turns_without_tools(self):
        ctx = ContextManager()
        ctx.clear()
        ctx.messages.append({"role": "user", "content": "hello"})
        self.assertEqual(ctx.tool_fingerprint(), "[]")


class LLMScoreTests(unittest.TestCase):
    """_llm_score calls high-tier model and extracts integer score."""

    def test_returns_integer(self):
        hp = MagicMock()
        hp.api_url = "https://test/api"
        hp.headers.return_value = {}
        hp.build_body.return_value = {}
        hp.parse_response.return_value = {"content": "7", "tool_calls": [], "has_tool_calls": False}
        with patch("mangopi_cli._request", return_value={}):
            self.assertEqual(RoutedProvider._llm_score("q", "[]", hp), 7)

    def test_clamps_to_1_10(self):
        hp = MagicMock()
        hp.api_url = "https://test/api"
        hp.headers.return_value = {}
        hp.build_body.return_value = {}
        hp.parse_response.return_value = {"content": "15", "tool_calls": [], "has_tool_calls": False}
        with patch("mangopi_cli._request", return_value={}):
            self.assertEqual(RoutedProvider._llm_score("q", "[]", hp), 10)
        hp.parse_response.return_value = {"content": "0", "tool_calls": [], "has_tool_calls": False}
        with patch("mangopi_cli._request", return_value={}):
            self.assertEqual(RoutedProvider._llm_score("q", "[]", hp), 1)

    def test_extracts_from_text(self):
        hp = MagicMock()
        hp.api_url = "https://test/api"
        hp.headers.return_value = {}
        hp.build_body.return_value = {}
        hp.parse_response.return_value = {"content": "complexity is 8 out of 10", "tool_calls": [], "has_tool_calls": False}
        with patch("mangopi_cli._request", return_value={}):
            self.assertEqual(RoutedProvider._llm_score("q", "[]", hp), 8)

    def test_fallback_on_error(self):
        hp = MagicMock()
        hp.api_url = "https://test/api"
        hp.headers.return_value = {}
        hp.build_body.return_value = {}
        hp.parse_response.side_effect = Exception("boom")
        with patch("mangopi_cli._request", side_effect=Exception("network down")):
            self.assertEqual(RoutedProvider._llm_score("q", "[]", hp), 5)


class RouteMethodTests(unittest.TestCase):
    """RoutedProvider.route() selects tier and switches _current."""

    def _make_rp(self, providers=None):
        if providers is None:
            providers = [
                {"name": "lo", "url": "https://lo.com", "model": "lo-model", "tier": "low",    "api_key": "k-lo"},
                {"name": "md", "url": "https://md.com", "model": "md-model", "tier": "medium", "api_key": "k-md"},
                {"name": "hi", "url": "https://hi.com", "model": "hi-model", "tier": "high",   "api_key": "k-hi"},
            ]
        p_file = _write_providers_json(providers)
        rp = RoutedProvider.from_file(p_file)
        self._cleanup_files = getattr(self, '_cleanup_files', [])
        self._cleanup_files.append(p_file)
        return rp

    def tearDown(self):
        for f in getattr(self, '_cleanup_files', []):
            try:
                os.unlink(f)
            except OSError:
                pass
        self._cleanup_files = []

    def test_keyword_low_routes_to_low(self):
        rp = self._make_rp()
        rp.route(_make_fake_ctx([]), "read the file")
        self.assertEqual(rp.model, "lo-model")

    def test_keyword_high_routes_to_high(self):
        rp = self._make_rp()
        rp.route(_make_fake_ctx([]), "design a distributed system")
        self.assertEqual(rp.model, "hi-model")

    def test_ambiguous_with_llm_low(self):
        rp = self._make_rp()
        with patch.object(RoutedProvider, "_llm_score", return_value=2):
            rp.route(_make_fake_ctx([]), "some ambiguous task")
        self.assertEqual(rp.model, "lo-model")

    def test_ambiguous_with_llm_medium(self):
        rp = self._make_rp()
        with patch.object(RoutedProvider, "_llm_score", return_value=5):
            rp.route(_make_fake_ctx([]), "some ambiguous task")
        self.assertEqual(rp.model, "md-model")

    def test_ambiguous_with_llm_high(self):
        rp = self._make_rp()
        # kw=4 * 0.3 + llm=10 * 0.7 = int(8.2) = 8 > 7 → high
        with patch.object(RoutedProvider, "_llm_score", return_value=10):
            rp.route(_make_fake_ctx([]), "some ambiguous task")
        self.assertEqual(rp.model, "hi-model")

    def test_no_high_provider_falls_back(self):
        rp = self._make_rp(providers=[
            {"name": "lo", "url": "https://lo.com", "model": "lo", "tier": "low", "api_key": "k-lo"},
        ])
        rp.route(_make_fake_ctx([]), "some ambiguous task")
        # No high-tier → skips LLM scoring, defaults to low (only tier available)
        self.assertEqual(rp.model, "lo")

    def test_properties_delegate_after_route(self):
        rp = self._make_rp()
        rp.route(_make_fake_ctx([]), "design a distributed system")
        self.assertEqual(rp.model, "hi-model")
        self.assertIn("hi.com", rp.api_url)
        self.assertIsNotNone(rp.headers())


class NewProviderTests(unittest.TestCase):
    """_new_provider returns correct Provider subclass and normalizes URL."""

    def test_deepseek_model(self):
        p = mangopi_cli._new_provider("deepseek-v4-flash", "https://api.deepseek.com", "k")
        self.assertIsInstance(p, mangopi_cli.DeepSeekProvider)
        self.assertEqual(p.model, "deepseek-v4-flash")
        self.assertEqual(p.api_url, "https://api.deepseek.com/chat/completions")

    def test_minimax_model(self):
        p = mangopi_cli._new_provider("minimax-m1", "https://api.minimax.com/v1", "k")
        self.assertIsInstance(p, mangopi_cli.MiniMaxProvider)

    def test_openai_model(self):
        p = mangopi_cli._new_provider("gpt-4o", "https://api.openai.com/v1", "k")
        self.assertIsInstance(p, mangopi_cli.OpenAIProvider)

    def test_url_already_has_chat_completions(self):
        p = mangopi_cli._new_provider("gpt-4o", "https://api.openai.com/v1/chat/completions", "k")
        self.assertEqual(p.api_url, "https://api.openai.com/v1/chat/completions")

    def test_url_with_trailing_slash(self):
        p = mangopi_cli._new_provider("gpt-4o", "https://api.openai.com/v1/", "k")
        self.assertEqual(p.api_url, "https://api.openai.com/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
```
## 5. 移除说明 / Removal notes

- **v0.1.52** — 核心移除：`RoutedProvider` 类、`FlashThinking` 类与单例、`MANGO_ROUTING`、
  `providers_file`、`doctor()` 检查、`main()` 装配与 fallback、启动横幅 `smart-routing[N]`、
  每轮 `provider.route()` 调用。`_new_provider`/`create_provider()` 保留（默认单模型路径）。
- **保留** — `providers.json.example`（仓库根，配置格式参考）；`BaseProvider._sanitize_messages` /
  `_reasoning_field`（多 provider 兼容基础设施，`create_provider` 仍使用）。
- 单模型模式（`MANGO_MODEL` / `MANGO_API_URL` / `MANGO_KEY` 直连）全程不受影响。
