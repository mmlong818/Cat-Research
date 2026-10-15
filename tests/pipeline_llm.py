"""完整流程的脚本化假模型：真实编排 + 真实智能体，只替换模型调用层。

按请求的系统提示词认出是哪个智能体，返回固定的结构化结果并记录每次请求；
供提示词快照（tests/test_prompt_snapshot.py）与用户补充要求（tests/test_user_directives.py）共用。
剧本（standard 档，3 轮改进）：第 1 轮研究 3 条声明，C1/C2 互相矛盾并被裁决；每轮评审都要求补充研究，
评审分 6.0 → 6.5 → 7.0，第 2 轮对最优稿引用的新声明做承重补核，第 3 轮达到轮数上限结束。
"""
import json
import re
from contextlib import ExitStack
from unittest import mock

import config as _config
import orchestrator as orch_mod
from agents import fact_checker as fc_mod
from agents import llm_agent
from agents import researcher as researcher_mod
from agents.analyst import ANALYST_SYSTEM_PROMPT
from agents.conclusion_validator import CONCLUSION_VALIDATOR_SYSTEM_PROMPT
from agents.conclusion_validator import SCORE_KEYS as VALIDATION_KEYS
from agents.critic import CRITIC_SYSTEM_PROMPT
from agents.critic import SCORE_KEYS as REVIEW_KEYS
from agents.fact_checker import ADJUDICATE_SYSTEM_PROMPT
from agents.planner import PLANNER_SYSTEM_PROMPT
from agents.reconciler import RECONCILER_SYSTEM_PROMPT
from agents.researcher import RESEARCHER_SYSTEM_PROMPT
from agents.source_verifier import SOURCE_VERIFIER_SYSTEM_PROMPT
from agents.writer import WRITER_SYSTEM_PROMPT
from llm import LLMResult
from tools import fact_tools

QUESTION = "固态电池量产进展"

ROLES = {
    PLANNER_SYSTEM_PROMPT: "planner",
    RESEARCHER_SYSTEM_PROMPT: "researcher",
    SOURCE_VERIFIER_SYSTEM_PROMPT: "source_verifier",
    RECONCILER_SYSTEM_PROMPT: "reconciler",
    ADJUDICATE_SYSTEM_PROMPT: "fact_checker",
    fact_tools.CROSS_CHECK_SYSTEM: "cross_check",
    ANALYST_SYSTEM_PROMPT: "analyst",
    WRITER_SYSTEM_PROMPT: "writer",
    CRITIC_SYSTEM_PROMPT: "critic",
    CONCLUSION_VALIDATOR_SYSTEM_PROMPT: "conclusion_validator",
}

# 提示词里随运行日期变化的部分（快照里换成占位符）
_DATES = {"<TODAY>": _config.CURRENT_DATE_STR, "<TODAY_ISO>": _config.CURRENT_DATE_ISO,
          "<3M_AGO>": _config.DATE_3M_AGO_STR, "<3M_AGO_ISO>": _config.DATE_3M_AGO_ISO,
          "<6M_AGO>": _config.DATE_6M_AGO_STR, "<6M_AGO_ISO>": _config.DATE_6M_AGO_ISO}

ROUND_1_CLAIMS = [
    ("甲公司合肥工厂 2026 年 3 月投产，年产能 20GWh", "https://www.gov.cn/zhengce/a1", "合肥市政府公告"),
    ("甲公司合肥工厂 2027 年投产", "https://news.example.com/a2", "行业快讯"),
    ("乙公司固态电芯能量密度达到 400Wh/kg", "https://www.example.org/b1", "乙公司技术白皮书"),
]


def normalize(text: str) -> str:
    for placeholder, value in _DATES.items():
        text = text.replace(value, placeholder)
    return text


def _ok(data=None, text=""):
    return LLMResult(text=text, data=data, duration_ms=0, num_turns=1, session_id="s", model_usage={})


def _number(pattern: str, prompt: str, default: int = 0) -> int:
    m = re.search(pattern, prompt)
    return int(m.group(1)) if m else default


