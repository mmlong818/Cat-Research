"""W1 报告清理：声明表的状态用中文自然说法；写作提示词禁止台账状态词与修订痕迹；
确定性检查（英文状态词、修订日志）记为引用违规，进入阻塞项与最终稿选择。"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import orchestrator as orch_mod
from agents.writer import REPORT_FORMAT, WriterAgent
from research.ledger import NEITHER, REFS_MARKER, Ledger, check_citations, format_violations, with_references
from tests.test_orchestrator import FakeAgents
from tests.test_research_agents import _WS, _ok

STATUS_WORDS = ("supported", "disputed", "unverifiable", "overruled", "unchecked", "merged")


def _ledger():
    ws = tempfile.mkdtemp()
    ledger = Ledger.load(ws)
    for t in ("甲公司 2027 年量产", "乙公司 2028 年量产", "丙公司扩产", "丁公司试产", "戊公司送样"):
        ledger.add_claim(t, "https://src.com/" + t)
    return ledger, ws


class ClaimsTableChineseStatusTests(unittest.TestCase):
    def setUp(self):
        self.l, self.ws = _ledger()
        self.addCleanup(shutil.rmtree, self.ws, True)
        self.l.set_status("C2", "supported")
        self.l.set_status("C3", "unverifiable")
        self.l.resolve(self.l.add_contradiction("C4", "C5"), NEITHER, "口径不一")  # C4 / C5 存疑

    def test_statuses_are_chinese_and_unchecked_is_not_marked(self):
        lines = {line.split("]")[0] + "]": line for line in self.l.claims_table().splitlines() if line.startswith("[C")}
        self.assertEqual(lines["[C1]"], "[C1] 甲公司 2027 年量产  — 来源 S1")  # unchecked：不标注
        self.assertIn("[C2] (已核实) 乙公司", lines["[C2]"])
        self.assertIn("[C3] (待核实) 丙公司", lines["[C3]"])
        self.assertIn("[C4] (存疑) 丁公司", lines["[C4]"])

    def test_no_english_status_word_reaches_the_table(self):
        table = self.l.claims_table()
        for word in STATUS_WORDS:
            self.assertNotIn(word, table)


class StatusWordCheckTests(unittest.TestCase):
    def setUp(self):
        self.l, self.ws = _ledger()
        self.addCleanup(shutil.rmtree, self.ws, True)

    def hygiene(self, text, **kw):
        found = check_citations(self.l, text, **kw)["violations"]
        return [v for v in found if v["type"] in ("status_word", "revision_log")]

    def test_each_english_status_word_is_caught_as_a_standalone_word(self):
        for word in STATUS_WORDS:
            with self.subTest(word=word):
                v = self.hygiene(f"该说法 ({word}) 尚无定论 [C1]。")
                self.assertEqual([(x["type"], x["claim"]) for x in v], [("status_word", "")])
                self.assertIn(word, v[0]["detail"])

    def test_case_insensitive_and_glued_to_chinese(self):
        self.assertEqual(len(self.hygiene("状态：Disputed。")), 1)
        self.assertEqual(len(self.hygiene("该条目前为unverifiable状态。")), 1)

    def test_one_violation_per_distinct_word(self):
        v = self.hygiene("disputed 与 disputed，另一条 supported。")
        self.assertEqual(len(v), 2)
        self.assertEqual([w in v[0]["detail"] + v[1]["detail"] for w in ("disputed", "supported")], [True, True])

    def test_urls_citation_ids_and_ordinary_text_are_not_flagged(self):
        text = ("乙公司披露产能 [C12]，详见 https://example.com/supported/disputed?merged=1 与 "
                "[官方公告](https://x.com/unchecked)。\n\n各方说法不一，有待官方确认。")
        self.assertEqual(self.hygiene(text), [])
        self.assertEqual(self.hygiene("该方案 unsupported，也不是 supportedness 的问题；self-merged-cell。"), [])

    def test_generated_appendices_are_out_of_scope(self):
        self.l.set_status("C2", "supported")
        text, check = with_references(self.l, "正文只写自然语言 [C2]。")
        self.assertIn("## 声明来源", text)
        self.assertEqual(check["violations"], [])
        quality = text + "\n\n---\n## 研究质量报告\n\n| 维度 | 评分 |\n| disputed | supported |\n"
        self.assertEqual(self.hygiene(quality), [])
        self.assertEqual(self.hygiene(f"正文干净。{REFS_MARKER}- **[C1]** unchecked merged"), [])

    def test_english_reports_skip_the_status_word_check(self):
        text = "The claim is supported by the filing, although a rival figure is disputed."
        self.assertEqual(len(self.hygiene(text)), 2)
        self.assertEqual(self.hygiene(text, language="en"), [])

    def test_format_violations_reads_naturally_without_a_claim_id(self):
        out = format_violations(self.hygiene("该条 disputed。"))
        self.assertTrue(out.startswith("- 报告正文出现英文台账状态词"), out)
        self.assertNotIn("[]", out)


class RevisionLogCheckTests(unittest.TestCase):
    def setUp(self):
        self.l, self.ws = _ledger()
        self.addCleanup(shutil.rmtree, self.ws, True)

    def hits(self, text, **kw):
        return [v for v in check_citations(self.l, text, **kw)["violations"] if v["type"] == "revision_log"]

    def test_revision_headings_and_openers_are_caught(self):
        cases = ["## 修订说明\n\n1. 补充了车企", "# 报告\n\n> 本版修订：补充了宝马与奔驰",
                 "**改版说明**：本版调整了结构", "- 相比上一版，新增了三家厂商", "相较上一版，删除了重复表述",
                 "## 本版改动\n\n- 调整摘要", "与上一版相比，结论更谨慎", "根据评审意见，本版做了以下修改",
                 "第 2 版修订要点如下", "## 修订记录"]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(len(self.hits(text)), 1)

    def test_english_revision_logs_are_caught_in_both_languages(self):
        for text in ("## Revision Notes\n\n- added OEMs", "Changelog\n\n- v2",
                     "Changes from the previous version:\n- x", "Compared with the previous draft, this version adds"):
            for lang in ("zh", "en"):
                with self.subTest(text=text, language=lang):
                    self.assertEqual(len(self.hits(text, language=lang)), 1)

    def test_normal_text_is_not_flagged(self):
        for text in ("相比上一代产品，新电池能量密度提升 [C1]。", "报告摘要：全固态电池预计 2027 年小批量量产。",
                     "## 引言\n\n该标准的修订说明了硫化物路线的要求。", "宝马计划于 2027 年示范运行 [C1]。",
                     "The revision of the standard took effect in 2026."):
            with self.subTest(text=text):
                self.assertEqual(self.hits(text), [])

    def test_violation_detail_quotes_the_offending_line(self):
        v = self.hits("# 标题\n\n正文。\n\n## 修订说明\n- 补充了车企")
        self.assertIn("修订说明", v[0]["detail"])
        self.assertEqual(v[0]["claim"], "")


class WriterCleanRulesTests(_WS):
    def prompt(self, **kw):
        self.put("05_analysis.md", "分析A")
        self.put("06_drafts/draft_0.md", "上一版D0")
        ledger = Ledger.load(self.ws)
        ledger.add_claim("甲公司 2027 年量产", "https://a.com")
        ledger.set_status("C1", "disputed")
        ledger.save()
        self.patch_call(_ok(text="# 报告"))
        WriterAgent().write_draft(self.ws, "问题", **kw)
        return self.reqs[0].prompt

    def test_report_format_forbids_status_tags_and_revision_traces(self):
        for needle in ("supported", "disputed", "unverifiable", "有待官方确认", "各方说法不一",
                       "修订说明", "改版日志", "本版", "上一版"):
            self.assertIn(needle, REPORT_FORMAT)

    def test_draft_and_rewrite_prompts_carry_the_rules_and_chinese_status(self):
        for kw in ({"draft_num": 0}, {"draft_num": 1}):
            p = self.prompt(**kw)
            self.assertIn("不得在报告中输出台账状态标签", p)
            self.assertIn("[C1] (存疑) 甲公司", p)
            self.assertNotIn("(disputed)", p)

    def test_rewrite_says_review_feedback_is_not_to_be_narrated(self):
        self.assertIn("不要在报告中说明改了什么", self.prompt(draft_num=1))


class HygieneBlocksTheLoopTests(unittest.TestCase):
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

    def test_dirty_draft_is_fed_back_and_final_avoids_it(self):
        fake = FakeAgents([7.0, 8.0])
        fake.draft_texts = {0: "DRAFT-0 [C1]。\n\n## 修订说明\n- 补充车企", 1: "DRAFT-1 事实 [C1]。"}
        _, result = self.run_with(fake, min_cycles=2, max_cycles=2)
        self.assertIn("修订", fake.citation_issues[1])  # 改写收到了上一版的修订痕迹问题
        self.assertTrue(result.startswith("DRAFT-1"))
        self.assertNotIn("引用问题", result)

    def test_best_scored_draft_with_status_words_is_not_the_final(self):
        fake = FakeAgents([7.0, 8.0])
        fake.draft_texts = {0: "DRAFT-0 [C1]。", 1: "DRAFT-1 该说法 disputed [C1]。"}
        _, result = self.run_with(fake, min_cycles=2, max_cycles=2)
        self.assertTrue(result.startswith("DRAFT-0"))

    def test_status_words_block_quality_exit(self):
        fake = FakeAgents([7.5, 8.2, 8.3], conclusion_avg=7.8)
        fake.draft_texts = {1: "DRAFT-1 该说法 unverifiable [C1]。", 2: "DRAFT-2 干净 [C1]。"}
        o, _ = self.run_with(fake, min_cycles=2, max_cycles=5)
        with open(os.path.join(o.workspace, "00_session.json"), encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual((meta["total_cycles"], meta["final_draft"]), (3, 2))

    def test_english_task_does_not_flag_ordinary_english_words(self):
        fake = FakeAgents([7.0, 8.0])
        fake.draft_texts = {0: "DRAFT-0 [C1].", 1: "DRAFT-1 The claim is supported by the filing [C1]."}
        _, result = self.run_with(fake, min_cycles=2, max_cycles=2, language="en")
        self.assertTrue(result.startswith("DRAFT-1"))


if __name__ == "__main__":
    unittest.main()
