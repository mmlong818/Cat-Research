"""OpenAI 兼容 chat.completions 的通用实现（智谱与 OpenAI 兼容端点共用），流式累积，长生成不会撞单次读超时。

各家差异由 Vendor 参数化：名称与错误码、base_url 与 key、是否走系统代理、额外请求体、
是否传顶层 reasoning_effort、哪些可选参数被 400 拒绝时去掉重试。
- 联网：本地工具循环（llm.tools_local）——WebSearch 调所选搜索后端（llm.search）、WebFetch 本机抓取；
  模型一次返回多个 tool_calls 时并行执行；达到 max_turns 仍未给出最终答案即报错。
- 结构化：只有 json_object；schema 写进系统提示词 + 本地 jsonschema 校验，不合格带错误信息重试（最多 2 次）。
  带工具时不传 response_format（与工具调用同用的行为官方未写明）。
- 退避：429、5xx、连接错误与流中断退避重试；额度/拦截类错误码不重试。
"""
import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from llm.keys import require_key
from llm.models import ModelSpec
from llm.providers.openai_common import close_client, is_transient, openai_sdk, to_llm_error
from llm.retry import Sleep, with_backoff
from llm.schema import MAX_REPAIRS, parse_valid, repair_instruction, schema_instruction
from llm.search import BACKENDS, get_search, selected_backend
from llm.tools_local import FetchFn, SearchFn, ToolRunner, fetch_page, function_tools
from llm.types import LLMBlockedError, LLMError, LLMPermanentError, LLMRequest, LLMResult
from llm.usage import Usage

CHUNK_TIMEOUT = 300  # 流式每个数据块的读超时（秒）；整体超时由 LLMRequest.timeout 控制


def _no_extra(spec: ModelSpec, req: LLMRequest) -> dict:
    return {}


async def _no_search(query: str, count: int, recency: str) -> dict:
    return {"error": "本次请求未启用联网搜索"}


@dataclass(frozen=True)
class Vendor:
    label: str
    key_name: str                          # llm.keys 里的密钥名
    base_url: Callable[[], str]
    quota_codes: tuple[str, ...] = ()
    blocked_codes: tuple[str, ...] = ()
    trust_env: bool = False                # 国内接口不走系统代理；海外端点允许
    extra_body: Callable[[ModelSpec, LLMRequest], dict] = _no_extra
    model_prefix: str = ""                 # 注册表 ID 的前缀，发给端点时去掉
    echo_reasoning: bool = False           # 回传助手消息时带上思考内容（智谱官方示例如此）
    effort_param: bool = False             # 把 req.effort 原样作为顶层 reasoning_effort 传
    fallback_params: tuple[str, ...] = ()  # 被 400 拒绝时按此顺序逐个去掉重试的可选参数
    effort_floor: str = ""                 # reasoning_effort 被拒时先退到这一档重试，再被拒才去掉


def build_client(key: str, vendor: Vendor, timeout: float = CHUNK_TIMEOUT):
    openai = openai_sdk()
    return openai.AsyncOpenAI(api_key=key, base_url=vendor.base_url(), timeout=timeout, max_retries=0,
                              http_client=openai.DefaultAsyncHttpxClient(trust_env=vendor.trust_env))


class _StreamInterrupted(Exception):
    """流式输出以 finish_reason=network_error 结束（可退避重试）"""


@dataclass
class _Reply:
    content: str = ""
    reasoning: str = ""
    tool_slots: dict[int, dict] = field(default_factory=dict)
    finish: str = ""
    usage: Any = None


def _merge_tool_call(slots: dict[int, dict], tc) -> None:
    slot = slots.setdefault(tc.index or 0, {"id": "", "name": "", "arguments": ""})
    slot["id"] = slot["id"] or tc.id or ""
    if tc.function is not None:
        slot["name"] = slot["name"] or tc.function.name or ""
        slot["arguments"] += tc.function.arguments or ""


