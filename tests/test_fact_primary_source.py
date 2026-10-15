"""F1-F3 事实核查「一手来源优先」：证据等级映射、裁决/核实兜底、挑选关键词、条数按深度、schema 严格合规。"""
import shutil
import tempfile
import unittest
from unittest import mock

from agents import fact_checker as fc_mod
from agents.fact_checker import (
    ADJUDICATE_SCHEMA,
    ADJUDICATE_SYSTEM_PROMPT,
    MAX_VERIFY,
    FactCheckerAgent,
    adjudication_outcome,
    pick_for_verification,
)
from llm import LLMResult
from research.ledger import NEITHER, Ledger
from tools.fact_tools import CROSS_CHECK_SCHEMA, CROSS_CHECK_SYSTEM, EVIDENCE_TIERS, verification_outcome


def _ok(data):
    return LLMResult(text="", data=data, duration_ms=1, num_turns=1, session_id="s", model_usage={})


def _adj(side, tier):
    return _ok({"sides_with": side, "reason": "理由", "evidence_url": "u", "evidence_tier": tier})


def _check(verdict, tier):
    return {"verdict": verdict, "confidence": 0.9, "supporting": [], "contradicting": [],
            "explanation": f"核实 {verdict}", "evidence_tier": tier}


def _ledger_with(ws, texts, contradictions=()):
    ledger = Ledger.load(ws)
    for i, t in enumerate(texts):
        ledger.add_claim(t, f"https://src.com/{i}")
    for a, b in contradictions:
        ledger.add_contradiction(a, b, "冲突")
    ledger.save()
    return ledger


class TierMappingTests(unittest.TestCase):
    def test_tiers_enum(self):
        self.assertEqual(EVIDENCE_TIERS, ["primary", "authority", "media", "none"])

    def test_adjudication_only_primary_or_authority_can_overrule(self):
        for side in ("A", "B"):
            for tier in ("primary", "authority"):
                with self.subTest(side=side, tier=tier):
                    self.assertEqual(adjudication_outcome(side, tier, "r"), (side, "r"))
            for tier in ("media", "none"):
                with self.subTest(side=side, tier=tier):
                    out_side, reason = adjudication_outcome(side, tier, "r")
                    self.assertEqual(out_side, NEITHER)
                    self.assertTrue(reason.startswith("仅有媒体证据，按两方存疑处理"), reason)
                    self.assertTrue(reason.endswith("r"))

    def test_adjudication_neither_is_untouched_for_every_tier(self):
        for tier in EVIDENCE_TIERS:
            self.assertEqual(adjudication_outcome(NEITHER, tier, "r"), (NEITHER, "r"), tier)

    def test_adjudication_unknown_tier_is_treated_as_none(self):
        self.assertEqual(adjudication_outcome("A", "gossip", "r")[0], NEITHER)
        self.assertEqual(adjudication_outcome("A", None, "r")[0], NEITHER)

    def test_verification_mapping_table(self):
        expected = {
            ("supported", "primary"): "supported", ("supported", "authority"): "supported",
            ("supported", "media"): "unverifiable", ("supported", "none"): "unverifiable",
            ("disputed", "primary"): "disputed", ("disputed", "authority"): "disputed",
            ("disputed", "media"): "unverifiable", ("disputed", "none"): "unverifiable",
        }
        for verdict in ("unverifiable", "insufficient"):
            for tier in EVIDENCE_TIERS:
                expected[(verdict, tier)] = "unverifiable"
        for (verdict, tier), status in expected.items():
            with self.subTest(verdict=verdict, tier=tier):
                self.assertEqual(verification_outcome(verdict, tier, "说明")[0], status)

    def test_verification_note_explains_the_downgrade_and_keeps_the_explanation(self):
        _, note = verification_outcome("supported", "media", "三家媒体一致")
        self.assertIn("仅媒体来源，未找到一手或权威来源", note)
        self.assertIn("三家媒体一致", note)
        self.assertEqual(verification_outcome("supported", "primary", "原文一致")[1], "原文一致")

    def test_verification_unknown_tier_is_treated_as_none(self):
        self.assertEqual(verification_outcome("supported", None, "x")[0], "unverifiable")
        self.assertEqual(verification_outcome("supported", "gossip", "x")[0], "unverifiable")


