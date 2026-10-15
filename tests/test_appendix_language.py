"""程序生成的报告附录（声明来源 / 研究质量报告 / 引用问题）跟随报告语言；
按附录标题切分、识别的地方对中英两种标题都有效（旧报告与新报告通用）；中文报告的附录保持原样。"""
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

import orchestrator as orch_mod
from research.ledger import (
    QUALITY_HEADINGS,
    REFS_HEADINGS,
    VIOLATIONS_HEADINGS,
    Ledger,
    body_of,
    check_citations,
    format_violations,
    report_hygiene_violations,
    with_references,
)
from research.loop_policy import LoopState
from tests.test_language import AGENTS
from tests.test_orchestrator import FakeAgents
from tools.eval import judge

CJK = re.compile(r"[一-鿿]")
CONF = {"overall_confidence": 0.82,
        "breakdown": {"source_quality": {"quality_rating": "good"},
                      "fact_accuracy": {"score": 0.9},
                      "conclusion_validity": {"score": None}}}

ZH_QUALITY_GOLDEN = """

---
## 研究质量报告

| 维度 | 评分 |
|------|------|
| 综合置信度 | 82% |
| 来源质量 | good |
| 事实准确度 | 90% |
| 结论有效性 | N/A（未完成） |
| 评审轮数 | 2 轮 |
| 最终评审分 | 7.5/10（第 1 版） |

*本报告由多智能体研究系统自动生成，包含来源验证、事实核查和结论验证流程*
"""


def make_ledger() -> Ledger:
    ledger = Ledger()
    ledger.add_claim("甲公司 2026 年量产", "https://a.com/1")      # C1
    ledger.add_claim("乙公司尚无公开来源")                          # C2
    return ledger


class HeadingConstantsTests(unittest.TestCase):
    def test_both_languages_are_defined_for_every_appendix(self):
        for table in (REFS_HEADINGS, QUALITY_HEADINGS, VIOLATIONS_HEADINGS):
            self.assertEqual(sorted(table), ["en", "zh"])
        self.assertEqual((REFS_HEADINGS["zh"], QUALITY_HEADINGS["zh"]), ("声明来源", "研究质量报告"))
        self.assertEqual((REFS_HEADINGS["en"], QUALITY_HEADINGS["en"]),
                         ("Claim sources", "Research quality report"))
        self.assertEqual(VIOLATIONS_HEADINGS["en"], "Citation issues (not resolved during revision)")


class LedgerAppendixTests(unittest.TestCase):
    def setUp(self):
        self.l = make_ledger()

    def test_zh_appendix_is_unchanged(self):
        text, _ = with_references(self.l, "正文 [C1] [C2]。")
        self.assertEqual(text, "正文 [C1] [C2]。\n\n---\n## 声明来源\n"
                               "- **[C1]** 甲公司 2026 年量产 — https://a.com/1\n"
                               "- **[C2]** 乙公司尚无公开来源 — （无来源）\n")
        empty, _ = with_references(self.l, "没有引用。")
        self.assertTrue(empty.endswith("\n\n---\n## 声明来源\n（正文未引用任何声明）\n"))

    def test_en_appendix_uses_english_heading_and_fixed_text(self):
        text, _ = with_references(self.l, "Body [C1] [C2].", "en")
        self.assertEqual(text, "Body [C1] [C2].\n\n---\n## Claim sources\n"
                               "- **[C1]** 甲公司 2026 年量产 — https://a.com/1\n"
                               "- **[C2]** 乙公司尚无公开来源 — (no source)\n")
        empty, _ = with_references(self.l, "Nothing cited.", "en")
        self.assertTrue(empty.endswith("\n\n---\n## Claim sources\n(no claims cited in the body)\n"))

    def test_en_appendix_joins_multiple_urls_in_english_style(self):
        self.l.add_claim("甲公司 2026 年量产", "https://b.com/2")  # 同一声明追加第二个来源
        text, _ = with_references(self.l, "Body [C1].", "en")
        self.assertIn("— https://a.com/1; https://b.com/2\n", text)
        zh, _ = with_references(self.l, "正文 [C1]。")
        self.assertIn("— https://a.com/1；https://b.com/2\n", zh)

    def test_body_of_strips_either_heading(self):
        for lang in ("zh", "en"):
            text, _ = with_references(self.l, "Body [C1].", lang)
            self.assertEqual(body_of(text), "Body [C1].")
        self.assertEqual(body_of("旧报告 [C1]\n\n---\n## 声明来源\n- **[C1]** x"), "旧报告 [C1]")
        self.assertEqual(body_of("old [C1]\n\n---\n## Claim sources\n- **[C1]** x"), "old [C1]")

    def test_regenerating_replaces_the_appendix_even_when_the_language_differs(self):
        zh, _ = with_references(self.l, "正文 [C1]。")
        en, _ = with_references(self.l, zh, "en")  # 旧中文稿以英文重新生成：替换而非叠加
        self.assertEqual((en.count("## "), "## Claim sources" in en, "声明来源" in en), (1, True, False))
        back, _ = with_references(self.l, en)
        self.assertEqual((back.count("## "), "## 声明来源" in back, "Claim sources" in back), (1, True, False))

    def test_citation_counts_ignore_the_english_appendix(self):
        from research.ledger import citation_counts
        text, _ = with_references(self.l, "Body [C1]。", "en")
        self.assertEqual(citation_counts(self.l, text), {"C1": 1})

    def test_format_violations_has_an_english_variant(self):
        v = check_citations(self.l, "[C9]")["violations"]
        self.assertTrue(format_violations(v).startswith("- [C9] 不存在的声明编号"))
        self.assertTrue(format_violations(v, "en").startswith("- [C9] Claim ID not in the ledger: "))


