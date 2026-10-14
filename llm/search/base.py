"""各搜索后端共用：常量、HTTP 发送与限流/5xx 退避、结果裁剪。

后端统一签名 `async search(query, count, recency) -> {"results": [...]} | {"error": str}`（key 已绑定），
失败以 {"error": ...} 交回模型，不抛异常。结果字段：title / link / media / publish_date / content（空值省略）。
"""
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import requests  # type: ignore[import-untyped]  # 未安装 types-requests 存根

from llm.retry import Sleep, with_backoff

SEARCH_QUERY_MAX = 70
SEARCH_COUNT_MAX = 20
SEARCH_SNIPPET_CHARS = 800
RECENCY = ("oneDay", "oneWeek", "oneMonth", "oneYear", "noLimit")

SearchFn = Callable[[str, int, str], Awaitable[dict]]
PostFn = Callable[[str, dict, dict], tuple[int, dict]]
Transient = Callable[[int, dict], bool]


class _Transient(Exception):
    """可退避重试的搜索失败（429 / 并发超限 / 5xx）"""


class SearchError(Exception):
    """退避用尽或请求本身失败；消息可直接交给模型"""


def http_post(url: str, headers: dict, payload: dict, trust_env: bool = False) -> tuple[int, dict]:
    with requests.Session() as session:
        session.trust_env = trust_env
        resp = session.post(url, headers=headers, json=payload, timeout=30)
    try:
        body = resp.json()
    except ValueError:
        body = None
    return resp.status_code, body if isinstance(body, dict) else {"error": {"message": resp.text[:200]}}


def is_busy(status: int, body: dict) -> bool:
    return status == 429 or status >= 500


async def post_json(url: str, headers: dict, payload: dict, *, post: PostFn, sleep: Sleep, label: str,
                    busy: Transient = is_busy) -> tuple[int, dict]:
    """POST 并解析 JSON；busy 判定为暂时不可用时按退避重试，用尽后抛 SearchError。"""
    async def once() -> tuple[int, dict]:
        status, body = await asyncio.to_thread(post, url, headers, payload)
        if busy(status, body):
            raise _Transient(f"HTTP {status}")
        return status, body

    try:
        return await with_backoff(once, lambda e: isinstance(e, _Transient), sleep, label)
    except _Transient as e:
        raise SearchError(f"搜索暂时不可用（已退避重试）：{e}") from None
    except requests.RequestException as e:
        raise SearchError(f"搜索请求失败：{type(e).__name__}") from None


def trim(item: dict[str, Any]) -> dict:
    """统一结果字段，摘要截断，空值省略。"""
    out = {k: item.get(k) for k in ("title", "link", "media", "publish_date")}
    out["content"] = (item.get("content") or "")[:SEARCH_SNIPPET_CHARS]
    return {k: v for k, v in out.items() if v not in (None, "")}
