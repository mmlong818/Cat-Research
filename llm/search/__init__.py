"""联网搜索后端注册表：zhipu / bocha / tavily。与模型提供方分开配置，凡 web="client_tools" 的提供方
（智谱、OpenAI 兼容端点）都用所选后端的 WebSearch；网页抓取（fetch_page）与后端无关。

所选后端：user_config.json 的 search.backend，环境变量 SEARCH_BACKEND 兜底，默认 zhipu。
各后端的 key 复用 llm.keys（zhipu / bocha / tavily）。按次计价（美元），由 Usage.add_local_tools 记账。
"""
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from llm import keys
from llm.retry import Sleep
from llm.search.base import SearchFn
from llm.search.bocha import PRICE_USD as BOCHA_PRICE
from llm.search.bocha import bocha_search
from llm.search.tavily import PRICE_USD as TAVILY_PRICE
from llm.search.tavily import tavily_search
from llm.search.zhipu import PRICE_USD as ZHIPU_PRICE
from llm.search.zhipu import zhipu_search
from llm.types import LLMConfigError

__all__ = ["BACKENDS", "Backend", "SearchFn", "get_search", "selected_backend"]


@dataclass(frozen=True)
class Backend:
    name: str                 # 同时是 llm.keys 里的密钥名
    label: str
    price: float              # 美元/次
    search: Callable[..., Awaitable[dict]]  # (key, query, count, recency, *, post, sleep)


BACKENDS: dict[str, Backend] = {b.name: b for b in (
    Backend("zhipu", "智谱搜索", ZHIPU_PRICE, zhipu_search),
    Backend("bocha", "博查搜索", BOCHA_PRICE, bocha_search),
    Backend("tavily", "Tavily 搜索", TAVILY_PRICE, tavily_search),
)}

selected_backend = keys.selected_search_backend


def get_search(backend: str | None = None, *, sleep: Sleep = asyncio.sleep) -> tuple[SearchFn, float, str]:
    """(绑定了 key 的搜索函数, 单价, 显示名)。backend 省略时取当前所选；key 缺失抛 LLMConfigError。"""
    name = backend or selected_backend()
    spec = BACKENDS.get(name)
    if spec is None:
        raise LLMConfigError(f"未知联网搜索后端 {name!r}（可选：{', '.join(BACKENDS)}）")
    key = keys.require_key(name)

    async def search(query: str, count: int, recency: str) -> dict:
        out = await spec.search(key, query, count, recency, sleep=sleep)
        return {"error": keys.redact(out["error"], key)} if "error" in out else out

    return search, spec.price, spec.label