class SchemaTests(unittest.TestCase):
    def assert_strict(self, schema, path="$"):
        if schema.get("type") == "object":
            self.assertIs(schema.get("additionalProperties"), False, path)
            self.assertEqual(sorted(schema["required"]), sorted(schema["properties"]), path)
            for key, sub in schema["properties"].items():
                self.assert_strict(sub, f"{path}.{key}")
        elif schema.get("type") == "array":
            self.assert_strict(schema["items"], f"{path}[]")

    def test_both_schemas_have_required_evidence_tier_and_stay_strict(self):
        for name, schema in (("adjudicate", ADJUDICATE_SCHEMA), ("cross_check", CROSS_CHECK_SCHEMA)):
            with self.subTest(name):
                self.assertEqual(schema["properties"]["evidence_tier"]["enum"], EVIDENCE_TIERS)
                self.assertIn("evidence_tier", schema["required"])
                self.assert_strict(schema)

    def test_prompts_carry_the_source_hierarchy(self):
        for prompt in (ADJUDICATE_SYSTEM_PROMPT, CROSS_CHECK_SYSTEM):
            for needle in ("primary", "authority", "media", "openstd.samr.gov.cn", "只算一个来源"):
                self.assertIn(needle, prompt)


class AdjudicationFallbackTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, True)
        _ledger_with(self.ws, ["GB/T 43568 于 7 月 1 日实施", "第 1 部分于 8 月 28 日发布"], [("C1", "C2")])

    def adjudicate(self, outcome):
        with mock.patch.object(fc_mod, "call_many", side_effect=lambda reqs, max_concurrency: [outcome]):
            self.assertEqual(FactCheckerAgent().adjudicate(self.ws), 1)
        ledger = Ledger.load(self.ws)
        return ledger, ledger.contradictions["X1"]["resolution"]

    def test_media_only_win_is_downgraded_to_neither(self):
        ledger, res = self.adjudicate(_adj("A", "media"))
        self.assertEqual(res["sides_with"], NEITHER)
        self.assertIn("仅有媒体证据", res["reason"])
        self.assertEqual([ledger.claims[c]["status"] for c in ("C1", "C2")], ["disputed", "disputed"])

    def test_no_evidence_win_is_downgraded_to_neither(self):
        ledger, res = self.adjudicate(_adj("B", "none"))
        self.assertEqual(res["sides_with"], NEITHER)
        self.assertEqual([ledger.claims[c]["status"] for c in ("C1", "C2")], ["disputed", "disputed"])

    def test_primary_evidence_decides_normally(self):
        ledger, res = self.adjudicate(_adj("B", "primary"))
        self.assertEqual(res["sides_with"], "C2")
        self.assertEqual([ledger.claims[c]["status"] for c in ("C1", "C2")], ["overruled", "supported"])

    def test_authority_evidence_decides_normally(self):
        ledger, _ = self.adjudicate(_adj("A", "authority"))
        self.assertEqual([ledger.claims[c]["status"] for c in ("C1", "C2")], ["supported", "overruled"])

    def test_missing_tier_from_a_weak_model_is_conservative(self):
        ledger, res = self.adjudicate(_ok({"sides_with": "A", "reason": "r", "evidence_url": ""}))
        self.assertEqual(res["sides_with"], NEITHER)


class VerificationFallbackTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, True)

    def check(self, checks, **kw):
        with mock.patch.object(fc_mod, "cross_reference_claims", return_value=checks):
            result, _ = FactCheckerAgent().check_facts(self.ws, **kw)
        return result, Ledger.load(self.ws)

    def test_supported_by_media_only_is_recorded_as_unverifiable(self):
        _ledger_with(self.ws, ["GB/T 43568-2026 于 2026 年 7 月 1 日实施"])
        result, ledger = self.check([_check("supported", "media")])
        self.assertEqual(ledger.claims["C1"]["status"], "unverifiable")
        self.assertIn("仅媒体来源，未找到一手或权威来源", ledger.claims["C1"]["note"])
        self.assertEqual(result["claims"][0]["verdict"], "unverifiable")
        self.assertEqual(result["overall_confidence"], 0.5)
        self.assertEqual(result["high_confidence_claims"], 0)

    def test_primary_support_and_dispute_are_kept_and_tiers_are_counted(self):
        _ledger_with(self.ws, ["营收 10 亿", "良率 70%", "毛利 5 亿", "出货 3 万台"])
        result, ledger = self.check([_check("supported", "primary"), _check("disputed", "authority"),
                                     _check("disputed", "media"), _check("unverifiable", "none")])
        self.assertEqual([ledger.claims[c]["status"] for c in ("C1", "C2", "C3", "C4")],
                         ["supported", "disputed", "unverifiable", "unverifiable"])
        self.assertEqual(result["evidence_tiers"], {"primary": 1, "authority": 1, "media": 1, "none": 1})

    def test_adjudication_tiers_are_counted_in_the_summary(self):
        _ledger_with(self.ws, ["标准 A 7 月实施", "标准 A 8 月发布", "营收 10 亿"], [("C1", "C2")])
        with mock.patch.object(fc_mod, "call_many", side_effect=lambda reqs, max_concurrency: [_adj("A", "media")]):
            result, _ = self.check([_check("unverifiable", "none")])
        self.assertEqual(result["adjudication_evidence_tiers"],
                         {"primary": 0, "authority": 0, "media": 1, "none": 0})
        self.assertEqual(result["contradictions"]["neither"], 1)

    def test_limit_caps_the_number_of_verified_claims(self):
        _ledger_with(self.ws, [f"营收 {i} 亿" for i in range(1, 6)])
        seen = []

        def fake_cross(texts, model):
            seen.extend(texts)
            return [_check("supported", "primary")] * len(texts)

        with mock.patch.object(fc_mod, "cross_reference_claims", side_effect=fake_cross):
            FactCheckerAgent().check_facts(self.ws, limit=2)
        self.assertEqual(len(seen), 2)

    def test_default_limit_is_max_verify(self):
        _ledger_with(self.ws, [f"营收 {i} 亿" for i in range(1, MAX_VERIFY + 4)])
        seen = []

        def fake_cross(texts, model):
            seen.extend(texts)
            return [_check("supported", "primary")] * len(texts)

        with mock.patch.object(fc_mod, "cross_reference_claims", side_effect=fake_cross):
            FactCheckerAgent().check_facts(self.ws)
        self.assertEqual(len(seen), MAX_VERIFY)


class PickForVerificationTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, True)

    def test_primary_record_claims_come_before_plain_numeric_claims(self):
        ledger = _ledger_with(self.ws, ["营收 10 亿", "GB/T 43568-2026 于 2026 年 7 月 1 日起实施",
                                        "没有数字也没有关键词的观点", "工信部发布了相关通知", "良率 70%"])
        self.assertEqual(pick_for_verification(ledger), ["C2", "C4", "C1", "C5"])

    def test_fewer_sources_first_within_a_group_and_ties_by_claim_number(self):
        ledger = _ledger_with(self.ws, ["营收 10 亿", "良率 70%", "毛利 5 亿"])
        ledger.add_claim("营收 10 亿", "https://other.com/x")  # 合并到 C1，C1 有两个来源
        ledger.save()
        self.assertEqual(pick_for_verification(ledger), ["C2", "C3", "C1"])
        self.assertEqual(pick_for_verification(ledger), pick_for_verification(Ledger.load(self.ws)))

    def test_limit_applies_after_priority(self):
        ledger = _ledger_with(self.ws, ["营收 10 亿", "良率 70%", "该条例自 2027 年起施行"])
        self.assertEqual(pick_for_verification(ledger, limit=1), ["C3"])
        self.assertEqual(pick_for_verification(ledger, limit=0), [])

    def test_checked_and_uncitable_claims_are_skipped(self):
        ledger = _ledger_with(self.ws, ["国标 A 已发布", "国标 B 已发布", "国标 C 已发布"])
        ledger.set_status("C1", "supported")
        ledger.set_status("C2", "overruled")
        self.assertEqual(pick_for_verification(ledger), ["C3"])

    def test_keyword_table_covers_chinese_and_english(self):
        texts = ["企业标准", "国标", "行标", "GB 38031", "ISO 26262", "IEC 62660", "法规", "条例", "办法", "政策",
                 "通知", "发布", "实施", "生效", "财报", "年报", "季报", "公告", "产能", "专利", "论文",
                 "DOI 10.1000/xyz", "批准", "认证", "The regulation took effect", "annual report",
                 "SEC filing", "patent granted", "FDA approval", "certification"]
        ledger = _ledger_with(self.ws, texts)
        self.assertEqual(len(pick_for_verification(ledger, limit=100)), len(texts))

    def test_plain_text_and_storage_units_are_not_keywords(self):
        ledger = _ledger_with(self.ws, ["电池容量 512GB 级别", "传输 10 GB/s", "没有任何特征的观点",
                                        "second-generation cell"])
        self.assertEqual(pick_for_verification(ledger, limit=100), ["C1", "C2"])  # 只有含数字的两条，无关键词


class DepthVerifyTests(unittest.TestCase):
    def test_presets_carry_verify_counts(self):
        import config
        self.assertEqual({k: v["verify"] for k, v in config.DEPTH_PRESETS.items()},
                         {"quick": 8, "standard": 12, "deep": 16})

    def test_default_param_keeps_the_old_signature(self):
        import inspect
        self.assertEqual(inspect.signature(FactCheckerAgent.check_facts).parameters["limit"].default, MAX_VERIFY)
        self.assertEqual(MAX_VERIFY, 8)


if __name__ == "__main__":
    unittest.main()
