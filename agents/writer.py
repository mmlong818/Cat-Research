"""
WriterAgent - 文档撰写智能体
负责将分析结果转化为高质量的研究报告
"""
import os

import config as _config
from agents.llm_agent import LLMAgent, read_dir_markdown, read_text
from agents.planner import format_key_entities
from research.ledger import Ledger, body_of
from research.source_quality import load_verification

WRITER_SYSTEM_PROMPT = """你是一位专业的研究报告撰写专家，能够将复杂的研究和分析成果转化为清晰、专业、有价值的文档。

## 你的写作原则
1. **准确性**：所有内容必须有研究材料支撑，不凭空添加
2. **深度**：深入分析，提供真正有价值的洞见，不流于表面
3. **清晰性**：结构清晰，逻辑严密，易于理解
4. **完整性**：全面覆盖问题的各个重要方面
5. **专业性**：使用准确的术语，保持专业水准

## 写作风格
- 语言精准、表达流畅
- 段落逻辑清晰，层层递进
- 适当使用小标题、列表等增强可读性
- 数据和事实要具体，避免模糊表述
- 结论要有力，建议要可操作

## 文档结构要求
每份报告必须包含：
1. **标题和摘要** - 核心内容概括
2. **引言/背景** - 问题的重要性和研究背景
3. **主体内容** - 多个维度的深入分析（至少3-5个主要章节）
4. **结论与展望** - 综合结论和未来方向
5. **出处** - 事实与数据用 [C编号] 标注（文末「声明来源」由系统按引用自动生成，不要自己编写参考资料列表）

## 改进要求
当收到评审反馈时：
- 认真阅读每条反馈意见
- 逐条解决提出的问题
- 补充缺失的内容
- 改进薄弱的分析
- 提升整体质量"""


REPORT_FORMAT = """## 报告要求
- 篇幅：不设字数下限，篇幅服务于内容；同一事实只在最相关处写一次，避免重复表述，表格只用于确实需要横向对比的数据
- 结构完整：必须有标题、摘要、引言、多个分析章节（至少5个）、结论与展望
- 内容深度：不只是罗列信息，要有分析和洞见
- 数据具体：使用研究材料中的真实数字和案例
- 结论有力：提供清晰的结论和可行的建议
- 以 Markdown 直接返回完整报告（从一级标题开始），不要写文件

## 引用规则（系统会逐条检查）
- 每个事实、数字、日期都在句末用 [C编号] 标注，可一次标多个如 [C3, C8]；只能使用声明台账中列出的编号
- 台账未列出的声明（已被推翻、重复或矛盾未裁决）不得作为事实写入
- 「成对引用要求」中的两条声明必须出现在同一段落，并如实呈现分歧
- 声明行末标注「（与 Cxx 说法冲突，须同段一并引用）」的声明，引用时必须与所列的对方声明出现在同一段落；\
这条标注只是写作参考，不得原样写进报告
- 不要自己编写参考资料或来源列表

## 报告清洁规则（系统会逐条检查）
- 声明台账里括号中的「已核实 / 存疑 / 待核实」只是写作参考，不得在报告中输出台账状态标签或英文状态词\
（supported、disputed、unverifiable、overruled、unchecked、merged 这类词作为状态标记一律不得出现）
- 对存疑或待核实的说法用自然语言表述，如"有待官方确认""各方说法不一""目前仅见媒体转述"
- 不得保留修订说明、改版日志、"本版/上一版改动""根据评审意见修改"之类的编辑痕迹；\
报告从标题开始，读者只应看到一份完成稿，不应看到它的修改过程

## 来源可信度规则
- 声明台账里标有「(来源可信度低)」的声明，其全部来源都是社交媒体、自媒体或聚合研报一类低可信来源：\
只能带明确限定语引用，如"据社交媒体汇总""据聚合研报""据自媒体报道"；\
不得作为关键结论、厂商时间表或数据表的唯一依据
- 低可信来源的声明与其他来源冲突时，以高可信来源为准；没有高可信来源佐证的产线地点、投产时间与产能数字，\
写"公开信息不足"或"有待官方确认"，不要当作事实陈述
- 「来源可信度低」只是写作参考，不得作为标签原样写进报告

## 摘录核对规则
- 声明台账里标有「(摘录待核)」的声明，其来源的原文片段与声明里的数字或时间对不上（或缺原文片段），\
数字、时间可能被记错：只能带限定语引用，如"据报道，具体时间有待核实"，或改用更可靠来源的说法；\
不得作为关键结论、厂商时间表或数据表的唯一依据
- 没有更可靠来源佐证的时间与数字，写"公开信息不足"或"有待官方确认"，不要当作事实陈述
- 「摘录待核」只是写作参考，不得作为标签原样写进报告

## 范围限定规则（系统会逐条检查）
- 不得断言全网范围的"不存在"：不要写"只见于""仅见于""唯一来源""没有其他来源""未见其他报道"这类无限定表述\
（声明台账里的来源数只反映本研究检索到的范围，不代表全网只有这些）
- 需要说明证据单薄时必须带范围限定，如"本研究检索到的来源中仅见于……""本次检索未见其他报道"之类的表述"""

