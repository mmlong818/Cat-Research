"""X3 禁止无限定的「不存在」断言：写作提示词的规则，以及 report_hygiene_violations 的 absence_claim 确定性检查
（中文：只见于 / 仅见于 / 唯一来源 等，同一句无「本研究 / 检索到」等范围限定才算违规；英文同理；附录与 URL 不查）。"""
import unittest

from agents.writer import REPORT_FORMAT
from research.ledger import (
    VIOLATION_LABELS,
    VIOLATION_LABELS_EN,
    Ledger,
    check_citations,
    format_violations,
    report_hygiene_violations,
)


def absence(text, language="zh"):
    return [v for v in report_hygiene_violations(text, language) if v["type"] == "absence_claim"]


class ChineseAbsenceTests(unittest.TestCase):
    def test_unqualified_absence_claims_are_caught(self):
        cases = ["清陶昆山 10GWh 的这一数字目前只见于该来源 [C179]。", "该产线仅见于一篇报道。", "这是唯一来源。",
                 "仅见于一份报告。", "只见于单一来源。", "这一数据仅见于此文章。",
                 "该说法是唯一的来源 [C3]。", "目前没有其他来源印证。", "没有其他报道提及此事。",
                 "未见其他来源证实。", "未见其他报道。"]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(len(absence(text)), 1)

    def test_scope_qualified_sentences_are_not_flagged(self):
        cases = ["本研究检索到的来源中，该数字仅见于该来源 [C179]。", "在检索到的来源中仅见于一篇报道。",
                 "本次检索未见其他报道。", "我们检索到的资料中没有其他来源印证。", "据本研究所见，这是唯一来源。"]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(absence(text), [])

    def test_hedges_about_the_kind_of_source_are_not_absence_claims(self):
        cases = ["含量阈值目前只见于媒体转述 [C1]。", "该数字只见于二手摘要 [C2]。",
                 "坪山良率 95% 只见于自媒体，可信度低。", "指标仅见于专家交流纪要 [C441]。",
                 "只见于没有注明出处的中文媒体。", "该数字只见于使用错误编号的报道。"]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(absence(text), [])

    def test_qualifier_must_be_in_the_same_sentence(self):
        self.assertEqual(len(absence("本研究检索了 20 个来源。该数字只见于该来源。")), 1)
        self.assertEqual(absence("该数字只见于该来源，本研究检索到的其他来源均未提及。"), [])
        self.assertEqual(len(absence("本研究检索了 20 个来源\n该数字只见于该来源")), 1)

    def test_one_violation_per_offending_sentence_and_detail_quotes_it(self):
        v = absence("甲数字只见于该来源。乙数字未见其他报道。丙数字本研究检索到的来源中仅见于该来源。")
        self.assertEqual(len(v), 2)
        self.assertIn("甲数字只见于该来源", v[0]["detail"])
        self.assertIn("本研究检索到", v[0]["detail"])  # 提示改写方式
        self.assertEqual(v[0]["claim"], "")

    def test_ordinary_sentences_and_urls_are_not_flagged(self):
        for text in ("宁德时代披露产能 [C1]，详见 https://example.com/只见于/唯一来源。", "唯一的区别在于工艺路线。",
                     "两家公司没有其他合作。", "[公告](https://x.com/仅见于)", "该技术仅用于车规级场景。"):
            with self.subTest(text=text):
                self.assertEqual(absence(text), [])

    def test_appendices_are_not_checked(self):
        for appendix in ("\n\n---\n## 声明来源\n- **[C1]** 该数字目前只见于该来源 — https://a.com",
                         "\n\n---\n## Claim sources\n- **[C1]** only found in one report",
                         "\n\n---\n## 研究质量报告\n仅见于单一来源"):
            with self.subTest(appendix=appendix):
                self.assertEqual(absence("正文干净 [C1]。" + appendix), [])
        self.assertEqual(len(absence("该数字只见于该来源。\n\n---\n## 声明来源\n- x")), 1)  # 正文仍检查

    def test_chinese_report_does_not_apply_english_patterns(self):
        self.assertEqual(absence("This is the sole source. 正文。"), [])


class EnglishAbsenceTests(unittest.TestCase):
    def test_unqualified_absence_claims_are_caught(self):
        cases = ["The 10 GWh figure is only found in that source [C1].", "This only appears in one report.",
                 "The capacity was only reported in a single article.", "That article is the sole source.",
                 "There is no other source confirming it.", "No other reports mention the plant.",
                 "ONLY FOUND IN THE REPORT.", "It only appears in this source."]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(len(absence(text, "en")), 1)

    def test_hedges_about_the_kind_of_source_are_not_absence_claims(self):
        for text in ("The capacity was only reported in a blog post.", "It is only found in secondary summaries.",
                     "This only appears in media retellings.", "The figure is only found in the sources listed."):
            with self.subTest(text=text):
                self.assertEqual(absence(text, "en"), [])

    def test_scope_qualified_sentences_are_not_flagged(self):
        cases = ["The figure is only found in the sources reviewed here [C1].",
                 "It only appears in our search results.", "The sole source in our research is a blog post.",
                 "No other reports surfaced in the search."]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(absence(text, "en"), [])

    def test_sentences_are_split_on_terminal_punctuation_and_decimals_do_not_split(self):
        text = "We searched in our research. The 1.5 GWh line is the sole source here."
        self.assertEqual(len(absence(text, "en")), 1)
        self.assertEqual(absence("The 1.5 GWh line is the sole source in our research.", "en"), [])

    def test_english_appendix_and_urls_are_not_checked(self):
        text = ("Clean body [C1]. See https://example.com/sole-source."
                "\n\n---\n## Claim sources\n- **[C1]** only found in x")
        self.assertEqual(absence(text, "en"), [])

    def test_english_report_does_not_apply_chinese_patterns(self):
        self.assertEqual(absence("该数字只见于该来源。", "en"), [])


class WiringTests(unittest.TestCase):
    def test_violation_flows_through_check_citations_and_has_labels_in_both_languages(self):
        ledger = Ledger()
        v = check_citations(ledger, "该数字目前只见于该来源。")["violations"]
        self.assertEqual([x["type"] for x in v], ["absence_claim"])
        self.assertIn("absence_claim", VIOLATION_LABELS)
        self.assertIn("absence_claim", VIOLATION_LABELS_EN)
        self.assertIn("只见于", format_violations(v))
        ven = check_citations(ledger, "It is the sole source.", "en")["violations"]
        self.assertTrue(format_violations(ven, "en").startswith("- "))
        self.assertIn("sole source", format_violations(ven, "en"))

    def test_report_format_forbids_unscoped_absence_claims(self):
        for needle in ("只见于", "仅见于", "唯一来源", "没有其他来源", "未见其他报道", "本研究检索到的来源中仅见于"):
            self.assertIn(needle, REPORT_FORMAT)


if __name__ == "__main__":
    unittest.main()
