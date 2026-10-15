"""模型注册表（能力表）：上下文、推理强度、联网方式、结构化方式、默认并发。

数据来源：各厂商官方文档，2026-10-02 核对。
"""
from dataclasses import dataclass

from llm.types import LLMConfigError

EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
_ALL_EFFORTS = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class ModelSpec:
    id: str
    provider: str            # claude / openai / zhipu / compat
    context: int
    max_output: int
    efforts: tuple[str, ...]  # 支持的推理强度；空表示不传该参数
    web: str                 # native：Claude Code 内置工具 / hosted_search：OpenAI 托管 / client_tools：本地工具循环
    structured: str          # json_schema / strict_json_schema / json_object（均再做本地 jsonschema 校验）
    max_concurrency: int     # 单个 call_many 内同一模型的并发上限
    output_budget: int = 0   # 每次请求的输出上限（max_output_tokens / max_tokens）；0 表示不传


def _claude(id_: str, efforts=_ALL_EFFORTS) -> ModelSpec:
    return ModelSpec(id_, "claude", context=1_000_000, max_output=128_000, efforts=efforts, web="native",
                     structured="json_schema", max_concurrency=4)


def _gpt(id_: str, efforts=_ALL_EFFORTS) -> ModelSpec:
    return ModelSpec(id_, "openai", context=1_050_000, max_output=128_000, efforts=efforts, web="hosted_search",
                     structured="strict_json_schema", max_concurrency=8, output_budget=64_000)


def _glm(id_: str, concurrency: int) -> ModelSpec:
    return ModelSpec(id_, "zhipu", context=1_000_000, max_output=128_000, efforts=("low",), web="client_tools",
                     structured="json_object", max_concurrency=concurrency, output_budget=65_536)


MODELS: dict[str, ModelSpec] = {s.id: s for s in (
    _claude("claude-opus-5-5"),
    _claude("claude-sonnet-5-5"),
    _claude("claude-opus-5"),
    _claude("claude-sonnet-5"),
    _gpt("gpt-6.1-sol"),
    _gpt("gpt-6-luna"),
    _gpt("gpt-6-astra"),
    _glm("glm-5.3", concurrency=3),
    _glm("glm-5.3-flash", concurrency=5),
    _glm("glm-5.3-flashx", concurrency=5),
)}

_CLAUDE_ALIASES = ("opus", "sonnet", "haiku", "fable")
COMPAT_PREFIX = "compat:"  # OpenAI 兼容端点的模型 ID 写作 compat:<端点里的模型名>，发给端点时去掉前缀


def _compat_spec(model: str) -> ModelSpec:
    if not model.removeprefix(COMPAT_PREFIX):
        raise LLMConfigError(f"模型 ID {model!r} 缺少端点里的模型名（应写作 {COMPAT_PREFIX}<模型名>）")
    # 上下文按 128k 估计；不传 max_tokens 与推理参数
    return ModelSpec(model, "compat", context=128_000, max_output=0, efforts=(), web="client_tools",
                     structured="json_object", max_concurrency=3)


def get_spec(model: str) -> ModelSpec:
    """按模型 ID 查能力表。未登记的 claude-* 与别名交给 Claude Code 自行解析；compat: 前缀动态生成。"""
    spec = MODELS.get(model)
    if spec:
        return spec
    if model.startswith(COMPAT_PREFIX):
        return _compat_spec(model)
    if model.startswith("claude-") or model.split("[")[0] in _CLAUDE_ALIASES:
        return ModelSpec(model, "claude", context=0, max_output=0, efforts=(), web="native",
                         structured="json_schema", max_concurrency=4)
    raise LLMConfigError(f"未知模型 {model!r}：不在模型注册表中（已注册：{', '.join(MODELS)}）")


def resolve_effort(spec: ModelSpec, effort: str) -> str | None:
    """把通用推理强度映射到模型支持的档位：不支持的取最近的一档，距离相同取较高档。"""
    if not spec.efforts:
        return None
    if effort in spec.efforts:
        return effort
    want = EFFORT_ORDER.index(effort)
    return min(spec.efforts, key=lambda e: (abs(EFFORT_ORDER.index(e) - want), -EFFORT_ORDER.index(e)))

