"""tools/eval：盲评脚本的确定性部分（匿名化、指标、抽样、顺序换算）与基线登记。"""
import json
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from tools.eval import judge
from tools.eval.questions import BASELINES, QUESTIONS
from tools.eval.run import final_draft_path


class AnonymizeAndMetricsTests(unittest.TestCase):
    def test_anonymize_drops_quality_appendix_and_version_traces(self):
        text = "# 报告\n正文（第3版）\n本版修订了数据\n结论\n\n---\n## 研究质量报告\n评分 8.1"
        out = judge.anonymize(text)
        self.assertNotIn("研究质量报告", out)
        self.assertNotIn("第3版", out)
        self.assertNotIn("本版", out)
        self.assertIn("结论", out)

    def test_metrics_counts_unique_urls_domains_and_cited_numbers(self):
        text = ("宁德时代2026年产能达到5GWh的中试线规模 [1]。\n"
                "丰田计划2027年推出首款车型，来源 https://www.toyota.com/a。\n"
                "这一句没有任何引用但含有数字2028年的节点。\n"
                "参考 https://toyota.com/b 与 https://example.org/c")
        m = judge.metrics(text)
        self.assertEqual((m["unique_urls"], m["distinct_domains"]), (3, 2))
        self.assertEqual(m["numeric_sentences"], 3)
        self.assertAlmostEqual(m["numeric_cited_ratio"], 0.667, places=3)

    def test_sample_claims_is_deterministic_and_skips_tables_and_references(self):
        lines = [f"第{i}家厂商在2026年宣布了规模为{i}GWh的固态电池中试线建设计划" for i in range(20)]
        text = "\n".join(lines + ["| 表格 | 2026 | 一行很长很长很长很长很长的表格内容 |",
                                  "[12] https://example.com/source-2026-report-very-long"])
        a, b = judge.sample_claims(text), judge.sample_claims(text)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 5)
        self.assertTrue(all(not s.startswith(("|", "[")) for s in a))


class JudgePairTests(unittest.TestCase):
    def test_scores_are_mapped_back_to_a_and_b_in_both_orders(self):
        def fake_call(req):
            x_better = {f"X_{d}": 9 for d in judge.DIMS} | {f"Y_{d}": 7 for d in judge.DIMS}
            return SimpleNamespace(data={**x_better, "winner": "X", "reason": "r"})

        with mock.patch.object(judge, "call", fake_call):
            ab, ba = judge.judge_pair("q", "A 文本", "B 文本")
        self.assertEqual((ab["winner"], ab["scores"]["A"]["accuracy"]), ("A", 9))
        self.assertEqual((ba["winner"], ba["scores"]["B"]["accuracy"]), ("B", 9))  # BA 时 X 是 B


class RegistryAndRunTests(unittest.TestCase):
    def test_every_baseline_exists_and_has_a_question(self):
        for label, path in BASELINES.items():
            self.assertIn(label, QUESTIONS)
            self.assertTrue(os.path.isfile(path), path)

    def test_final_draft_path_reads_session_meta(self):
        ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, ws, True)
        with open(os.path.join(ws, "00_session.json"), "w", encoding="utf-8") as f:
            json.dump({"final_draft": 3}, f)
        self.assertEqual(final_draft_path(ws), os.path.join(ws, "06_drafts", "draft_3.md"))


if __name__ == "__main__":
    unittest.main()
