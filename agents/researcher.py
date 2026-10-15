"""
ResearcherAgent - 网络研究智能体
负责执行搜索查询并深入收集信息
"""
import json
import os

import config as _config
from agents.llm_agent import LLMAgent, write_text_atomic
from llm import LLMError, call_many
from research.ledger import Ledger
from tools.verification_registry import add_executed_query, load_registry, save_registry

GROUP_SIZE = 3      # 每个并行调用负责的查询数
MAX_PARALLEL = 4    # 同时进行的调用数

RESEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "notes": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "source_url": {"type": "string"},
                    "source_title": {"type": "string"},
                    "published": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["text", "source_url", "source_title", "published", "quote"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["notes", "claims"],
    "additionalProperties": False,
}


def _build_researcher_system_prompt() -> str:
    today   = _config.CURRENT_DATE_STR
    d3m     = _config.DATE_3M_AGO_STR
    d6m     = _config.DATE_6M_AGO_STR
    return f"""你是一位专业的全球网络研究员，擅长从互联网上收集、筛选和整理高质量的多语言信息。

## 你的职责
1. 执行搜索查询获取相关信息
2. 对有价值的链接进行深度抓取
3. 识别和筛选高质量、可靠的信息源
4. 整理收集到的信息，以研究笔记（notes）与结构化声明（claims）返回

## 时效性原则
今天是 **{today}**。研究时间窗口：**{d6m} 至今**（近6个月）。

### 搜索策略（按优先级执行）
1. **首轮必须**：优先查找 **{d3m} 至 {today}（近3个月）** 的内容
   - 搜索词加具体月份或年份，并核对结果的发布日期，确保在窗口内
   - 这段时间的高质量信息应占整体研究的 **50% 以上**
2. **次轮补充**：扩展至 **{d6m} 至 {d3m}（3-6个月前）** 填补空白
   - 搜索词加该时段对应的月份
3. **背景层（按需）**：仅当研究需求明确要求历史背景时，才查找 **{d6m} 之前** 的内容
   - 须明确标注为"历史背景资料"

### 信息标注规则
- 每条信息必须标注**发布日期**
- 按以下分类标记：
  - `[近3个月]`：{d3m} 至 {today} → **优先引用**
  - `[3-6个月前]`：{d6m} 至 {d3m} → 次要引用
  - `[6个月以上]`：{d6m} 之前 → 仅作背景，标注"历史参考"
- 若无法确定发布日期，标注 `[日期未知]` 并降低权重

## 多语言原则
不能将搜索局限于单一语言。根据话题特点：
- **科技/AI/学术话题**：必须包含英文搜索（arXiv、GitHub、技术博客、英文媒体）
- **政策/经济/地缘话题**：同时搜索中文（官方媒体、智库）和英文（国际媒体、研究机构）
- **特定地区话题**：优先使用该地区的主要语言进行搜索
- **全球话题**：至少覆盖中文和英文两个语种，条件允许时加入其他语言
- 搜索词应根据话题领域在中英文之间灵活切换，不要全部只用中文或只用英文

## 广度和深度
- **先广后深**：先搜索多个查询词获取全貌，再对最有价值的结果深度抓取
- **多源验证**：重要信息需要至少2-3个独立来源确认
- **跨圈层覆盖**：学术界、产业界、政策界、媒体的视角都要纳入

## 信息质量标准
- 优先选择权威机构、学术来源、主流媒体的内容
- 区分事实和观点，都要记录
- 遇到矛盾信息时，记录不同说法及各自来源

## 输出要求
以 Markdown 直接返回研究结果（不要写文件），包含：
- 每个关键主题的信息摘要（注明信息时间）
- 重要数据和统计数字
- 关键引述和观点（注明来源语言）
- 来源列表（标题 + URL + 发布时间）"""


RESEARCHER_SYSTEM_PROMPT = _build_researcher_system_prompt()


