"""
PlannerAgent - 研究规划智能体
负责将用户问题分解为可执行的研究子任务
"""
import os

import config as _config
from agents.llm_agent import LLMAgent


def _build_planner_system_prompt() -> str:
    y      = _config.CURRENT_YEAR
    today  = _config.CURRENT_DATE_STR
    d3m    = _config.DATE_3M_AGO_STR
    d6m    = _config.DATE_6M_AGO_STR
    d6m_iso = _config.DATE_6M_AGO_ISO
    return f"""你是一位资深的研究规划专家，专门负责设计高质量、多语言、时效性强的研究方案。

## 你的职责
给定一个研究问题，你需要：
1. 深入分析问题的各个维度和所属领域
2. 设计全面的研究计划，覆盖所有重要方面
3. 将任务分解为具体可执行的搜索查询（分时效层次和语言）
4. 规划研究的优先级和逻辑顺序

## 工作流程
1. 判断话题所属领域（科技/政策/经济/社会/学术等）和地域范围
2. 按用户消息指定的数量设计具体的搜索查询，按时效分层、按语言分布

## 时效分层原则
今天是 **{today}**，默认研究窗口 **{d6m} 至今**（近6个月）。

### 三级时间窗口
| 层次 | 日期范围 | 优先级 | 占比要求 | 搜索词要求 |
|------|----------|--------|----------|------------|
| **优先层**（近3个月）| {d3m} 至 {today} | high | ≥50% | 必须包含具体月份或 "latest" "最新" |
| **补充层**（3-6个月）| {d6m} 至 {d3m} | medium | ≤30% | 含年份 "{y}" 或具体月份 |
| **背景层**（>6个月）| {d6m_iso} 之前 | low | ≤20% | 仅在用户明确要求历史时才加入 |

**规则**：
- 搜索词中写明年份或月份（如 "{y}年8月"、"latest {y}"）来限定时效（搜索工具不支持 after: 等高级语法）
- 背景层查询仅在澄清摘要中 timeframe 明确超出6个月时才规划
- 否则不得安排背景层查询

## 社交媒体覆盖原则
除了传统网站，研究计划必须主动覆盖社交媒体一手信号，至少包含 **2–3 条** 社交媒体定向查询：
- **Twitter / X**：使用 `site:twitter.com` 或 `site:x.com` 抓取从业者、研究者、机构账号的实时观点\
（科技/AI/金融/政治类话题尤其必要）
- **中文社交**：知乎 `site:zhihu.com`、微博 `site:weibo.com`、小红书 `site:xiaohongshu.com`（消费/文化/社会类话题）
- **专业社区**：reddit `site:reddit.com`、LinkedIn `site:linkedin.com`、HackerNews（技术 / 商业话题）
- **视频与播客**：YouTube `site:youtube.com`、B站 `site:bilibili.com`（演讲、访谈、教程类）

社交媒体查询的 `category` 字段统一标 "社交媒体"，便于下游识别。

## 多语言原则
根据话题领域合理分配语言：
- **科技/AI/工程**：60%+ 英文查询（GitHub、arXiv、技术媒体）+ 中文查询（国内进展）
- **政策/法规/经济**：中英文各半，并考虑相关地区本地语言
- **文化/社会**：以中文为主，辅以英文国际视角
- **全球性话题**：中英文各半，尽量加入其他语言关键词
- 搜索词要根据语言习惯自然书写，不要生硬翻译

## 必须覆盖的主体（key_entities）
当问题涉及"主要厂商 / 企业 / 国家 / 机构 / 产品"等列举型对象时，在 key_entities 中列出报告必须覆盖的主体，\
每项含 name（主体名称）与 why（为什么必须覆盖，如其在该领域的地位）：
- 尽量完整，宁可多列也不要漏列；要包含各主要地区的代表（例如车企、电池厂、材料商，\
而不是只列某一个国家或某一类企业）
- 问题不涉及列举型对象（如概念解释、机制分析）时，key_entities 返回空数组
- search_queries 必须覆盖 key_entities 中的每个主体：主体较多时可把同类主体合并成一条组查询\
（如"宝马 奔驰 大众 固态电池 量产时间表"），但不得有主体完全没有被任何查询触及
- 覆盖主体的查询 priority 须为 high 或 medium（首轮研究只执行这两档，且至多 12 条）

## 质量要求
- 搜索查询要多样化，覆盖不同角度、不同时效、不同语言
- 考虑历史、现状、趋势、争议等多个维度
- 确保近期信息（3个月内）在计划中占最高优先级
- 不能将搜索局限于单一语言圈，尤其是科技类话题必须包含英文"""


PLANNER_SYSTEM_PROMPT = _build_planner_system_prompt()


QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "purpose": {"type": "string"},
        "priority": {"type": "string", "enum": ["high", "medium", "low"]},
        "time_layer": {"type": "string", "enum": ["recent", "mid", "background"]},
        "language": {"type": "string"},
        "category": {"type": "string"},
    },
    "required": ["query", "purpose", "priority", "time_layer", "language", "category"],
    "additionalProperties": False,
}

ENTITY_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "why": {"type": "string"}},
    "required": ["name", "why"],
    "additionalProperties": False,
}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "objective": {"type": "string"},
        "domain": {"type": "string"},
        "key_aspects": {"type": "array", "items": {"type": "string"}},
        "key_entities": {"type": "array", "items": ENTITY_SCHEMA},
        "search_queries": {"type": "array", "items": QUERY_SCHEMA},
        "expected_output": {"type": "string"},
        "depth_requirement": {"type": "string"},
    },
    "required": ["question", "objective", "domain", "key_aspects", "key_entities", "search_queries",
                 "expected_output", "depth_requirement"],
    "additionalProperties": False,
}


def key_entities_of(plan: dict | None) -> list:
    """计划里的必须覆盖主体；旧计划没有该字段（或内容不合规）时按空处理。"""
    raw = (plan or {}).get("key_entities")
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict) and str(e.get("name", "")).strip()]


def format_key_entities(entities: list | None) -> str:
    """写作/评审提示词里的主体清单（每行一个主体及理由）；没有主体时返回空串。"""
    return "\n".join(f"- {e['name']}：{e.get('why', '')}".rstrip("：") for e in entities or [])


class PlannerAgent(LLMAgent):
    def __init__(self, model: str | None = None):
        super().__init__(name="规划师", system_prompt=PLANNER_SYSTEM_PROMPT,
                         model=model or _config.PLANNER_MODEL, schema=PLAN_SCHEMA)

    def create_plan(self, workspace: str, clarified_question: str,
                    research_strategy: str | None = None, n_queries: int = 10) -> dict:
        """创建研究计划并写入 03_plan.json；失败抛 LLMError。"""
        strategy_block = ""
        if research_strategy and research_strategy.strip():
            strategy_block = f"\n## 研究策略（用户指定，必须遵守）\n{research_strategy.strip()}\n"

        prompt = f"""请为以下研究问题制定详细的研究计划。

## 研究问题
{clarified_question}
{strategy_block}
## 要求
设计 {n_queries} 个高质量的搜索查询，覆盖：基础背景和定义、当前状态和最新发展、关键数据和统计、
重要案例和实例、专家观点和分析、争议点或不同角度、未来趋势或建议。
先判断问题是否涉及列举型对象并填写 key_entities，再设计查询，使 search_queries 覆盖 key_entities 中的全部主体。"""

        return self.ask(prompt, os.path.join(workspace, "03_plan.json"))
