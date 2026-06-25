"""
多提供商 LLM 抽象层
- 统一注册表：Anthropic / OpenAI / DeepSeek / OpenRouter / 智谱 / Moonshot / 通义 / Groq / 自定义
- 实时拉取模型列表（凭用户提供的 key）
- 统一 call_text / call_structured 调用入口
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

import requests


# ── 提供商注册表 ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    base_url: str           # OpenAI 兼容 base（含 /v1）
    models_path: str        # 列模型相对路径（GET）
    auth_scheme: str        # "bearer" | "x-api-key" | "key-header"
    key_placeholder: str
    default_model: str
    fallback_models: tuple  # 拉取失败时的降级列表
    docs_url: str = ""


PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider(
        id="anthropic",
        name="Anthropic Claude",
        base_url="https://api.anthropic.com/v1",
        models_path="/models",
        auth_scheme="x-api-key",
        key_placeholder="sk-ant-...",
        default_model="claude-sonnet-4-5",
        fallback_models=(
            "claude-opus-4-5",
            "claude-sonnet-4-5",
            "claude-haiku-4-5",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
        ),
        docs_url="https://console.anthropic.com/",
    ),
    "openai": Provider(
        id="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        models_path="/models",
        auth_scheme="bearer",
        key_placeholder="sk-...",
        default_model="gpt-4o",
        fallback_models=("gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1-mini"),
        docs_url="https://platform.openai.com/api-keys",
    ),
    "deepseek": Provider(
        id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        models_path="/models",
        auth_scheme="bearer",
        key_placeholder="sk-...",
        default_model="deepseek-chat",
        fallback_models=("deepseek-chat", "deepseek-reasoner"),
        docs_url="https://platform.deepseek.com/api_keys",
    ),
    "openrouter": Provider(
        id="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        models_path="/models",
        auth_scheme="bearer",
        key_placeholder="sk-or-...",
        default_model="anthropic/claude-sonnet-4-5",
        fallback_models=(
            "anthropic/claude-sonnet-4-5",
            "openai/gpt-4o",
            "google/gemini-2.0-flash-exp",
            "deepseek/deepseek-chat",
        ),
        docs_url="https://openrouter.ai/keys",
    ),
    "zhipu": Provider(
        id="zhipu",
        name="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        models_path="/models",
        auth_scheme="bearer",
        key_placeholder="xxxxxxxx.xxxxx",
        default_model="glm-4-plus",
        fallback_models=("glm-4-plus", "glm-4-air", "glm-4-flash", "glm-4v-plus"),
        docs_url="https://bigmodel.cn/usercenter/apikeys",
    ),
    "moonshot": Provider(
        id="moonshot",
        name="Moonshot Kimi",
        base_url="https://api.moonshot.cn/v1",
        models_path="/models",
        auth_scheme="bearer",
        key_placeholder="sk-...",
        default_model="moonshot-v1-32k",
        fallback_models=("moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"),
        docs_url="https://platform.moonshot.cn/console/api-keys",
    ),
    "qwen": Provider(
        id="qwen",
        name="通义千问 (DashScope)",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        models_path="/models",
        auth_scheme="bearer",
        key_placeholder="sk-...",
        default_model="qwen-max",
        fallback_models=("qwen-max", "qwen-plus", "qwen-turbo", "qwen-long"),
        docs_url="https://bailian.console.aliyun.com/?apiKey=1",
    ),
    "groq": Provider(
        id="groq",
        name="Groq",
        base_url="https://api.groq.com/openai/v1",
        models_path="/models",
        auth_scheme="bearer",
        key_placeholder="gsk_...",
        default_model="llama-3.3-70b-versatile",
        fallback_models=(
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
        ),
        docs_url="https://console.groq.com/keys",
    ),
}


def list_providers() -> list[dict]:
    """对外暴露的提供商列表（不含敏感字段）"""
    return [
        {
            "id": p.id,
            "name": p.name,
            "key_placeholder": p.key_placeholder,
            "default_model": p.default_model,
            "docs_url": p.docs_url,
            "openai_compatible": p.auth_scheme != "x-api-key",
        }
        for p in PROVIDERS.values()
    ]


def get_provider(pid: str) -> Provider:
    p = PROVIDERS.get(pid)
    if not p:
        raise ValueError(f"未知提供商: {pid}")
    return p


# ── 模型拉取 ─────────────────────────────────────────────────────────────────

def _auth_headers(p: Provider, api_key: str) -> dict:
    if p.auth_scheme == "x-api-key":
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {api_key}"}


def fetch_models(provider_id: str, api_key: str, *, timeout: int = 8) -> dict:
    """实时拉取模型列表。返回 {models, source, error}。失败时降级到 fallback。"""
    p = get_provider(provider_id)
    if not api_key:
        return {
            "models": list(p.fallback_models),
            "source": "fallback",
            "error": "未提供 API Key",
        }

    url = p.base_url + p.models_path
    try:
        resp = requests.get(url, headers=_auth_headers(p, api_key), timeout=timeout)
        if resp.status_code != 200:
            return {
                "models": list(p.fallback_models),
                "source": "fallback",
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
        data = resp.json()
        models = _parse_models(provider_id, data)
        if not models:
            return {
                "models": list(p.fallback_models),
                "source": "fallback",
                "error": "返回数据无可识别模型",
            }
        return {"models": models, "source": "live", "error": None}
    except Exception as e:
        return {
            "models": list(p.fallback_models),
            "source": "fallback",
            "error": str(e),
        }


def _parse_models(provider_id: str, data: dict) -> list[str]:
    """归一化各家 /models 返回结构 → 字符串列表"""
    items = data.get("data") or data.get("models") or []
    if not isinstance(items, list):
        return []

    out: list[str] = []
    for item in items:
        if isinstance(item, str):
            out.append(item)
            continue
        if not isinstance(item, dict):
            continue
        mid = item.get("id") or item.get("name") or item.get("model")
        if mid:
            out.append(mid)

    # 过滤明显非聊天模型（OpenAI 会返回 whisper / tts / embedding 等）
    if provider_id == "openai":
        out = [m for m in out if any(k in m for k in ("gpt", "o1", "o3", "chatgpt"))]
        out = [m for m in out if not any(k in m for k in ("audio", "realtime", "embedding", "tts", "whisper", "moderation", "image", "dall-e"))]

    # 去重保持顺序
    seen = set()
    deduped = []
    for m in out:
        if m not in seen:
            seen.add(m)
            deduped.append(m)
    return deduped


# ── 统一调用入口 ─────────────────────────────────────────────────────────────

def call_text(prompt: str, system: str, model: str,
              provider_id: str, api_key: str, max_tokens: int = 4096) -> str:
    """统一文本调用：Anthropic 走专用，其他走 OpenAI 兼容协议"""
    if provider_id == "anthropic":
        return _anthropic_text(prompt, system, model, api_key, max_tokens=max_tokens)
    return _oai_compat_text(prompt, system, model, provider_id, api_key, max_tokens=max_tokens)


def call_structured(prompt: str, system: str, schema: dict, model: str,
                    provider_id: str, api_key: str) -> dict:
    """统一结构化调用"""
    if provider_id == "anthropic":
        return _anthropic_structured(prompt, system, schema, model, api_key)
    return _oai_compat_structured(prompt, system, schema, model, provider_id, api_key)


def _anthropic_text(prompt, system, model, api_key, *, max_tokens=4096) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


def _anthropic_structured(prompt, system, schema, model, api_key) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    tool = {"name": "return_result", "description": "Return structured result", "input_schema": schema}
    resp = client.messages.create(
        model=model, max_tokens=4096, system=system,
        messages=[{"role": "user", "content": prompt}],
        tools=[tool],
        tool_choice={"type": "tool", "name": "return_result"},
    )
    for block in resp.content:
        if block.type == "tool_use":
            return block.input
    raise RuntimeError(f"Anthropic SDK: 无 tool_use, stop_reason={resp.stop_reason}")


def _oai_compat_text(prompt, system, model, provider_id, api_key, *, timeout=180, max_tokens=4096) -> str:
    p = get_provider(provider_id)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
    }
    resp = requests.post(
        p.base_url + "/chat/completions",
        headers={**_auth_headers(p, api_key), "Content-Type": "application/json"},
        json=payload, timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"{p.name} HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"{p.name} 响应格式异常: {data}") from e


def _oai_compat_structured(prompt, system, schema, model, provider_id, api_key, *, timeout=180) -> dict:
    """OpenAI 兼容协议的结构化输出 - 优先 tools，否则降级 JSON 模式"""
    p = get_provider(provider_id)
    tool = {
        "type": "function",
        "function": {
            "name": "return_result",
            "description": "Return structured result",
            "parameters": schema,
        },
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "tools": [tool],
        "tool_choice": {"type": "function", "function": {"name": "return_result"}},
        "max_tokens": 4096,
    }
    resp = requests.post(
        p.base_url + "/chat/completions",
        headers={**_auth_headers(p, api_key), "Content-Type": "application/json"},
        json=payload, timeout=timeout,
    )
    if resp.status_code != 200:
        # 兼容部分模型不支持 tools：降级 response_format=json
        return _oai_json_mode(prompt, system, schema, model, p, api_key, timeout)

    data = resp.json()
    try:
        msg = data["choices"][0]["message"]
        tool_calls = msg.get("tool_calls") or []
        if tool_calls:
            args = tool_calls[0]["function"]["arguments"]
            return json.loads(args) if isinstance(args, str) else args
        # 部分实现把结果放在 content
        if msg.get("content"):
            return json.loads(msg["content"])
    except (KeyError, json.JSONDecodeError) as e:
        raise RuntimeError(f"{p.name} 结构化解析失败: {e} | data={str(data)[:300]}") from e
    raise RuntimeError(f"{p.name} 未返回结构化结果")


def _oai_json_mode(prompt, system, schema, model, p: Provider, api_key, timeout) -> dict:
    sys_with_schema = (
        f"{system}\n\n"
        f"必须返回严格符合此 JSON Schema 的 JSON 对象（无任何额外文本）：\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_with_schema},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 4096,
    }
    resp = requests.post(
        p.base_url + "/chat/completions",
        headers={**_auth_headers(p, api_key), "Content-Type": "application/json"},
        json=payload, timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"{p.name} JSON 模式 HTTP {resp.status_code}: {resp.text[:300]}")
    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)
