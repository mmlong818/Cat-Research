"""
LLMAgent - 研究智能体基类（基于 llm 调用层）

输入内容由调用方内联进 prompt，不再让模型自己读写文件；
ask() 取 schema 校验过的 JSON，ask_text() 取 Markdown 正文，均由 Python 原子写入 output_file。
调用失败（含 llm 层重试后）抛 LLMError，不返回兜底值。
"""
import json
import os
from collections.abc import Callable, Sequence
from typing import Any

from llm import LLMError, LLMRequest, LLMResult, call
from llm.client import EffortLevel
from tools.file_tools import ensure_parent_dir


class ResearchStopped(LLMError):
    """用户请求停止（不是调用失败，调用方不应当作可降级的错误吞掉）"""


def write_json_atomic(path: str, data) -> None:
    _write_atomic(path, json.dumps(data, ensure_ascii=False, indent=2))


def write_text_atomic(path: str, text: str) -> None:
    _write_atomic(path, text)


def _write_atomic(path: str, content: str) -> None:
    ensure_parent_dir(path)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)


def read_text(path: str | None) -> str:
    if not path or not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_dir_markdown(directory: str) -> str:
    """按文件名顺序拼接目录下所有 .md 文件，带文件名标题。"""
    if not os.path.isdir(directory):
        return ""
    parts = [f"### {name}\n\n{read_text(os.path.join(directory, name))}"
             for name in sorted(os.listdir(directory)) if name.endswith(".md")]
    return "\n\n".join(parts)


class LLMAgent:
    def __init__(self, name: str, system_prompt: str, model: str, schema: dict | None = None,
                 tools: Sequence[str] = (), effort: EffortLevel = "medium", max_turns: int = 20):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        self.schema = schema
        self.tools = tuple(tools)
        self.effort = effort
        self.max_turns = max_turns
        self.stream_callback: Callable[[str, dict], Any] | None = None  # 由 orchestrator 注入
        self.stop_event = None       # 由 orchestrator 注入
        self.directives: Callable[[], str] | None = None  # 由 orchestrator 注入：返回「用户补充要求」小节，没有时为空串

    def request(self, prompt: str, schema: dict | None = None,
                tools: Sequence[str] | None = None) -> LLMRequest:
        """构造请求；注入了 directives 时在提示词末尾追加用户补充要求（没有补充要求时提示词不变）。"""
        if self.directives:
            prompt += self.directives()
        return LLMRequest(prompt=prompt, system=self.system_prompt, model=self.model,
                          effort=self.effort, schema=schema,
                          tools=self.tools if tools is None else tuple(tools),
                          max_turns=self.max_turns)

    def ask(self, prompt: str, output_file: str,
            finalize: Callable[[dict], dict] | None = None) -> dict:
        """取结构化结果，经 finalize 补充确定性字段后落盘。"""
        result = self._invoke(self.request(prompt, schema=self.schema))
        data = finalize(result.data) if finalize else result.data
        write_json_atomic(output_file, data)
        return data

    def ask_text(self, prompt: str, output_file: str) -> str:
        """取 Markdown 正文落盘；空结果视为失败。"""
        result = self._invoke(self.request(prompt))
        if not result.text.strip():
            raise LLMError(f"[{self.name}] 返回内容为空")
        write_text_atomic(output_file, result.text)
        return result.text

    def _invoke(self, req: LLMRequest) -> LLMResult:
        self.check_stop()
        print(f"\n{'─'*70}\n🤖 智能体 [{self.name}] 开始工作（{self.model}）...", flush=True)
        self.emit("agent_thinking", {"turn": 1})
        result = call(req)
        self.report_usage(result)
        return result

    def check_stop(self):
        if self.stop_event and self.stop_event.is_set():
            raise ResearchStopped(f"[{self.name}] 收到停止指令")

    def emit(self, event: str, data: dict):
        if self.stream_callback:
            self.stream_callback(event, {"agent": self.name, **data})

    def report_usage(self, result: LLMResult, label: str = ""):
        """total_input 含缓存命中与缓存写入的输入，cached_input 单独记缓存命中；按本次调用涉及的所有模型累加。"""
        usages = result.model_usage.values()
        cached = sum(u.get("cacheReadInputTokens", 0) for u in usages)
        total_input = sum(u.get("inputTokens", 0) + u.get("cacheCreationInputTokens", 0) for u in usages) + cached
        print(f"✅ 智能体 [{self.name}]{label} 完成（{result.num_turns} 轮，"
              f"{result.duration_ms / 1000:.0f}s）", flush=True)
        self.emit("token_usage", {
            "model": self.model,
            "total_input": total_input,
            "cached_input": cached,
            "total_output": sum(u.get("outputTokens", 0) for u in usages),
        })
