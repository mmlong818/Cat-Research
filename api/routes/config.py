"""
设置 API：默认配置档（提供方 + 核心/辅助模型）、各提供方与搜索后端的 API Key、OpenAI 兼容端点（compat）与联网搜索后端。
key 只存系统凭据库，接口里只返回"是否已配置 + 末 4 位预览"；compat 的 base_url 与模型、搜索后端存 user_config.json。
"""
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from llm import keys
from llm.models import COMPAT_PREFIX, MODELS
from llm.profiles import PROFILES, default_profile
from llm.providers import compat
from llm.search import BACKENDS

from ..config_store import SecretStoreUnavailable, load_config, save_config
from ..profile_resolver import missing_setup_detail, validate_profile

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ProfileIn(BaseModel):
    provider: str
    core: str | None = None      # 不传取该提供方默认
    support: str | None = None


class CompatIn(BaseModel):
    """None 表示不改，空字符串表示清除；core/support 可不带 compat: 前缀，服务端补上"""
    base_url: str | None = None
    core: str | None = None
    support: str | None = None


class CompatTestIn(BaseModel):
    base_url: str | None = None   # 缺省用已保存的
    api_key: str | None = None
    model: str | None = None


class SettingsUpdate(BaseModel):
    default_profile: ProfileIn | None = None
    compat: CompatIn | None = None
    search_backend: str | None = None
    api_keys: dict[str, str] = Field(default_factory=dict)   # 提供方 -> key；空字符串表示不改
    clear_keys: list[str] = Field(default_factory=list)      # 要删除 key 的提供方


def _tier(output_price: float) -> str:
    """按输出价（美元/百万 token）粗分价格档，供界面提示。"""
    return "low" if output_price < 2 else "mid" if output_price < 15 else "high"


def models_by_provider() -> dict[str, list[dict]]:
    """能力表里的模型按提供方分组（顺序同注册表）。"""
    grouped: dict[str, list[dict]] = {p: [] for p in PROFILES}
    for spec in MODELS.values():
        grouped[spec.provider].append({
            "id": spec.id, "tier": _tier(spec.output_price), "input_price": spec.input_price,
            "cached_price": spec.cached_price, "output_price": spec.output_price, "context": spec.context,
        })
    return grouped


_KEY_NAMES = {**keys.PROVIDER_KEY, **{b: b for b in BACKENDS}}  # 接口里的名称 -> 密钥名（提供方与搜索后端）


def _secret_field(name: str) -> str:
    if name not in _KEY_NAMES:
        raise HTTPException(status_code=400, detail=f"未知提供方或搜索后端 {name!r}（可选：{', '.join(_KEY_NAMES)}）")
    return f"{_KEY_NAMES[name]}_api_key"


def _key_view(name: str, stored: dict) -> dict:
    key, source = keys.key_status(name, stored)
    return {"has_key": bool(key), "key_source": source, "key_preview": f"...{key[-4:]}" if len(key) > 4 else ""}


def _compat_view(stored: dict) -> dict:
    cfg = keys.compat_settings(stored)
    view = _key_view("compat", stored)
    ids = list(dict.fromkeys(m for m in (cfg["core"], cfg["support"]) if m))
    available = bool(view["has_key"] and cfg["base_url"] and cfg["core"] and cfg["support"])
    return {"needs_key": True, **view, "available": available,
            "defaults": {"core": cfg["core"], "support": cfg["support"]},
            "models": [{"id": i, "tier": "low", "input_price": 0.0, "cached_price": 0.0, "output_price": 0.0,
                        "context": 128_000} for i in ids],
            "base_url": cfg["base_url"]}


def settings_view() -> dict:
    stored = load_config()
    grouped = models_by_provider()
    providers = {}
    for provider, base in PROFILES.items():
        view = _key_view(keys.PROVIDER_KEY[provider], stored)
        needs_key = provider != "claude"   # Claude 走订阅（claude-agent-sdk），Anthropic key 只是可选的 API 模式
        providers[provider] = {
            "needs_key": needs_key, **view, "available": view["has_key"] or not needs_key,
            "defaults": {"core": base.core, "support": base.support},
            "models": grouped[provider],
        }
    providers["compat"] = _compat_view(stored)
    current = default_profile()
    backends = {name: {**_key_view(name, stored), "price_usd": b.price} for name, b in BACKENDS.items()}
    return {"default_profile": {"provider": current.provider, "core": current.core, "support": current.support},
            "providers": providers,
            "search": {"backend": keys.selected_search_backend(stored), "backends": backends}}


