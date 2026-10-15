"""各提供方 API Key：优先取设置页存入系统凭据库的值（api.config_store），环境变量兜底。

任何错误信息都只提字段名与环境变量名，不包含 key 本身。
"""
import os

from llm.types import LLMConfigError

_KEYS = {
    "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY", "Anthropic"),
    "openai": ("openai_api_key", "OPENAI_API_KEY", "OpenAI"),
    "zhipu": ("zhipu_api_key", "ZHIPU_API_KEY", "智谱"),
    "compat": ("compat_api_key", "COMPAT_API_KEY", "OpenAI 兼容端点"),
    "bocha": ("bocha_api_key", "BOCHA_API_KEY", "博查搜索"),
    "tavily": ("tavily_api_key", "TAVILY_API_KEY", "Tavily 搜索"),
}


def stored_config() -> dict:
    from api.config_store import load_config  # 延迟导入：llm 层不在导入期依赖 api 包
    return load_config()


# 配置档的提供方 -> 上面的密钥名
PROVIDER_KEY = {"claude": "anthropic", "openai": "openai", "zhipu": "zhipu", "compat": "compat"}
CLIENT_TOOLS_PROVIDERS = ("zhipu", "compat")  # web="client_tools"：WebSearch 用所选搜索后端


def _section(cfg: dict, name: str) -> dict:
    value = cfg.get(name)
    return value if isinstance(value, dict) else {}


def selected_search_backend(stored: dict | None = None) -> str:
    """联网搜索后端：user_config 的 search.backend，环境变量 SEARCH_BACKEND 兜底，默认 zhipu。"""
    cfg = stored if stored is not None else stored_config()
    return str(_section(cfg, "search").get("backend") or os.environ.get("SEARCH_BACKEND", "") or "zhipu").strip()


def compat_settings(stored: dict | None = None) -> dict:
    """OpenAI 兼容端点的非密钥设置：base_url（环境变量 COMPAT_BASE_URL 兜底）与带 compat: 前缀的核心/辅助模型。"""
    section = _section(stored if stored is not None else stored_config(), "compat")
    base_url = section.get("base_url") or os.environ.get("COMPAT_BASE_URL", "")
    return {"base_url": str(base_url).strip(), "core": section.get("core") or "",
            "support": section.get("support") or ""}


def get_key(provider: str) -> str:
    field, env, _ = _KEYS[provider]
    return stored_config().get(field) or os.environ.get(env, "")


def key_status(name: str, stored: dict | None = None) -> tuple[str, str]:
    """(key, 来源)：来源为 keyring（设置页存入）、env（环境变量）或空串（未配置）。stored 省略时现读。"""
    field, env, _ = _KEYS[name]
    stored_key = (stored if stored is not None else stored_config()).get(field)
    if stored_key:
        return stored_key, "keyring"
    env_key = os.environ.get(env, "")
    return env_key, "env" if env_key else ""


def missing_key_label(provider: str, stored: dict | None = None) -> str | None:
    """配置档的提供方必须有 key 却没配置时返回其显示名；Claude 走订阅（可选 Anthropic key），不要求 key。
    stored 为"假设的已存配置"（设置页提交时用来预判），省略时取当前的。"""
    name = PROVIDER_KEY.get(provider)
    if provider == "claude" or name is None or key_status(name, stored)[0]:
        return None
    return _KEYS[name][2]


def missing_requirements(provider: str, stored: dict | None = None) -> list[str]:
    """启动研究前缺的配置项（中文短语，可直接拼进"请先在设置中填写 …"）：提供方自己的 key；
    兼容端点还要 Base URL；凡 client_tools 提供方还要所选搜索后端的 key（与提供方 key 相同时不重复）。
    核心/辅助模型由 make_profile 校验。"""
    from llm.search import BACKENDS  # 延迟导入：llm.search 依赖本模块
    cfg = stored if stored is not None else stored_config()
    items = []
    if provider == "compat" and not compat_settings(cfg)["base_url"]:
        items.append("OpenAI 兼容端点 的 Base URL")
    label = missing_key_label(provider, cfg)
    if label:
        items.append(f"{label} 的 API Key")
    if provider in CLIENT_TOOLS_PROVIDERS:
        backend = selected_search_backend(cfg)
        if backend not in BACKENDS:
            items.append(f"有效的联网搜索后端（当前 {backend!r}，可选：{', '.join(BACKENDS)}）")
        elif backend != PROVIDER_KEY[provider] and not key_status(backend, cfg)[0]:
            items.append(f"{BACKENDS[backend].label} 的 API Key")
    return items


def require_key(provider: str) -> str:
    key = get_key(provider)
    if not key:
        field, env, label = _KEYS[provider]
        raise LLMConfigError(f"未配置{label} API Key：请到设置页填写（{field}），或设置环境变量 {env}")
    return key


def redact(text: str, key: str) -> str:
    """去掉错误信息里可能回显的 key（含常见的前后片段）。"""
    if not key:
        return text
    for part in (key, key[:8], key[-6:]):
        if len(part) >= 6:
            text = text.replace(part, "***")
    return text