# 报告语言指令：只约束最终报告的撰写语言（中文为默认，不加指令）；引用标记 [C编号] 与系统生成的附录标题保持原样
LANGUAGE_INSTRUCTIONS = {
    "en": ("## 输出语言\n"
           "Write the entire report in English (title, summary, headings and body); keep source titles and "
           "quotes in their original language. Keep the [C<number>] citation markers exactly as specified above."),
}


def _report_format(language: str) -> str:
    extra = LANGUAGE_INSTRUCTIONS.get(language)
    return f"{REPORT_FORMAT}\n\n{extra}" if extra else REPORT_FORMAT


def _entities_block(key_entities: list | None) -> str:
    """研究计划指定的必须覆盖主体：逐一覆盖，信息不足的要明说而不是略去；没有主体时不加这一节。"""
    if not key_entities:
        return ""
    return ("\n\n## 必须覆盖的主体（研究计划指定）\n"
            "下列主体须在报告中逐一覆盖（各自的进展、时间表或关键事实，能对比时做横向对比）；"
            "研究材料中信息不足的主体，明确写\"公开信息不足\"，不得略去：\n"
            f"{format_key_entities(key_entities)}")


class WriterAgent(LLMAgent):
    def __init__(self, model: str | None = None):
        super().__init__(name="写作者", system_prompt=WRITER_SYSTEM_PROMPT, model=model or _config.WRITER_MODEL)

    def write_draft(self, workspace: str, question: str, draft_num: int = 0, review_file: str | None = None,
                    base_draft: int | None = None, citation_issues: str = "",
                    language: str = "zh", key_entities: list | None = None,
                    validation_notes: str = "") -> str:
        """写初稿（draft_num=0）或基于 base_draft（默认上一版）与评审意见改进，写入 draft_N.md。

        改进时同样提供全部研究材料与最新声明台账，使补充研究能进入报告；
        citation_issues 为上一版的引用违规清单（必须修正）；language 为报告语言（zh/en）；
        key_entities 为研究计划指定的必须覆盖主体（逐一覆盖）；
        validation_notes 为结论验证员对最优稿的意见（已渲染成一节，仅改进时使用，评审意见优先）。失败抛 LLMError。
        """
        output_file = os.path.join(workspace, "06_drafts", f"draft_{draft_num}.md")
        entities = _entities_block(key_entities)
        if draft_num == 0:
            task = (f"请根据分析报告、研究材料与声明台账撰写一份全面的研究报告。\n\n"
                    f"## 研究问题\n{question}\n\n{_materials(workspace)}{entities}\n\n{_report_format(language)}")
        else:
            base = draft_num - 1 if base_draft is None else base_draft
            task = _improve_task(workspace, question, draft_num, base, review_file, citation_issues, language,
                                 entities, validation_notes)
        self.ask_text(task, output_file)
        return output_file


def _materials(workspace: str) -> str:
    return (f"## 分析报告\n{read_text(os.path.join(workspace, '05_analysis.md'))}\n\n"
            f"## 研究材料（含改进循环中的补充研究）\n{read_dir_markdown(os.path.join(workspace, '04_research'))}\n\n"
            f"## 声明台账（已去重、已裁决矛盾；括号内为核查状态）\n"
            f"{Ledger.load(workspace).claims_table(load_verification(workspace)) or '（无）'}")


def _improve_task(workspace: str, question: str, draft_num: int, base: int,
                  review_file: str | None, citation_issues: str, language: str, entities: str = "",
                  validation_notes: str = "") -> str:
    prev = body_of(read_text(os.path.join(workspace, "06_drafts", f"draft_{base}.md")))
    issues = f"\n\n## 上一版的引用问题（必须全部修正）\n{citation_issues}" if citation_issues else ""
    if validation_notes:
        issues += f"\n\n{validation_notes}"
    return f"""请根据评审意见改进研究报告（基于第 {base} 版，生成第 {draft_num} 版）。

## 研究问题
{question}

## 上一版草稿
{prev}

## 评审意见
{read_text(review_file) or "（无）"}{issues}

{_materials(workspace)}{entities}

## 改进要求
- 逐条解决每个评审问题，补充缺失内容，深化浅显分析，修正不准确内容
- 在不失去原有优点的同时做出实质性改进
- 上一版已成对引用的冲突声明，改写时不得拆开（调整、拆分或移动段落时，成对的两条声明仍须在同一段落）；\
新增内容引用冲突声明时同样须成对引用
- 评审意见与上一版的问题清单只供你修改参考，直接交出改好的完整报告，不要在报告中说明改了什么

{_report_format(language)}"""
