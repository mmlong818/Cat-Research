"""Tavily Search API。海外接口，允许系统代理。

401 Key 无效、432/433 额度用尽、400/422 参数错都不重试；429/5xx 退避重试。
"""
import asyncio
import functools
from urllib.parse import urlparse

from llm.retry import Sleep
from llm.search.base import PostFn, SearchError, http_post, post_json, trim

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_COUNT_MAX = 20
PRICE_USD = 0.008  # 美元/次
_TIME_RANGE = {"oneDay": "day", "oneWeek": "week", "oneMonth": "month", "oneYear": "year"}  # noLimit 不传


def _describe(status: int, body: dict) -> str:
    detail = body.get("detail")
    detail = detail.get("error") if isinstance(detail, dict) else detail
    err = body.get("error")
    msg = detail or (err.get("message") if isinstance(err, dict) else err) or ""
    return f"HTTP {status} {msg if isinstance(msg, str) else ''}".strip()


def _item(raw: dict) -> dict:
    link = raw.get("url") or ""
    host = (urlparse(link).hostname or "").removeprefix("www.")
    return trim({"title": raw.get("title"), "link": link, "media": host,
                 "publish_date": raw.get("published_date"), "content": raw.get("content")})


async def tavily_search(key: str, query: str, count: int = 8, recency: str = "noLimit", *,
                        post: PostFn | None = None, sleep: Sleep = asyncio.sleep) -> dict:
    payload = {"query": query, "max_results": min(max(count, 1), TAVILY_COUNT_MAX), "search_depth": "basic",
               "include_published_date": True}
    if recency in _TIME_RANGE:
        payload["time_range"] = _TIME_RANGE[recency]
    headers = {"Authorization": f"Bearer {key}"}
    poster = post or functools.partial(http_post, trust_env=True)
    try:
        status, body = await post_json(TAVILY_SEARCH_URL, headers, payload, post=poster, sleep=sleep,
                                       label="Tavily 搜索")
    except SearchError as e:
        return {"error": str(e)}
    if status != 200:
        return {"error": f"搜索失败：{_describe(status, body)}"}
    return {"results": [_item(i) for i in body.get("results") or [] if isinstance(i, dict)]}
