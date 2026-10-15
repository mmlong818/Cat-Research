"""OpenAI GPT：Responses API。

- 联网：托管 web_search 工具（由 OpenAI 执行搜索，并可打开网页阅读），WebSearch / WebFetch 都映射到它，
  不需要本地工具循环；max_turns 映射为 max_tool_calls，限制托管工具调用次数。
- 结构化：text.format json_schema（schema 满足 strict 要求时 strict=True）；与 web_search 同用若被拒（400），
  降级为提示词约束 + 本地校验 + 带错误信息重试。
- 推理强度：reasoning.effort，按能力表映射。限流/5xx 由本层退避（SDK 自身重试关闭，避免叠加）。
"""
import asyncio
import time
from collections.abc import Callable
from typing import Any

from llm.keys import require_key
from llm.models import ModelSpec, resolve_effort
from llm.providers.openai_common import close_client, is_transient, openai_sdk, to_llm_error
from llm.retry import Sleep, with_backoff
from llm.schema import MAX_REPAIRS, all_required, parse_valid, repair_instruction, schema_instruction, strict_schema
from llm.types import LLMBlockedError, LLMConfigError, LLMError, LLMRequest, LLMResult
from llm.usage import Usage

LABEL = "OpenAI"
_WEB_TOOLS = ("WebSearch", "WebFetch")
_PERMANENT_CODES = ("insufficient_quota",)
_WEB_NOTE = ("\n\n（联网说明：本环境用 web_search 工具完成 WebSearch / WebFetch——它既能搜索，也能打开网页阅读全文；"
             "引用来源时给出你实际读到的页面 URL。）")


def make_client(key: str, timeout: float):
    return openai_sdk().AsyncOpenAI(api_key=key, timeout=timeout, max_retries=0)


def build_params(req: LLMRequest, spec: ModelSpec, native_schema: bool) -> dict:
    params: dict[str, Any] = {"model": spec.id, "input": req.prompt, "store": False}
    instructions = req.system
    effort = resolve_effort(spec, req.effort)
    if effort:
        params["reasoning"] = {"effort": effort}
    if spec.output_budget:
        params["max_output_tokens"] = spec.output_budget
    if req.tools:
        params.update(tools=[{"type": "web_search"}], include=["web_search_call.action.sources"],
                      max_tool_calls=req.max_turns)
        instructions += _WEB_NOTE
    if req.schema and native_schema:
        schema = strict_schema(req.schema)
        params["text"] = {"format": {"type": "json_schema", "name": "result", "schema": schema,
                                     "strict": all_required(schema)}}
    elif req.schema:
        instructions += schema_instruction(req.schema)
    params["instructions"] = instructions
    return params


def _refusal(resp) -> str:
    for item in resp.output or []:
        for part in getattr(item, "content", None) or []:
            if getattr(part, "type", "") == "refusal":
                return part.refusal or "（无说明）"
    return ""


def response_text(resp, model: str) -> str:
    if resp.status == "incomplete":
        reason = getattr(resp.incomplete_details, "reason", "") or "unknown"
        if reason == "content_filter":
            raise LLMBlockedError(f"{LABEL} 内容过滤拦截了输出（{model}）")
        raise LLMError(f"{LABEL} 输出不完整（{reason}）")
    if resp.status == "failed":
        raise LLMError(f"{LABEL} 调用失败：{getattr(resp.error, 'message', '')}")
    refusal = _refusal(resp)
    if refusal:
        raise LLMError(f"模型拒答（{model}）: {refusal}")
    return resp.output_text or ""


def _record(usage: Usage, resp) -> None:
    u = resp.usage
    if u is None:
        return
    cached = getattr(u.input_tokens_details, "cached_tokens", 0) or 0
    reasoning = getattr(u.output_tokens_details, "reasoning_tokens", 0) or 0
    searches = sum(1 for item in resp.output or [] if item.type == "web_search_call")
    usage.add_call(u.input_tokens, cached, u.output_tokens, reasoning, searches=searches)


class OpenAIProvider:
    def __init__(self, make_client: Callable[[str, float], Any] = make_client, sleep: Sleep = asyncio.sleep):
        self._make_client = make_client
        self._sleep = sleep

    async def run(self, req: LLMRequest, spec: ModelSpec) -> LLMResult:
        unknown = [t for t in req.tools if t not in _WEB_TOOLS]
        if unknown:
            raise LLMConfigError(f"{LABEL} 不支持工具：{', '.join(unknown)}（可用：{', '.join(_WEB_TOOLS)}）")
        key = require_key("openai")
        openai = openai_sdk()
        client = self._make_client(key, req.timeout)
        usage, started = Usage(spec), time.monotonic()
        try:
            text, data, resp_id = await self._answer(client, req, spec, usage)
        except openai.OpenAIError as e:
            raise to_llm_error(e, LABEL, key, quota_codes=_PERMANENT_CODES) from None
        finally:
            await close_client(client)
        return LLMResult(text=text, data=data,
                         duration_ms=int((time.monotonic() - started) * 1000), num_turns=usage.calls,
                         session_id=resp_id, model_usage=usage.model_usage())

    async def _create(self, client, params: dict, usage: Usage):
        resp = await with_backoff(lambda: client.responses.create(**params),
                                  lambda e: is_transient(e, _PERMANENT_CODES), self._sleep, LABEL)
        _record(usage, resp)
        return resp

    async def _answer(self, client, req: LLMRequest, spec: ModelSpec, usage: Usage) -> tuple[str, Any, str]:
        params = build_params(req, spec, native_schema=True)
        try:
            resp = await self._create(client, params, usage)
        except openai_sdk().BadRequestError:
            if not (req.schema and req.tools):
                raise
            print(f"  [llm] {LABEL} 拒绝 web_search 与 json_schema 同用，降级为提示词约束 + 本地校验", flush=True)
            params = build_params(req, spec, native_schema=False)
            resp = await self._create(client, params, usage)
        text = response_text(resp, spec.id)
        if not req.schema:
            return text, None, resp.id
        if "text" in params:
            try:
                return text, parse_valid(text, req.schema), resp.id
            except ValueError as e:
                raise LLMError(f"{LABEL} 结构化输出未通过本地校验：{e}") from None
        return await self._repair(client, params, req, text, usage, resp.id)

    async def _repair(self, client, params: dict, req: LLMRequest, text: str, usage: Usage,
                      resp_id: str) -> tuple[str, Any, str]:
        """提示词约束模式：本地校验不过就把错误反馈给模型重答，最多 MAX_REPAIRS 次。"""
        schema = req.schema or {}
        history: list[dict] = [{"role": "user", "content": req.prompt}]
        for attempt in range(MAX_REPAIRS + 1):
            try:
                return text, parse_valid(text, schema), resp_id
            except ValueError as e:
                if attempt == MAX_REPAIRS:
                    raise LLMError(f"{LABEL} 输出不合格（已重试 {MAX_REPAIRS} 次）：{e}") from None
                history += [{"role": "assistant", "content": text},
                            {"role": "user", "content": repair_instruction(str(e))}]
            resp = await self._create(client, {**params, "input": list(history)}, usage)
            text, resp_id = response_text(resp, req.model), resp.id
        raise AssertionError("unreachable")
