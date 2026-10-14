import json
import os
import tempfile
import unittest
from unittest import mock

from agents import fact_checker as fact_checker_mod
from agents import llm_agent
from agents.conclusion_validator import ConclusionValidatorAgent
from agents.critic import SCORE_KEYS, CriticAgent
from agents.fact_checker import FactCheckerAgent
from agents.reconciler import RECONCILER_SYSTEM_PROMPT, ReconcilerAgent
from agents.source_verifier import SourceVerifierAgent
from llm import LLMError, LLMResult
from research.ledger import NEITHER, Ledger


def _ok(data):
    return LLMResult(text="", data=data, duration_ms=1000,
                     num_turns=1, session_id="s", model_usage={})


class _Base(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.ws, ignore_errors=True))
        self.prompts = []

    def put(self, rel, text):
        path = os.path.join(self.ws, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def patch_call(self, *outcomes):
        seq = list(outcomes)

        def fake(req):
            self.prompts.append(req.prompt)
            out = seq.pop(0)
            if isinstance(out, Exception):
                raise out
            return _ok(out)

        p = mock.patch.object(llm_agent, "call", side_effect=fake)
        self.call_mock = p.start()
        self.addCleanup(p.stop)

    def read_json(self, rel):
        with open(os.path.join(self.ws, rel), encoding="utf-8") as f:
            return json.load(f)


REVIEW = {"scores": {k: 8 for k in SCORE_KEYS}, "strengths": [], "critical_issues": [],
          "missing_content": [], "additional_research_needed": ["x"],
          "overall_assessment": "ok", "priority_improvements": []}


class CriticTests(_Base):
    def test_average_computed_in_python_and_clamped(self):
        self.put("06_drafts/draft_0.md", "草稿正文ABC")
        scores = {k: 8 for k in SCORE_KEYS}
        scores["depth"] = 15  # 越界值被截到 10
        self.patch_call({**REVIEW, "scores": scores})
        review, path = CriticAgent().review(self.ws, 0, 1, question="问题")
        self.assertAlmostEqual(review["average_score"], round((8 * 6 + 10) / 7, 2))
        self.assertEqual(review["cycle"], 1)
        self.assertIn("草稿正文ABC", self.prompts[0])
        self.assertEqual(self.read_json("07_reviews/review_1.json")["average_score"], review["average_score"])

    def test_previous_review_included(self):
        self.put("06_drafts/draft_1.md", "d")
        self.put("07_reviews/review_1.json", '{"marker": "PREV-REVIEW"}')
        self.patch_call(REVIEW)
        CriticAgent().review(self.ws, 1, 2, question="问题")
        self.assertIn("PREV-REVIEW", self.prompts[0])

    def test_llm_error_propagates_without_fallback(self):
        self.put("06_drafts/draft_0.md", "d")
        self.patch_call(LLMError("down"))
        with self.assertRaises(LLMError):
            CriticAgent().review(self.ws, 0, 1, question="问题")
        self.assertFalse(os.path.exists(os.path.join(self.ws, "07_reviews/review_1.json")))


VALIDATION = {"validation_scores": {"evidence_sufficiency": 8, "logical_rigor": 8,
                                    "coverage_completeness": 6, "practical_value": 8,
                                    "limitations_acknowledged": 6},
              "strengths": [], "gaps": [], "logic_issues": [], "missing_perspectives": [],
              "overall_verdict": "needs_improvement", "improvement_instructions": "..."}


class ConclusionValidatorTests(_Base):
    def test_confidence_formula_and_plan_included(self):
        self.put("03_plan.json", '{"question": "PLAN-MARKER"}')
        draft = self.put("06_drafts/draft_2.md", "结论正文")
        self.patch_call(VALIDATION)
        data, _ = ConclusionValidatorAgent().validate_conclusions(
            self.ws, draft_file=draft, question="问题-MARKER",
            source_verification={"total_sources": 5, "summary": {"average_score": 80, "high_confidence_count": 2}},
            fact_check={"overall_confidence": 0.9})
        self.assertEqual(data["average_score"], 7.2)
        self.assertAlmostEqual(data["conclusion_confidence"], 0.8 * 0.25 + 0.9 * 0.35 + 0.72 * 0.40, places=3)
        self.assertIn("PLAN-MARKER", self.prompts[0])
        self.assertIn("问题-MARKER", self.prompts[0])
        self.assertIn("结论正文", self.prompts[0])

    def test_missing_upstream_results_do_not_crash_and_latest_draft_found(self):
        self.put("06_drafts/draft_1.md", "old")
        self.put("06_drafts/draft_10.md", "NEWEST")
        self.patch_call(VALIDATION)
        ConclusionValidatorAgent().validate_conclusions(self.ws, source_verification=None, fact_check=None,
                                                          question="问题")
        self.assertIn("NEWEST", self.prompts[0])


def _ledger_with(ws, texts, contradictions=()):
    ledger = Ledger.load(ws)
    for i, t in enumerate(texts):
        ledger.add_claim(t, f"https://src.com/{i}")
    for a, b in contradictions:
        ledger.add_contradiction(a, b, "冲突")
    ledger.save()
    return ledger


def _check(verdict, conf=0.9, tier="primary"):
    return {"verdict": verdict, "confidence": conf, "supporting": [], "contradicting": [],
            "explanation": f"核实结果 {verdict}", "evidence_tier": tier}


class FactCheckerTests(_Base):
    def patch_many(self, outcomes):
        self.adj_prompts = []

        def fake(reqs, max_concurrency):
            self.adj_prompts += [r.prompt for r in reqs]
            return [outcomes.pop(0) for _ in reqs]

        p = mock.patch.object(fact_checker_mod, "call_many", side_effect=fake)
        p.start()
        self.addCleanup(p.stop)

    def test_adjudication_resolves_and_overrules_loser(self):
        _ledger_with(self.ws, ["A 良率 85%", "A 良率 60%", "B 2027 量产", "B 2029 量产"],
                     [("C1", "C2"), ("C3", "C4")])
        self.patch_many([_ok({"sides_with": "B", "reason": "官方 60%", "evidence_url": "u",
                              "evidence_tier": "primary"}),
                         _ok({"sides_with": "neither", "reason": "口径不一", "evidence_url": "",
                              "evidence_tier": "none"})])
        self.assertEqual(FactCheckerAgent().adjudicate(self.ws), 2)
        ledger = Ledger.load(self.ws)
        self.assertEqual([ledger.claims[c]["status"] for c in ("C1", "C2", "C3", "C4")],
                         ["overruled", "supported", "disputed", "disputed"])
        self.assertIn("https://src.com/0", self.adj_prompts[0])  # 裁决时附上原始来源

    def test_failed_adjudication_stays_unresolved(self):
        _ledger_with(self.ws, ["x 1", "x 2"], [("C1", "C2")])
        self.patch_many([LLMError("down")])
        self.assertEqual(FactCheckerAgent().adjudicate(self.ws), 0)
        self.assertEqual(Ledger.load(self.ws).unresolved(), ["X1"])

    def test_verification_picks_numeric_single_source_claims_and_scores_deterministically(self):
        ledger = _ledger_with(self.ws, ["营收 10 亿", "没有数字的观点", "毛利 5 亿", "良率 70%"])
        ledger.add_claim("毛利 5 亿", "https://other.com/x")  # C3 有两个来源，优先级最低
        ledger.save()
        seen = []

        def fake_cross(texts, model):
            seen.extend(texts)
            return [_check("supported"), _check("unverifiable"), None]

        with mock.patch.object(fact_checker_mod, "cross_reference_claims", side_effect=fake_cross):
            result, _ = FactCheckerAgent().check_facts(self.ws)
        self.assertEqual(seen, ["营收 10 亿", "良率 70%", "毛利 5 亿"])
        self.assertEqual(result["total_claims_checked"], 2)  # 第 3 条核实失败，不计入
        self.assertEqual(result["overall_confidence"], 0.75)  # (1 + 0.5) / 2
        self.assertEqual(Ledger.load(self.ws).claims["C4"]["status"], "unverifiable")
        self.assertTrue(os.path.exists(os.path.join(self.ws, "08_verification", "fact_check.json")))

    def test_nothing_verified_raises(self):
        _ledger_with(self.ws, ["营收 10 亿"])
        with mock.patch.object(fact_checker_mod, "cross_reference_claims", return_value=[None]), \
                self.assertRaises(LLMError):
            FactCheckerAgent().check_facts(self.ws)


class ReconcilerTests(_Base):
    def test_merges_duplicates_and_adds_contradictions_with_validation(self):
        ledger = _ledger_with(self.ws, ["丰田 2027 年量产", "Toyota mass production in 2027", "丰田 2028 年量产"])
        ledger.claims["C1"]["round"] = 0
        ledger.save()
        self.patch_call({"duplicates": [{"keep": "C1", "drop": "C2"}, {"keep": "C1", "drop": "C9"}],
                         "contradictions": [{"a": "C1", "b": "C3", "topic": "量产年份"},
                                            {"a": "C3", "b": "C3", "topic": "自相矛盾"}]})
        stats = ReconcilerAgent().reconcile(self.ws, since_round=0)
        self.assertEqual(stats, {"merged": 1, "contradictions": 1, "skipped": 2})
        ledger = Ledger.load(self.ws)
        self.assertEqual(ledger.claims["C2"]["status"], "merged")
        self.assertEqual(ledger.unresolved(), ["X1"])

    def test_only_new_round_claims_are_listed_as_new(self):
        ledger = Ledger.load(self.ws)
        ledger.add_claim("旧声明 1", round_num=1)
        ledger.add_claim("新声明 2", round_num=3)
        ledger.save()
        self.patch_call({"duplicates": [], "contradictions": []})
        ReconcilerAgent().reconcile(self.ws, since_round=3)
        new_part, old_part = self.prompts[0].split("## 已有声明")
        self.assertIn("新声明 2", new_part)
        self.assertIn("旧声明 1", old_part)

    def test_prompt_lists_existing_contradictions_with_topic_and_verdict(self):
        ledger = _ledger_with(self.ws, ["国轩 2026 底小批量", "国轩 2027 小批量", "广汽 2026 搭载", "广汽 2026 仅实验"])
        for c in ledger.claims.values():
            c["round"] = 1
        ledger.claims["C4"]["round"] = 3
        x1 = ledger.add_contradiction("C1", "C2", "国轩小批量时间")
        ledger.resolve(x1, NEITHER, "口径不一")
        ledger.add_contradiction("C3", "C4", "广汽昊铂搭载")
        ledger.save()
        self.patch_call({"duplicates": [], "contradictions": []})
        ReconcilerAgent().reconcile(self.ws, since_round=3)
        section = self.prompts[0].split("## 已有矛盾")[1]
        self.assertIn("X1", section)
        self.assertIn("C1 与 C2", section)
        self.assertIn("国轩小批量时间", section)
        self.assertIn("两方存疑", section)
        self.assertIn("C3 与 C4", section)
        self.assertIn("未裁决", section)

    def test_prompt_marks_no_existing_contradictions(self):
        _ledger_with(self.ws, ["甲 2027", "乙 2028"])
        self.patch_call({"duplicates": [], "contradictions": []})
        ReconcilerAgent().reconcile(self.ws, since_round=0)
        self.assertEqual(self.prompts[0].split("## 已有矛盾")[1].split("\n", 1)[1].strip().splitlines()[0], "（无）")

    def test_system_prompt_merges_same_fact_but_still_registers_different_facts(self):
        self.assertIn("同一冲突点", RECONCILER_SYSTEM_PROMPT)
        self.assertIn("先判断新旧声明是否陈述同一事实", RECONCILER_SYSTEM_PROMPT)
        self.assertIn("合并重复声明", RECONCILER_SYSTEM_PROMPT)
        self.assertIn("仍应登记为新矛盾", RECONCILER_SYSTEM_PROMPT)
        self.assertIn("不要为避免重复而漏登冲突", RECONCILER_SYSTEM_PROMPT)
        self.assertNotIn("不要另立矛盾", RECONCILER_SYSTEM_PROMPT)

    def test_duplicate_merge_then_same_conflict_does_not_add_a_second_contradiction(self):
        ledger = _ledger_with(self.ws, ["国轩 2026 底小批量", "国轩 2027 小批量", "Gotion small batch end 2026"])
        ledger.claims["C3"]["round"] = 2
        ledger.add_contradiction("C1", "C2", "国轩小批量时间")
        ledger.save()
        self.patch_call({"duplicates": [{"keep": "C1", "drop": "C3"}],
                         "contradictions": [{"a": "C3", "b": "C2", "topic": "国轩小批量时间"}]})
        stats = ReconcilerAgent().reconcile(self.ws, since_round=2)
        self.assertEqual(stats, {"merged": 1, "contradictions": 0, "skipped": 1})
        self.assertEqual(list(Ledger.load(self.ws).contradictions), ["X1"])

    def test_no_new_claims_skips_llm(self):
        self.patch_call()
        self.assertEqual(ReconcilerAgent().reconcile(self.ws, since_round=5)["merged"], 0)
        self.call_mock.assert_not_called()


def _src(url, score, reliable, level="high"):
    return {"url": url, "title": "t", "domain_score": score, "confidence_level": level, "tier": 1,
            "category": "news", "is_reliable": reliable, "warning": ""}


class SourceVerifierTests(_Base):
    def test_summary_computed_from_entries(self):
        self.put("04_research/research_round_1.md",
                 "见 [A](https://www.reuters.com/a) 和 [B](https://blog.example.xyz/b)")
        self.patch_call({"verified_sources": [_src("https://www.reuters.com/a", 90, True),
                                              _src("https://blog.example.xyz/b", 30, False, "low")],
                         "recommendation": "r"})
        data, _ = SourceVerifierAgent().verify_sources(self.ws)
        s = data["summary"]
        self.assertEqual((data["total_sources"], s["average_score"], s["overall_quality"]), (2, 60.0, "fair"))
        self.assertEqual(data["unreliable_sources"], ["https://blog.example.xyz/b"])
        self.assertEqual(data["top_sources"], ["https://www.reuters.com/a"])
        self.assertIn("reuters.com", self.prompts[0])

    def test_no_sources_is_poor_without_llm_call(self):
        self.patch_call()
        data, _ = SourceVerifierAgent().verify_sources(self.ws)
        self.assertEqual((data["total_sources"], data["summary"]["overall_quality"]), (0, "poor"))
        self.call_mock.assert_not_called()

    def test_llm_failure_falls_back_to_rule_engine_marked_degraded(self):
        self.put("04_research/r.md", "https://www.nature.com/articles/x")
        self.patch_call(LLMError("down"), LLMError("down"))
        data, _ = SourceVerifierAgent().verify_sources(self.ws)
        self.assertTrue(data["degraded"])
        self.assertEqual(data["total_sources"], 1)
        self.assertGreater(data["summary"]["average_score"], 0)


if __name__ == "__main__":
    unittest.main()
