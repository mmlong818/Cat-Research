"""LLM 调用层的公共类型：请求、结果与错误分类（各提供方共用）。"""
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]


class LLMError(RuntimeError):
    """LLM 调用失败（进程错误、超时、拒答、结构化输出缺失等）"""


class LLMPermanentError(LLMError):
    """重试无意义的失败（额度、配置、请求参数、内容拦截），acall 不重试"""


class LLMQuotaError(LLMPermanentError):
    """订阅/账号额度用尽或欠费"""


class LLMConfigError(LLMPermanentError):
    """配置问题：未知模型、缺少或无效的 API Key、不支持的工具"""


class LLMBlockedError(LLMPermanentError):
    """内容安全拦截"""


_QUOTA_MARKERS = ("session limit", "usage limit", "weekly limit")


def error_from_message(message: str) -> LLMError:
    lowered = message.lower()
    return (LLMQuotaError if any(m in lowered for m in _QUOTA_MARKERS) else LLMError)(message)


@dataclass
class LLMRequest:
    prompt: str
    system: str
    model: str
    effort: EffortLevel = "medium"
    tools: Sequence[str] = ()
    schema: dict | None = None
    max_turns: int = 40
    cwd: str | None = None
    timeout: float = 1800
    fallback_model: str | None = None
    retries: int = 1
    provider: str | None = None  # 显式指定传输方式（如 "anthropic" 走 API Key）；None 时按 model 查注册表


@dataclass
class LLMResult:
    text: str
    data: Any
    duration_ms: int
    num_turns: int
    session_id: str
    model_usage: dict = field(default_factory=dict)  # {模型: Claude Code modelUsage 形状的用量}
