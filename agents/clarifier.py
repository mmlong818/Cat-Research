"""
ClarifierAgent - 研究前置澄清智能体
通过多轮对话帮助用户明确研究方向、范围和重点，不使用外部工具，纯对话推理。
"""
import json

import config as _config
from llm import LLMRequest, call
from llm.profiles import Profile, default_profile


def _build_clarifier_system() -> str:
    today    = _config.CURRENT_DATE_STR
    d3m      = _config.DATE_3M_AGO_STR
    d6m      = _config.DATE_6M_AGO_STR
    return f"""你是一位顶级的研究需求分析师，负责在正式研究开始前，通过简短的对话帮助用户明确研究的真实需求。

今天是 **{today}**。系统的默认研究时间窗口为：**{d6m} 至今（近6个月）**。

## 你的目标
通过 2-4 轮对话，逐步澄清：
1. **时效性** - 用户最关心的是近期（6个月内）、还是需要扩展到更早？**默认聚焦 {d6m} 至今**
2. **技术领域的具体边界** - 哪些具体产品/技术/公司要深入？哪些只需提及？
3. **研究角度** - 技术原理？商业应用？竞争格局？政策影响？用户体验？
4. **深度 vs 广度** - 需要全面概览，还是某几个重点深挖？
5. **排除项** - 什么明确不在本次研究范围内？

## 时间窗口规则（重要）
- **默认窗口**：{d6m} 至 {today}（近6个月）
- **优先分析窗口**：{d3m} 至 {today}（近3个月）内的高质量信息优先
- **超出6个月**：如果用户的问题暗示需要更早的内容（如"历史发展""2024年以前""几年来"），\
**必须明确询问用户是否确认扩展时间范围**，不得静默扩展
- 在 summary 的 timeframe 字段中使用具体日期（如 "{d6m} 至今"），不使用模糊说法

## 对话原则
- 每次最多问 1-2 个有针对性的问题，不要罗列大量选项
- 优先识别容易遗漏的内容（如：新发布的版本、某个细分方向、特定地区市场）
- 对用户的答案给予简短确认，然后继续或总结
- 当置信度达到 0.85+ 时，主动建议确认并开始研究
- 根据 urgency（紧迫度）判断是否缩短澄清轮数：用户表达出"快点""直接开始"等信号时，urgency 升高，可提前结束澄清

## 意图类型说明
根据用户的研究问题，判断最匹配的意图类型（只选一个）：
- `info_seeking`：用户缺少某方面知识，需要综合信息汇总（广度优先）
- `problem_solving`：用户遇到具体问题或困境，需要找到解决方案（深度优先）
- `exploration`：用户想开放探索某个领域，发现新方向（发散优先）
- `optimization`：用户想对比评估多个选项，找到最优解（对比优先）
- `task_completion`：用户需要产出具体成果（报告/方案/文档等）（结构优先）

## 三个关键维度（0.0-1.0评分）
- **urgency（紧迫度）**：0=纯探索性，无时间压力；1=现在就需要结果
- **specificity（具体度）**：0=开放宽泛，边界模糊；1=目标明确，范围精确
- **complexity（复杂度）**：0=单一简单问题；1=多维度深度研究

注意：首次回复时 summary 是基于问题的初步猜测，后续随对话更新。confidence 表示你对研究需求理解的完整度（0-1）。
timeframe 使用具体日期（如：{d6m} 至今）。"""


CLARIFIER_SYSTEM = _build_clarifier_system()


INTENT_TYPES = ["info_seeking", "problem_solving", "exploration", "optimization", "task_completion"]

CLARIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "summary": {
            "type": "object",
            "properties": {
                "objective": {"type": "string"},
                "scope": {"type": "string"},
                "key_aspects": {"type": "array", "items": {"type": "string"}},
                "timeframe": {"type": "string"},
                "depth": {"type": "string"},
                "angle": {"type": "string"},
                "exclude": {"type": "string"},
                "search_hints": {"type": "array", "items": {"type": "string"}},
                "intent_type": {"type": "string", "enum": INTENT_TYPES},
                "dimensions": {
                    "type": "object",
                    "properties": {k: {"type": "number"} for k in ("urgency", "specificity", "complexity")},
                    "required": ["urgency", "specificity", "complexity"],
                    "additionalProperties": False,
                },
            },
            "required": ["objective", "scope", "key_aspects", "timeframe", "depth", "angle",
                         "exclude", "search_hints", "intent_type", "dimensions"],
            "additionalProperties": False,
        },
        "ready": {"type": "boolean"},
        "confidence": {"type": "number"},
    },
    "required": ["message", "summary", "ready", "confidence"],
    "additionalProperties": False,
}


class ClarifierAgent:
    """研究前置澄清智能体（纯对话，无工具调用）；调用失败抛 LLMError。
    用所给配置档的核心模型；不传则取默认配置档（设置页保存的）。"""

    def __init__(self, profile: Profile | None = None):
        self.model = (profile or default_profile()).core

    def _call(self, messages: list) -> dict:
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        history = []
        for m in messages:
            if m["role"] == "user":
                history.append(f"用户：{m['content']}")
            elif m["role"] == "assistant":
                history.append(f"助手（历史回复）：{m['content']}")
        result = call(LLMRequest(prompt="\n\n".join(history), system=system,
                                 model=self.model, effort="low",
                                 schema=CLARIFY_SCHEMA, max_turns=3))
        return result.data

    def start(self, question: str) -> dict:
        """启动澄清会话，返回第一条 AI 消息 + 初步摘要"""
        messages = [
            {"role": "system", "content": CLARIFIER_SYSTEM},
            {"role": "user", "content": f"我想研究：{question}"}
        ]
        result = self._call(messages)
        result["history"] = [
            {"role": "user", "content": f"我想研究：{question}"},
            {"role": "assistant", "content": json.dumps(result.get("summary", {}), ensure_ascii=False)}
        ]
        return result

    def reply(self, history: list, user_message: str) -> dict:
        """处理用户回复，返回下一条 AI 消息 + 更新摘要"""
        messages = [{"role": "system", "content": CLARIFIER_SYSTEM}] + history + [
            {"role": "user", "content": user_message}
        ]
        result = self._call(messages)
        new_history = history + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": json.dumps(result.get("summary", {}), ensure_ascii=False)}
        ]
        result["history"] = new_history
        return result


def summary_to_brief(summary: dict, extra_note: str | None = "", goal: str | None = None) -> tuple:
    """把澄清摘要转成 (补充说明文本, intent_meta)，供 orchestrator.run 使用（API 与 CLI 共用）。
    goal 为用户在委托台确认的研究目标，写在第一行。"""
    s = summary or {}
    parts = []
    if goal:
        parts.append(f"研究目标：{goal}")
    if s.get("scope"):
        parts.append(f"研究范围：{s['scope']}")
    if s.get("key_aspects"):
        parts.append(f"重点方面：{'、'.join(s['key_aspects'])}")
    if s.get("timeframe"):
        parts.append(f"时间范围：{s['timeframe']}")
    if s.get("depth"):
        parts.append(f"研究深度：{s['depth']}")
    if s.get("angle"):
        parts.append(f"研究角度：{s['angle']}")
    if s.get("exclude"):
        parts.append(f"排除内容：{s['exclude']}")
    if s.get("search_hints"):
        parts.append(f"关键搜索词：{', '.join(s['search_hints'])}")
    if extra_note:
        parts.append(f"用户补充：{extra_note}")
    intent_meta = {
        "intent_type": s.get("intent_type", "info_seeking"),
        "dimensions": s.get("dimensions", {"urgency": 0.5, "specificity": 0.5, "complexity": 0.5}),
    }
    return "\n".join(parts), intent_meta
