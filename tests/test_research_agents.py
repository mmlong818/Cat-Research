import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from agents import clarifier as clarifier_mod
from agents import llm_agent
from agents import researcher as researcher_mod
from agents.analyst import AnalystAgent
from agents.clarifier import ClarifierAgent
from agents.planner import PlannerAgent
from agents.researcher import ResearcherAgent
from agents.writer import WriterAgent
from llm import LLMError, LLMResult
from research.ledger import Ledger
from tools import fact_tools
from tools.verification_registry import load_registry


def _ok(text="", data=None):
    return LLMResult(text=text, data=data, duration_ms=1000,
                     num_turns=1, session_id="s", model_usage={})


def _notes(notes, claims=()):
    return _ok(data={"notes": notes, "claims": [
        {"text": t, "source_url": u, "source_title": "", "published": "", "quote": q[0] if q else ""}
        for t, u, *q in claims]})


class _WS(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, True)

    def put(self, rel, text):
        path = os.path.join(self.ws, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def read(self, rel):
        with open(os.path.join(self.ws, rel), encoding="utf-8") as f:
            return f.read()

    def patch_call(self, result):
        self.reqs = []

        def fake(req):
            self.reqs.append(req)
            return result

        p = mock.patch.object(llm_agent, "call", side_effect=fake)
        p.start()
        self.addCleanup(p.stop)


PLAN = {"question": "Q", "objective": "O", "domain": "科技", "key_aspects": [],
        "search_queries": [{"query": f"q{i}", "purpose": "", "priority": "high",
                            "time_layer": "recent", "language": "zh", "category": ""}
                           for i in range(7)],
        "expected_output": "", "depth_requirement": ""}


class PlannerTests(_WS):
    def test_plan_written_from_structured_output(self):
        self.patch_call(_ok(data=PLAN))
        plan = PlannerAgent().create_plan(self.ws, "研究问题XYZ", research_strategy="只看中国市场")
        self.assertEqual(plan["search_queries"][0]["query"], "q0")
        self.assertEqual(json.loads(self.read("03_plan.json"))["question"], "Q")
        self.assertIn("研究问题XYZ", self.reqs[0].prompt)
        self.assertIn("只看中国市场", self.reqs[0].prompt)
        self.assertIsNotNone(self.reqs[0].schema)

    def test_failure_raises_no_fallback_plan(self):
        with mock.patch.object(llm_agent, "call", side_effect=LLMError("down")), self.assertRaises(LLMError):
            PlannerAgent().create_plan(self.ws, "Q")
        self.assertFalse(os.path.exists(os.path.join(self.ws, "03_plan.json")))


class ResearcherTests(_WS):
    def setUp(self):
        super().setUp()
        self.batches = []

    def _run(self, outcomes, **kw):
        def fake_many(reqs, max_concurrency):
            self.batches.append(reqs)
            return [outcomes(i, r) for i, r in enumerate(reqs)]

        with mock.patch.object(researcher_mod, "call_many", side_effect=fake_many):
            return ResearcherAgent().research(self.ws, PLAN, **kw)

    def test_queries_split_into_parallel_groups_and_registered(self):
        path = self._run(lambda i, r: _notes(f"发现{i}"), round_num=1)
        reqs = self.batches[0]
        self.assertEqual(len(reqs), 3)  # 7 个查询按 3 个一组
        self.assertEqual(reqs[0].tools, ("WebSearch", "WebFetch"))
        self.assertEqual((reqs[0].effort, reqs[0].max_turns), ("high", 60))
        body = self.read(os.path.relpath(path, self.ws))
        self.assertIn("发现0", body)
        self.assertIn("发现2", body)
        self.assertEqual(len(load_registry(self.ws)["executed_queries"]), 7)

    def test_partial_failure_keeps_successes_and_skips_registering_failed(self):
        self._run(lambda i, r: LLMError("x") if i == 1 else _notes("ok"), round_num=1)
        executed = set(load_registry(self.ws)["executed_queries"])
        self.assertEqual(executed, {"q0", "q1", "q2", "q6"})

    def test_all_groups_fail_raises(self):
        with self.assertRaises(LLMError):
            self._run(lambda i, r: LLMError("x"), round_num=1)

    def test_additional_queries_used_and_executed_skipped(self):
        self._run(lambda i, r: _notes("ok"), round_num=1)
        self._run(lambda i, r: _notes("ok"), round_num=2, additional_queries=["q0", "新话题"])
        second = self.batches[1]
        self.assertEqual(len(second), 1)
        self.assertIn("新话题", second[0].prompt)
        self.assertNotIn('"q0"', second[0].prompt)

    def test_claims_ingested_with_round_and_deduped_across_groups(self):
        claims = [("丰田 2027 年量产", "https://a.com/1"), ("丰田2027年量产", "https://b.com/2")]
        self._run(lambda i, r: _notes(f"n{i}", claims if i < 2 else [("宁德时代 2027 小批量", "https://c.com")]),
                  round_num=1)
        ledger = Ledger.load(self.ws)
        self.assertEqual(len(ledger.claims), 2)
        self.assertEqual(ledger.claims["C1"]["sources"], ["S1", "S2"])
        self.assertEqual(ledger.new_claims_in_round(1), 2)
        self.assertIsNotNone(self.batches[0][0].schema)

    def test_notes_written_to_round_file(self):
        path = self._run(lambda i, r: _notes(f"笔记{i}"), round_num=1)
        self.assertIn("笔记1", self.read(os.path.relpath(path, self.ws)))


class AnalystWriterTests(_WS):
    def test_analyst_inlines_research_and_writes_analysis(self):
        self.put("04_research/round_1.md", "研究材料R1")
        self.patch_call(_ok(text="# 分析"))
        AnalystAgent().analyze(self.ws, "问题")
        self.assertEqual(self.read("05_analysis.md"), "# 分析")
        self.assertIn("研究材料R1", self.reqs[0].prompt)

    def test_empty_text_raises(self):
        self.patch_call(_ok(text="  "))
        with self.assertRaises(LLMError):
            AnalystAgent().analyze(self.ws, "问题")

    def test_writer_improvement_gets_prev_draft_review_and_new_research(self):
        self.put("05_analysis.md", "分析A")
        self.put("04_research/round_3.md", "补充研究R3")
        self.put("06_drafts/draft_1.md", "上一版D1")
        review = self.put("07_reviews/review_2.json", '{"x": "评审意见V"}')
        self.patch_call(_ok(text="# 新报告"))
        out = WriterAgent().write_draft(self.ws, "问题", draft_num=2, review_file=review)
        p = self.reqs[0].prompt
        for marker in ("分析A", "补充研究R3", "上一版D1", "评审意见V"):
            self.assertIn(marker, p)
        self.assertTrue(out.endswith("draft_2.md"))
        self.assertFalse(os.path.exists(os.path.join(self.ws, "09_final.md")))


class WriterLedgerTests(_WS):
    def test_improvement_strips_old_appendix_and_includes_issues_and_claims(self):
        ledger = Ledger.load(self.ws)
        ledger.add_claim("台账声明甲", "https://a.com")
        ledger.save()
        self.put("06_drafts/draft_0.md", "旧正文 [C1]\n\n---\n## 声明来源\n- **[C1]** OLD-APPENDIX")
        self.patch_call(_ok(text="# 新"))
        WriterAgent().write_draft(self.ws, "问题", draft_num=1, citation_issues="- [C9] 不存在的声明编号")
        p = self.reqs[0].prompt
        self.assertIn("旧正文 [C1]", p)
        self.assertNotIn("OLD-APPENDIX", p)
        self.assertIn("上一版的引用问题", p)
        self.assertIn("[C1] 台账声明甲", p)  # unchecked 不标注状态

    def test_prompts_tell_the_writer_not_to_split_pairs_and_not_to_copy_the_annotation(self):
        ledger = Ledger.load(self.ws)
        ledger.add_claim("甲 2027", "https://a.com")
        ledger.add_claim("甲 2029", "https://b.com")
        ledger.resolve(ledger.add_contradiction("C1", "C2"), "neither", "口径不一")
        ledger.save()
        self.put("06_drafts/draft_0.md", "旧正文 [C1] [C2]")
        self.patch_call(_ok(text="# 新"))
        WriterAgent().write_draft(self.ws, "问题", draft_num=1)
        WriterAgent().write_draft(self.ws, "问题", draft_num=0)
        improve, first = self.reqs[0].prompt, self.reqs[1].prompt
        self.assertIn("[C1] (存疑) 甲 2027  — 来源 S1  （与 C2 说法冲突，须同段一并引用）", improve)
        for p in (improve, first):
            self.assertIn("行末标注「（与 Cxx 说法冲突，须同段一并引用）」", p)
            self.assertIn("不得原样写进报告", p)
        self.assertIn("上一版已成对引用的冲突声明，改写时不得拆开", improve)
        self.assertIn("新增内容引用冲突声明时同样须成对引用", improve)


CLARIFY = {"message": "请问关注哪个市场？", "summary": {}, "ready": False, "confidence": 0.4}


class ClarifierTests(unittest.TestCase):
    def test_start_and_reply_carry_history(self):
        prompts = []

        def fake(req):
            prompts.append(req.prompt)
            return _ok(data=dict(CLARIFY, summary={"objective": "o"}))

        with mock.patch.object(clarifier_mod, "call", side_effect=fake):
            first = ClarifierAgent().start("固态电池")
            second = ClarifierAgent().reply(first["history"], "中国市场")
        self.assertEqual(first["message"], "请问关注哪个市场？")
        self.assertIn("我想研究：固态电池", prompts[1])
        self.assertIn("中国市场", prompts[1])
        self.assertEqual(len(second["history"]), 4)

    def test_failure_raises(self):
        with mock.patch.object(clarifier_mod, "call", side_effect=LLMError("down")), \
                self.assertRaises(LLMError):
            ClarifierAgent().start("x")

    def test_summary_to_brief(self):
        brief, meta = clarifier_mod.summary_to_brief(
            {"scope": "中日韩", "key_aspects": ["量产", "良率"], "exclude": "",
             "intent_type": "optimization", "dimensions": {"complexity": 0.8}}, extra_note="要表格")
        self.assertEqual(brief, "研究范围：中日韩\n重点方面：量产、良率\n用户补充：要表格")
        self.assertEqual(meta, {"intent_type": "optimization", "dimensions": {"complexity": 0.8}})


class CrossReferenceTests(unittest.TestCase):
    def test_each_claim_checked_independently_failures_are_none(self):
        verdict = {"verdict": "supported", "confidence": 1.7,
                   "supporting": [{"url": "u", "title": "t"}], "contradicting": [], "explanation": ""}
        seen = []

        def fake_many(reqs, max_concurrency):
            seen.extend(reqs)
            return [_ok(data=dict(verdict)), LLMError("x")]

        with mock.patch.object(fact_tools, "call_many", side_effect=fake_many):
            out = fact_tools.cross_reference_claims(["声明A", "声明B"], model="m")
        self.assertEqual(len(seen), 2)
        self.assertIn("声明A", seen[0].prompt)
        self.assertNotIn("声明B", seen[0].prompt)
        self.assertEqual(out[0]["confidence"], 1.0)
        self.assertIsNone(out[1])


if __name__ == "__main__":
    unittest.main()
