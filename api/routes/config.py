"""
配置管理 API 路由 - 多提供商支持
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from .. import providers as providers_mod
from ..config_store import load_config, save_config

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ConfigUpdate(BaseModel):
    # 旧字段（向后兼容）
    anthropic_api_key: Optional[str] = None
    core_model: Optional[str] = None
    # 新字段
    active_provider: Optional[str] = None
    active_model: Optional[str] = None
    keys: Optional[dict] = None  # {provider_id: key}


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


def _public_view() -> dict:
    cfg = load_config()
    keys = cfg.get("keys", {}) or {}
    active = cfg.get("active_provider") or "anthropic"
    active_key = keys.get(active, "")
    return {
        "active_provider": active,
        "active_model": cfg.get("active_model") or cfg.get("core_model") or "",
        "configured_providers": [
            {"id": pid, "preview": _mask(k)}
            for pid, k in keys.items()
        ],
        "has_api_key": bool(active_key),
        "api_key_preview": _mask(active_key),
        "core_model": cfg.get("active_model") or cfg.get("core_model") or "",
        "mode": "api" if active_key else "cli",
    }


@router.get("")
def get_config():
    return _public_view()


@router.post("")
def update_config(body: ConfigUpdate):
    updates: dict = {}

    # 兼容旧字段
    if body.anthropic_api_key is not None:
        updates["keys"] = {"anthropic": body.anthropic_api_key.strip()}
        if not body.active_provider:
            updates["active_provider"] = "anthropic"
    if body.core_model is not None:
        updates["active_model"] = body.core_model.strip()
        updates["core_model"] = body.core_model.strip()

    # 新字段
    if body.active_provider is not None:
        try:
            providers_mod.get_provider(body.active_provider)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        updates["active_provider"] = body.active_provider
    if body.active_model is not None:
        updates["active_model"] = body.active_model.strip()
        updates["core_model"] = body.active_model.strip()
    if body.keys:
        merged = updates.get("keys", {})
        for pid, k in body.keys.items():
            try:
                providers_mod.get_provider(pid)
            except ValueError:
                continue
            merged[pid] = (k or "").strip()
        updates["keys"] = merged

    save_config(updates)
    return _public_view()


@router.delete("/api-key")
def clear_api_key():
    """清除当前激活 provider 的 key（兼容旧接口）"""
    cfg = load_config()
    active = cfg.get("active_provider") or "anthropic"
    save_config({"keys": {active: ""}})
    return _public_view()


@router.delete("/keys/{provider_id}")
def clear_provider_key(provider_id: str):
    save_config({"keys": {provider_id: ""}})
    return _public_view()


# ── 提供商目录 / 实时模型拉取 ────────────────────────────────────────────────

@router.get("/providers")
def list_providers_endpoint():
    return {"providers": providers_mod.list_providers()}


class FetchModelsRequest(BaseModel):
    api_key: Optional[str] = None  # 不传则用已存配置中的 key


@router.post("/providers/{provider_id}/models")
def fetch_provider_models(provider_id: str, body: FetchModelsRequest):
    try:
        providers_mod.get_provider(provider_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    key = body.api_key
    if key is None or key == "":
        cfg = load_config()
        key = (cfg.get("keys") or {}).get(provider_id, "")
    result = providers_mod.fetch_models(provider_id, key or "")
    return result
