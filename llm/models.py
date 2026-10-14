"""模型注册表（能力表）：价格、上下文、推理强度、联网方式、结构化方式、默认并发。

价格单位均为美元/百万 token（智谱用 z.ai 国际站美元价，不做汇率换算）；联网搜索按次计价。
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
    input_price: float       # 未命中缓存的输入
    cached_price: float      # 命中缓存的输入
    output_price: float      # 输出（含推理 token）
    context: int
    max_output: int
    efforts: tuple[str, ...]  # 支持的推理强度；空表示不传该参数
    web: str                 # native：Claude Code 内置工具 / hosted_search：OpenAI 托管 / client_tools：本地工具循环
    structured: str          # json_schema / strict_json_schema / json_object（均再做本地 jsonschema 校验）
    max_concurrency: int     # 单个 call_many 内同一模型的并发上限
    output_budget: int = 0   # 每次请求的输出上限（max_output_tokens / max_tokens）；0 表示不传
    cache_write_price: float = 0.0
    search_price: float = 0.0          # 美元/次（仅托管搜索；client_tools 按所选搜索后端计价，见 llm.search）
    long_context_threshold: int = 0    # 单次输入超过该值后按倍率计价（0 表示无此规则）
    long_input_factor: float = 1.0
    long_output_factor: float = 1.0


def _claude(id_: str, inp: float, cached: float, out: float, efforts=_ALL_EFFORTS) -> ModelSpec:
    return ModelSpec(id_, "claude", inp, cached, out, 1_000_000, 128_000, efforts, "native", "json_schema",
                     max_concurrency=4, cache_write_price=inp * 1.25)


def _gpt(id_: str, inp: float, cached: float, out: float, efforts=_ALL_EFFORTS) -> ModelSpec:
    return ModelSpec(id_, "openai", inp, cached, out, 1_050_000, 128_000, efforts, "hosted_search",
                     "strict_json_schema", max_concurrency=8, output_budget=64_000, search_price=0.01,
                     long_context_threshold=272_000, long_input_factor=2.0, long_output_factor=1.5)


def _glm(id_: str, inp: float, cached: float, out: float, concurrency: int) -> ModelSpec:
    return ModelSpec(id_, "zhipu", inp, cached, out, 1_000_000, 128_000, ("low",),
                     "client_tools", "json_object", max_concurrency=concurrency, output_budget=65_536)


MODELS: dict[str, ModelSpec] = {s.id: s for s in (
    _claude("claude-opus-5-5", 4.0, 0.20, 20.0),
    _claude("claude-sonnet-5-5", 2.0, 0.20, 10.0),
    _claude("claude-opus-5", 5.0, 0.50, 25.0),
    _claude("claude-sonnet-5", 2.0, 0.20, 10.0),
    _gpt("gpt-6.1-sol", 2.0, 0.10, 10.0),
    _gpt("gpt-6-luna", 0.10, 0.01, 0.50),
    _gpt("gpt-6-astra", 10.0, 1.0, 50.0),
    _glm("glm-5.3", 1.4, 0.26, 4.4, concurrency=3),
    _glm("glm-5.3-flash", 0.15, 0.03, 0.50, concurrency=5),
    _glm("glm-5.3-flashx", 0.37, 0.075, 1.25, concurrency=5),
)}

_CLAUDE_ALIASES = ("opus", "sonnet", "haiku", "fable")
COMPAT_PREFIX = "compat:"  # OpenAI 兼容端点的模型 ID 写作 compat:<端点里的模型名>，发给端点时去掉前缀


def _compat_spec(model: str) -> ModelSpec:
    if not model.removeprefix(COMPAT_PREFIX):
        raise LLMConfigError(f"模型 ID {model!r} 缺少端点里的模型名（应写作 {COMPAT_PREFIX}<模型名>）")
    # 价格未知按 0 计（费用只含搜索）；上下文按 128k 估计；不传 max_tokens 与推理参数
    return ModelSpec(model, "compat", 0.0, 0.0, 0.0, 128_000, 0, (), "client_tools", "json_object",
                     max_concurrency=3)


def get_spec(model: str) -> ModelSpec:
    """按模型 ID 查能力表。未登记的 claude-* 与别名交给 Claude Code 自行解析（费用由其上报）；compat: 前缀动态生成。"""
    spec = MODELS.get(model)
    if spec:
        return spec
    if model.startswith(COMPAT_PREFIX):
        return _compat_spec(model)
    if model.startswith("claude-") or model.split("[")[0] in _CLAUDE_ALIASES:
        return ModelSpec(model, "claude", 0.0, 0.0, 0.0, 0, 0, (), "native", "json_schema", max_concurrency=4)
    raise LLMConfigError(f"未知模型 {model!r}：不在模型注册表中（已注册：{', '.join(MODELS)}）")


def resolve_effort(spec: ModelSpec, effort: str) -> str | None:
    """把通用推理强度映射到模型支持的档位：不支持的取最近的一档，距离相同取较高档。"""
    if not spec.efforts:
        return None
    if effort in spec.efforts:
        return effort
    want = EFFORT_ORDER.index(effort)
    return min(spec.efforts, key=lambda e: (abs(EFFORT_ORDER.index(e) - want), -EFFORT_ORDER.index(e)))


def cost_usd(spec: ModelSpec, input_tokens: int, cached: int = 0, output: int = 0,
             cache_write: int = 0, searches: int = 0) -> float:
    """单次 API 调用的费用。input_tokens 为全部输入（含缓存命中与缓存写入部分）。"""
    long = bool(spec.long_context_threshold) and input_tokens > spec.long_context_threshold
    in_factor = spec.long_input_factor if long else 1.0
    out_factor = spec.long_output_factor if long else 1.0
    uncached = max(input_tokens - cached - cache_write, 0)
    tokens = (uncached * spec.input_price + cached * spec.cached_price) * in_factor \
        + cache_write * spec.cache_write_price + output * spec.output_price * out_factor
    return tokens / 1_000_000 + searches * spec.search_price
