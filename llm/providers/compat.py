"""OpenAI 兼容端点：任意一个支持 function calling 的 chat.completions 服务（base_url、key、模型名由用户配置）。

通用逻辑见 chat_completions，这里只放兼容端点的差异：
- 模型 ID 写作 compat:<端点里的模型名>，发给端点时去掉前缀；价格未知按 0 计（费用只含搜索）。
- 不传 max_tokens、thinking（不同厂商参数各异，传了反而可能被拒）。
- 推理强度按智能体的 effort 原样传顶层 reasoning_effort：部分模型不传时默认最高强度思考，
  实测 GLM-5.3 同一请求不传 954s、传 high 22s。
- 传 schema 且无工具时带 response_format=json_object（schema 同时写进系统提示词 + 本地校验）。
- 端点以 400 拒绝时，按 response_format → reasoning_effort 的顺序逐个退让重试（先退损失小的），
  本次请求后续沿用：强度先退到 low（智谱只认 low/high/max，拒收 medium），low 也被拒才去掉；
  都退完仍 400 才算永久错误。
- 额度用尽沿用 OpenAI 的 insufficient_quota（429 但不重试）；
  允许系统代理（海外端点常需要）。回传助手消息时不带思考内容（部分端点会拒收）。
- probe：设置页的"测试连接"，用只含 WebSearch 的极短请求验证连通与 function calling。
"""
import asyncio
import dataclasses
import time
from collections.abc import Callable
from typing import Any

from llm import keys
from llm.models import COMPAT_PREFIX
from llm.providers.chat_completions import ChatCompletionsProvider, Vendor, build_client
from llm.providers.openai_common import close_client, openai_sdk, to_llm_error
from llm.retry import Sleep
from llm.tools_local import TOOL_SPECS, FetchFn, SearchFn
from llm.types import LLMConfigError

LABEL = "OpenAI 兼容端点"
PROBE_TIMEOUT = 30
_PROBE_PROMPT = "请调用 WebSearch 工具搜索“今天的日期”，不要直接回答。"


def base_url() -> str:
    url = keys.compat_settings()["base_url"]
    if not url:
        raise LLMConfigError("未配置 OpenAI 兼容端点的 Base URL：请到设置页填写，或设置环境变量 COMPAT_BASE_URL")
    return url


VENDOR = Vendor(label=LABEL, key_name="compat", base_url=base_url, quota_codes=("insufficient_quota",),
                trust_env=True, model_prefix=COMPAT_PREFIX, effort_param=True,
                fallback_params=("response_format", "reasoning_effort"), effort_floor="low")


def make_client(key: str):
    return build_client(key, VENDOR)


class CompatProvider(ChatCompletionsProvider):
    def __init__(self, make_client: Callable[[str], Any] = make_client, sleep: Sleep = asyncio.sleep,
                 search: SearchFn | None = None, fetch: FetchFn | None = None):
        super().__init__(VENDOR, make_client, sleep, search, fetch)


def make_probe_client(url: str, key: str):
    return build_client(key, dataclasses.replace(VENDOR, base_url=lambda: url), timeout=PROBE_TIMEOUT)


def _probe_result(started: float, ok: bool, tool_calls: bool, detail: str) -> dict:
    return {"ok": ok, "tool_calls": tool_calls, "latency_ms": int((time.monotonic() - started) * 1000),
            "detail": detail}


async def probe(url: str, key: str, model: str, make: Callable[[str, str], Any] | None = None) -> dict:
    """测一次连通与 function calling：模型返回了 tool_calls 才算可用于研究。错误信息不含 key。"""
    openai = openai_sdk()
    client = (make or make_probe_client)(url, key)
    started = time.monotonic()
    try:
        resp = await client.chat.completions.create(
            model=model.removeprefix(COMPAT_PREFIX), messages=[{"role": "user", "content": _PROBE_PROMPT}],
            tools=[TOOL_SPECS["WebSearch"]])
    except openai.APIConnectionError:
        return _probe_result(started, False, False, "无法连接端点：请检查 Base URL、网络或代理设置")
    except openai.OpenAIError as e:
        return _probe_result(started, False, False, str(to_llm_error(e, LABEL, key)))
    finally:
        await close_client(client)
    message = resp.choices[0].message if resp.choices else None
    if getattr(message, "tool_calls", None):
        return _probe_result(started, True, True, "连通正常，模型支持工具调用")
    return _probe_result(started, False, False, "该模型不支持工具调用，无法用于研究")
