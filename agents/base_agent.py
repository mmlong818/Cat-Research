"""
BaseAgent - 所有研究智能体的基类
实现工具调用循环和文件通信机制
使用 OpenAI 兼容接口对接智谱 GLM 模型
"""
import json
import sys
import time
from typing import Optional
from openai import OpenAI
import config as _config
from config import (MAX_AGENT_TURNS, SHOW_AGENT_THOUGHTS,
                    COMPRESS_THRESHOLD_CHARS, COMPRESS_KEEP_RECENT)
from tools.web_search import web_search, web_fetch
from tools.file_tools import read_file, write_file, list_files
from tools.domain_checker import check_domain_authority
from tools.fact_tools import cross_reference_search_tool


class BaseAgent:
    """
    多Agent研究系统的基础智能体
    - 自动处理工具调用循环
    - 通过文件进行智能体间通信
    - 内置网络搜索、网页抓取、文件读写能力
    """

    def __init__(self, name: str, system_prompt: str, model: str = None):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model or _config.ORCHESTRATOR_MODEL
        # 每次实例化时从 config 读取最新值（运行时更新后立即生效）
        self.client = OpenAI(api_key=_config.API_KEY, base_url=_config.API_BASE_URL)
        self.tools = self._define_tools()
        self._tool_call_count = 0
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self.stream_callback = None  # 由 orchestrator 注入，用于流式输出
        self.stop_event = None       # 由 orchestrator 注入，set() 时立即停止

    def _use_builtin_web_search(self) -> bool:
        return "bigmodel" in _config.API_BASE_URL

    def _define_tools(self) -> list:
        """定义智能体可用的工具集（OpenAI 格式）"""
        tool_defs = [
            {
                "name": "web_search",
                "description": (
                    "搜索网络信息并返回结果摘要。"
                    "用于查找相关新闻、背景资料和公开来源。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索查询词"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "最多返回结果数，默认 8"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "web_fetch",
                "description": (
                    "获取指定 URL 网页的文本内容。"
                    "在搜索结果中找到有价值的链接后，用此工具获取详细内容。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "要获取内容的完整 URL"
                        }
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "read_file",
                "description": (
                    "读取工作空间中的文件内容。"
                    "用于读取其他智能体生成的结果、计划或草稿。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "要读取的文件的完整路径"
                        }
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "write_file",
                "description": (
                    "将内容写入工作空间中的文件。"
                    "用于保存研究结果、分析报告和文档草稿。"
                    "会自动创建所需的目录。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "要写入的文件的完整路径"
                        },
                        "content": {
                            "type": "string",
                            "description": "要写入的文件内容"
                        }
                    },
                    "required": ["path", "content"]
                }
            },
            {
                "name": "list_files",
                "description": "列出指定目录中的文件和子目录。用于了解工作空间的当前状态。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "directory": {
                            "type": "string",
                            "description": "要列出的目录路径"
                        }
                    },
                    "required": ["directory"]
                }
            },
            {
                "name": "check_domain_authority",
                "description": (
                    "评估指定 URL 的域名权威性和可信度。"
                    "返回域名评级（Tier 1-4）、置信度（high/medium/low）和综合评分（0-100）。"
                    "用于验证信息来源的可靠性，在引用来源前使用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "要评估的完整 URL"
                        }
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "cross_reference_search",
                "description": (
                    "对特定声明或事实进行多角度交叉验证搜索。"
                    "生成多个不同视角的搜索查询，将结果分类为支持/反驳/中立，"
                    "并给出核查结论（supported/disputed/unverifiable/insufficient）和置信度。"
                    "用于验证重要声明的准确性。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "claim": {
                            "type": "string",
                            "description": "需要验证的声明或事实陈述"
                        },
                        "context": {
                            "type": "string",
                            "description": "声明的背景上下文（可选）"
                        },
                        "max_queries": {
                            "type": "integer",
                            "description": "最多使用几个查询进行验证（默认3，最多5）"
                        }
                    },
                    "required": ["claim"]
                }
            }
        ]
        if self._use_builtin_web_search():
            builtin_web_search = {
                "type": "web_search",
                "web_search": {
                    "enable": True,
                    "search_result": True
                }
            }
            function_tools = [d for d in tool_defs if d["name"] != "web_search"]
            return [builtin_web_search] + [{"type": "function", "function": d} for d in function_tools]

        return [{"type": "function", "function": d} for d in tool_defs]

    def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """执行工具调用并返回结果"""
        self._tool_call_count += 1
        try:
            if tool_name == "web_search":
                return web_search(
                    tool_input["query"],
                    tool_input.get("max_results", 8)
                )
            elif tool_name == "web_fetch":
                return web_fetch(tool_input["url"])
            elif tool_name == "read_file":
                return read_file(tool_input["path"])
            elif tool_name == "write_file":
                return write_file(tool_input["path"], tool_input["content"])
            elif tool_name == "list_files":
                return list_files(tool_input["directory"])
            elif tool_name == "check_domain_authority":
                return check_domain_authority(tool_input["url"])
            elif tool_name == "cross_reference_search":
                return cross_reference_search_tool(
                    tool_input["claim"],
                    tool_input.get("context", ""),
                    tool_input.get("max_queries", 3)
                )
            else:
                return f"[错误] 未知工具: {tool_name}"
        except Exception as e:
            return f"[工具执行错误] {tool_name}: {str(e)}"

    def _print_progress(self, message: str):
        """打印进度信息，并向前端推送工具调用事件"""
        if SHOW_AGENT_THOUGHTS:
            print(f"  [{self.name}] {message}", flush=True)
        if self.stream_callback:
            try:
                self.stream_callback("tool_call", {"agent": self.name, "message": message})
            except Exception:
                pass

    def _compress_context(self, messages: list) -> list:
        """
        上下文压缩：当 messages 总字符数超过阈值时，将旧消息压缩为摘要。
        始终保留 messages[0]（系统提示）和 messages[1]（原始任务）。
        返回压缩后的 messages 列表（失败时返回原始列表）。
        """
        total_chars = sum(len(str(m)) for m in messages)
        if total_chars <= COMPRESS_THRESHOLD_CHARS:
            return messages

        # 至少需要 system + task + COMPRESS_KEEP_RECENT 条才能压缩
        if len(messages) <= 2 + COMPRESS_KEEP_RECENT:
            return messages

        original_count = len(messages)
        system_msg = messages[0]
        task_msg = messages[1]
        # 待压缩部分（排除 system、task 和最近 N 条）
        to_compress = messages[2: len(messages) - COMPRESS_KEEP_RECENT]
        recent_msgs = messages[len(messages) - COMPRESS_KEEP_RECENT:]

        # 构建摘要 prompt
        history_text = ""
        for m in to_compress:
            role = m.get("role", "unknown")
            content = m.get("content", "")
            if not content and m.get("tool_calls"):
                content = f"[工具调用: {[tc.get('function', {}).get('name', '') for tc in m['tool_calls']]}]"
            history_text += f"\n[{role}]: {str(content)[:2000]}\n"

        summary_prompt = (
            "你是一个上下文压缩助手。请将以下对话历史压缩为简洁的结构化摘要，保留所有关键信息。\n\n"
            f"【对话历史】\n{history_text}\n\n"
            "请输出：\n"
            "1. 【已完成的操作】已执行的工具调用和结果要点（按时间顺序）\n"
            "2. 【收集到的数据】重要数据、事实、引用、URL、文件内容摘要\n"
            "3. 【当前进度】任务执行到哪个阶段，已写入哪些文件\n"
            "4. 【关键结论】到目前为止得出的重要结论或发现\n\n"
            "保持摘要精炼，聚焦信息价值。"
        )

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": summary_prompt}],
                max_tokens=2000,
                temperature=0.1,
                stream=False
            )
            summary = ""
            if resp.choices:
                summary = resp.choices[0].message.content or ""

            if not summary:
                return messages

            new_messages = [
                system_msg,
                task_msg,
                {"role": "user", "content": f"[历史上下文摘要 - 已压缩]\n\n{summary}"},
                {"role": "assistant", "content": "收到历史摘要，我将基于此继续执行任务。"},
            ] + recent_msgs

            new_count = len(new_messages)
            self._print_progress(
                f"🗜️ 上下文已压缩（{original_count}→{new_count} 条消息）"
            )
            return new_messages

        except Exception as e:
            # 压缩失败时静默跳过
            print(f"  [{self.name}] 上下文压缩失败（已跳过）: {type(e).__name__}", flush=True)
            return messages

    def run(self, task: str, max_turns: int = MAX_AGENT_TURNS) -> str:
        """
        运行智能体执行任务（OpenAI 兼容接口，支持流式输出）
        """
        print(f"\n{'─'*70}", flush=True)
        print(f"🤖 智能体 [{self.name}] 开始工作...", flush=True)

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task}
        ]
        self._tool_call_count = 0

        for turn in range(max_turns):
            # 每轮开始前检查停止信号
            if self.stop_event and self.stop_event.is_set():
                print(f"  [{self.name}] 收到停止信号，中断执行", flush=True)
                return f"[已停止] 智能体 [{self.name}] 收到停止指令"

            # 每轮 LLM 调用前触发上下文压缩检查
            messages = self._compress_context(messages)

            response = None
            for attempt in range(4):
                try:
                    # 通知前端新一轮 LLM 调用开始
                    if self.stream_callback:
                        try:
                            self.stream_callback("agent_thinking", {
                                "agent": self.name,
                                "turn": turn + 1
                            })
                        except Exception:
                            pass

                    # 流式调用（启用深度思考，优化 research 参数）
                    stream = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        tools=self.tools,
                        tool_choice="auto",
                        max_tokens=16384,
                        temperature=0.3,     # 研究场景需要低温度保证准确性
                        top_p=0.85,
                        stream=True,
                        extra_body={"thinking": {"type": "enabled"}}
                    )

                    # 收集流式输出
                    full_content = ""
                    full_reasoning = ""   # 深度思考内容
                    tool_calls_map = {}   # index → {id, name, arguments}
                    turn_input_tokens = 0
                    turn_output_tokens = 0

                    for chunk in stream:
                        # 捕获 usage（通常在最后一个 chunk）
                        usage = getattr(chunk, "usage", None)
                        if usage:
                            turn_input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                            turn_output_tokens = getattr(usage, "completion_tokens", 0) or 0

                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta

                        # 深度思考 token（reasoning_content）
                        reasoning = getattr(delta, "reasoning_content", None)
                        if reasoning:
                            full_reasoning += reasoning
                            if self.stream_callback:
                                try:
                                    self.stream_callback("text_delta", {
                                        "agent": self.name,
                                        "text": reasoning,
                                        "is_thinking": True
                                    })
                                except Exception:
                                    pass

                        # 正文文本 delta
                        if delta.content:
                            full_content += delta.content
                            if self.stream_callback:
                                try:
                                    self.stream_callback("text_delta", {
                                        "agent": self.name,
                                        "text": delta.content
                                    })
                                except Exception:
                                    pass

                        # 工具调用 delta（分片累积）
                        if delta.tool_calls:
                            for tc in delta.tool_calls:
                                idx = tc.index
                                if idx not in tool_calls_map:
                                    tool_calls_map[idx] = {
                                        "id": tc.id or "",
                                        "name": "",
                                        "arguments": "",
                                        "type": "function"
                                    }
                                if tc.id:
                                    tool_calls_map[idx]["id"] = tc.id
                                if hasattr(tc, "type") and tc.type:
                                    tool_calls_map[idx]["type"] = tc.type
                                if tc.function:
                                    if tc.function.name:
                                        tool_calls_map[idx]["name"] += tc.function.name
                                    if tc.function.arguments:
                                        tool_calls_map[idx]["arguments"] += tc.function.arguments

                        finish_reason = chunk.choices[0].finish_reason
                        if finish_reason in ("stop", "tool_calls", "end"):
                            break

                    response = {
                        "content": full_content,
                        "tool_calls": list(tool_calls_map.values()) if tool_calls_map else []
                    }

                    # 累计 token 并推送统计事件
                    if turn_input_tokens or turn_output_tokens:
                        self._total_input_tokens += turn_input_tokens
                        self._total_output_tokens += turn_output_tokens
                        if self.stream_callback:
                            try:
                                self.stream_callback("token_usage", {
                                    "agent": self.name,
                                    "model": self.model,
                                    "turn_input": turn_input_tokens,
                                    "turn_output": turn_output_tokens,
                                    "total_input": self._total_input_tokens,
                                    "total_output": self._total_output_tokens,
                                })
                            except Exception:
                                pass

                    break  # 成功

                except Exception as e:
                    err = str(e)
                    if "rate" in err.lower() or "429" in err:
                        wait = 30 * (attempt + 1)
                        print(f"  [警告] API 限速，等待 {wait}s（第 {attempt+1}/3 次）...", flush=True)
                        time.sleep(wait)
                    elif attempt < 3:
                        wait = 5 * (2 ** attempt)
                        print(f"  [警告] API 调用出错（{type(e).__name__}），{wait}s 后重试...", flush=True)
                        time.sleep(wait)
                    else:
                        print(f"  [错误] API 调用失败: {err}", flush=True)
                        return f"智能体 [{self.name}] 遇到错误: {err}"

            if response is None:
                return f"智能体 [{self.name}] 所有重试均失败"

            tool_calls = response["tool_calls"]
            content = response["content"]

            # 无工具调用 → 任务完成
            if not tool_calls:
                print(f"✅ 智能体 [{self.name}] 完成（共调用工具 {self._tool_call_count} 次，"
                      f"思考 {len(full_reasoning)} 字符）", flush=True)
                return content or full_reasoning

            # 将助手回复（含工具调用）加入消息历史
            # 必须保留 reasoning_content，否则 interleaved thinking 链断裂
            assistant_msg = {
                "role": "assistant",
                "content": content or None,
                "tool_calls": []
            }
            if full_reasoning:
                assistant_msg["reasoning_content"] = full_reasoning
            for tc in tool_calls:
                assistant_msg["tool_calls"].append({
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]}
                })
            messages.append(assistant_msg)

            # 执行每个工具并将结果追加
            for tc in tool_calls:
                name = tc["name"]

                # 智谱内置 web_search：搜索结果已由后端自动注入，无需我们执行
                if tc.get("type") == "web_search" or (
                    name == "web_search" and self._use_builtin_web_search()
                ):
                    try:
                        args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    except Exception:
                        args = {}
                    query = args.get("query", "搜索中")
                    self._print_progress(f"[内置搜索] {query[:60]}")
                    # 回传空确认，让模型继续（搜索结果已在模型上下文中）
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": "已完成网页搜索，结果已整合到上下文中。"
                    })
                    continue

                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}

                # 显示自定义工具进度（执行前）
                if name == "web_fetch":
                    self._print_progress(f"🌐 抓取页面: {args.get('url', '')[:70]}")
                elif name == "write_file":
                    self._print_progress(f"💾 写入文件: {args.get('path', '').split('/')[-1]}")
                elif name == "read_file":
                    self._print_progress(f"📖 读取文件: {args.get('path', '').split('/')[-1]}")
                elif name == "check_domain_authority":
                    self._print_progress(f"🔍 评估来源可信度: {args.get('url', '')[:60]}")
                elif name == "cross_reference_search":
                    self._print_progress(f"✅ 交叉核查: {args.get('claim', '')[:60]}")

                result = self._execute_tool(name, args)

                # 工具执行完毕后推送结果摘要
                if name == "web_fetch":
                    chars = len(result) if result else 0
                    self._print_progress(f"✔ 页面内容获取完成（{chars} 字符）")
                elif name == "write_file":
                    self._print_progress(f"✔ 文件写入完成")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result
                })

        print(f"⚠️  智能体 [{self.name}] 达到最大轮数限制", flush=True)
        return f"智能体 [{self.name}] 达到最大轮数限制（{max_turns} 轮）"