class ScriptedLLM:
    def __init__(self):
        self.requests: list = []   # [(角色, LLMRequest)]
        self._reconciles = 0

    def call(self, req):
        role = ROLES[req.system]   # 系统提示词不是已知智能体之一时直接 KeyError
        self.requests.append((role, req))
        return getattr(self, f"_{role}")(req.prompt)

    def call_many(self, reqs, max_concurrency=None):
        return [self.call(r) for r in reqs]

    def patches(self) -> list:
        return [mock.patch.object(llm_agent, "call", self.call),
                mock.patch.object(researcher_mod, "call_many", self.call_many),
                mock.patch.object(fc_mod, "call_many", self.call_many),
                mock.patch.object(fact_tools, "call_many", self.call_many)]

    def prompts(self, role: str) -> list[str]:
        return [req.prompt for r, req in self.requests if r == role]

    def snapshot(self) -> list[dict]:
        return [{"role": role, "effort": req.effort, "tools": list(req.tools), "max_turns": req.max_turns,
                 "schema": req.schema is not None, "prompt": normalize(req.prompt)}
                for role, req in self.requests]

    # ── 各智能体的剧本 ──────────────────────────────────────────────────────

    def _planner(self, prompt):
        queries = [{"query": f"固态电池 量产 {i}", "purpose": "进展", "priority": "high", "time_layer": "recent",
                    "language": "zh", "category": "进展"} for i in range(3)]
        return _ok({"question": QUESTION, "objective": "梳理固态电池量产进展", "domain": "科技",
                    "key_aspects": ["量产时间"], "key_entities": [{"name": "甲公司", "why": "头部厂商"}],
                    "search_queries": queries, "expected_output": "研究报告", "depth_requirement": "深入"})

    def _researcher(self, prompt):
        n = _number(r"（第 (\d+) 轮，本组", prompt, 1)
        if n == 1:
            claims = ROUND_1_CLAIMS
            notes = "固态电池产业研究笔记。" * 32 + "\n" + "\n".join(f"- [{t}]({u})" for _, u, t in claims)
        else:
            claims = [(f"丙公司第 {n} 期产线 2026 年 {n} 月开工", f"https://www.example.org/r{n}", f"丙公司公告 {n}")]
            notes = f"第 {n} 轮补充研究：[{claims[0][2]}]({claims[0][1]})"
        return _ok({"notes": notes, "claims": [{"text": c, "source_url": u, "source_title": t,
                                                "published": "2025-11-20", "quote": c} for c, u, t in claims]})

    def _source_verifier(self, prompt):
        urls = re.findall(r'"url": "([^"]+)"', prompt)
        return _ok({"verified_sources": [
            {"url": u, "title": u, "domain_score": 90, "confidence_level": "high", "tier": 1,
             "category": "research", "is_reliable": True, "warning": ""} for u in urls],
            "recommendation": "来源整体可靠"})

    def _reconciler(self, prompt):
        self._reconciles += 1
        contradictions = [{"a": "C1", "b": "C2", "topic": "甲公司合肥工厂投产时间"}] if self._reconciles == 1 else []
        return _ok({"duplicates": [], "contradictions": contradictions})

    def _fact_checker(self, prompt):
        return _ok({"sides_with": "A", "reason": "政府公告明确投产时间", "evidence_url": "https://www.gov.cn/zhengce/a1",
                    "evidence_tier": "primary"})

    def _cross_check(self, prompt):
        return _ok({"verdict": "supported", "confidence": 0.9,
                    "supporting": [{"url": "https://www.gov.cn/zhengce/a1", "title": "公告"}],
                    "contradicting": [], "explanation": "一手记录支持", "evidence_tier": "primary"})

    def _analyst(self, prompt):
        return _ok(text="# 研究分析报告\n\n## 执行摘要\n甲公司合肥工厂 2026 年 3 月投产 [C1]。")

    def _writer(self, prompt):
        n = _number(r"生成第 (\d+) 版", prompt)
        if n == 0:
            return _ok(text="# 固态电池报告\n\n甲公司合肥工厂 2026 年 3 月投产，年产能 20GWh [C1]。"
                            "乙公司固态电芯能量密度达到 400Wh/kg [C3]。")
        return _ok(text=f"# 固态电池报告（第 {n} 版）\n\n甲公司合肥工厂 2026 年 3 月投产 [C1]。"
                        f"丙公司第 {n + 1} 期产线 2026 年 {n + 1} 月开工 [C{n + 3}]。")

    def _critic(self, prompt):
        cycle = _number(r"这是第 (\d+) 轮评审", prompt, 1)
        score = 5.5 + 0.5 * cycle
        return _ok({"scores": dict.fromkeys(REVIEW_KEYS, score), "strengths": ["结构清晰"],
                    "critical_issues": [{"issue": "缺少横向对比", "severity": "high", "suggestion": "补充对比"}],
                    "missing_content": [],
                    "additional_research_needed": [{"topic": f"丙公司 产线 进展 {cycle}", "claim_id": "",
                                                    "reason": "缺少最新进展"}],
                    "overall_assessment": "尚可", "priority_improvements": ["补充数据"]})

    def _conclusion_validator(self, prompt):
        return _ok({"validation_scores": dict.fromkeys(VALIDATION_KEYS, 7.0), "strengths": [], "gaps": [],
                    "logic_issues": [], "missing_perspectives": [], "overall_verdict": "needs_improvement",
                    "improvement_instructions": "补充数据"})


def run_pipeline(root: str, llm: ScriptedLLM, on_event=None, before_run=None, replay_from: str | None = None,
                 workspace: str = "", clarification: str | None = None):
    """在 root 下跑完整流程（或在 workspace 上从 replay_from 重放）；返回 (orchestrator, 事件列表)。
    on_event(o, 事件名, 数据) 在每个进度事件时调用，可借此在检查点前注入用户消息；
    clarification 为委托时确认的补充说明（不传时与没有澄清的任务相同）。"""
    events: list = []
    holder: dict = {}

    def callback(kind, data):
        events.append((kind, json.loads(json.dumps(data, ensure_ascii=False))))
        if on_event:
            on_event(holder["o"], kind, data)

    with ExitStack() as stack:
        for p in [*llm.patches(), mock.patch.object(orch_mod, "WORKSPACE_DIR", root), mock.patch("builtins.print")]:
            stack.enter_context(p)
        o = holder["o"] = orch_mod.ResearchOrchestrator(progress_callback=callback)
        if before_run:
            before_run(o)
        if replay_from:
            o.replay(workspace, replay_from)
        else:
            o.run(QUESTION, depth="standard", clarification=clarification)
    return o, events
