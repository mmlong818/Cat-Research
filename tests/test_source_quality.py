"""X1/X2 来源可信度：低可信判定（JSON 分数 / 不可靠列表 / 规则回落 / 社交与聚合域名）、声明表「来源可信度低」标注、
生产类关键词、核查挑选的低可信优先。"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from agents import fact_checker as fc_mod
from agents.analyst import AnalystAgent
from agents.fact_checker import PRIMARY_RECORD_PATTERN, FactCheckerAgent, pick_for_verification, pick_load_bearing
from agents.writer import REPORT_FORMAT, _materials
from research.ledger import (
    VIOLATION_LABELS_EN,
    Ledger,
    check_citations,
    format_violations,
    report_hygiene_violations,
)
from research.source_quality import LOW_SCORE, index_verification, is_low_credibility, load_verification
from tests.test_fact_primary_source import _ledger_with
from tests.test_research_agents import _WS, _ok

TAG = "(来源可信度低)"


def _sv(*entries, unreliable=()):
    """entries: (url, score) 或 (url, score, tier)"""
    return {"verified_sources": [{"url": e[0], "title": "", "domain_score": e[1], "tier": e[2] if len(e) > 2 else 3,
                                  "confidence_level": "low", "category": "news", "is_reliable": e[0] not in unreliable,
                                  "warning": ""} for e in entries],
            "unreliable_sources": list(unreliable)}


class LowCredibilityJudgementTests(unittest.TestCase):
    def test_threshold_is_below_the_rule_engine_score_of_an_unlisted_https_domain(self):
        self.assertEqual(LOW_SCORE, 50)

    def test_verification_score_below_threshold_is_low_and_at_or_above_is_not(self):
        idx = index_verification(_sv(("https://a.example.com/x", 49), ("https://b.example.com/x", 50),
                                     ("https://c.example.com/x", 80)))
        self.assertTrue(is_low_credibility("https://a.example.com/x", idx))
        self.assertFalse(is_low_credibility("https://b.example.com/x", idx))
        self.assertFalse(is_low_credibility("https://c.example.com/x", idx))

    def test_verification_beats_the_rule_engine_for_non_listed_domains(self):
        # 规则引擎对未收录的 https 域名给 50（不低）；验证阶段评为 30 时以验证为准，评为 90 时同样以验证为准
        idx = index_verification(_sv(("https://a.example.com/x", 30), ("https://reuters.com/x", 20)))
        self.assertTrue(is_low_credibility("https://a.example.com/x", idx))
        self.assertTrue(is_low_credibility("https://reuters.com/x", idx))  # 验证阶段明确判低

    def test_unreliable_list_marks_low_even_with_a_high_score(self):
        url = "https://a.example.com/x"
        idx = index_verification({"verified_sources": [], "unreliable_sources": [url]})
        self.assertTrue(is_low_credibility(url, idx))
        idx = index_verification(_sv((url, 90), unreliable=[url]))
        self.assertTrue(is_low_credibility(url, idx))

    def test_url_matching_ignores_scheme_www_case_and_trailing_slash(self):
        idx = index_verification(_sv(("http://www.A.example.com/x/", 30)))
        self.assertTrue(is_low_credibility("https://a.example.com/x", idx))

    def test_rule_fallback_when_there_is_no_verification_or_the_url_is_missing_from_it(self):
        for idx in (None, index_verification(None), index_verification(_sv(("https://other.com/y", 80)))):
            with self.subTest(index=idx):
                self.assertFalse(is_low_credibility("https://reuters.com/x", idx))
                self.assertFalse(is_low_credibility("https://unlisted-site.com/x", idx))  # 未收录 https 域名 50：不低
                self.assertTrue(is_low_credibility("http://unlisted-site.com/x", idx))    # 无 https：35，低
                self.assertTrue(is_low_credibility("not a url", idx))                     # 无效 URL：0，低

    def test_social_media_domains_are_low_regardless_of_score(self):
        urls = ["https://weibo.com/123", "https://www.zhihu.com/question/1", "https://zhuanlan.zhihu.com/p/1",
                "https://www.xiaohongshu.com/explore/1", "https://x.com/a/status/1", "https://twitter.com/a/status/1",
                "https://www.reddit.com/r/x", "https://www.bilibili.com/video/BV1", "https://www.youtube.com/watch?v=1"]
        idx = index_verification(_sv(*[(u, 95) for u in urls]))
        for u in urls:
            with self.subTest(url=u):
                self.assertTrue(is_low_credibility(u), "规则库直接判低")
                self.assertTrue(is_low_credibility(u, idx), "验证阶段给高分也不改变")

    def test_sina_weibo_digest_page_is_social_but_sina_finance_is_not(self):
        self.assertTrue(is_low_credibility("https://www.sina.cn/weibo/detail/5349128771210772.html"))
        self.assertFalse(is_low_credibility("https://finance.sina.com.cn/stock/x.shtml"))
        self.assertFalse(is_low_credibility("https://www.sina.cn/news/x.html"))

    def test_self_media_platforms_and_aggregators_are_low(self):
        for u in ("https://mp.weixin.qq.com/s/abc", "https://baijiahao.baidu.com/s?id=1",
                  "https://www.toutiao.com/article/1", "https://caifuhao.eastmoney.com/news/1",
                  "https://chejiahao.autohome.com.cn/info/1", "https://k.sina.com.cn/article_1.html",
                  "https://www.h33.top/report/20260831-4e0e", "https://h33.top/x"):
            with self.subTest(url=u):
                self.assertTrue(is_low_credibility(u))

    def test_lookalike_hosts_and_mainstream_media_are_not_caught(self):
        for u in ("https://notweibo.com.example.org/1", "https://eastmoney.com/a", "https://www.nasdaq.com/x",
                  "https://sec.gov/x", "https://www.36kr.com/p/1", "https://news.qq.com/rain/a/1"):
            with self.subTest(url=u):
                self.assertFalse(is_low_credibility(u))

    def test_malformed_verification_is_ignored(self):
        for bad in (None, [], {}, {"verified_sources": "x"}, {"verified_sources": [None, {"url": 3}, {"url": "u"}]},
                    {"verified_sources": [{"url": "https://a.example.com/x", "domain_score": "high"}]},
                    {"unreliable_sources": None}):
            with self.subTest(bad=bad):
                idx = index_verification(bad)
                self.assertFalse(is_low_credibility("https://reuters.com/x", idx))
                self.assertFalse(is_low_credibility("https://a.example.com/x", idx))

    def test_load_verification(self):
        ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, ws, True)
        self.assertIsNone(load_verification(ws))
        path = os.path.join(ws, "08_verification", "source_verification.json")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as f:
            f.write("{坏的 json")
        self.assertIsNone(load_verification(ws))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_sv(("https://a.example.com/x", 30)), f)
        self.assertEqual(load_verification(ws)["verified_sources"][0]["domain_score"], 30)


class ClaimsTableTagTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, True)
        self.l = Ledger.load(self.ws)

    def line(self, cid, verification=None):
        return next(x for x in self.l.claims_table(verification).splitlines() if x.startswith(f"[{cid}]"))

    def test_all_sources_low_is_tagged_after_the_status_label(self):
        self.l.add_claim("甲公司重庆产线 2027 年投产", "https://weibo.com/1")
        self.l.add_claim("乙公司 10GWh 产能", "https://www.h33.top/r/1")
        self.l.set_status("C2", "unverifiable")
        self.assertEqual(self.line("C1"), f"[C1] {TAG} 甲公司重庆产线 2027 年投产  — 来源 S1")
        self.assertEqual(self.line("C2"), f"[C2] (待核实) {TAG} 乙公司 10GWh 产能  — 来源 S2")

    def test_one_good_source_means_no_tag(self):
        self.l.add_claim("甲公司扩产", "https://weibo.com/1")
        self.l.add_claim("甲公司扩产", "https://www.reuters.com/x")
        self.assertNotIn(TAG, self.l.claims_table())

    def test_good_single_source_and_no_source_claims_are_not_tagged(self):
        self.l.add_claim("甲公司扩产", "https://www.reuters.com/x")
        self.l.add_claim("没有来源的声明")
        self.assertNotIn(TAG, self.l.claims_table())

    def test_verification_json_score_drives_the_tag(self):
        self.l.add_claim("丙公司扩产", "https://some-blog.example.com/p")
        self.assertNotIn(TAG, self.line("C1"))  # 无 JSON：规则 50，不低
        sv = _sv(("https://some-blog.example.com/p", 38))
        self.assertIn(TAG, self.line("C1", sv))
        self.assertNotIn(TAG, self.line("C1", _sv(("https://some-blog.example.com/p", 70))))

    def test_mixed_by_verification_means_no_tag(self):
        self.l.add_claim("丙公司扩产", "https://a.example.com/p")
        self.l.add_claim("丙公司扩产", "https://b.example.com/p")
        sv = _sv(("https://a.example.com/p", 30), ("https://b.example.com/p", 70))
        self.assertNotIn(TAG, self.line("C1", sv))
        sv = _sv(("https://a.example.com/p", 30), ("https://b.example.com/p", 40))
        self.assertIn(TAG, self.line("C1", sv))

    def test_merged_claim_sources_are_pooled(self):
        self.l.add_claim("丁公司扩产", "https://weibo.com/1")
        self.l.add_claim("丁公司扩产（重复）", "https://www.reuters.com/x")
        self.l.merge("C1", "C2")
        self.assertNotIn(TAG, self.line("C1"))

    def test_tag_is_computed_not_persisted(self):
        self.l.add_claim("甲公司扩产", "https://weibo.com/1")
        self.assertIn(TAG, self.l.claims_table())
        self.l.save()
        with open(self.l.path, encoding="utf-8") as f:
            self.assertNotIn("来源可信度", f.read())
        self.assertEqual(Ledger.load(self.ws).claims["C1"]["status"], "unchecked")

    def test_claims_table_without_argument_keeps_working_with_rules_only(self):
        self.l.add_claim("甲公司扩产", "https://www.reuters.com/x")
        self.assertEqual(self.l.claims_table(), "[C1] 甲公司扩产  — 来源 S1")


class PromptWiringTests(_WS):
    def setUp(self):
        super().setUp()
        ledger = Ledger.load(self.ws)
        ledger.add_claim("甲公司重庆产线 2027 年投产", "https://weibo.com/1")
        ledger.save()

    def test_writer_materials_and_analyst_prompt_use_the_workspace_verification_file(self):
        self.assertIn(f"[C1] {TAG} 甲公司", _materials(self.ws))  # 无 JSON：规则回落（weibo.com）
        self.put("08_verification/source_verification.json", json.dumps(_sv(("https://weibo.com/1", 90))))
        self.assertIn(f"[C1] {TAG} 甲公司", _materials(self.ws))  # 社交域名不受高分影响
        self.patch_call(_ok(text="# 分析"))
        AnalystAgent().analyze(self.ws, "问题")
        self.assertIn(f"[C1] {TAG} 甲公司", self.reqs[0].prompt)

    def test_verification_file_lowers_an_unlisted_domain_in_both_prompts(self):
        ledger = Ledger.load(self.ws)
        ledger.add_claim("乙公司扩产", "https://some-blog.example.com/p")
        ledger.save()
        self.assertIn("[C2] 乙公司扩产", _materials(self.ws))
        self.put("08_verification/source_verification.json", json.dumps(_sv(("https://some-blog.example.com/p", 30))))
        self.assertIn(f"[C2] {TAG} 乙公司扩产", _materials(self.ws))
        self.patch_call(_ok(text="# 分析"))
        AnalystAgent().analyze(self.ws, "问题")
        self.assertIn(f"[C2] {TAG} 乙公司扩产", self.reqs[0].prompt)

    def test_report_format_and_analyst_prompt_carry_the_low_credibility_rule(self):
        self.patch_call(_ok(text="# 分析"))
        AnalystAgent().analyze(self.ws, "问题")
        for text in (REPORT_FORMAT, self.reqs[0].prompt):
            for needle in ("来源可信度低", "据社交媒体汇总", "据聚合研报", "唯一依据", "高可信来源为准"):
                self.assertIn(needle, text)


class ProductionKeywordTests(unittest.TestCase):
    def test_production_and_project_keywords_hit(self):
        for text in ("亿纬锂能重庆产线 2027 年投产", "宁德时代中试线量产", "新建生产线", "固态电池基地落成",
                     "新工厂开工", "公司已选址成都", "项目落地", "产线建成", "The plant will start in 2027",
                     "A new factory in Ohio", "a pilot production line", "mass production begins",
                     "groundbreaking ceremony", "Gigafactory ramp", "three plants", "factories closed"):
            with self.subTest(text=text):
                self.assertTrue(PRIMARY_RECORD_PATTERN.search(text), text)

    def test_no_false_positives_on_lookalike_words(self):
        for text in ("The implant market", "plantation economy", "plant-based material", "supplant rivals",
                     "factorytalk", "productive discussion", "基数增长", "该观点值得讨论", "second-generation cell"):
            with self.subTest(text=text):
                self.assertFalse(PRIMARY_RECORD_PATTERN.search(text), text)


class LowCredibilityPriorityTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, True)

    def test_all_low_claim_comes_before_a_higher_ranked_claim_from_good_sources(self):
        ledger = Ledger.load(self.ws)
        ledger.add_claim("工信部发布 A 通知", "https://www.reuters.com/a")           # C1：好来源，本应一手记录
        ledger.add_claim("某地良率 70%", "https://weibo.com/1")                       # C2：低来源，只含数字
        ledger.add_claim("某地良率 80%", "https://www.reuters.com/b")                 # C3：好来源，只含数字
        ledger.add_claim("某地产线投产", "https://weibo.com/2")                       # C4：低来源，一手类关键词
        self.assertEqual(pick_for_verification(ledger), ["C4", "C2", "C1", "C3"])

    def test_old_order_is_kept_inside_each_low_group_and_when_nothing_is_low(self):
        ledger = _ledger_with(self.ws, ["营收 10 亿", "GB/T 43568-2026 于 2026 年 7 月 1 日起实施",
                                        "工信部发布了相关通知"])
        self.assertEqual(pick_for_verification(ledger), ["C2", "C3", "C1"])

    def test_a_claim_with_one_good_source_is_not_prioritised(self):
        ledger = Ledger.load(self.ws)
        ledger.add_claim("某地良率 70%", "https://weibo.com/1")
        ledger.add_claim("某地良率 70%", "https://www.reuters.com/x")
        ledger.add_claim("某地良率 80%", "https://weibo.com/2")
        self.assertEqual(pick_for_verification(ledger), ["C2", "C1"])

    def test_verification_json_is_honoured_by_the_picker(self):
        ledger = Ledger.load(self.ws)
        ledger.add_claim("某地良率 70%", "https://www.reuters.com/x")
        ledger.add_claim("某地良率 80%", "https://some-blog.example.com/p")
        sv = _sv(("https://some-blog.example.com/p", 30))
        self.assertEqual(pick_for_verification(ledger, 8, sv), ["C2", "C1"])
        self.assertEqual(pick_for_verification(ledger, 8), ["C1", "C2"])

    def test_check_facts_and_recheck_read_the_workspace_verification_file(self):
        ledger = Ledger.load(self.ws)
        ledger.add_claim("工信部发布 A 通知", "https://www.reuters.com/a")
        ledger.add_claim("工信部发布 B 通知", "https://some-blog.example.com/p")
        ledger.save()
        path = os.path.join(self.ws, "08_verification", "source_verification.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_sv(("https://some-blog.example.com/p", 30)), f)
        seen = []

        def fake_cross(texts, model):
            seen.extend(texts)
            return [{"verdict": "supported", "confidence": 0.9, "supporting": [], "contradicting": [],
                     "explanation": "x", "evidence_tier": "primary"}] * len(texts)

        with mock.patch.object(fc_mod, "cross_reference_claims", side_effect=fake_cross):
            FactCheckerAgent().check_facts(self.ws, limit=1)
            self.assertEqual(seen, ["工信部发布 B 通知"])
            seen.clear()
            self.assertEqual(FactCheckerAgent().recheck(self.ws, "[C1] [C1] [C2]", 1), ["C1"])  # C2 已核实，只剩 C1
            self.assertEqual(seen, ["工信部发布 A 通知"])

    def test_limit_applies_after_the_low_credibility_layer(self):
        ledger = Ledger.load(self.ws)
        ledger.add_claim("工信部发布 A 通知", "https://www.reuters.com/a")
        ledger.add_claim("某地产线投产", "https://weibo.com/1")
        self.assertEqual(pick_for_verification(ledger, limit=1), ["C2"])

    def test_load_bearing_prefers_low_credibility_over_citation_count(self):
        ledger = Ledger.load(self.ws)
        ledger.add_claim("工信部发布 A 通知", "https://www.reuters.com/a")   # C1：被引 3 次
        ledger.add_claim("某地产线投产", "https://weibo.com/1")               # C2：被引 1 次，低来源
        ledger.add_claim("某地基地建成", "https://weibo.com/2")               # C3：被引 2 次，低来源
        ledger.add_claim("某地良率 70%", "https://weibo.com/3")               # C4：低来源但无一手关键词，不入选
        text = "[C1] [C1] [C1] [C2] [C3] [C3] [C4]"
        self.assertEqual(pick_load_bearing(ledger, text, 10), ["C3", "C2", "C1"])
        self.assertEqual(pick_load_bearing(ledger, text, 1), ["C3"])

    def test_load_bearing_unchanged_without_low_sources_and_honours_verification(self):
        ledger = _ledger_with(self.ws, ["工信部发布 A 通知", "工信部发布 B 通知"])
        self.assertEqual(pick_load_bearing(ledger, "[C1] [C2] [C2]", 10), ["C2", "C1"])
        sv = _sv(("https://src.com/0", 30))
        self.assertEqual(pick_load_bearing(ledger, "[C1] [C2] [C2]", 10, sv), ["C1", "C2"])


def _mixed_ledger(ws, n_low, n_other, template="某地良率 {i}%"):
    """先 n_low 条只有微博来源的声明，再 n_other 条路透来源的声明（编号连续）。"""
    ledger = Ledger.load(ws)
    for i in range(n_low):
        ledger.add_claim(template.format(i=i + 1), f"https://weibo.com/{i}")
    for i in range(n_other):
        ledger.add_claim(template.format(i=100 + i), f"https://www.reuters.com/{i}")
    return ledger


class LowCredibilityQuotaTests(unittest.TestCase):
    """低可信声明最多占 limit 的一半（向上取整），其余给非低可信；任一侧不足时名额让给另一侧。"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, True)

    def ids(self, first, count):
        return [f"C{n}" for n in range(first, first + count)]

    def test_verification_picks_at_most_half_low_rounded_up_and_the_rest_from_the_others(self):
        ledger = _mixed_ledger(self.ws, 6, 6)  # C1-C6 低，C7-C12 非低
        self.assertEqual(pick_for_verification(ledger, 8), self.ids(1, 4) + self.ids(7, 4))
        self.assertEqual(pick_for_verification(ledger, 5), self.ids(1, 3) + self.ids(7, 2))
        self.assertEqual(pick_for_verification(ledger, 1), ["C1"])
        self.assertEqual(pick_for_verification(ledger, 0), [])

    def test_unused_low_quota_goes_to_the_others(self):
        ledger = _mixed_ledger(self.ws, 1, 10)
        self.assertEqual(pick_for_verification(ledger, 8), ["C1"] + self.ids(2, 7))

    def test_unused_other_quota_goes_back_to_low(self):
        ledger = _mixed_ledger(self.ws, 10, 2)
        picked = pick_for_verification(ledger, 8)
        self.assertEqual(picked, self.ids(1, 4) + self.ids(11, 2) + self.ids(5, 2))
        self.assertEqual(len(picked), 8)

    def test_when_everything_is_low_or_nothing_is_low_the_limit_is_still_filled(self):
        self.assertEqual(pick_for_verification(_mixed_ledger(self.ws, 10, 0), 8), self.ids(1, 8))
        ws2 = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, ws2, True)
        self.assertEqual(pick_for_verification(_mixed_ledger(ws2, 0, 10), 8), self.ids(1, 8))

    def test_non_low_claims_keep_the_old_ranking_inside_their_share(self):
        ledger = Ledger.load(self.ws)
        ledger.add_claim("某地良率 1%", "https://weibo.com/1")                       # C1 低
        ledger.add_claim("某地良率 2%", "https://www.reuters.com/a")                 # C2 非低，仅数字
        ledger.add_claim("工信部发布 A 通知", "https://www.reuters.com/b")           # C3 非低，一手类
        ledger.add_claim("某地良率 3%", "https://weibo.com/2")                       # C4 低
        # 低 2 条（上取整），其余 1 条取非低里最优的 C3
        self.assertEqual(pick_for_verification(ledger, 3), ["C1", "C4", "C3"])

    def test_load_bearing_applies_the_same_half_quota_and_backfill(self):
        ledger = _mixed_ledger(self.ws, 6, 6, "工信部发布 {i} 通知")
        text = " ".join(f"[C{n}]" for n in range(1, 13))
        self.assertEqual(pick_load_bearing(ledger, text, 8), self.ids(1, 4) + self.ids(7, 4))
        self.assertEqual(pick_load_bearing(ledger, text, 5), self.ids(1, 3) + self.ids(7, 2))
        self.assertEqual(pick_load_bearing(ledger, text, 0), [])
        ws2 = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, ws2, True)
        ledger = _mixed_ledger(ws2, 10, 2, "工信部发布 {i} 通知")
        text = " ".join(f"[C{n}]" for n in range(1, 13))
        self.assertEqual(pick_load_bearing(ledger, text, 8), self.ids(1, 4) + self.ids(11, 2) + self.ids(5, 2))

    def test_load_bearing_keeps_citation_count_order_inside_each_share(self):
        ledger = _mixed_ledger(self.ws, 3, 3, "工信部发布 {i} 通知")
        text = "[C1] [C2] [C2] [C3] [C3] [C3] [C4] [C5] [C5] [C6]"  # 低：C3>C2>C1；非低：C5>C4=C6
        self.assertEqual(pick_load_bearing(ledger, text, 4), ["C3", "C2", "C5", "C4"])


