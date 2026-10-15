"""Z1/Z3 原文片段与「摘录待核」：登记时附原文片段、按来源存储、确定性核对后给声明打标记，
标记进声明表 / 核查优先级 / 报告清洁检查，独立核实 supported 后清除。"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from agents import fact_checker as fc_mod
from agents import researcher as researcher_mod
from agents.analyst import AnalystAgent
from agents.fact_checker import FactCheckerAgent, pick_for_verification, pick_load_bearing
from agents.researcher import RESEARCH_SCHEMA, ResearcherAgent
from agents.writer import REPORT_FORMAT, _materials
from research.ledger import Ledger, check_citations, report_hygiene_violations
from tests.test_fact_primary_source import _check
from tests.test_research_agents import _WS, PLAN, _notes, _ok

C17 = "三星 SDI 全固态电池 2027 年第二季度量产"
SMM = "mass production is scheduled to begin in the second half of 2027"
GOOD = "三星 SDI 计划 2027 年下半年量产"
TAG = "(摘录待核)"


def _ledger():
    ws = tempfile.mkdtemp()
    return Ledger.load(ws), ws


class QuoteStorageTests(unittest.TestCase):
    def setUp(self):
        self.l, self.ws = _ledger()
        self.addCleanup(shutil.rmtree, self.ws, True)

    def test_quote_is_stored_per_source(self):
        cid, _ = self.l.add_claim("甲公司 2027 年量产", "https://a.com/1", quote="甲公司宣布 2027 年量产")
        self.assertEqual(self.l.claims[cid]["quotes"], {"S1": "甲公司宣布 2027 年量产"})

    def test_duplicate_text_adds_the_new_sources_quote(self):
        self.l.add_claim("甲公司 2027 年量产", "https://a.com/1", quote="Q-A 2027")
        cid, new = self.l.add_claim("甲公司2027年量产", "https://b.com/2", quote="Q-B 2027")
        self.assertFalse(new)
        self.assertEqual(self.l.claims[cid]["sources"], ["S1", "S2"])
        self.assertEqual(self.l.claims[cid]["quotes"], {"S1": "Q-A 2027", "S2": "Q-B 2027"})

    def test_same_source_again_keeps_the_first_non_empty_quote(self):
        self.l.add_claim("甲公司 2027 年量产", "https://a.com/1", quote="首条 2027")
        self.l.add_claim("甲公司 2027 年量产", "https://a.com/1", quote="")
        self.l.add_claim("甲公司 2027 年量产", "https://a.com/1", quote="另一条 2027")
        self.assertEqual(self.l.claims["C1"]["quotes"], {"S1": "首条 2027"})

    def test_empty_quote_is_recorded_as_empty(self):
        self.l.add_claim("甲公司 2027 年量产", "https://a.com/1", quote="")
        self.assertEqual(self.l.claims["C1"]["quotes"], {"S1": ""})

    def test_quote_is_trimmed_and_truncated_to_300_chars(self):
        self.l.add_claim("甲公司 2027 年量产", "https://a.com/1", quote="  " + "字" * 400 + "  ")
        self.assertEqual(self.l.claims["C1"]["quotes"]["S1"], "字" * 300)

    def test_legacy_calls_without_quote_store_nothing_and_never_flag(self):
        self.l.add_claim("甲公司 2027 年量产", "https://a.com/1")
        self.assertNotIn("quotes", self.l.claims["C1"])
        self.assertNotIn("extraction", self.l.claims["C1"])

    def test_claim_without_a_source_cannot_hold_a_quote(self):
        self.l.add_claim("甲公司 2027 年量产", quote="甲公司 2027 年量产")
        self.assertNotIn("quotes", self.l.claims["C1"])
        self.assertNotIn("extraction", self.l.claims["C1"])

    def test_quotes_and_extraction_survive_save_and_load(self):
        self.l.add_claim(C17, "https://a.com/1", quote=SMM)
        self.l.save()
        again = Ledger.load(self.ws)
        self.assertEqual(again.claims["C1"]["quotes"], {"S1": SMM})
        self.assertFalse(again.claims["C1"]["extraction"]["ok"])

    def test_old_ledger_file_without_quotes_loads_and_works(self):
        os.makedirs(os.path.join(self.ws, "08_verification"))
        old = {"sources": {"S1": {"url": "https://a.com", "title": "", "published": "", "round": 1}},
               "claims": {"C1": {"text": "甲公司 2027 年量产", "sources": ["S1"], "round": 1,
                                 "status": "unchecked", "note": ""}}, "contradictions": {}}
        with open(os.path.join(self.ws, "08_verification", "ledger.json"), "w", encoding="utf-8") as f:
            json.dump(old, f)
        ledger = Ledger.load(self.ws)
        self.assertIn("[C1] 甲公司 2027 年量产", ledger.claims_table())
        ledger.add_claim("甲公司 2027 年量产", "https://b.com", quote="甲公司 2027 年量产")
        self.assertNotIn("extraction", ledger.claims["C1"])

    def test_merge_combines_quotes(self):
        self.l.add_claim("甲公司 2027 年量产", "https://a.com/1", quote="Q-A 2027")
        self.l.add_claim("甲公司计划于 2027 年量产", "https://b.com/2", quote="Q-B 2027")
        self.l.merge("C1", "C2")
        self.assertEqual(self.l.claims["C1"]["quotes"], {"S1": "Q-A 2027", "S2": "Q-B 2027"})
        self.assertEqual(self.l.claims["C1"]["sources"], ["S1", "S2"])


class ExtractionFlagTests(unittest.TestCase):
    def setUp(self):
        self.l, self.ws = _ledger()
        self.addCleanup(shutil.rmtree, self.ws, True)

    def test_c17_is_flagged_with_detail_and_status_is_untouched(self):
        cid, _ = self.l.add_claim(C17, "https://smm.com/a", quote=SMM)
        ex = self.l.claims[cid]["extraction"]
        self.assertIs(ex["ok"], False)
        self.assertIn("Q2", ex["detail"])
        self.assertEqual(self.l.claims[cid]["status"], "unchecked")

    def test_consistent_quote_leaves_no_flag(self):
        cid, _ = self.l.add_claim(GOOD, "https://smm.com/a", quote=SMM)
        self.assertNotIn("extraction", self.l.claims[cid])

    def test_missing_quote_is_flagged_as_missing(self):
        cid, _ = self.l.add_claim(GOOD, "https://smm.com/a", quote="")
        self.assertEqual(self.l.claims[cid]["extraction"], {"ok": False, "detail": "S1：缺原文片段"})

    def test_a_later_source_with_a_consistent_quote_clears_the_flag(self):
        cid, _ = self.l.add_claim(GOOD, "https://smm.com/a", quote="")
        self.l.add_claim(GOOD, "https://b.com/b", quote=SMM)
        self.assertNotIn("extraction", self.l.claims[cid])

    def test_a_later_source_with_a_bad_quote_keeps_the_flag_and_adds_detail(self):
        cid, _ = self.l.add_claim(C17, "https://smm.com/a", quote=SMM)
        self.l.add_claim(C17, "https://b.com/b", quote="")
        ex = self.l.claims[cid]["extraction"]
        self.assertFalse(ex["ok"])
        self.assertIn("S1", ex["detail"])
        self.assertIn("S2：缺原文片段", ex["detail"])

    def test_one_consistent_source_among_bad_ones_means_no_flag(self):
        cid, _ = self.l.add_claim(GOOD, "https://smm.com/a", quote="")
        self.l.add_claim(GOOD, "https://b.com/b", quote="2026 年底")
        self.assertFalse(self.l.claims[cid]["extraction"]["ok"])
        self.l.add_claim(GOOD, "https://c.com/c", quote=SMM)
        self.assertNotIn("extraction", self.l.claims[cid])

    def test_a_bad_later_source_does_not_flag_a_claim_with_a_consistent_source(self):
        cid, _ = self.l.add_claim(GOOD, "https://smm.com/a", quote=SMM)
        self.l.add_claim(GOOD, "https://b.com/b", quote="")
        self.assertNotIn("extraction", self.l.claims[cid])

    def test_detail_is_capped(self):
        for i in range(30):
            self.l.add_claim(C17, f"https://s{i}.com/x", quote="")
        self.assertLessEqual(len(self.l.claims["C1"]["extraction"]["detail"]), 300)

    def test_merge_recomputes_the_flag_from_the_combined_quotes(self):
        self.l.add_claim(GOOD, "https://a.com/1", quote="")           # C1：缺片段，被标记
        self.l.add_claim("三星 SDI 将在 2027 年下半年开始量产", "https://b.com/2", quote=SMM)  # C2：一致
        self.assertIn("extraction", self.l.claims["C1"])
        self.l.merge("C1", "C2")
        self.assertNotIn("extraction", self.l.claims["C1"])

    def test_merge_of_legacy_claims_does_not_create_flags(self):
        self.l.add_claim("甲 2027 量产", "https://a.com/1")
        self.l.add_claim("甲于 2027 年量产", "https://b.com/2")
        self.l.merge("C1", "C2")
        self.assertNotIn("extraction", self.l.claims["C1"])

    def test_clear_extraction(self):
        self.l.add_claim(C17, "https://a.com/1", quote=SMM)
        self.l.clear_extraction("C1")
        self.assertNotIn("extraction", self.l.claims["C1"])
        self.l.clear_extraction("C1")  # 没有标记时无事发生

    def test_extraction_issue_claims_lists_flagged_ids_only(self):
        self.l.add_claim(C17, "https://a.com/1", quote=SMM)
        self.l.add_claim(GOOD, "https://a.com/2", quote=SMM)
        self.l.add_claim("没有来源的声明")
        self.assertEqual(self.l.extraction_issue_claims(), {"C1"})


class ClaimsTableTests(unittest.TestCase):
    def setUp(self):
        self.l, self.ws = _ledger()
        self.addCleanup(shutil.rmtree, self.ws, True)

    def test_flagged_claim_gets_the_tag_after_the_status_label(self):
        self.l.add_claim(C17, "https://www.reuters.com/a", quote=SMM)
        self.assertIn(f"[C1] {TAG} {C17}", self.l.claims_table())
        self.l.set_status("C1", "unverifiable")
        self.assertIn(f"[C1] (待核实) {TAG} {C17}", self.l.claims_table())

    def test_tag_follows_the_low_credibility_tag(self):
        self.l.add_claim(C17, "https://weibo.com/1", quote=SMM)
        self.assertIn(f"[C1] (来源可信度低) {TAG} {C17}", self.l.claims_table())

    def test_unflagged_and_legacy_claims_have_no_tag(self):
        self.l.add_claim(GOOD, "https://www.reuters.com/a", quote=SMM)
        self.l.add_claim("没有片段信息的旧声明 2027", "https://www.reuters.com/b")
        self.assertNotIn("摘录待核", self.l.claims_table())

    def test_tag_clears_with_the_flag(self):
        self.l.add_claim(C17, "https://www.reuters.com/a", quote=SMM)
        self.l.clear_extraction("C1")
        self.assertNotIn("摘录待核", self.l.claims_table())


class LabelLeakTests(unittest.TestCase):
    def test_tag_in_the_report_body_is_a_violation(self):
        out = report_hygiene_violations("三星 SDI 计划量产（摘录待核）[C1]。")
        self.assertEqual([v["type"] for v in out], ["label_leak"])
        self.assertIn("摘录待核", out[0]["detail"])

    def test_bare_phrase_is_also_caught_but_appendix_and_english_are_not(self):
        self.assertTrue(report_hygiene_violations("该声明摘录待核。"))
        self.assertEqual(report_hygiene_violations("正文。\n\n---\n## 声明来源\n- [C1] x（摘录待核）\n"), [])
        self.assertEqual(report_hygiene_violations("Body text.", "en"), [])

    def test_flows_through_check_citations(self):
        ledger, ws = _ledger()
        self.addCleanup(shutil.rmtree, ws, True)
        ledger.add_claim(C17, "https://a.com", quote=SMM)
        r = check_citations(ledger, "三星 SDI (摘录待核) 量产 [C1]。")
        self.assertIn("label_leak", [v["type"] for v in r["violations"]])


class PromptTests(_WS):
    def test_report_format_and_analyst_prompt_carry_the_rule(self):
        self.patch_call(_ok(text="# 分析"))
        AnalystAgent().analyze(self.ws, "问题")
        for text in (REPORT_FORMAT, self.reqs[0].prompt):
            for needle in ("摘录待核", "限定语", "唯一依据"):
                with self.subTest(needle=needle):
                    self.assertIn(needle, text)
        self.assertIn("原样", REPORT_FORMAT)

    def test_flagged_tag_reaches_writer_materials_and_analyst_prompt(self):
        ledger = Ledger.load(self.ws)
        ledger.add_claim(C17, "https://www.reuters.com/a", quote=SMM)
        ledger.save()
        self.assertIn(f"[C1] {TAG} {C17}", _materials(self.ws))
        self.patch_call(_ok(text="# 分析"))
        AnalystAgent().analyze(self.ws, "问题")
        self.assertIn(f"[C1] {TAG} {C17}", self.reqs[0].prompt)


class PickerTests(unittest.TestCase):
    def setUp(self):
        self.l, self.ws = _ledger()
        self.addCleanup(shutil.rmtree, self.ws, True)

    def good(self, text):
        return self.l.add_claim(text, f"https://www.reuters.com/{len(self.l.claims)}", quote=text)[0]

    def flagged(self, text):
        return self.l.add_claim(text, f"https://www.reuters.com/{len(self.l.claims)}", quote="")[0]

    def low(self, text):
        return self.l.add_claim(text, f"https://weibo.com/{len(self.l.claims)}", quote=text)[0]

    def test_flagged_claim_outranks_a_low_credibility_claim(self):
        c1 = self.low("某地良率 70%")
        c2 = self.flagged("某地良率 80%")
        self.assertEqual(pick_for_verification(self.l, 8), [c2, c1])

    def test_flagged_claim_outranks_a_better_ranked_ordinary_claim(self):
        c1 = self.good("工信部发布 A 通知")   # 一手关键词
        c2 = self.flagged("某地良率 80%")      # 只含数字，但被标记
        self.assertEqual(pick_for_verification(self.l, 8), [c2, c1])

    def test_flagged_and_low_credibility_share_at_most_half_the_quota(self):
        ordinary = [self.good(f"工信部发布 {i} 号通知") for i in range(1, 5)]
        flagged = [self.flagged(f"某地良率 {i}%") for i in range(11, 14)]
        low = [self.low(f"某地产线 {i} 投产") for i in range(21, 24)]
        picked = pick_for_verification(self.l, 4)
        self.assertEqual(len(picked), 4)
        self.assertEqual(sum(1 for c in picked if c in flagged + low), 2)
        self.assertEqual(picked[:2], [flagged[0], flagged[1]])  # 队内摘录待核优先
        self.assertEqual(picked[2:], ordinary[:2])

    def test_unused_risk_quota_goes_back_to_the_others_and_vice_versa(self):
        ordinary = [self.good(f"工信部发布 {i} 号通知") for i in range(1, 4)]
        f1 = self.flagged("某地良率 70%")
        self.assertEqual(pick_for_verification(self.l, 4), [f1] + ordinary)
        l2, ws = _ledger()
        self.addCleanup(shutil.rmtree, ws, True)
        only = [l2.add_claim(f"某地良率 {i}%", f"https://weibo.com/{i}", quote="")[0] for i in range(1, 5)]
        self.assertEqual(pick_for_verification(l2, 3), only[:3])

    def test_flagged_claim_without_digits_or_keywords_is_still_a_candidate(self):
        c = self.flagged("新电池预计年底前上市")
        self.assertIn("extraction", self.l.claims[c])
        self.assertEqual(pick_for_verification(self.l, 8), [c])

    def test_ordinary_claim_without_digits_or_keywords_is_not_a_candidate(self):
        self.l.add_claim("丰田推出了新电池", "https://www.reuters.com/x", quote="Toyota unveiled a new battery")
        self.assertEqual(pick_for_verification(self.l, 8), [])

    def test_checked_flagged_claim_is_not_picked_again(self):
        c = self.flagged("某地良率 80%")
        self.l.set_status(c, "unverifiable")
        self.assertEqual(pick_for_verification(self.l, 8), [])

    def test_load_bearing_puts_flagged_first_and_shares_the_half_quota(self):
        ordinary = [self.good(f"工信部发布 {i} 号通知") for i in range(1, 4)]
        f1 = self.flagged("工信部发布 90 号通知")
        text = " ".join(f"[{c}]" * (n + 1) for n, c in enumerate(ordinary)) + f" [{f1}]"
        self.assertEqual(pick_load_bearing(self.l, text, 10)[0], f1)
        picked = pick_load_bearing(self.l, text, 2)
        self.assertEqual(picked, [f1, ordinary[2]])  # 高风险队 1 个名额 + 其余被引最多者


class ClearOnVerificationTests(unittest.TestCase):
    def setUp(self):
        self.l, self.ws = _ledger()
        self.addCleanup(shutil.rmtree, self.ws, True)
        self.l.add_claim("工信部发布 A 通知，2027 年第二季度施行", "https://www.reuters.com/a", quote=SMM)
        self.l.add_claim("工信部发布 B 通知，2027 年第二季度施行", "https://www.reuters.com/b", quote=SMM)
        self.l.save()

    def run_check(self, verdicts):
        out = [_check(v, t) for v, t in verdicts]
        with mock.patch.object(fc_mod, "cross_reference_claims", return_value=out):
            FactCheckerAgent().check_facts(self.ws, limit=2)
        return Ledger.load(self.ws)

    def test_supported_with_strong_evidence_clears_the_flag(self):
        ledger = self.run_check([("supported", "primary"), ("supported", "authority")])
        self.assertTrue(all("extraction" not in c for c in ledger.claims.values()))

    def test_other_outcomes_keep_the_flag(self):
        ledger = self.run_check([("supported", "media"), ("disputed", "primary")])
        self.assertEqual([c["status"] for c in ledger.claims.values()], ["unverifiable", "disputed"])
        self.assertTrue(all(c["extraction"]["ok"] is False for c in ledger.claims.values()))

    def test_recheck_clears_the_flag_on_supported(self):
        out = [_check("supported", "primary")]
        with mock.patch.object(fc_mod, "cross_reference_claims", return_value=out):
            targets = FactCheckerAgent().recheck(self.ws, "[C1] [C1] [C2]", 1)
        ledger = Ledger.load(self.ws)
        self.assertEqual(targets, ["C1"])
        self.assertNotIn("extraction", ledger.claims["C1"])
        self.assertIn("extraction", ledger.claims["C2"])


class ResearcherSchemaTests(unittest.TestCase):
    def claim_schema(self):
        return RESEARCH_SCHEMA["properties"]["claims"]["items"]

    def test_quote_is_a_required_string_and_schema_stays_strict(self):
        s = self.claim_schema()
        self.assertEqual(s["properties"]["quote"]["type"], "string")
        self.assertEqual(sorted(s["required"]), sorted(s["properties"]))
        self.assertIn("quote", s["required"])
        self.assertIs(s["additionalProperties"], False)
        self.assertIs(RESEARCH_SCHEMA["additionalProperties"], False)

    def test_prompt_demands_verbatim_quotes_from_opened_pages(self):
        p = ResearcherAgent()._group_prompt(PLAN, [{"query": "q"}], 1)
        for needle in ("quote", "300", "原样", "不得改写", "不得翻译", "不得拼接", "搜索摘要", "notes",
                       "仅见于搜索摘要", "英文来源保留英文原文", "数字", "时间"):
            with self.subTest(needle=needle):
                self.assertIn(needle, p)

class ResearcherIngestTests(_WS):
    def _run(self, claims):
        def fake_many(reqs, max_concurrency):
            return [_notes("n", claims) for _ in reqs]

        with mock.patch.object(researcher_mod, "call_many", side_effect=fake_many):
            ResearcherAgent().research(self.ws, PLAN, round_num=1)
        return Ledger.load(self.ws)

    def test_quotes_are_stored_and_c17_is_flagged_at_ingest(self):
        ledger = self._run([(C17, "https://smm.com/a", SMM), (GOOD + "（另一条）", "https://smm.com/b", SMM)])
        self.assertEqual(ledger.claims["C1"]["quotes"], {"S1": SMM})
        self.assertFalse(ledger.claims["C1"]["extraction"]["ok"])
        self.assertNotIn("extraction", ledger.claims["C2"])
        self.assertEqual(ledger.claims["C1"]["status"], "unchecked")

    def test_empty_quote_from_the_researcher_is_flagged_missing(self):
        ledger = self._run([(GOOD, "https://smm.com/a", "")])
        self.assertIn("缺原文片段", ledger.claims["C1"]["extraction"]["detail"])

    def test_duplicate_claim_from_another_group_with_a_good_quote_clears_the_flag(self):
        calls = iter([[(GOOD, "https://smm.com/a", "")], [(GOOD, "https://b.com/b", SMM)]])

        def fake_many(reqs, max_concurrency):
            return [_notes("n", next(calls)) for _ in reqs[:2]] + [_notes("n") for _ in reqs[2:]]

        with mock.patch.object(researcher_mod, "call_many", side_effect=fake_many):
            ResearcherAgent().research(self.ws, PLAN, round_num=1)
        ledger = Ledger.load(self.ws)
        self.assertEqual(ledger.claims["C1"]["sources"], ["S1", "S2"])
        self.assertNotIn("extraction", ledger.claims["C1"])


if __name__ == "__main__":
    unittest.main()
