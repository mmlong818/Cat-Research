"""
用户配置持久化（多提供商版）

存储结构：
{
  "active_provider": "anthropic",
  "active_model":    "claude-sonnet-4-5",
  "support_model":   "claude-haiku-4-5",
  "keys": {
    "anthropic": "sk-ant-...",
    "openai":    "sk-...",
    ...
  },
  // 旧字段（向后兼容）
  "anthropic_api_key": "...",
  "core_model": "..."
}
"""
import json
import os

from api.paths import project_root
_CONFIG_FILE = os.path.join(project_root(), "user_config.json")


def load_config() -> dict:
    if not os.path.exists(_CONFIG_FILE):
        return {}
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return {}
    return _migrate(cfg)


def save_config(updates: dict) -> dict:
    cfg = load_config()
    # 合并 keys
    if "keys" in updates and isinstance(updates["keys"], dict):
        merged_keys = dict(cfg.get("keys", {}))
        merged_keys.update(updates["keys"])
        # 空字符串 = 删除该 provider 的 key
        merged_keys = {k: v for k, v in merged_keys.items() if v}
        cfg["keys"] = merged_keys
        updates = {k: v for k, v in updates.items() if k != "keys"}
    cfg.update(updates)
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    return cfg


def _migrate(cfg: dict) -> dict:
    """旧字段 → 新字段迁移（不写盘，仅在内存）"""
    if "keys" not in cfg or not isinstance(cfg.get("keys"), dict):
        cfg["keys"] = {}
    legacy_key = cfg.get("anthropic_api_key")
    if legacy_key and "anthropic" not in cfg["keys"]:
        cfg["keys"]["anthropic"] = legacy_key
    if not cfg.get("active_provider"):
        cfg["active_provider"] = "anthropic" if cfg["keys"].get("anthropic") or legacy_key else (
            next(iter(cfg["keys"]), "anthropic")
        )
    if not cfg.get("active_model"):
        cfg["active_model"] = cfg.get("core_model", "")
    return cfg


def get_active_provider_key() -> tuple[str, str, str]:
    """返回 (provider_id, api_key, model) - 用于 LLM 调用层"""
    cfg = load_config()
    pid = cfg.get("active_provider") or "anthropic"
    keys = cfg.get("keys") or {}
    key = keys.get(pid) or os.getenv(f"{pid.upper()}_API_KEY") or ""
    if pid == "anthropic" and not key:
        key = os.getenv("ANTHROPIC_API_KEY", "")
    model = cfg.get("active_model") or cfg.get("core_model") or ""
    return pid, key, model
