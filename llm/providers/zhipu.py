"""智谱 GLM：OpenAI 兼容的 chat.completions（通用逻辑见 chat_completions），这里只放智谱的差异。

- 思考：5.3 系列强制开启；强度用顶层 reasoning_effort，经 extra_body 传；接口支持 low/high/max，
  能力表只登记 low（high 以上思考过久、提速有限），所有智能体都映射到 low。
- 错误码：1302/1305、5xx、连接错误与流中断退避重试；1113 欠费、1308 达到使用上限按额度错误不重试；
  1301 内容安全拦截不重试。
- 国内接口，不走系统代理；回传助手消息时带上思考内容。
"""
import asyncio
from collections.abc import Callable
from typing import Any

from llm.models import ModelSpec, resolve_effort
from llm.providers.chat_completions import ChatCompletionsProvider, Vendor, build_client
from llm.retry import Sleep
from llm.tools_local import FetchFn, SearchFn
from llm.types import LLMRequest

BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
LABEL = "智谱"
QUOTA_CODES = ("1113", "1308")
BLOCKED_CODES = ("1301",)


def _extra_body(spec: ModelSpec, req: LLMRequest) -> dict:
    extra: dict[str, Any] = {"thinking": {"type": "enabled"}}
    effort = resolve_effort(spec, req.effort)
    if effort:
        extra["reasoning_effort"] = effort
    return extra


VENDOR = Vendor(label=LABEL, key_name="zhipu", base_url=lambda: BASE_URL, quota_codes=QUOTA_CODES,
                blocked_codes=BLOCKED_CODES, extra_body=_extra_body, echo_reasoning=True)


def make_client(key: str):
    return build_client(key, VENDOR)


class ZhipuProvider(ChatCompletionsProvider):
    def __init__(self, make_client: Callable[[str], Any] = make_client, sleep: Sleep = asyncio.sleep,
                 search: SearchFn | None = None, fetch: FetchFn | None = None):
        super().__init__(VENDOR, make_client, sleep, search, fetch)
