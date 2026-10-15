"""F4 核查对象挑选与承重声明补核：本应有一手记录的声明来源越多越该核；改进循环里补核最优稿中被引用最多的未核查声明。"""
import shutil
import tempfile
import unittest
from unittest import mock

import config
import orchestrator as orch_mod
from agents import fact_checker as fc_mod
from agents.fact_checker import FactCheckerAgent, pick_for_verification, pick_load_bearing
from llm import LLMError
from research.ledger import Ledger, citation_counts
from research.params import resolve_params
from tests.test_fact_primary_source import _check, _ledger_with
from tests.test_orchestrator import FakeAgents

STANDARD_DATE = "GB/T 43568-2026 于 2026 年 7 月 1 日起实施"


def _more_sources(ledger, text, n):
    for i in range(n):
        ledger.add_claim(text, f"https://media{i}.com/x")


class PickOrderTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, True)

    def test_three_source_standard_date_claim_comes_before_one_source_plain_number(self):
        ledger = _ledger_with(self.ws, ["营收 10 亿", STANDARD_DATE])
        _more_sources(ledger, STANDARD_DATE, 2)  # C2 共 3 个来源
        self.assertEqual(len(ledger.claims["C2"]["sources"]), 3)
        self.assertEqual(pick_for_verification(ledger), ["C2", "C1"])

    def test_among_primary_record_claims_more_sources_come_first(self):
        ledger = _ledger_with(self.ws, ["工信部发布 A 通知", "工信部发布 B 通知", "工信部发布 C 通知"])
        _more_sources(ledger, "工信部发布 B 通知", 3)  # C2：4 个来源，全是转述
        _more_sources(ledger, "工信部发布 C 通知", 1)  # C3：2 个来源
        self.assertEqual(pick_for_verification(ledger), ["C2", "C3", "C1"])

    def test_among_plain_numeric_claims_fewer_sources_still_come_first(self):
        ledger = _ledger_with(self.ws, ["营收 10 亿", "良率 70%", "毛利 5 亿"])
        _more_sources(ledger, "营收 10 亿", 1)
        self.assertEqual(pick_for_verification(ledger), ["C2", "C3", "C1"])

    def test_digit_still_ranks_above_no_digit_inside_the_primary_group(self):
        ledger = _ledger_with(self.ws, ["工信部发布了相关通知", "工信部 2026 年发布通知"])
        _more_sources(ledger, "工信部发布了相关通知", 3)
        self.assertEqual(pick_for_verification(ledger), ["C2", "C1"])

    def test_ties_fall_back_to_claim_number(self):
        ledger = _ledger_with(self.ws, ["工信部发布 A 通知", "工信部发布 B 通知"])
        self.assertEqual(pick_for_verification(ledger), ["C1", "C2"])


class CitationCountTests(unittest.TestCase):
    def test_counts_every_occurrence_and_follows_merges(self):
        ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, ws, True)
        ledger = _ledger_with(ws, ["标准 A 已发布", "标准 B 已发布", "标准 B 已发布（重复）"])
        ledger.merge("C2", "C3")
        text = "甲 [C1]。乙 [C1, C2]。丙 [C3]。\n\n丁 [C1]。\n\n---\n## 声明来源\n- **[C1]** x [C1]"
        self.assertEqual(citation_counts(ledger, text), {"C1": 3, "C2": 2})


class LoadBearingPickTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, True)
        self.ledger = _ledger_with(self.ws, [
            "国标 A 于 7 月实施",       # C1 关键词，引用 3 次
            "国标 B 已发布",             # C2 关键词，引用 1 次
            "营收 10 亿美元",             # C3 无关键词，引用 4 次
            "国标 C 已发布",             # C4 关键词，已核实，引用 4 次
            "国标 D 已发布",             # C5 关键词，未被引用
            "国标 E 已发布",             # C6 关键词，引用 2 次
        ])
        self.ledger.set_status("C4", "supported")
        self.text = ("[C1] [C3] [C4]。[C1][C3] [C4, C6]。\n\n[C1] [C3] [C4]，[C6]，[C2]，[C3]，[C4]。")

    def test_only_cited_unchecked_keyword_claims_most_cited_first(self):
        self.assertEqual(pick_load_bearing(self.ledger, self.text, 10), ["C1", "C6", "C2"])

    def test_limit_applies_and_zero_is_empty(self):
        self.assertEqual(pick_load_bearing(self.ledger, self.text, 2), ["C1", "C6"])
        self.assertEqual(pick_load_bearing(self.ledger, self.text, 0), [])

    def test_uncitable_claims_are_skipped_and_ties_go_by_number(self):
        self.ledger.set_status("C1", "overruled")
        self.assertEqual(pick_load_bearing(self.ledger, "[C1] [C2] [C6] [C99]", 5), ["C2", "C6"])


class RecheckAgentTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, True)
        _ledger_with(self.ws, ["国标 A 于 7 月实施", "国标 B 已发布", "营收 10 亿"])
        self.text = "[C1] [C1] [C2] [C3]"

    def test_verdicts_are_written_back_through_the_evidence_tier_rule(self):
        seen = []

        def fake_cross(texts, model):
            seen.extend(texts)
            return [_check("supported", "primary"), _check("supported", "media")]

        with mock.patch.object(fc_mod, "cross_reference_claims", side_effect=fake_cross):
            done = FactCheckerAgent().recheck(self.ws, self.text, 5)
        ledger = Ledger.load(self.ws)
        self.assertEqual((done, seen), (["C1", "C2"], ["国标 A 于 7 月实施", "国标 B 已发布"]))
        self.assertEqual([ledger.claims[c]["status"] for c in ("C1", "C2", "C3")],
                         ["supported", "unverifiable", "unchecked"])  # 仅媒体证据降为待核实；无关键词的不碰

    def test_limit_zero_and_no_candidates_never_call_the_checker(self):
        with mock.patch.object(fc_mod, "cross_reference_claims") as cross:
            self.assertEqual(FactCheckerAgent().recheck(self.ws, self.text, 0), [])
            self.assertEqual(FactCheckerAgent().recheck(self.ws, "没有任何引用", 5), [])
            cross.assert_not_called()

    def test_failed_single_check_leaves_the_claim_unchecked(self):
        with mock.patch.object(fc_mod, "cross_reference_claims", return_value=[None, _check("disputed", "primary")]):
            FactCheckerAgent().recheck(self.ws, self.text, 5)
        ledger = Ledger.load(self.ws)
        self.assertEqual((ledger.claims["C1"]["status"], ledger.claims["C2"]["status"]), ("unchecked", "disputed"))


class RecheckBudgetConfigTests(unittest.TestCase):
    def test_presets_and_snapshot_carry_the_budget(self):
        self.assertEqual({k: v["recheck"] for k, v in config.DEPTH_PRESETS.items()},
                         {"quick": 0, "standard": 3, "deep": 5})
        for depth, n in (("quick", 0), ("standard", 3), ("deep", 5)):
            self.assertEqual(resolve_params(depth)["recheck"], n)


class RecheckInLoopTests(unittest.TestCase):
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
        return o, o.run("固态电池", **kw)

    def test_quick_budget_is_zero_so_the_checker_is_never_called(self):
        fake = FakeAgents([6.0, 7.0])
        self.run_with(fake, depth="quick", min_cycles=2, max_cycles=2)
        self.assertEqual(fake.recheck_calls, [])

    def test_budget_is_shared_across_rounds_and_stops_when_spent(self):
        fake = FakeAgents([6.0, 7.0, 8.0])
        self.run_with(fake, depth="standard", min_cycles=3, max_cycles=3)
        self.assertEqual([limit for _, limit in fake.recheck_calls], [3, 1])  # 每次核实 2 条：剩 3 -> 1 -> 用完

    def test_deep_budget_is_five(self):
        fake = FakeAgents([6.0, 7.0, 8.0, 8.5, 9.0])
        self.run_with(fake, depth="deep", min_cycles=5, max_cycles=5)
        self.assertEqual([limit for _, limit in fake.recheck_calls], [5, 3, 1])

    def test_it_runs_only_in_rounds_that_are_followed_by_a_rewrite(self):
        fake = FakeAgents([6.0, 7.0])
        self.run_with(fake, depth="standard", min_cycles=2, max_cycles=2)
        self.assertEqual(len(fake.recheck_calls), 1)  # 最后一轮评审后不再改写，补核也就没有意义

    def test_it_looks_at_the_current_best_draft(self):
        fake = FakeAgents([6.0, 7.0, 8.0])
        fake.draft_texts = {0: "DRAFT-0 [C1]", 1: "DRAFT-1 [C1]"}
        self.run_with(fake, depth="standard", min_cycles=3, max_cycles=3)
        self.assertEqual([t.split()[0] for t, _ in fake.recheck_calls], ["DRAFT-0", "DRAFT-1"])

    def test_a_failing_recheck_does_not_break_the_loop(self):
        fake = FakeAgents([6.0, 7.0, 8.0])
        fake.recheck_error = LLMError("down")
        o, result = self.run_with(fake, depth="standard", min_cycles=3, max_cycles=3)
        self.assertTrue(result.startswith("DRAFT-2"))
        self.assertEqual(len(fake.recheck_calls), 2)  # 失败不消耗预算，下一轮仍会再试


if __name__ == "__main__":
    unittest.main()
