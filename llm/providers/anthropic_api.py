"""Claude（API Key）：Anthropic Messages API，需显式以 provider="anthropic" 选用。

结构化输出用 output_config.format（Opus 5.5 / Sonnet 5.5 不接受强制 tool_choice，返回 400）；
思考无法关闭且计入 max_tokens，取文本时跳过思考块；推理强度经 output_config.effort 传。
暂不支持联网工具（研究链路的联网走订阅模式的 Claude Code 内置工具）。
"""
import time
from collections.abc import Callable
from typing import Any

from llm.keys import redact, require_key
from llm.models import ModelSpec, resolve_effort
from llm.schema import parse_valid, strict_schema
from llm.types import LLMConfigError, LLMError, LLMRequest, LLMResult
from llm.usage import Usage

# 思考计入 max_tokens，给足余量；非流式请求的官方建议值
MAX_TOKENS = 16000


def make_client(key: str):
    import anthropic  # 延迟导入：只在 API Key 模式下需要
    return anthropic.AsyncAnthropic(api_key=key)


def _first_text(resp) -> str:
    for block in resp.content:
        if block.type == "text":
            return block.text
    raise LLMError(f"Anthropic 响应中没有文本块, stop_reason={resp.stop_reason}")


def _params(req: LLMRequest, spec: ModelSpec) -> dict:
    params: dict[str, Any] = {"model": req.model, "max_tokens": MAX_TOKENS, "system": req.system,
                              "messages": [{"role": "user", "content": req.prompt}]}
    output_config: dict[str, Any] = {}
    effort = resolve_effort(spec, req.effort)
    if effort:
        output_config["effort"] = effort
    if req.schema:
        output_config["format"] = {"type": "json_schema", "schema": strict_schema(req.schema)}
    if output_config:
        params["output_config"] = output_config
    return params


def _record(usage: Usage, resp) -> None:
    u = resp.usage
    cached = getattr(u, "cache_read_input_tokens", 0) or 0
    written = getattr(u, "cache_creation_input_tokens", 0) or 0
    usage.add_call(u.input_tokens + cached + written, cached, u.output_tokens, cache_write=written)


class AnthropicApiProvider:
    def __init__(self, make_client: Callable[[str], Any] = make_client):
        self._make_client = make_client

    async def run(self, req: LLMRequest, spec: ModelSpec) -> LLMResult:
        if req.tools:
            raise LLMConfigError("Anthropic API Key 模式暂不支持联网工具，请改用订阅模式（claude-agent-sdk）")
        key = require_key("anthropic")
        import anthropic
        started = time.monotonic()
        client = self._make_client(key)
        try:
            resp = await client.messages.create(**_params(req, spec))
        except anthropic.AuthenticationError:
            raise LLMConfigError("Anthropic API Key 无效（HTTP 401），请到设置页检查") from None
        except anthropic.APIError as e:
            raise LLMError(f"Anthropic 调用失败：{redact(str(e), key)[:500]}") from None
        finally:
            close = getattr(client, "close", None)  # 在事件循环关闭前关掉本次新建的客户端
            if close is not None:
                await close()
        usage = Usage(spec)
        _record(usage, resp)
        if resp.stop_reason == "refusal":
            raise LLMError(f"模型拒答（{req.model}）stop_reason=refusal")
        text = _first_text(resp)
        try:
            data = parse_valid(text, req.schema) if req.schema else None
        except ValueError as e:
            raise LLMError(f"Anthropic 结构化输出未通过本地校验：{e}") from None
        return LLMResult(text=text, data=data,
                         duration_ms=int((time.monotonic() - started) * 1000), num_turns=1,
                         session_id=getattr(resp, "id", ""), model_usage=usage.model_usage())