@router.get("")
def get_settings():
    return settings_view()


def _http_url(url: str) -> str:
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise HTTPException(status_code=400, detail=f"Base URL 必须是 http(s) 地址：{url!r}")
    return url


def _compat_model(name: str) -> str:
    """补上 compat: 前缀；前缀后必须有模型名。"""
    full = name if name.startswith(COMPAT_PREFIX) else COMPAT_PREFIX + name
    if not full.removeprefix(COMPAT_PREFIX).strip():
        raise HTTPException(status_code=400, detail=f"模型名不能为空（应写作 {COMPAT_PREFIX}<模型名>）")
    return full


def _compat_update(body: CompatIn, stored: dict) -> dict:
    """把提交的 compat 字段并进已存的 compat 段（空字符串清除该项）；返回要整体写回的新段。"""
    section = dict(stored.get("compat") or {})
    checks = {"base_url": _http_url, "core": _compat_model, "support": _compat_model}
    for field, check in checks.items():
        value = getattr(body, field)
        if value is None:
            continue
        value = value.strip()
        if value:
            section[field] = check(value)
        else:
            section.pop(field, None)
    return section


def _search_update(backend: str, stored: dict) -> dict:
    if backend not in BACKENDS:
        raise HTTPException(status_code=400, detail=f"未知搜索后端 {backend!r}（可选：{', '.join(BACKENDS)}）")
    return {**(stored.get("search") or {}), "backend": backend}


def _apply_profile(body: ProfileIn, pending: dict) -> dict:
    """校验默认配置档（缺的模型取该提供方默认；compat 取同一请求里待存的 compat 设置）并检查缺项。"""
    core, support = body.core, body.support
    if body.provider == "compat":
        pending_compat = keys.compat_settings(pending)
        core, support = core or pending_compat["core"] or None, support or pending_compat["support"] or None
    profile = validate_profile(body.provider, core, support)
    items = keys.missing_requirements(profile.provider, pending)  # 同一请求里一并提交的 key 与设置也算
    if items:
        raise HTTPException(status_code=400, detail=missing_setup_detail(items))
    return {"provider": profile.provider, "core": profile.core, "support": profile.support}


@router.post("")
def update_settings(body: SettingsUpdate):
    stored = load_config()
    updates: dict = {_secret_field(p): "" for p in body.clear_keys}
    updates.update({_secret_field(p): v.strip() for p, v in body.api_keys.items() if v.strip()})
    if body.compat:
        updates["compat"] = _compat_update(body.compat, stored)
    if body.search_backend is not None:
        updates["search"] = _search_update(body.search_backend, stored)
    if body.default_profile:
        updates["default_profile"] = _apply_profile(body.default_profile, {**stored, **updates})
    _save(updates)
    return settings_view()


@router.post("/compat/test")
async def test_compat(body: CompatTestIn):
    """用只含 WebSearch 的极短请求测兼容端点的连通与 function calling；缺省参数用已保存的设置。返回里不含 key。"""
    stored = load_config()
    cfg = keys.compat_settings(stored)
    url = (body.base_url or "").strip() or cfg["base_url"]
    key = (body.api_key or "").strip() or keys.key_status("compat", stored)[0]
    model = (body.model or "").strip() or cfg["core"]
    missing = [name for name, value in (("Base URL", url), ("API Key", key), ("模型名", model)) if not value]
    if missing:
        raise HTTPException(status_code=400, detail=missing_setup_detail([f"OpenAI 兼容端点 的 {n}" for n in missing]))
    return await compat.probe(_http_url(url), key, model)


@router.delete("/keys/{provider}")
def clear_key(provider: str):
    _save({_secret_field(provider): ""})
    return settings_view()


def _save(updates: dict):
    try:
        save_config(updates)
    except SecretStoreUnavailable as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
