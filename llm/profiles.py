"""模型配置档（profile）：一个提供方 + 核心模型 + 辅助模型，按角色分配给各智能体。

编排器持有自己的 profile，并发的多个研究任务互不影响（不靠改全局 config 切换）。
"""
from dataclasses import dataclass

import config as _config
from llm import keys
from llm.models import get_spec
from llm.types import LLMConfigError

# 角色分工沿用 config.py：核心模型负责推理/规划/研究/分析/写作，辅助模型负责评审与各类验证
CORE_ROLES = ("clarifier", "planner", "researcher", "analyst", "writer")
SUPPORT_ROLES = ("critic", "source_verifier", "fact_checker", "conclusion_validator", "reconciler")


@dataclass(frozen=True)
class Profile:
    provider: str
    core: str
    support: str

    def model_for(self, role: str) -> str:
        if role in CORE_ROLES:
            return self.core
        if role in SUPPORT_ROLES:
            return self.support
        raise ValueError(f"未知角色: {role}")


PROFILES: dict[str, Profile] = {
    "claude": Profile("claude", "claude-opus-5-5", "claude-sonnet-5-5"),
    "openai": Profile("openai", "gpt-6.1-sol", "gpt-6-luna"),
    "zhipu": Profile("zhipu", "glm-5.3", "glm-5.3-flash"),
}


COMPAT = "compat"  # 兼容端点的配置档没有固定默认值：核心/辅助模型取 user_config 的 compat.core / compat.support


def known_provider(provider: str) -> bool:
    return provider in PROFILES or provider == COMPAT


def _base_profile(provider: str) -> Profile:
    if provider == COMPAT:
        cfg = keys.compat_settings()
        return Profile(COMPAT, cfg["core"], cfg["support"])
    return PROFILES[provider]


def make_profile(provider: str, core: str | None = None, support: str | None = None) -> Profile:
    """按提供方默认值补全并校验：模型必须已登记（compat:<模型名> 动态认）且属于该提供方。"""
    if not known_provider(provider):
        raise ValueError(f"未知提供方 {provider!r}（可选：{', '.join((*PROFILES, COMPAT))}）")
    base = _base_profile(provider)
    profile = Profile(provider, core or base.core, support or base.support)
    if provider == COMPAT and not (profile.core and profile.support):
        raise ValueError("请先在设置中填写 OpenAI 兼容端点的核心模型与辅助模型")
    for model in (profile.core, profile.support):
        try:
            owner = get_spec(model).provider
        except LLMConfigError as e:
            raise ValueError(str(e)) from e
        if owner != provider:
            raise ValueError(f"模型 {model} 属于 {owner}，不能用于 {provider} 配置档")
    return profile


def _saved_default() -> Profile | None:
    """设置页保存的默认配置档（user_config.json 的 default_profile）；没有或已失效时返回 None。
    更早版本的设置页只存 core_model，按其所属提供方折算成配置档。"""
    cfg = keys.stored_config()
    raw = cfg.get("default_profile")
    legacy_core = cfg.get("core_model")
    try:
        if isinstance(raw, dict):
            return make_profile(raw.get("provider", ""), raw.get("core"), raw.get("support"))
        if legacy_core:
            provider = get_spec(legacy_core).provider
            support = _config.SUPPORT_MODEL if get_spec(_config.SUPPORT_MODEL).provider == provider else None
            return make_profile(provider, legacy_core, support)
    except (ValueError, LLMConfigError):
        return None
    return None


def default_profile() -> Profile:
    """未指定 profile 时的默认配置档：设置页保存的优先，否则取当前 config 的模型（环境变量与 settings.json 可覆盖）"""
    saved = _saved_default()
    if saved:
        return saved
    core, support = _config.CORE_MODEL, _config.SUPPORT_MODEL
    try:
        provider = get_spec(core).provider
    except LLMConfigError:
        provider = "unknown"  # 调用时由路由层报出清晰错误
    return Profile(provider, core, support)
