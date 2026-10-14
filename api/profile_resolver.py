"""请求级模型配置档：把请求里可选的 provider/core/support 与设置里的默认配置档合并并校验。
缺 key、模型不合法都在建任务/调用前以 400 返回，不留给后台线程去失败。"""
import json
import os

from fastapi import HTTPException

from llm import keys
from llm.models import COMPAT_PREFIX, MODELS
from llm.profiles import PROFILES, Profile, default_profile, known_provider, make_profile


def missing_setup_detail(items: list[str]) -> str:
    return "请先在设置中填写 " + "、".join(items)


def validate_profile(provider: str, core: str | None = None, support: str | None = None,
                     fill: Profile | None = None) -> Profile:
    """校验并补全配置档：显式给出的模型必须登记在模型注册表里且属于该提供方；
    没给出的取 fill（同提供方的已有配置档）里的，再没有就取该提供方的默认。不检查 key。"""
    try:
        profile = make_profile(provider, core or (fill.core if fill else None),
                               support or (fill.support if fill else None))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    for model in (core, support):
        if model and model not in MODELS and not model.startswith(COMPAT_PREFIX):  # compat: 模型名由用户的端点决定
            raise HTTPException(status_code=400, detail=f"模型 {model} 不在模型注册表中（已注册：{', '.join(MODELS)}）")
    return profile


def resolve_profile(provider: str | None = None, core: str | None = None, support: str | None = None) -> Profile:
    """本次任务/调用使用的配置档：不传 provider 沿用设置里的默认提供方（及其模型）；
    换提供方时核心/辅助模型取该家默认，除非请求显式指定。该提供方缺 key 时 400。"""
    saved = default_profile()
    if not (provider or core or support) and known_provider(saved.provider):
        return ensure_key(saved)  # 原样使用默认配置档（含用 CORE_MODEL/SUPPORT_MODEL 环境变量配出的跨提供方组合）
    target = provider or saved.provider
    profile = validate_profile(target, core, support, fill=saved if target == saved.provider else None)
    return ensure_key(profile)


def ensure_key(profile: Profile) -> Profile:
    """该配置档的提供方（及联网搜索后端）缺 key、兼容端点缺 Base URL 时 400，并列出具体缺项。"""
    items = keys.missing_requirements(profile.provider)
    if items:
        raise HTTPException(status_code=400, detail=missing_setup_detail(items))
    return profile


def session_profile(workspace: str) -> Profile:
    """重放沿用会话原来的配置档（00_session.json 的 provider 与 resolved_params 里的模型）；
    M3 之前的会话没有这些字段，一律按 Claude 默认。"""
    try:
        with open(os.path.join(workspace, "00_session.json"), encoding="utf-8") as f:
            meta = json.load(f)
        params = meta.get("resolved_params") or {}
        return make_profile(meta["provider"], params.get("core_model"), params.get("support_model"))
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        return PROFILES["claude"]
