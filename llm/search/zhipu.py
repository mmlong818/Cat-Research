"""智谱 Web Search API（search_pro）。国内接口，不走系统代理。"""
import asyncio

from llm.retry import Sleep
from llm.search.base import RECENCY, SEARCH_COUNT_MAX, SEARCH_QUERY_MAX, PostFn, SearchError, http_post, post_json, trim

ZHIPU_SEARCH_URL = "https://open.bigmodel.cn/api/paas/v4/web_search"
SEARCH_ENGINE = "search_pro"
PRICE_USD = 0.01  # 美元/次


def _describe(status: int, body: dict) -> str:
    err = body.get("error")
    err = err if isinstance(err, dict) else {}
    return f"HTTP {status} code={err.get('code', '')} {err.get('message', '')}".strip()


async def zhipu_search(key: str, query: str, count: int = 8, recency: str = "noLimit", *,
                       post: PostFn | None = None, sleep: Sleep = asyncio.sleep) -> dict:
    payload = {"search_query": query[:SEARCH_QUERY_MAX], "search_engine": SEARCH_ENGINE,
               "count": min(max(count, 1), SEARCH_COUNT_MAX),
               "search_recency_filter": recency if recency in RECENCY else "noLimit"}
    headers = {"Authorization": f"Bearer {key}"}
    try:
        status, body = await post_json(ZHIPU_SEARCH_URL, headers, payload, post=post or http_post, sleep=sleep,
                                       label="智谱搜索")
    except SearchError as e:
        return {"error": str(e)}
    if status != 200:
        return {"error": f"搜索失败：{_describe(status, body)}"}
    return {"results": [trim(i) for i in body.get("search_result") or []]}