class LabelLeakTests(unittest.TestCase):
    """台账内部标注（来源可信度低 / 括号形式的已核实、存疑、待核实）不得写进中文报告正文。"""

    def leaks(self, text, language="zh"):
        return [v for v in report_hygiene_violations(text, language) if v["type"] == "label_leak"]

    def test_internal_labels_in_the_body_are_violations(self):
        cases = ["亿纬重庆产线 2027 年投产 (来源可信度低) [C33]。", "该数字（已核实）[C1]。", "良率 93.4% (存疑)。",
                 "产能 5GWh（待核实）。", "据社交媒体汇总，该产线（来源可信度低）。", "该来源可信度低，需谨慎。"]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(len(self.leaks(text)), 1)

    def test_copied_pair_annotation_is_a_leak(self):
        cases = ["国轩 2027 年小批量（与 C197 说法冲突，须同段一并引用）[C157]。",
                 "该数字与 C12、C13 说法冲突，需谨慎。", "两说法冲突，须同段一并引用。",
                 "（与 [C197] 说法冲突）"]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(len(self.leaks(text)), 1)

    def test_natural_conflict_wording_is_not_a_leak(self):
        for text in ("两家机构的说法冲突，本文一并呈现 [C1, C2]。", "该说法与官方说法冲突。", "与 2025 年数据冲突。"):
            with self.subTest(text=text):
                self.assertEqual(self.leaks(text), [])

    def test_one_violation_per_distinct_label_and_detail_names_it(self):
        v = self.leaks("甲（已核实），乙（已核实），丙 (待核实)，丁 (来源可信度低)。")
        self.assertEqual(len(v), 3)
        self.assertTrue(any("(待核实)" in x["detail"] for x in v))
        self.assertEqual(v[0]["claim"], "")

    def test_natural_wording_brackets_and_urls_are_not_flagged(self):
        for text in ("该说法存疑，有待官方确认。", "数据已核实无误。", "【待核实】另一说法。", "[已核实](https://x.com/待核实)",
                     "详见 https://example.com/(存疑)/x", "财报显示（见表 2）营收增长。", "该来源的可信度较低。"):
            with self.subTest(text=text):
                self.assertEqual(self.leaks(text), [])

    def test_appendices_are_not_checked_and_english_reports_are_out_of_scope(self):
        appendix = "\n\n---\n## 声明来源\n- **[C1]** (存疑) 来源可信度低 (待核实)\n\n---\n## 研究质量报告\n(已核实)\n"
        self.assertEqual(self.leaks("正文干净 [C1]。" + appendix), [])
        self.assertEqual(len(self.leaks("正文（存疑）。\n\n---\n## 声明来源\n- x")), 1)
        self.assertEqual(self.leaks("The claim (存疑) is weak.", "en"), [])

    def test_flows_through_check_citations_with_labels_in_both_languages(self):
        v = check_citations(Ledger(), "该产线（来源可信度低）。")["violations"]
        self.assertEqual([x["type"] for x in v], ["label_leak"])
        self.assertIn("来源可信度低", format_violations(v))
        self.assertIn("label_leak", VIOLATION_LABELS_EN)

    def test_writer_prompt_already_forbids_outputting_the_label(self):
        self.assertIn("不得作为标签原样写进报告", REPORT_FORMAT)


if __name__ == "__main__":
    unittest.main()
