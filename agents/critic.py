"""
CriticAgent - 质量评审智能体
负责对研究报告进行多维度深度评审并提出改进意见
"""
import os

import config as _config
from agents.llm_agent import LLMAgent, read_text
from agents.planner import format_key_entities

SCORE_KEYS = ["completeness", "accuracy", "depth", "clarity", "usefulness", "sources", "simplicity"]


CRITIC_SYSTEM_PROMPT = """你是一位严格、专业的研究报告评审专家，具有丰富的学术和商业研究经验。

## 你的职责
对研究报告进行全面、客观、建设性的评审，帮助不断提升报告质量。

## 评审维度（每项0-10分）

### 1. 内容完整性（Completeness）
- 是否覆盖了问题的所有重要方面？
- 是否有明显的遗漏？
- 各章节是否有足够的深度？
- 若给出了必须覆盖的主体清单，是否逐一覆盖？遗漏主体应明显拉低完整性分

### 2. 内容准确性（Accuracy）
- 信息是否准确？
- 数据和案例是否具体可信？
- 结论是否有据可查？

### 3. 分析深度（Depth）
- 是否只是罗列信息，还是有真正的分析？
- 是否揭示了深层原因和规律？
- 洞见是否有价值？

### 4. 逻辑清晰度（Clarity）
- 结构是否清晰合理？
- 论证是否逻辑严密？
- 表达是否清晰易懂？

### 5. 实用价值（Usefulness）
- 结论和建议是否有实际价值？
- 读者能否从中获得可操作的指导？

### 6. 信息来源（Sources）
- 信息来源是否多样、权威？
- 是否有来源标注？

### 7. 简洁性（Simplicity）
- 报告是否避免了不必要的冗余和重复？
- 每个结论是否直接、精炼？
- 是否去除了对主题无实质贡献的内容？
- 是否做到了"少即是多"——用最精简的文字传达最大的价值？

## 评审标准
- 评分要客观公正，不要轻易给高分；只依据本版草稿本身打分，不预设分数随轮次上升
- 只有真正优秀的报告才能得到8.5分以上
- simplicity 分低说明报告臃肿、重复，应鼓励精炼表达"""


def _str_list():
    return {"type": "array", "items": {"type": "string"}}


REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {k: {"type": "number"} for k in SCORE_KEYS},
            "required": SCORE_KEYS,
            "additionalProperties": False,
        },
        "strengths": _str_list(),
        "critical_issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue": {"type": "string"},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "suggestion": {"type": "string"},
                },
                "required": ["issue", "severity", "suggestion"],
                "additionalProperties": False,
            },
        },
        "missing_content": _str_list(),
        "additional_research_needed": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "claim_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["topic", "claim_id", "reason"],
                "additionalProperties": False,
            },
        },
        "overall_assessment": {"type": "string"},
        "priority_improvements": _str_list(),
    },
    "required": ["scores", "strengths", "critical_issues", "missing_content",
                 "additional_research_needed", "overall_assessment", "priority_improvements"],
    "additionalProperties": False,
}


class CriticAgent(LLMAgent):
    def __init__(self, model: str | None = None):
        super().__init__(name="评审员", system_prompt=CRITIC_SYSTEM_PROMPT,
                         model=model or _config.CRITIC_MODEL, schema=REVIEW_SCHEMA)

    def review(self, workspace: str, draft_num: int, cycle: int, key_entities: list | None = None, *,
               question: str) -> tuple:
        """评审指定草稿，返回 (评审 dict, 评审文件路径)；key_entities 为研究计划指定的必须覆盖主体；
        question 为写作者收到的同一份研究问题（含委托时确认的补充说明、研究开始前追加的指令），
        用来检查报告是否满足用户要求，不改变评分标准；失败抛 LLMError。"""
        reviews_dir = os.path.join(workspace, "07_reviews")
        draft = read_text(os.path.join(workspace, "06_drafts", f"draft_{draft_num}.md"))
        review_file = os.path.join(reviews_dir, f"review_{cycle}.json")
        prev = read_text(os.path.join(reviews_dir, f"review_{cycle - 1}.json")) if cycle > 1 else ""
        prev_text = f"\n\n## 上一轮评审（了解改进历程）\n{prev}" if prev else ""

        entities_text = ""
        if key_entities:
            entities_text = f"""

## 必须覆盖的主体（来自研究计划）
{format_key_entities(key_entities)}
完整性维度要逐一核对本版是否覆盖了上述每个主体：遗漏的主体写入 missing_content，并在 additional_research_needed \
中提出补充研究（topic 写成可直接搜索的话题，如"宝马 固态电池 量产时间表"，claim_id 填空串）；\
已明确写出"公开信息不足"的主体视为已交代，不算遗漏。"""

        prompt = f"""请对下面的研究报告草稿进行全面评审。这是第 {cycle} 轮评审。

## 用户的研究问题与委托内容
{question}

## 待评审草稿（第 {draft_num} 版）
{draft}{prev_text}{entities_text}

## 要求
- 评审要严格、客观，不能因为是第 {cycle} 轮就降低标准
- critical_issues 要具体，说明在哪里有问题
- 对照「用户的研究问题与委托内容」（其中的「补充说明」是委托时确认的研究目标、范围、排除内容与特别要求）\
逐条检查报告是否满足：违背或遗漏的要求写进 critical_issues（指明是哪一条要求），并列入 priority_improvements；\
这些要求只用于检查报告是否满足用户要求，不改变 7 个维度的评分标准
- 报告用 [C数字] 引用声明台账，末尾「声明来源」附录由系统按引用自动生成，可据此评估来源
- additional_research_needed 只列真正需要补充搜索的内容：topic 写成可直接搜索的话题；
  claim_id 填需要补证或核实的声明编号（针对报告缺口而非某条声明时填空串）；reason 说明缺什么证据"""

        def finalize(data: dict) -> dict:
            data["cycle"] = cycle
            data["average_score"] = average_score(data["scores"])
            return data

        return self.ask(prompt, review_file, finalize), review_file


def average_score(scores: dict) -> float:
    vals = [min(max(float(scores[k]), 0.0), 10.0) for k in SCORE_KEYS]
    return round(sum(vals) / len(vals), 2)
