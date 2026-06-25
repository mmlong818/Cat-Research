"""
统一 LLM 调用层 - 多提供商分发
- 有 API key：走对应 provider 的 SDK / OpenAI 兼容接口
- 无 API key：降级到 Claude CLI（仅当激活 provider 是 anthropic 时）
"""
import json
import os
import shutil
import subprocess

from api import providers
from api.config_store import get_active_provider_key, load_config

_CLAUDE_EXE = shutil.which("claude") or "claude"
_HOME = os.path.expanduser("~")


def get_api_key() -> str:
    """向后兼容：返回当前激活 provider 的 key"""
    _, key, _ = get_active_provider_key()
    return key


def get_model(default: str = "claude-sonnet-4-5") -> str:
    _, _, model = get_active_provider_key()
    return model or os.getenv("CORE_MODEL") or default


def get_active() -> tuple[str, str, str]:
    return get_active_provider_key()


def call_structured(prompt: str, system: str, schema: dict, model: str | None = None) -> dict:
    pid, key, default_model = get_active_provider_key()
    use_model = model or default_model
    if key:
        return providers.call_structured(prompt, system, schema, use_model, pid, key)
    if pid == "anthropic":
        return _cli_structured(prompt, system, schema, use_model)
    raise RuntimeError(
        f"提供商 [{pid}] 缺少 API Key。请在「设置」中填入 Key 后重试。"
    )


def call_text(prompt: str, system: str, model: str | None = None,
              max_tokens: int = 4096) -> str:
    pid, key, default_model = get_active_provider_key()
    use_model = model or default_model
    if key:
        return providers.call_text(prompt, system, use_model, pid, key, max_tokens=max_tokens)
    if pid == "anthropic":
        return _cli_text(prompt, system, use_model)
    raise RuntimeError(
        f"提供商 [{pid}] 缺少 API Key。请在「设置」中填入 Key 后重试。"
    )


# ── Claude CLI 降级（仅 anthropic 无 key 时使用） ────────────────────────────

def _cli_structured(prompt: str, system: str, schema: dict, model: str) -> dict:
    cmd = [
        _CLAUDE_EXE, "--output-format", "json", "--model", model,
        "--max-turns", "5", "--dangerously-skip-permissions",
        "--system-prompt", system, "--json-schema", json.dumps(schema),
    ]
    result = subprocess.run(
        cmd, input=prompt.encode("utf-8"),
        capture_output=True, timeout=180, cwd=_HOME,
    )
    stdout = (result.stdout or b"").decode("utf-8", errors="replace").strip()
    stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
    if not stdout:
        raise RuntimeError(f"CLI 空输出 rc={result.returncode} stderr={stderr[:400]}")
    try:
        wrapper = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JSON 解析失败: {e} | stdout={stdout[:300]!r}")
    so = wrapper.get("structured_output")
    if not so:
        raise RuntimeError(
            f"无 structured_output subtype={wrapper.get('subtype')} "
            f"result={str(wrapper.get('result', ''))[:200]}"
        )
    return so


def _cli_text(prompt: str, system: str, model: str) -> str:
    cmd = [
        _CLAUDE_EXE, "--output-format", "text", "--model", model,
        "--max-turns", "5", "--dangerously-skip-permissions",
        "--system-prompt", system,
    ]
    result = subprocess.run(
        cmd, input=prompt.encode("utf-8"),
        capture_output=True, timeout=180, cwd=_HOME,
    )
    stdout = (result.stdout or b"").decode("utf-8", errors="replace").strip()
    if not stdout:
        stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"CLI 空输出 rc={result.returncode} stderr={stderr[:300]}")
    return stdout