class ResearcherAgent(LLMAgent):
    def __init__(self, model: str | None = None):
        # effort=high：报告完整性明显好于 medium；high 下一组 3 个查询可能用到几十轮工具调用，上限 60
        super().__init__(name="研究员", system_prompt=RESEARCHER_SYSTEM_PROMPT,
                         model=model or _config.RESEARCHER_MODEL, tools=["WebSearch", "WebFetch"],
                         effort="high", max_turns=60)

    def research(self, workspace: str, plan: dict, round_num: int = 1,
                 additional_queries: list | None = None) -> str:
        """并行执行本轮查询：研究笔记写入 04_research/round_N.md，结构化声明登记到声明台账。

        部分查询组失败时保留成功部分（失败查询不登记，后续可重试）；全部失败抛 LLMError。
        """
        output_file = os.path.join(workspace, "04_research", f"round_{round_num}.md")
        registry = load_registry(workspace)
        queries = _select_queries(plan, round_num, additional_queries,
                                  set(registry.get("executed_queries", [])))
        if not queries:
            print("  [研究员] 所有查询均已执行，跳过本轮研究", flush=True)
            return output_file

        groups = [queries[i:i + GROUP_SIZE] for i in range(0, len(queries), GROUP_SIZE)]
        self.check_stop()
        print(f"\n{'─'*70}\n🤖 智能体 [研究员] 第 {round_num} 轮：{len(queries)} 个查询，"
              f"{len(groups)} 组并行（{self.model}）...", flush=True)
        self.emit("agent_thinking", {"turn": 1})
        results = call_many([self.request(self._group_prompt(plan, g, round_num), schema=RESEARCH_SCHEMA)
                             for g in groups], max_concurrency=MAX_PARALLEL)

        sections, done = self._ingest(workspace, groups, results, round_num)
        header = f"# 研究结果 - 第{round_num}轮\n## 研究问题：{plan.get('question', '')}\n\n"
        write_text_atomic(output_file, header + "\n\n".join(sections))
        for q in done:
            add_executed_query(registry, q.get("query", ""))
        save_registry(workspace, registry)
        return output_file

    def _ingest(self, workspace: str, groups: list, results: list, round_num: int) -> tuple:
        """收集成功组的笔记与已执行查询，并把声明登记到台账；全部失败抛 LLMError。"""
        ledger = Ledger.load(workspace)
        sections, done, new = [], [], 0
        for i, (group, r) in enumerate(zip(groups, results, strict=True), 1):
            if isinstance(r, LLMError):
                print(f"  [研究员] 第 {i} 组失败，未登记其查询: {r}", flush=True)
                continue
            self.report_usage(r, f"（第 {i} 组）")
            sections.append(f"## 查询组 {i}\n\n{r.data['notes']}")
            done.extend(group)
            for c in r.data["claims"]:
                new += ledger.add_claim(c["text"], c["source_url"], c["source_title"],
                                        c["published"], round_num, quote=c["quote"])[1]
        if not sections:
            raise LLMError(f"第 {round_num} 轮研究的 {len(groups)} 个查询组全部失败")
        ledger.save()
        print(f"  [研究员] 第 {round_num} 轮新增 {new} 条声明（台账共 {len(ledger.claims)} 条）", flush=True)
        return sections, done

    def _group_prompt(self, plan: dict, group: list, round_num: int) -> str:
        return f"""请执行以下研究任务，深入收集关于"{plan.get('question', '该主题')}"的信息。

## 研究目标
{plan.get('objective', '深入研究该主题')}

## 需要执行的搜索查询（第 {round_num} 轮，本组 {len(group)} 个）
{json.dumps(group, ensure_ascii=False, indent=2)}

## 执行步骤
1. 对每个搜索查询使用 WebSearch 进行搜索
2. 从搜索结果中选择最有价值的 3-5 个链接，使用 WebFetch 获取详细内容
3. notes：以 Markdown 整理收集到的信息，包含主要发现（按主题）、关键数据与统计、
   重要观点与引述、来源列表（标题 + URL + 发布时间）
4. claims：把 notes 中的关键事实逐条拆成原子声明（一条只陈述一个事实，保留具体数字、日期、主体），
   每条对应你实际读到它的那一个来源页面 URL；published 填来源的发布日期（YYYY-MM-DD，未知填空串）。
   只登记来源里明确写着的事实，不要登记你的推断或观点
5. quote（每条声明必填）：从该来源页面里原样摘抄支持这条声明的原文片段，不超过 300 字，
   须包含声明里的数字与时间表述（年份、日期、季度、半年等）
   - quote 必须是你用 WebFetch 实际打开的页面里的原文：不得改写、不得翻译、不得拼接不同位置的句子，
     也不得凭记忆或搜索摘要补写；英文来源保留英文原文，不要译成中文
   - 声明里的数字与时间表述必须与 quote 一致：原文写"下半年"就不能登记成"第二季度"，原文没有的数字不要写进声明
   - 声明里的标准号、文件编号、型号等标识（如 GB/T 48093.1-2026、计划号）也要出现在 quote 里；
     若该标识只在页面标题出现，quote 可以从标题开始摘抄，连同标题后面的正文一起
   - 来源的发布日期写进 published 字段，不要写进声明正文（不要写"SMM 7月报告称……"，直接陈述事实）
   - 只在搜索摘要（WebSearch 返回的摘要）里看到、页面原文里找不到的事实，不要登记为声明；
     把它写进 notes，并注明"仅见于搜索摘要"
   - 程序会逐条核对声明与 quote 的数字、时间表述，对不上的声明会被标为待核，之后不能作为关键依据

所有内容都来自你实际执行的搜索与读到的页面；没有找到的信息如实说明，不要补全或推测。"""


def _select_queries(plan: dict, round_num: int, additional_queries: list | None, executed: set) -> list:
    """第 1 轮取计划中的高/中优先级查询；后续轮次优先取补充查询。已执行过的查询跳过。"""
    if additional_queries:
        queries = [{"query": q, "purpose": "补充研究", "priority": "high", "category": "补充"}
                   if isinstance(q, str) else q for q in additional_queries]
    elif round_num == 1:
        queries = [q for q in plan.get("search_queries", []) if q.get("priority") in ("high", "medium")][:12]
    else:
        queries = plan.get("search_queries", [])[-8:]
    fresh = [q for q in queries if q.get("query", "").strip() not in executed]
    if len(fresh) < len(queries):
        print(f"  [研究员] 跳过 {len(queries) - len(fresh)} 个已执行的查询，执行 {len(fresh)} 个新查询", flush=True)
    return fresh
