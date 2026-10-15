"""提供方注册表：名称 → 实现。claude（订阅）/ anthropic（API Key）/ openai / zhipu / compat（OpenAI 兼容端点）。

每次调用新建实例（无状态）；测试可替换 PROVIDERS 中的工厂。
"""
from collections.abc import Callable
from typing import Protocol

from llm.models import ModelSpec
from llm.providers.anthropic_api import AnthropicApiProvider
from llm.providers.claude import ClaudeAgentProvider
from llm.providers.compat import CompatProvider
from llm.providers.openai_responses import OpenAIProvider
from llm.providers.zhipu import ZhipuProvider
from llm.types import LLMConfigError, LLMRequest, LLMResult


class Provider(Protocol):
    async def run(self, req: LLMRequest, spec: ModelSpec) -> LLMResult: ...


PROVIDERS: dict[str, Callable[[], Provider]] = {
    "claude": ClaudeAgentProvider,
    "anthropic": AnthropicApiProvider,
    "openai": OpenAIProvider,
    "zhipu": ZhipuProvider,
    "compat": CompatProvider,
}
_VENDOR = {"anthropic": "claude"}  # 传输方式 → 模型所属厂商


def get_provider(name: str, spec: ModelSpec) -> Provider:
    if name not in PROVIDERS:
        raise LLMConfigError(f"未知提供方 {name!r}（可选：{', '.join(PROVIDERS)}）")
    if _VENDOR.get(name, name) != spec.provider:
        raise LLMConfigError(f"模型 {spec.id} 属于 {spec.provider}，不能经 {name} 调用")
    return PROVIDERS[name]()
