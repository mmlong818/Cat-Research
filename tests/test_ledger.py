import shutil
import tempfile
import threading
import unittest

from research.ledger import NEITHER, Ledger, LedgerError, body_of, check_citations, format_violations, with_references


def _ledger():
    ws = tempfile.mkdtemp()
    return Ledger.load(ws), ws


class LedgerWriteTests(unittest.TestCase):
    def setUp(self):
        self.l, self.ws = _ledger()
        self.addCleanup(shutil.rmtree, self.ws, True)

    def test_claims_dedupe_by_text_and_merge_sources(self):
        a, new_a = self.l.add_claim("丰田计划 2027 年量产全固态电池", "https://www.toyota.com/a", round_num=1)
        b, new_b = self.l.add_claim("丰田计划2027年量产全固态电池。", "https://reuters.com/b", round_num=2)
        self.assertEqual((a, new_a, b, new_b), ("C1", True, "C1", False))
        self.assertEqual(self.l.claims["C1"]["sources"], ["S1", "S2"])
        self.assertEqual(self.l.new_claims_in_round(2), 0)

    def test_sources_dedupe_by_normalized_url(self):
        s1 = self.l.add_source("https://www.Example.com/x/")
        s2 = self.l.add_source("http://example.com/x")
        self.assertEqual(s1, s2)

    def test_resolve_one_side_overrules_the_other(self):
        a, _ = self.l.add_claim("良率 85%")
        b, _ = self.l.add_claim("良率 60%")
        x = self.l.add_contradiction(a, b, "良率")
        self.assertEqual(self.l.unresolved(), [x])
        self.l.resolve(x, b, "官方披露为 60%", "https://ir.example.com")
        self.assertEqual((self.l.claims[a]["status"], self.l.claims[b]["status"]), ("overruled", "supported"))
        self.assertEqual(self.l.unresolved(), [])
        self.assertNotIn(a, self.l.citable())

    def test_overruled_is_sticky_across_contradictions(self):
        a, _ = self.l.add_claim("2027 量产")
        b, _ = self.l.add_claim("2030 量产")
        c, _ = self.l.add_claim("2028 量产")
        x1 = self.l.add_contradiction(a, b)
        x2 = self.l.add_contradiction(a, c)
        self.l.resolve(x1, b, "官方为 2030")
        self.l.resolve(x2, a, "相对 2028 更可信")  # 在另一处胜出也不能撤销「被推翻」
        self.assertEqual(self.l.claims[a]["status"], "overruled")
        self.assertEqual(self.l.claims[c]["status"], "overruled")

    def test_resolve_rejects_side_outside_pair(self):
        a, _ = self.l.add_claim("x1")
        b, _ = self.l.add_claim("x2")
        c, _ = self.l.add_claim("x3")
        x = self.l.add_contradiction(a, b)
        with self.assertRaisesRegex(LedgerError, "只能裁决为"):
            self.l.resolve(x, c, "错配")

    def test_contradiction_pairs_dedupe_and_reject_self(self):
        a, _ = self.l.add_claim("x1")
        b, _ = self.l.add_claim("x2")
        self.assertEqual(self.l.add_contradiction(a, b), self.l.add_contradiction(b, a))
        with self.assertRaises(LedgerError):
            self.l.add_contradiction(a, a)

    def test_merge_marks_duplicate_and_keeps_sources(self):
        a, _ = self.l.add_claim("QuantumScape 2026 年出货 B 样品", "https://qs.com/1")
        b, _ = self.l.add_claim("QS 在 2026 年交付 B 样", "https://news.com/2")
        self.l.merge(a, b)
        self.assertEqual(self.l.claims[a]["sources"], ["S1", "S2"])
        self.assertEqual(self.l.claims[b]["status"], "merged")
        self.assertNotIn(b, self.l.citable())
        v = check_citations(self.l, f"QS 交付 B 样 [{b}]。")["violations"]
        self.assertEqual([(x["type"], x["claim"]) for x in v], [("merged", b)])
        self.assertIn(a, v[0]["detail"])

    def test_save_load_roundtrip_and_concurrent_adds(self):
        threads = [threading.Thread(target=self.l.add_claim, args=(f"声明{i}", f"https://s.com/{i}"))
                   for i in range(40)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.l.save()
        again = Ledger.load(self.ws)
        self.assertEqual((len(again.claims), len(again.sources)), (40, 40))
        self.assertEqual(sorted(again.claims), sorted(f"C{i}" for i in range(1, 41)))


class CitationCheckTests(unittest.TestCase):
    def setUp(self):
        self.l, self.ws = _ledger()
        self.addCleanup(shutil.rmtree, self.ws, True)
        for t in ("A 公司良率 85%", "A 公司良率 60%", "B 公司 2027 量产", "B 公司 2029 量产", "C 公司扩产"):
            self.l.add_claim(t, "https://src.com/" + t)
        self.l.resolve(self.l.add_contradiction("C1", "C2"), "C2", "官方为 60%")
        self.pair = self.l.add_contradiction("C3", "C4")
        self.l.resolve(self.pair, NEITHER, "口径不一")

    def types(self, text):
        return sorted((v["type"], v["claim"]) for v in check_citations(self.l, text)["violations"])

    def test_clean_report_has_no_violations(self):
        text = "A 公司良率为 60% [C2]。\n\nB 公司量产时间存在分歧：2027 [C3] 与 2029 [C4]。"
        r = check_citations(self.l, text)
        self.assertEqual(r["violations"], [])
        self.assertEqual(r["cited"], ["C2", "C3", "C4"])

    def test_overruled_and_unknown_are_violations(self):
        self.assertEqual(self.types("良率 85% [C1]，另见 [C99]。"), [("overruled", "C1"), ("unknown", "C99")])

    def test_neither_claims_must_be_paired_in_same_paragraph(self):
        self.assertEqual(self.types("B 公司 2027 量产 [C3]。\n\n另一种说法 [C4]。"),
                         [("unpaired", "C3"), ("unpaired", "C4")])

    def test_unresolved_contradiction_blocks_citation(self):
        x = self.l.add_contradiction("C5", "C2")
        self.assertEqual(self.types("C 公司扩产 [C5, C2]。"), [("unresolved", "C2"), ("unresolved", "C5")])
        self.assertIn(x, self.l.unresolved())

    def test_numeric_coverage(self):
        r = check_citations(self.l, "A 公司 2026 年良率 60% 左右 [C2]。B 公司 2029 年的计划尚不明确说法很多。")
        self.assertEqual(r["numeric_coverage"], 0.5)

    def test_references_lists_cited_claims_with_urls(self):
        ref = self.l.references({"C2", "C3"})
        self.assertIn("[C2]", ref)
        self.assertIn("https://src.com/A 公司良率 60%", ref)
        self.assertNotIn("[C1]", ref)

    def test_merged_citations_are_remapped_to_kept_claim(self):
        self.l.add_claim("C 公司扩产（重复表述）")  # C6
        self.l.add_claim("D 公司扩产")              # C7
        self.l.merge("C5", "C6")
        self.l.merge("C7", "C5")                    # 链式合并：C6 -> C5 -> C7
        text, check = with_references(self.l, "扩产 [C6]，另见 [C5, C2]。")
        self.assertEqual(body_of(text), "扩产 [C7]，另见 [C7, C2]。")
        self.assertEqual((check["cited"], check["violations"]), (["C2", "C7"], []))

    def test_merge_repoints_contradictions_and_status_to_kept_claim(self):
        self.l.add_claim("B 公司 2029 年量产（另一来源）")  # C6
        self.l.merge("C6", "C4")  # C4 属于「两方都不可靠」的矛盾 X2
        self.assertEqual(self.l.contradictions[self.pair]["claims"], ["C3", "C6"])
        self.assertEqual(self.l.claims["C6"]["status"], "disputed")
        self.assertIn("[C6] (存疑)", self.l.claims_table())
        x = self.l.add_contradiction("C5", "C2")
        self.l.add_claim("C 公司扩产（重复）")  # C7
        self.l.merge("C7", "C5")  # 未决矛盾同样转移
        self.assertEqual(sorted(self.l.contradictions[x]["claims"]), ["C2", "C7"])

    def test_pair_requirement_follows_merged_claim(self):
        self.l.add_claim("B 公司 2027 量产（另一来源）")  # C6
        self.l.merge("C6", "C4")  # 成对声明 C4 被并入 C6
        self.assertEqual(self.types("分歧：2027 [C3] 与 2029 [C6]。"), [])
        self.assertIn("C3 与 C6 须在同一段落成对引用", self.l.claims_table())

    def test_with_references_regenerates_appendix_and_checks_body_only(self):
        text, check = with_references(self.l, "正文 [C2]。")
        self.assertIn("## 声明来源", text)
        self.assertEqual(body_of(text), "正文 [C2]。")
        again, check2 = with_references(self.l, text)  # 重复附加时替换而非叠加
        self.assertEqual(again.count("## 声明来源"), 1)
        self.assertEqual((check["cited"], check2["violations"]), (["C2"], []))

    def test_claims_table_hides_unresolved_and_lists_pairs(self):
        self.l.add_contradiction("C5", "C2")
        table = self.l.claims_table()
        self.assertNotIn("[C5]", table)
        self.assertNotIn("[C1]", table)  # 已被推翻
        self.assertIn("暂不可引用（矛盾尚未裁决）：C2, C5", table)
        self.assertIn("C3 与 C4 须在同一段落成对引用", table)

    def test_format_violations(self):
        v = check_citations(self.l, "[C1]")["violations"]
        self.assertTrue(format_violations(v).startswith("- [C1] 引用了已被推翻的声明"))


class ClaimsTablePairAnnotationTests(unittest.TestCase):
    """两方存疑的矛盾：声明行内标注冲突的对方编号，写作者在该行就能看到要成对引用谁。"""

    def setUp(self):
        self.l, self.ws = _ledger()
        self.addCleanup(shutil.rmtree, self.ws, True)
        for t in ("甲 2027 量产", "甲 2029 量产", "甲 2030 量产", "乙 良率 85%", "乙 良率 60%", "丙 扩产"):
            self.l.add_claim(t, "https://src.com/" + t)  # C1..C6
        self.l.resolve(self.l.add_contradiction("C1", "C2"), NEITHER, "口径不一")
        self.l.resolve(self.l.add_contradiction("C1", "C3"), NEITHER, "口径不一")
        self.l.resolve(self.l.add_contradiction("C4", "C5"), "C5", "官方为 60%")

    def line(self, cid):
        return next(x for x in self.l.claims_table().splitlines() if x.startswith(f"[{cid}]"))

    def test_single_pair_is_annotated_inline_in_chinese(self):
        self.assertTrue(self.line("C2").endswith("（与 C1 说法冲突，须同段一并引用）"), self.line("C2"))

    def test_claim_in_several_neither_contradictions_lists_every_counterpart(self):
        self.assertTrue(self.line("C1").endswith("（与 C2、C3 说法冲突，须同段一并引用）"), self.line("C1"))

    def test_decisive_verdicts_and_untouched_claims_are_not_annotated(self):
        self.assertNotIn("说法冲突", self.line("C5"))  # 裁决胜出
        self.assertNotIn("说法冲突", self.line("C6"))
        self.assertEqual(self.line("C6"), "[C6] 丙 扩产  — 来源 S6")

    def test_annotation_follows_merge_to_the_kept_claim(self):
        self.l.add_claim("甲 2029 量产（另一来源）")  # C7
        self.l.merge("C7", "C2")
        self.assertTrue(self.line("C7").endswith("（与 C1 说法冲突，须同段一并引用）"))
        self.assertTrue(self.line("C1").endswith("（与 C3、C7 说法冲突，须同段一并引用）"), self.line("C1"))

    def test_pair_summary_section_is_kept(self):
        table = self.l.claims_table()
        self.assertIn("## 成对引用要求", table)
        self.assertIn("C1 与 C2 须在同一段落成对引用", table)


class VoidPairTests(unittest.TestCase):
    """neither 矛盾中一方已不可引用（被推翻/合并到被推翻的声明）：成对引用要求作废。"""

    def setUp(self):
        self.l, self.ws = _ledger()
        self.addCleanup(shutil.rmtree, self.ws, True)
        for t in ("甲 2027", "甲 2029", "甲 2030", "乙 扩产"):
            self.l.add_claim(t, "https://src.com/" + t)  # C1..C4
        self.l.resolve(self.l.add_contradiction("C1", "C2"), NEITHER, "口径不一")
        self.l.resolve(self.l.add_contradiction("C1", "C3"), NEITHER, "口径不一")

    def types(self, text):
        return sorted((v["type"], v["claim"]) for v in check_citations(self.l, text)["violations"])

    def line(self, cid):
        return next(x for x in self.l.claims_table().splitlines() if x.startswith(f"[{cid}]"))

    def test_single_pair_void_when_one_side_overruled(self):
        self.l.set_status("C2", "overruled", "被别处裁决推翻")
        self.l.set_status("C3", "overruled", "被别处裁决推翻")
        self.assertEqual(self.types("甲 2027 [C1]。"), [])  # 不再报 unpaired
        self.assertEqual(self.types("甲 2029 [C2]。"), [("overruled", "C2")])  # 引用被推翻者仍违规
        self.assertNotIn("说法冲突", self.line("C1"))
        table = self.l.claims_table()
        self.assertNotIn("## 成对引用要求", table)
        self.assertNotIn("须在同一段落成对引用", table)

    def test_multi_pair_only_the_dead_counterpart_is_dropped(self):
        self.l.set_status("C3", "overruled", "被别处裁决推翻")
        self.assertTrue(self.line("C1").endswith("（与 C2 说法冲突，须同段一并引用）"), self.line("C1"))
        self.assertEqual(self.types("甲 2027 [C1]。"), [("unpaired", "C1")])
        self.assertEqual(self.types("甲 2027 [C1]，另一说法 [C2]。"), [])
        table = self.l.claims_table()
        self.assertIn("C1 与 C2 须在同一段落成对引用", table)
        self.assertNotIn("C1 与 C3", table)

    def test_void_follows_canonical_after_merge(self):
        self.l.add_claim("甲 2029（另一来源）")  # C5
        self.l.merge("C5", "C2")  # C2 并入 C5，矛盾转到 C5
        self.l.set_status("C5", "overruled", "被别处裁决推翻")
        self.l.set_status("C3", "overruled", "被别处裁决推翻")
        self.assertEqual(self.types("甲 2027 [C1]。"), [])
        self.assertNotIn("说法冲突", self.line("C1"))
        self.assertNotIn("C5", self.l.claims_table().split("## 成对引用要求")[-1])

    def test_live_pairs_are_unaffected(self):
        self.assertTrue(self.line("C1").endswith("（与 C2、C3 说法冲突，须同段一并引用）"), self.line("C1"))
        self.assertEqual(self.types("甲 2027 [C1]。"), [("unpaired", "C1")])


class ContradictionDedupeTests(unittest.TestCase):
    """合并重复声明后，canonical 化后声明对相同的矛盾只保留一处（保留已有裁决，冲突取更强者）。"""

    def setUp(self):
        self.l, self.ws = _ledger()
        self.addCleanup(shutil.rmtree, self.ws, True)
        for t in ("甲 2027 量产", "Jia mass production 2027", "甲 2029 量产", "乙 良率 85%", "乙 良率 60%"):
            self.l.add_claim(t, "https://src.com/" + t)  # C1 C2(与 C1 重复) C3 C4 C5

    def test_merge_collapses_contradictions_that_become_the_same_pair(self):
        x1 = self.l.add_contradiction("C2", "C3", "量产年份")
        x2 = self.l.add_contradiction("C1", "C3", "量产年份")
        self.l.resolve(x2, NEITHER, "口径不一")
        self.l.merge("C1", "C2")
        self.assertEqual(list(self.l.contradictions), [x1])
        x = self.l.contradictions[x1]
        self.assertEqual((x["claims"], x["resolution"]["sides_with"]), (["C1", "C3"], NEITHER))

    def test_existing_resolution_is_kept_when_the_other_is_unresolved(self):
        x1 = self.l.add_contradiction("C2", "C3")
        x2 = self.l.add_contradiction("C1", "C3")
        self.l.resolve(x1, NEITHER, "口径不一")
        self.l.merge("C1", "C2")
        self.assertEqual(list(self.l.contradictions), [x1])
        self.assertEqual(self.l.contradictions[x1]["resolution"]["sides_with"], NEITHER)
        self.assertNotIn(x2, self.l.contradictions)
        self.assertEqual(self.l.unresolved(), [])

    def test_decisive_verdict_beats_neither_in_either_order(self):
        for first_neither in (True, False):
            with self.subTest(first_neither=first_neither):
                led, ws = _ledger()
                self.addCleanup(shutil.rmtree, ws, True)
                for t in ("甲 2027", "Jia 2027", "甲 2029"):
                    led.add_claim(t, "https://src.com/" + t)
                xa = led.add_contradiction("C2", "C3")
                xb = led.add_contradiction("C1", "C3")
                led.resolve(xa, NEITHER if first_neither else "C3", "r1")
                led.resolve(xb, "C3" if first_neither else NEITHER, "r2")
                led.merge("C1", "C2")
                self.assertEqual(list(led.contradictions), [xa])
                self.assertEqual(led.contradictions[xa]["resolution"]["sides_with"], "C3")
                self.assertEqual([led.claims[c]["status"] for c in ("C1", "C3")], ["overruled", "supported"])

    def test_different_conflict_points_are_untouched(self):
        a = self.l.add_contradiction("C1", "C3")
        b = self.l.add_contradiction("C4", "C5")
        c = self.l.add_contradiction("C1", "C5")  # 与 C1 有关但是另一对
        self.l.merge("C1", "C2")  # C2 不在任何矛盾里
        self.assertEqual(list(self.l.contradictions), [a, b, c])

    def test_new_contradiction_ids_never_collide_after_a_dedupe(self):
        self.l.add_contradiction("C2", "C3")  # X1
        self.l.add_contradiction("C1", "C3")  # X2，合并后被去掉
        self.l.add_contradiction("C4", "C5")  # X3
        self.l.merge("C1", "C2")
        self.assertEqual(self.l.add_contradiction("C1", "C5"), "X4")
        self.assertEqual(sorted(self.l.contradictions), ["X1", "X3", "X4"])

    def test_dedupe_contradictions_on_a_loaded_ledger_is_idempotent(self):
        self.l.add_contradiction("C1", "C3")
        self.l.add_contradiction("C4", "C5")
        self.assertEqual(self.l.dedupe_contradictions(), 0)


if __name__ == "__main__":
    unittest.main()
