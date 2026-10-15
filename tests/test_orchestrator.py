import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

import orchestrator as orch_mod
from agents.llm_agent import write_json_atomic, write_text_atomic
from llm import LLMError, LLMQuotaError
from research.ledger import Ledger


class FakeAgents:
    """按剧本返回的假智能体；记录写作调用以便断言。"""

    def __init__(self, scores, fail_fact_check=False, conclusion_avg=7.0):
        self.scores = list(scores)
        self.fail_fact_check = fail_fact_check
        self.conclusion_avg = conclusion_avg
        self.writes = []
        self.research_rounds = []
        self.claim_rounds = {1}
        self.reconciled = []
        self.adjudications = 0
        self.verify_limits = []
        self.citation_issues = []
        self.languages = []
        self.draft_texts = {}
        self.plan_entities = None   # None：旧计划，没有 key_entities 字段
        self.writer_entities = []
        self.critic_entities = []
        self.recheck_calls = []     # (最优稿正文, 条数上限)
        self.recheck_spend = 2      # 每次补核「核实」的声明数（不超过上限）
        self.recheck_error = None

    def create_plan(self, ws, q, research_strategy=None, n_queries=None):
        plan = {"question": q, "objective": "o", "domain": "d", "key_aspects": ["a"],
                "search_queries": [{"query": "x", "priority": "high"}],
                "expected_output": "", "depth_requirement": ""}
        if self.plan_entities is not None:
            plan["key_entities"] = self.plan_entities
        return plan

    def research(self, ws, plan, round_num=1, additional_queries=None):
        self.research_rounds.append((round_num, additional_queries))
        path = os.path.join(ws, "04_research", f"round_{round_num}.md")
        write_text_atomic(path, "研究内容 " * 300)
        if round_num in self.claim_rounds:  # 这些轮次产生新声明
            ledger = Ledger.load(ws)
            ledger.add_claim(f"第 {round_num} 轮的新事实", f"https://src.com/{round_num}", round_num=round_num)
            ledger.save()
        return path

    def verify_sources(self, ws):
        return {"total_sources": 3, "top_sources": [], "unreliable_sources": [],
                "summary": {"high_confidence_count": 1, "medium_confidence_count": 1,
                            "low_confidence_count": 1, "average_score": 80.0,
                            "overall_quality": "excellent"}}, ""

    def analyze(self, ws, q):
        write_text_atomic(os.path.join(ws, "05_analysis.md"), "分析")

    def write_draft(self, ws, q, draft_num=0, review_file=None, base_draft=None, citation_issues="",
                    language="zh", key_entities=None, validation_notes=""):
        self.writer_entities.append(key_entities)
        self.writes.append((draft_num, base_draft, review_file))
        self.citation_issues.append(citation_issues)
        self.languages.append(language)
        path = os.path.join(ws, "06_drafts", f"draft_{draft_num}.md")
        write_text_atomic(path, self.draft_texts.get(draft_num, f"DRAFT-{draft_num}"))
        return path

    def check_facts(self, ws, limit=None):
        self.verify_limits.append(limit)
        if self.fail_fact_check:
            raise LLMError("fact down")
        return {"total_claims_checked": 5, "overall_confidence": 0.9, "disputed_claims": [],
                "fact_check_summary": ""}, ""

    def recheck(self, ws, draft_text, limit):
        self.recheck_calls.append((draft_text, limit))
        if self.recheck_error:
            raise self.recheck_error
        return [f"C{i}" for i in range(1, min(limit, self.recheck_spend) + 1)]

    def reconcile(self, ws, since_round=0):
        self.reconciled.append(since_round)
        return {"merged": 0, "contradictions": 0, "skipped": 0}

    def adjudicate(self, ws):
        self.adjudications += 1
        return 0

    def review(self, ws, draft_num, cycle, key_entities=None, *, question):
        self.critic_entities.append(key_entities)
        path = os.path.join(ws, "07_reviews", f"review_{cycle}.json")
        data = {"scores": {}, "average_score": self.scores.pop(0), "critical_issues": [],
                "overall_assessment": "",
                "additional_research_needed": [{"topic": "补充话题", "claim_id": "C1", "reason": "缺数据"}]}
        write_json_atomic(path, data)
        return data, path

    def validate_conclusions(self, ws, draft_file=None, source_verification=None,
                             fact_check=None, cycle=1, *, question):
        return {"average_score": self.conclusion_avg, "overall_verdict": "needs_improvement",
                "conclusion_confidence": 0.7, "gaps": [], "improvement_instructions": ""}, ""


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        p = mock.patch.object(orch_mod, "WORKSPACE_DIR", self.root)
        p.start()
        self.addCleanup(p.stop)

    def run_with(self, fake, **kw):
        o = orch_mod.ResearchOrchestrator()
        for name in ("planner", "researcher", "analyst", "writer", "critic",
                     "source_verifier", "fact_checker", "conclusion_validator", "reconciler"):
            setattr(o, name, fake)
        o._agents = []
        result = o.run("固态电池", **kw)
        return o, result

    def read(self, o, rel):
        with open(os.path.join(o.workspace, rel), encoding="utf-8") as f:
            return f.read()

    def test_final_report_is_best_reviewed_draft_and_drafts_monotonic(self):
        fake = FakeAgents([6.8, 7.1, 7.3, 6.9, 6.4])  # 基线 Q1 的分数历程
        o, result = self.run_with(fake, min_cycles=2, max_cycles=5)
        self.assertTrue(result.startswith("DRAFT-2"))  # 7.3 的那一版
        self.assertEqual([w[0] for w in fake.writes], [0, 1, 2, 3])  # 第 4 轮停止后不再改写
        self.assertEqual(fake.writes[3][1], 2)  # 回退后基于最优稿（第 2 版）改写
        self.assertTrue(fake.writes[3][2].endswith("review_3.json"))  # 用最优稿自己的评审
        meta = json.loads(self.read(o, "00_session.json"))
        self.assertEqual((meta["final_draft"], meta["total_cycles"]), (2, 4))

    def test_quality_exit(self):
        fake = FakeAgents([7.5, 8.2, 9.0], conclusion_avg=7.8)
        o, _ = self.run_with(fake, min_cycles=2, max_cycles=5)
        meta = json.loads(self.read(o, "00_session.json"))
        self.assertEqual(meta["total_cycles"], 2)

    def test_last_cycle_does_not_rewrite(self):
        fake = FakeAgents([6.0, 7.0])
        self.run_with(fake, min_cycles=2, max_cycles=2)
        self.assertEqual([w[0] for w in fake.writes], [0, 1])

    def test_supplementary_rounds_get_unique_numbers(self):
        fake = FakeAgents([6.0, 7.0, 8.0])
        self.run_with(fake, min_cycles=3, max_cycles=3)
        rounds = [r for r, _ in fake.research_rounds]
        self.assertEqual(rounds, sorted(set(rounds)))

    def test_supplementary_research_stops_after_a_round_without_new_claims(self):
        fake = FakeAgents([6.0, 6.5, 7.0, 7.5, 8.0])
        fake.claim_rounds = {1, 2}  # 第 2 轮（首次补充）有新声明，第 3 轮没有
        self.run_with(fake, min_cycles=5, max_cycles=5)
        rounds = [r for r, _ in fake.research_rounds]
        self.assertEqual(rounds, [1, 2, 3])  # 第 3 轮零增益后，第 3 个循环的补充研究被跳过

    def test_ledger_reconciled_before_analysis_and_after_each_supplement(self):
        fake = FakeAgents([6.0, 6.5, 7.0])
        fake.claim_rounds = {1, 2, 3}
        self.run_with(fake, min_cycles=3, max_cycles=3)
        self.assertEqual(fake.reconciled, [0, 2, 3])  # 全量对账，然后每轮补充只对新一轮对账
        self.assertEqual(fake.adjudications, 2)

    def test_citation_violation_blocks_quality_exit_and_is_fed_to_rewrite(self):
        fake = FakeAgents([7.5, 8.2, 8.3], conclusion_avg=7.8)
        fake.draft_texts = {1: "DRAFT-1 引用了不存在的声明 [C99]。", 2: "DRAFT-2 合规 [C1]。"}
        o, result = self.run_with(fake, min_cycles=2, max_cycles=5)
        meta = json.loads(self.read(o, "00_session.json"))
        self.assertEqual((meta["total_cycles"], meta["final_draft"]), (3, 2))  # 第 2 轮 8.2 被阻塞
        self.assertIn("C99", fake.citation_issues[2])  # 第 2 版的改写收到了第 1 版的违规清单
        self.assertEqual(meta["citations"]["violations"], 0)

    def test_final_draft_avoids_best_scored_draft_with_violations(self):
        fake = FakeAgents([7.0, 8.0])
        fake.draft_texts = {0: "DRAFT-0 [C1]。", 1: "DRAFT-1 [C99]。"}
        o, result = self.run_with(fake, min_cycles=2, max_cycles=2)
        self.assertTrue(result.startswith("DRAFT-0"))
        meta = json.loads(self.read(o, "00_session.json"))
        self.assertEqual((meta["final_draft"], meta["best_scored_draft"]), (0, 1))

    def test_final_report_has_claim_source_appendix(self):
        fake = FakeAgents([7.0, 7.5])
        fake.draft_texts = {0: "DRAFT-0 第一轮事实 [C1]。", 1: "DRAFT-1 第一轮事实 [C1]。"}
        _, result = self.run_with(fake, min_cycles=2, max_cycles=2)
        self.assertIn("## 声明来源", result)
        self.assertIn("**[C1]** 第 1 轮的新事实 — https://src.com/1", result)
        self.assertNotIn("引用问题", result)

    def test_missing_fact_check_marked_not_defaulted(self):
        fake = FakeAgents([6.0, 7.0], fail_fact_check=True)
        o, result = self.run_with(fake, min_cycles=2, max_cycles=2)
        conf = json.loads(self.read(o, "08_verification/confidence_report.json"))
        self.assertEqual(conf["missing"], ["fact_accuracy"])
        self.assertIsNone(conf["breakdown"]["fact_accuracy"]["score"])
        self.assertEqual(conf["breakdown"]["fact_accuracy"]["weight"], "未完成")
        self.assertIn("N/A（未完成）", result)

    def test_quota_exhausted_mid_loop_keeps_best_and_finishes(self):
        fake = FakeAgents([7.0, 7.4, 7.7])
        real_review = fake.review

        def review(ws, draft_num, cycle, key_entities=None, *, question):
            if cycle == 4:
                raise LLMQuotaError("You've hit your session limit")
            return real_review(ws, draft_num, cycle, key_entities, question=question)

        fake.review = review
        o, result = self.run_with(fake, min_cycles=2, max_cycles=5)
        self.assertTrue(result.startswith("DRAFT-2"))
        meta = json.loads(self.read(o, "00_session.json"))
        self.assertEqual((meta["status"], meta["final_draft"], meta["total_cycles"]), ("completed", 2, 3))

    def test_stop_event_interrupts(self):
        stop = threading.Event()
        stop.set()
        _, result = self.run_with(FakeAgents([7.0]), stop_event=stop)
        self.assertEqual(result, "任务已中断")


if __name__ == "__main__":
    unittest.main()