class HygieneExcludesAppendixTests(unittest.TestCase):
    def test_english_appendices_are_out_of_scope_in_both_languages(self):
        appendix = ("\n\n---\n## Claim sources\n- **[C1]** unchecked merged disputed 本版修订\n"
                    "\n\n---\n## Research quality report\n\n| disputed | supported |\n")
        for lang in ("zh", "en"):
            self.assertEqual(report_hygiene_violations("Clean body [C1]." + appendix, lang), [], lang)

    def test_chinese_appendices_still_out_of_scope(self):
        appendix = "\n\n---\n## 声明来源\n- **[C1]** unchecked merged\n\n---\n## 研究质量报告\n| disputed |\n"
        self.assertEqual(report_hygiene_violations("正文干净 [C1]。" + appendix), [])

    def test_body_text_before_the_appendix_is_still_checked(self):
        text = "该条 disputed。\n\n---\n## Claim sources\n- **[C1]** x"
        self.assertEqual(len(report_hygiene_violations(text)), 1)

    def test_a_longer_heading_that_merely_starts_like_an_appendix_is_body(self):
        text = "## Research quality reporting in practice\n该条 disputed。"
        self.assertEqual(len(report_hygiene_violations("Intro\n" + text)), 1)


class JudgeAnonymizeTests(unittest.TestCase):
    def test_both_quality_headings_are_cut(self):
        for heading in QUALITY_HEADINGS.values():
            out = judge.anonymize(f"# Report\nbody\n\n---\n## {heading}\nscore 8.1")
            self.assertEqual(out.strip(), "# Report\nbody", heading)


class OrchestratorAppendixTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        p = mock.patch.object(orch_mod, "WORKSPACE_DIR", self.root)
        p.start()
        self.addCleanup(p.stop)

    def orchestrator(self, fake):
        o = orch_mod.ResearchOrchestrator()
        for name in AGENTS:
            setattr(o, name, fake)
        o._agents = []
        return o

    def run_report(self, language):
        fake = FakeAgents([7.0, 7.5])
        fake.draft_texts = {0: "DRAFT-0 [C1]。", 1: "DRAFT-1 [C1]。"}
        o = self.orchestrator(fake)
        return o.run("固态电池", min_cycles=2, max_cycles=2, language=language)

    def test_english_report_gets_english_appendices(self):
        report = self.run_report("en")
        self.assertIn("\n## Claim sources\n", report)
        self.assertIn("\n## Research quality report\n", report)
        self.assertNotIn("声明来源", report)
        self.assertNotIn("研究质量报告", report)
        quality = report.split("## Research quality report")[1]
        self.assertIsNone(CJK.search(quality), quality)
        self.assertIn("Overall confidence", quality)

    def test_chinese_report_keeps_chinese_appendices(self):
        report = self.run_report("zh")
        self.assertIn("\n## 声明来源\n", report)
        self.assertIn("\n## 研究质量报告\n", report)
        self.assertNotIn("Claim sources", report)
        self.assertNotIn("Research quality report", report)

    def test_zh_quality_appendix_is_byte_identical_to_before(self):
        o = self.orchestrator(FakeAgents([]))
        state = LoopState(scores=[7.0, 7.5])
        self.assertEqual(o._quality_appendix(CONF, state, 1, 7.5), ZH_QUALITY_GOLDEN)

    def test_en_quality_appendix_has_no_chinese(self):
        o = self.orchestrator(FakeAgents([]))
        o._language = "en"
        state = LoopState(scores=[7.0, 7.5])
        text = o._quality_appendix(CONF, state, 1, 7.5)
        self.assertIsNone(CJK.search(text), text)
        self.assertIn("## Research quality report", text)
        self.assertIn("N/A (incomplete)", text)
        self.assertIn("7.5/10 (draft 1)", text)

    def test_violations_appendix_follows_language(self):
        check = {"violations": [{"type": "unknown", "claim": "C9", "detail": "x"}]}
        zh = orch_mod._violations_appendix(check)
        en = orch_mod._violations_appendix(check, "en")
        self.assertTrue(zh.startswith("\n\n## 引用问题（未能在改进轮次中消除）\n- [C9] 不存在的声明编号"))
        self.assertTrue(en.startswith("\n\n## Citation issues (not resolved during revision)\n"
                                      "- [C9] Claim ID not in the ledger"))
        self.assertEqual(orch_mod._violations_appendix({"violations": []}, "en"), "")

    def test_annotate_writes_the_appendix_in_the_report_language(self):
        o = self.orchestrator(FakeAgents([7.0]))
        o.run("固态电池", min_cycles=1, max_cycles=1, language="en")
        with open(os.path.join(o.workspace, "06_drafts", "draft_0.md"), encoding="utf-8") as f:
            self.assertIn("## Claim sources", f.read())


if __name__ == "__main__":
    unittest.main()