def _merge(reply: _Reply, chunk) -> None:
    if getattr(chunk, "usage", None):
        reply.usage = chunk.usage
    for choice in chunk.choices or []:
        delta = choice.delta
        if delta is not None:
            reply.content += delta.content or ""
            reply.reasoning += getattr(delta, "reasoning_content", None) or ""
            for tc in delta.tool_calls or []:
                _merge_tool_call(reply.tool_slots, tc)
        reply.finish = choice.finish_reason or reply.finish


def _tool_calls(reply: _Reply) -> list[dict]:
    return [{"id": s["id"] or f"call_{i}", "type": "function",
             "function": {"name": s["name"], "arguments": s["arguments"] or "{}"}}
            for i, s in sorted(reply.tool_slots.items())]


def _record(usage: Usage, reply: _Reply) -> None:
    u = reply.usage
    if u is None:
        return
    cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
    reasoning = getattr(getattr(u, "completion_tokens_details", None), "reasoning_tokens", 0) or 0
    usage.add_call(u.prompt_tokens or 0, cached, u.completion_tokens or 0, reasoning)


class ChatCompletionsProvider:
    def __init__(self, vendor: Vendor, make_client: Callable[[str], Any], sleep: Sleep = asyncio.sleep,
                 search: SearchFn | None = None, fetch: FetchFn | None = None):
        self._vendor = vendor
        self._make_client = make_client
        self._sleep = sleep
        self._search = search
        self._fetch = fetch
        self._rejected: set[str] = set()  # 已被端点拒绝的可选参数：本实例后续请求不再带
        self._effort = ""                 # 原强度被拒后改用的强度

    async def run(self, req: LLMRequest, spec: ModelSpec) -> LLMResult:
        vendor = self._vendor
        tools = function_tools(req.tools) if req.tools else []
        key = require_key(vendor.key_name)
        openai = openai_sdk()
        client = self._make_client(key)
        search, search_price = self._search_for(req)
        runner = ToolRunner(search=search, fetch=self._fetch or fetch_page)
        usage, started = Usage(spec), time.monotonic()
        try:
            text, data = await self._answer(client, req, spec, tools, runner, usage)
        except openai.OpenAIError as e:
            raise to_llm_error(e, vendor.label, key, vendor.quota_codes, vendor.blocked_codes) from None
        except _StreamInterrupted:
            raise LLMError(f"{vendor.label} 流式输出中断（network_error），退避重试后仍失败") from None
        finally:
            await close_client(client)
        usage.add_local_tools(runner.searches, runner.fetches, search_price)
        return LLMResult(text=text, data=data, cost_usd=usage.cost,
                         duration_ms=int((time.monotonic() - started) * 1000), num_turns=usage.calls,
                         session_id="", model_usage=usage.model_usage())

    def _search_for(self, req: LLMRequest) -> tuple[SearchFn, float]:
        """所选搜索后端的搜索函数与单价；注入的 search 优先（测试用），计价仍按所选后端。"""
        backend = selected_backend()
        if self._search:
            return self._search, BACKENDS[backend].price if backend in BACKENDS else 0.0
        if "WebSearch" not in req.tools:
            return _no_search, 0.0  # 不联网的请求不要求搜索 key
        search, price, _ = get_search(backend, sleep=self._sleep)
        return search, price

    async def _answer(self, client, req: LLMRequest, spec: ModelSpec, tools: list[dict], runner: ToolRunner,
                      usage: Usage) -> tuple[str, Any]:
        system = req.system + (schema_instruction(req.schema) if req.schema else "")
        messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": req.prompt}]
        for attempt in range(MAX_REPAIRS + 1):
            text = await self._converse(client, req, spec, messages, tools, runner, usage)
            if not req.schema:
                return text, None
            try:
                return text, parse_valid(text, req.schema)
            except ValueError as e:
                if attempt == MAX_REPAIRS:
                    raise LLMError(f"{self._vendor.label} 输出不合格（已重试 {MAX_REPAIRS} 次）：{e}") from None
                messages += [{"role": "assistant", "content": text},
                             {"role": "user", "content": repair_instruction(str(e))}]
        raise AssertionError("unreachable")

    async def _converse(self, client, req: LLMRequest, spec: ModelSpec, messages: list[dict], tools: list[dict],
                        runner: ToolRunner, usage: Usage) -> str:
        """工具循环：执行模型请求的工具并回填结果，直到模型不再调用工具。"""
        for _ in range(req.max_turns):
            reply = await self._chat(client, self._params(req, spec, messages, tools), usage)
            if not reply.tool_slots:
                return reply.content
            calls = _tool_calls(reply)
            messages.append(self._assistant_message(reply, calls))
            results = await asyncio.gather(*(runner.run(c["function"]["name"], c["function"]["arguments"])
                                             for c in calls))
            messages.extend({"role": "tool", "tool_call_id": c["id"], "content": r}
                            for c, r in zip(calls, results, strict=True))
        raise LLMError(f"{self._vendor.label} 达到 max_turns={req.max_turns} 仍未给出最终答案")

    def _assistant_message(self, reply: _Reply, calls: list[dict]) -> dict:
        msg: dict[str, Any] = {"role": "assistant", "content": reply.content, "tool_calls": calls}
        if reply.reasoning and self._vendor.echo_reasoning:
            msg["reasoning_content"] = reply.reasoning
        return msg

    def _params(self, req: LLMRequest, spec: ModelSpec, messages: list[dict], tools: list[dict]) -> dict:
        wire_model = spec.id.removeprefix(self._vendor.model_prefix)
        params: dict[str, Any] = {"model": wire_model, "messages": list(messages), "stream": True}
        extra = self._vendor.extra_body(spec, req)
        if extra:
            params["extra_body"] = extra
        if spec.output_budget:
            params["max_tokens"] = spec.output_budget
        if self._vendor.effort_param:
            params["reasoning_effort"] = self._effort or req.effort
        if tools:
            params["tools"] = tools
        elif req.schema:
            params["response_format"] = {"type": "json_object"}
        return {k: v for k, v in params.items() if k not in self._rejected}

    async def _chat(self, client, params: dict, usage: Usage) -> _Reply:
        while True:
            try:
                reply = await self._stream(client, params)
                break
            except openai_sdk().BadRequestError:
                degraded = self._degrade(params)
                if degraded is None:
                    raise
                params = degraded
        _record(usage, reply)
        self._check_finish(reply)
        return reply

    def _degrade(self, params: dict) -> dict | None:
        """端点 400 拒绝后的下一版参数：强度先退到 effort_floor，其余可选参数按序去掉；无可退返回 None。"""
        label, floor = self._vendor.label, self._vendor.effort_floor
        name = next((p for p in self._vendor.fallback_params if p in params), None)
        if name is None:
            return None
        if name == "reasoning_effort" and floor and params[name] != floor:
            print(f"  [llm] {label} 拒绝 reasoning_effort={params[name]}，本次请求改用 {floor}", flush=True)
            self._effort = floor
            return {**params, name: floor}
        print(f"  [llm] {label} 拒绝 {name}，本次请求改为不带它", flush=True)
        self._rejected.add(name)
        return {k: v for k, v in params.items() if k != name}

    async def _stream(self, client, params: dict) -> _Reply:
        async def once() -> _Reply:
            reply = _Reply()
            async for chunk in await client.chat.completions.create(**params):
                _merge(reply, chunk)
            if reply.finish == "network_error":
                raise _StreamInterrupted()
            return reply

        permanent = self._vendor.quota_codes + self._vendor.blocked_codes

        def retryable(e: BaseException) -> bool:
            return isinstance(e, _StreamInterrupted) or is_transient(e, permanent)

        return await with_backoff(once, retryable, self._sleep, self._vendor.label)

    def _check_finish(self, reply: _Reply) -> None:
        label = self._vendor.label
        if reply.finish == "sensitive":
            raise LLMBlockedError(f"{label} 内容安全拦截（finish_reason=sensitive）")
        if reply.finish == "length":
            raise LLMError(f"{label} 输出达到 max_tokens 上限被截断")
        if reply.finish == "model_context_window_exceeded":
            raise LLMPermanentError(f"{label} 输入超出模型上下文窗口")
