"""
统一 LLM 调用层：按 req.model 查模型注册表（llm.models）路由到提供方（llm.providers）

- Claude 默认走 claude-agent-sdk（复用本机 Claude Code 登录，即订阅额度）；OpenAI 与智谱用 API Key
- 失败一律抛 LLMError，不返回兜底值；额度/配置/内容拦截类错误（LLMPermanentError）不重试
- 传 schema 时返回经本地 jsonschema 校验的 dict（result.data）
- call_many 并行执行多个独立请求，同一模型的并发不超过能力表的上限
"""
import asyncio
from collections.abc import Sequence

from llm import providers
from llm.models import ModelSpec, get_spec
from llm.schema import schema_errors
from llm.types import (
    EffortLevel,
    LLMBlockedError,
    LLMConfigError,
    LLMError,
    LLMPermanentError,
    LLMQuotaError,
    LLMRequest,
    LLMResult,
)

__all__ = ["EffortLevel", "LLMBlockedError", "LLMConfigError", "LLMError", "LLMPermanentError", "LLMQuotaError",
           "LLMRequest", "LLMResult", "acall", "acall_many", "call", "call_many"]


def _route(req: LLMRequest) -> tuple[ModelSpec, providers.Provider]:
    spec = get_spec(req.model)
    return spec, providers.get_provider(req.provider or spec.provider, spec)


async def _acall_once(req: LLMRequest, spec: ModelSpec, provider: providers.Provider) -> LLMResult:
    try:
        result = await asyncio.wait_for(provider.run(req, spec), timeout=req.timeout)
    except asyncio.TimeoutError as e:
        raise LLMError(f"调用超时（{req.timeout:.0f}s）") from e
    if req.schema:
        problems = schema_errors(result.data, req.schema)
        if problems:
            raise LLMError(f"结构化输出不符合 schema（{req.model}）：{'；'.join(problems)}")
    return result


async def acall(req: LLMRequest) -> LLMResult:
    """调用一次，失败后按 req.retries 重试（LLMPermanentError 不重试）；全部失败抛最后一个 LLMError。"""
    if req.retries < 0:
        raise ValueError(f"retries 不能为负数: {req.retries}")
    spec, provider = _route(req)
    for attempt in range(req.retries + 1):
        try:
            return await _acall_once(req, spec, provider)
        except LLMPermanentError:
            raise
        except LLMError as e:
            if attempt == req.retries:
                raise
            print(f"  [llm] 第 {attempt + 1} 次调用失败，重试: {e}", flush=True)
    raise AssertionError("unreachable")


def _model_limit(model: str, default: int) -> int:
    try:
        return get_spec(model).max_concurrency
    except LLMConfigError:
        return default  # 未知模型在 acall 中报错


async def acall_many(reqs: Sequence[LLMRequest], max_concurrency: int = 4) -> list:
    """并行执行；返回与 reqs 同序的列表，单个失败时该位置为 LLMError 实例。"""
    total = asyncio.Semaphore(max_concurrency)
    per_model = {r.model: asyncio.Semaphore(_model_limit(r.model, max_concurrency)) for r in reqs}

    async def one(r: LLMRequest):
        async with per_model[r.model], total:
            return await acall(r)

    results = await asyncio.gather(*(one(r) for r in reqs), return_exceptions=True)
    for r in results:
        if isinstance(r, BaseException) and not isinstance(r, LLMError):
            raise r
    return list(results)


def call(req: LLMRequest) -> LLMResult:
    return asyncio.run(acall(req))


def call_many(reqs: Sequence[LLMRequest], max_concurrency: int = 4) -> list:
    return asyncio.run(acall_many(reqs, max_concurrency))
