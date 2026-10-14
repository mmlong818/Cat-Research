"""博查 Web Search API。国内接口，不走系统代理。

注意：博查官方文档读不到，请求与响应字段来自第三方资料（待官方核实），因此解析对缺字段宽容。
成功判定：HTTP 200 且外层 code（若有）为 200。401 Key 无效、403 余额不足、400 参数错不重试；429/5xx 退避重试。
"""
import asyncio
import os

from llm import keys
from llm.retry import Sleep
from llm.search.base import RECENCY, PostFn, SearchError, http_post, post_json, trim

BOCHA_SEARCH_URL = "https://api.bochaai.com/v1/web-search"
BOCHA_COUNT_MAX = 50


def search_url() -> str:
    base = (keys.stored_config().get("search") or {}).get("bocha_base_url") or os.environ.get("BOCHA_BASE_URL", "")
    return base.strip() or BOCHA_SEARCH_URL


def _code(status: int, body: dict) -> int:
    """有效状态码：HTTP 非 200 时取 HTTP 状态，否则取外层 code（缺省视为 200）。"""
    if status != 200:
        return status
    outer = body.get("code")
    try:
        return int(outer) if outer is not None else 200
    except (TypeError, ValueError):
        return 200


def _busy(status: int, body: dict) -> bool:
    code = _code(status, body)
    return code == 429 or code >= 500


def _describe(status: int, body: dict) -> str:
    msg = body.get("msg") or body.get("message") or ""
    return f"HTTP {status} code={_code(status, body)} {msg if isinstance(msg, str) else ''}".strip()


def _item(raw: dict) -> dict:
    return trim({"title": raw.get("name"), "link": raw.get("url"), "media": raw.get("siteName"),
                 "publish_date": raw.get("datePublished"), "content": raw.get("summary") or raw.get("snippet")})


async def bocha_search(key: str, query: str, count: int = 8, recency: str = "noLimit", *,
                       post: PostFn | None = None, sleep: Sleep = asyncio.sleep) -> dict:
    payload = {"query": query, "count": min(max(count, 1), BOCHA_COUNT_MAX),
               "freshness": recency if recency in RECENCY else "noLimit", "summary": True}
    headers = {"Authorization": f"Bearer {key}"}
    try:
        status, body = await post_json(search_url(), headers, payload, post=post or http_post, sleep=sleep,
                                       label="博查搜索", busy=_busy)
    except SearchError as e:
        return {"error": str(e)}
    if _code(status, body) != 200:
        return {"error": f"搜索失败：{_describe(status, body)}"}
    data = body.get("data")
    pages = (data.get("webPages") or {}).get("value") if isinstance(data, dict) else None
    return {"results": [_item(i) for i in pages or [] if isinstance(i, dict)]}
