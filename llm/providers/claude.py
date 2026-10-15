"""Claude（订阅）：经 claude-agent-sdk 调用本机 Claude Code，复用其登录状态。

联网用 Claude Code 内置的 WebSearch / WebFetch，结构化输出用 output_format json_schema，
推理强度与思考由 Claude Code 处理；用量取 Claude Code 上报的值。
"""
import os
import shutil
import sys
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKError, ResultMessage, query

from llm.models import ModelSpec
from llm.types import LLMError, LLMRequest, LLMResult, error_from_message

CLI_PATH_ENV = "CLAUDE_CLI_PATH"
_NPM_NATIVE_EXE = Path("node_modules/@anthropic-ai/claude-code/bin/claude.exe")


def resolve_cli_path() -> str:
    """找到可执行的 claude 原生程序。

    Windows 上 npm 安装的 claude.CMD 经 cmd.exe 转发会截断多行参数（且 SDK 拒绝执行），
    因此改找同目录 npm 包内的原生 claude.exe。
    """
    explicit = os.environ.get(CLI_PATH_ENV)
    if explicit:
        if not os.path.isfile(explicit):  # 不可达的网络盘在 3.10/3.11 上会让 Path.is_file 抛 OSError
            raise LLMError(f"{CLI_PATH_ENV} 指向的文件不存在: {explicit}")
        return explicit

    found = shutil.which("claude")
    if not found:
        raise LLMError(f"未找到 claude 可执行文件，请安装 Claude Code 或设置 {CLI_PATH_ENV}")
    if sys.platform != "win32" or found.lower().endswith(".exe"):
        return found

    native = Path(found).parent / _NPM_NATIVE_EXE
    if native.is_file():
        return str(native)
    raise LLMError(
        f"找到的是批处理包装 {found}，Windows 下无法安全传参。"
        f"请设置 {CLI_PATH_ENV} 指向原生 claude.exe"
    )


def _build_options(req: LLMRequest) -> ClaudeAgentOptions:
    tools = list(req.tools)
    return ClaudeAgentOptions(
        system_prompt=req.system,
        model=req.model,
        fallback_model=req.fallback_model,
        effort=req.effort,
        tools=tools,
        allowed_tools=tools,
        output_format={"type": "json_schema", "schema": req.schema} if req.schema else None,
        max_turns=req.max_turns,
        cwd=req.cwd,
        cli_path=resolve_cli_path(),
        setting_sources=[],  # 不加载用户/项目的 CLAUDE.md 与设置，保证研究智能体行为可复现
    )


def _to_result(msg: ResultMessage, req: LLMRequest) -> LLMResult:
    if msg.is_error or msg.subtype != "success":
        detail = "; ".join(msg.errors or []) or msg.result or ""
        raise error_from_message(f"调用失败 subtype={msg.subtype} status={msg.api_error_status} {detail}".strip())
    if msg.stop_reason == "refusal":
        raise LLMError(f"模型拒答（{req.model}）: {msg.result or ''}")
    if req.schema and msg.structured_output is None:
        raise LLMError("要求结构化输出，但结果中没有 structured_output")
    return LLMResult(
        text=msg.result or "",
        data=msg.structured_output,
        duration_ms=msg.duration_ms,
        num_turns=msg.num_turns,
        session_id=msg.session_id,
        model_usage=dict(msg.model_usage or {}),
    )


async def _collect(req: LLMRequest) -> LLMResult:
    result = None
    try:
        async for msg in query(prompt=req.prompt, options=_build_options(req)):
            if isinstance(msg, ResultMessage):
                result = msg
    except ClaudeSDKError as e:  # SDK 在错误结果后会抛 ResultError/ProcessError，统一转为 LLMError
        raise error_from_message(f"CLI 调用失败: {e}") from e
    if result is None:
        raise LLMError("CLI 未返回 result 消息")
    return _to_result(result, req)


class ClaudeAgentProvider:
    async def run(self, req: LLMRequest, spec: ModelSpec) -> LLMResult:
        return await _collect(req)
