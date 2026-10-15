"""
用户配置：普通设置存 user_config.json；密钥（各提供方 API Key）存系统凭据库（keyring），不落明文。
文件里若有明文密钥，首次读取时迁移到凭据库并从文件删除。
"""
import json
import os
from contextlib import suppress

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

_CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_config.json")
_SERVICE = "cat-research"
SECRET_KEYS = ("anthropic_api_key", "openai_api_key", "zhipu_api_key", "compat_api_key", "bocha_api_key",
               "tavily_api_key")


class SecretStoreUnavailable(RuntimeError):
    """系统凭据库不可用（如无桌面环境的 Linux）；此时应改用环境变量提供密钥。"""


def _read_file() -> dict:
    if not os.path.exists(_CONFIG_FILE):
        return {}
    try:
        with open(_CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_file(cfg: dict):
    tmp = f"{_CONFIG_FILE}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _CONFIG_FILE)


def _set_secret(name: str, value: str):
    try:
        if value:
            keyring.set_password(_SERVICE, name, value)
        else:
            with suppress(PasswordDeleteError):  # 本来就没有
                keyring.delete_password(_SERVICE, name)
    except KeyringError as e:
        raise SecretStoreUnavailable(f"系统凭据库不可用，请改用环境变量提供 {name.upper()}：{e}") from e


def _get_secret(name: str) -> str:
    try:
        return keyring.get_password(_SERVICE, name) or ""
    except KeyringError:
        return ""


def _migrate_plaintext(cfg: dict) -> dict:
    leaked = {k: cfg.pop(k) for k in SECRET_KEYS if k in cfg}
    if leaked:
        for k, v in leaked.items():
            _set_secret(k, v)
        _write_file(cfg)
    return cfg


def load_config() -> dict:
    cfg = _migrate_plaintext(_read_file())
    for k in SECRET_KEYS:
        secret = _get_secret(k)
        if secret:
            cfg[k] = secret
    return cfg


def save_config(updates: dict):
    updates = dict(updates)
    for k in SECRET_KEYS:
        if k in updates:
            _set_secret(k, updates.pop(k) or "")
    cfg = _migrate_plaintext(_read_file())
    cfg.update(updates)
    _write_file(cfg)
