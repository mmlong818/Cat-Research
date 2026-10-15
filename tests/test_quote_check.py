"""Z2 摘录核对：声明里的数字与时间表述必须能在原文片段中找到（确定性纯函数，research/quote_check.py）。"""
import unittest

from research.quote_check import MISSING, check_quote


class _Base(unittest.TestCase):
    def ok(self, claim, quote):
        ok, detail = check_quote(claim, quote)
        self.assertTrue(ok, f"应一致：{claim!r} vs {quote!r} -> {detail}")
        self.assertEqual(detail, "")

    def bad(self, claim, quote, *needles):
        ok, detail = check_quote(claim, quote)
        self.assertFalse(ok, f"应不一致：{claim!r} vs {quote!r}")
        for n in needles:
            self.assertIn(n, detail)
        return detail


class RealCaseTests(_Base):
    def test_c17_second_half_vs_second_quarter_is_flagged(self):
        detail = self.bad("三星 SDI 全固态电池 2027年第二季度 量产",
                          "mass production is scheduled to begin in the second half of 2027", "Q2", "H2")
        self.assertNotIn("2027", detail)  # 年份本身是对的，不应报数字问题

    def test_same_sentence_with_the_right_period_is_consistent(self):
        self.ok("三星 SDI 计划 2027 年下半年量产",
                "mass production is scheduled to begin in the second half of 2027")


class MissingQuoteTests(_Base):
    def test_empty_none_and_blank_quote_are_missing(self):
        for q in ("", None, "   \n"):
            with self.subTest(q=q):
                self.assertEqual(check_quote("2027 年量产", q), (False, MISSING))
        self.assertEqual(MISSING, "缺原文片段")

    def test_missing_even_when_the_claim_has_no_numbers(self):
        self.assertEqual(check_quote("甲公司发布新电池", ""), (False, MISSING))


class NumberTests(_Base):
    def test_all_numbers_present_is_consistent(self):
        self.ok("宁德时代 2026 年产能 120 GWh", "CATL's capacity reaches 120 GWh in 2026.")

    def test_missing_number_is_flagged_and_named(self):
        detail = self.bad("宁德时代建设 1GWh 中试线", "宁德时代宣布建设中试线，预计 2026 年投产", "1")
        self.assertIn("数字", detail)

    def test_a_number_that_only_contains_the_digits_does_not_match(self):
        self.bad("产能 12 GWh", "capacity of 120 GWh")  # 12 不能匹配 120
        self.bad("2027 年量产", "scheduled for 20270 units in 2028")  # 片段里有别的年份，年份照常比对

    def test_percent_and_decimals(self):
        self.ok("能量密度提升 35.5%", "energy density improved by 35.5 percent")
        self.ok("良率 95%", "良率达到 95％")  # 全角百分号
        self.bad("良率 95.5%", "yield reached 95 percent", "95.5")
        self.ok("增长 10.0%", "growth of 10%")  # 尾零归一
        self.ok("增长 10%", "growth of 10.00%")

    def test_ranges_check_both_ends(self):
        self.ok("能量密度 1.6-2.2 倍", "energy density is 1.6 to 2.2 times")
        self.bad("能量密度 1.6-2.2 倍", "energy density is about 1.6 times", "2.2")

    def test_thousands_separators(self):
        self.ok("出货 1,200 万辆", "shipments of 1200 万辆")
        self.ok("shipments of 1200", "shipments of 1,200 units")

    def test_comma_between_separate_numbers_is_not_a_thousands_separator(self):
        self.ok("2026, 2027 年", "in 2026 and 2027")

    def test_full_width_digits_are_normalised(self):
        self.ok("2027 年量产", "２０２７年量产")

    def test_chinese_numerals_in_the_quote_count(self):
        self.ok("预计 2 条产线，投资 15 亿元", "预计建设二条产线，投资十五亿元")
        self.ok("共 25 项", "共二十五项")
        self.ok("共 120 项", "共一百二十项")
        self.ok("2027 年量产", "二〇二七年量产")

    def test_chinese_numerals_in_the_claim_are_not_checked(self):
        self.ok("建设三条产线", "builds production lines")

    def test_physical_units_are_not_converted(self):
        self.bad("1GWh 中试线", "a 1,000 MWh pilot line")  # 只比数字本身；量级词换算见 MagnitudeTests
        self.bad("2GWh 产线", "a 2000 MWh line")

    def test_digits_inside_known_outlet_names_are_not_data(self):
        self.ok("21世纪经济报道称，亿纬锂能 60Ah 全固态电芯于 2026 年下线", "亿纬锂能：60Ah 全固态电芯 2026 年下线")
        self.ok("36氪说宁德时代已建成 1GWh 中试线", "宁德时代已建成 1GWh 中试线")
        self.ok("据24/7 Wall St.报道，QuantumScape 目标 2026 年交付", "QuantumScape targets deliveries in 2026")
        self.bad("21世纪经济报道称 60Ah 电芯", "亿纬锂能 80Ah 电芯", "60")

    def test_year_counts_as_a_number(self):
        self.bad("2028 年量产", "mass production in 2027", "2028")

    def test_numbers_only_in_the_quote_are_not_a_violation(self):
        self.ok("丰田计划量产", "Toyota plans mass production by 2027 with 10 GWh")

    def test_claim_without_numbers_or_time_is_consistent_with_any_quote(self):
        self.ok("丰田发布全固态电池", "Toyota unveiled a solid-state battery")


class QuarterTests(_Base):
    def test_synonyms_are_equivalent(self):
        claims = ["2027 年第二季度", "2027 年二季度", "2027年第2季度", "2027 Q2", "2027年Q2", "2Q27",
                  "second quarter of 2027", "2nd quarter 2027", "2027Q2", "Q2'27"]
        quotes = ["二季度", "第二季度", "Q2 2027", "2Q 2027", "the second quarter of 2027", "2027-Q2"]
        for c in claims:
            for q in quotes:
                with self.subTest(claim=c, quote=q):
                    self.ok(c + " 量产", q + " 2027 量产")

    def test_different_quarter_is_flagged(self):
        self.bad("2027 年一季度量产", "Q2 2027 mass production", "Q1")
        self.bad("Q3 2027", "2027 Q4", "Q3")

    def test_quarter_digit_is_not_double_checked_as_a_plain_number(self):
        self.ok("Q2 2027 量产", "second quarter of 2027")  # 2 是季度，不要求片段里出现数字 2
        self.ok("第三季度 10 GWh", "third quarter, 10 GWh")

    def test_quarter_vs_half_is_not_equivalent(self):
        self.bad("2027 年第三季度", "second half of 2027", "Q3")
        self.bad("2027 年上半年", "Q1 2027", "H1")

    def test_cumulative_quarters_are_not_recognised(self):
        self.ok("前三季度营收 10 亿", "营收 10 亿，前三季度")
        self.ok("前三季度营收 10 亿", "first three quarters, revenue of 10")

    def test_range_of_quarters_checks_the_ends(self):
        self.ok("2027 年一至三季度", "Q1 to Q3 2027")
        self.bad("2027 年一至三季度", "Q1 2027", "Q3")

    def test_quarter_letters_inside_model_names_are_not_time(self):
        self.ok("使用 4680 电池", "4680 cells")
        self.ok("H100 芯片 2027", "H100 chips in 2027")
        self.ok("GQ2 型号 2027", "model GQ2 in 2027")


class HalfYearTests(_Base):
    def test_second_half_synonyms(self):
        for c in ("2027 年下半年", "2027 H2", "2H27", "2H 2027", "second half of 2027", "2nd half 2027", "2027H2"):
            for q in ("下半年", "H2 2027", "2H 2027", "second half of 2027", "the second-half of 2027"):
                with self.subTest(claim=c, quote=q):
                    self.ok(c + " 量产", q + " 2027 量产")

    def test_first_half_synonyms(self):
        for c in ("2027 年上半年", "H1 2027", "first half of 2027", "1H27"):
            for q in ("上半年", "H1", "1H", "first half"):
                with self.subTest(claim=c, quote=q):
                    self.ok(c + " 量产", q + " 2027 量产")

    def test_half_mismatch_is_flagged(self):
        self.bad("2027 年下半年", "first half of 2027", "H2")
        self.bad("2027 年上半年", "second half of 2027", "H1")

    def test_later_this_year_is_not_a_second_half(self):
        self.bad("2027 年下半年量产", "mass production later this year in 2027", "H2")

    def test_the_half_digit_is_not_checked_as_a_number(self):
        self.ok("H2 2027 量产", "second half 2027 量产")

    def test_two_digit_year_attached_to_the_half_token_counts_as_the_year(self):
        self.ok("2H27 量产", "second half of 2027")
        self.bad("2H28 量产", "second half of 2027", "2028")


class MonthTests(_Base):
    def test_chinese_and_english_months_are_equivalent(self):
        for c in ("3月", "三月", "March", "Mar", "3月份"):
            for q in ("3月", "March", "Mar.", "三月"):
                with self.subTest(claim=c, quote=q):
                    self.ok(f"2027 年{c}投产" if "月" in c else f"2027 {c} start", f"{q} 2027")

    def test_month_mismatch_is_flagged(self):
        self.bad("2027 年 3 月投产", "production starts in April 2027", "3月")

    def test_month_digit_is_not_checked_as_a_plain_number(self):
        self.ok("3月15日投产", "starts on March 15")
        self.ok("2027年10月投产", "October 2027")

    def test_day_number_is_still_checked(self):
        self.bad("3月15日投产", "starts in March", "15")

    def test_month_range(self):
        self.ok("3-5月投产", "from March to May")
        self.bad("3-5月投产", "in March", "5月")

    def test_iso_dates(self):
        self.ok("2026-10-03 发布", "published October 3, 2026")
        self.ok("发布于 3月", "2027-03-15")
        self.bad("2026-10-03 发布", "published November 3, 2026", "10月")

    def test_may_modal_verb_in_lowercase_is_not_a_month(self):
        self.bad("2027 年 5 月投产", "production may start in 2027", "5月")

    def test_month_in_a_duration_is_not_a_calendar_month(self):
        self.ok("耗时 18 个月", "took 18 months")


class YearEndTests(_Base):
    def test_synonyms(self):
        for c in ("2026 年底", "2026年末", "end of 2026", "by the end of the year 2026", "year-end 2026", "end-2026"):
            for q in ("2026年底", "年末", "by the end of 2026", "end of the year", "year end"):
                with self.subTest(claim=c, quote=q):
                    self.ok(c + " 量产", q + " 2026 量产")

    def test_ye_abbreviation_with_a_year(self):
        self.ok("Solid Power预计到2026年底电解质总年产能达到75吨",
                "Expect to reach 75 MT total annual capacity by YE 2026")
        self.ok("2026年底前宣布合资公司", "Expect to announce a joint venture by YE26")
        self.bad("2026年底投产", "ye shall see production in 2026", "年底")

    def test_end_of_the_decade_is_not_year_end(self):
        self.ok("本田目标在本十年末前推出固态电池电动车", "by the end of the decade")
        self.bad("2027年底投产", "by the end of the decade 2027", "年底")

    def test_year_end_missing_is_flagged(self):
        self.bad("2026 年底投产", "production starts in 2026", "年底")

    def test_month_end_is_not_year_end(self):
        self.bad("2026 年底投产", "end of March 2026", "年底")


class MixedLanguageTests(_Base):
    def test_chinese_claim_english_quote(self):
        self.ok("LG 新能源计划 2026 年 6 月量产 4680 电池，目标产能 10 GWh",
                "LG Energy Solution plans to start mass production of 4680 cells in June 2026, targeting 10 GWh.")

    def test_english_claim_chinese_quote(self):
        self.ok("CATL raises capacity to 120 GWh by Q4 2026", "宁德时代 2026 年第四季度产能提升至 120 GWh")

    def test_detail_is_in_chinese_and_lists_every_problem(self):
        detail = self.bad("2027 年第二季度产能 15 GWh", "second half of 2027, capacity of 10 GWh", "数字", "15", "Q2")
        self.assertIn("未见于原文片段", detail)


class KoreanJapaneseTimeTests(_Base):
    def test_c307_korean_second_half(self):
        self.ok("三星SDI在水原研究所运行全固态电池中试线，目标2027年下半年量产",
                "현재 경기 수원 연구소에 파일럿 라인을 가동 중이며, 2027년 하반기 양산을 목표로 하고 있다.")

    def test_c305_korean_month_and_quarters(self):
        self.ok("Solid Power与SK On约5月完成连续制造中试线含回转窑在内的主要设备安装，"
                "目标第三季度完成设备验收测试、第四季度开始工厂验证和试运行",
                "5월경 로터리 킬른을 포함한 주요 장비 설치를 완료했고, 3분기 장비 인수 테스트(SAT)를 마치고 "
                "4분기 공장 검증 및 시운전 개시를 목표로 하고 있다.")

    def test_c220_korean_last_year_end(self):
        self.ok("据电子新闻报道，现代汽车在京畿道义王建设的试点线上于报道所称的去年底大量生产了全固态电池",
                "현대자동차는 지난해 말 경기도 의왕에 구축한 파일럿 라인에서 "
                "전고체 배터리를 대거 생산한 것으로 파악됐다")

    def test_korean_synonyms(self):
        self.ok("2027年上半年量产", "2027년 상반기 양산")
        self.ok("2027年底量产", "2027년 말 양산")
        self.ok("年底量产", "올해 말 양산")
        self.ok("年底量产", "연말 양산")
        self.ok("2027年第一季度", "2027년 1분기")
        self.ok("2027年3月", "2027년 3월")

    def test_korean_mismatch_is_still_flagged(self):
        self.bad("2027年第二季度量产", "2027년 하반기 양산을 목표로", "Q2", "H2")
        self.bad("2027年上半年量产", "2027년 하반기 양산을 목표로", "H1")
        self.bad("2027年6月量产", "5월경 양산", "6月")
        self.bad("2027年第四季度", "3분기 완료", "Q4")

    def test_korean_month_duration_is_not_a_calendar_month(self):
        self.ok("耗时 18 个月", "18개월 소요")

    def test_japanese_synonyms(self):
        self.ok("2027年上半年", "2027年上半期")
        self.ok("2027年上半年", "2027年度上期")
        self.ok("2027年下半年", "2027年下半期")
        self.ok("2027年下半年", "2027年下期")
        self.ok("2027年第三季度", "2027年第3四半期")
        self.ok("2027年第二季度", "2027年第二四半期")
        self.ok("2027年5月投产", "2027年5月に投産")
        self.ok("2027年底", "2027年末")

    def test_japanese_year_end(self):
        self.ok("2027财年末量产", "2027年度末までに量産")
        self.ok("2027年底量产", "2027年度末までに量産")
        self.ok("期末现金 100 亿日元", "期末の現金 100 億円")

    def test_japanese_mismatch_is_still_flagged(self):
        self.bad("2027年下半年", "2027年上期", "H2")
        self.bad("2027年第二季度", "2027年第3四半期", "Q2")

    def test_quarter_end_is_not_year_end(self):
        self.bad("2027年底投产", "第3四半期末までに", "年底")


class FiscalYearEndTests(_Base):
    def test_c304_end_of_fiscal_year(self):
        self.ok("麦克赛尔考虑在2027财年末前量产中型全固态电池",
                "considering mass production of a medium-sized all-solid-state battery by the end of fiscal 2027")

    def test_english_variants_are_year_end(self):
        for q in ("end of fiscal 2027", "end of fiscal year 2027", "end of the fiscal year", "fiscal year-end",
                  "FY-end", "end of FY2027", "end of FY27", "year-end"):
            with self.subTest(q=q):
                self.ok("2027年底量产", f"mass production by {q} 2027")

    def test_fiscal_year_end_claim_needs_a_year_end_quote(self):
        self.bad("2027财年末量产", "mass production in 2027", "年底")

    def test_end_of_a_quarter_or_month_is_not_year_end(self):
        self.bad("2027年底量产", "by the end of the second quarter of 2027", "年底")


class MissingYearTests(_Base):
    def test_c40_claim_year_ignored_when_quote_has_no_year(self):
        self.ok("QuantumScape ended Q2 2026 with $859.0M in liquidity.", "We ended Q2 with $859.0M in liquidity")

    def test_claim_year_still_checked_when_quote_has_another_year(self):
        self.bad("2028 年量产", "mass production in 2027", "2028")
        self.bad("QuantumScape ended Q2 2026 with $859.0M", "We ended Q2 2025 with $859.0M", "2026")

    def test_other_numbers_are_still_checked_when_year_is_ignored(self):
        self.bad("QuantumScape ended Q2 2026 with $880.0M", "We ended Q2 with $859.0M", "880")

    def test_time_expressions_are_still_checked_when_year_is_ignored(self):
        self.bad("2027 年第二季度量产", "mass production in the third quarter", "Q2")

    def test_quote_with_year_from_chinese_numerals_or_short_year_counts(self):
        self.bad("2028 年量产", "二〇二七年量产", "2028")
        self.bad("2028 年下半年", "H2'27", "2028")

    def test_year_like_quantities_are_not_ignored(self):
        self.bad("2000 units shipped", "1500 units shipped", "2000")
        self.bad("2,000 cycles", "cycles exceeding 1,500", "2000")
        self.bad("capacity of 2000 MWh", "capacity of 1500 MWh", "2000")

    def test_non_year_number_in_quote_is_not_a_year(self):
        self.ok("QuantumScape ended Q2 2026 with $859.0M", "We ended Q2 with $859.0M, up 12%")


class MagnitudeTests(_Base):
    def test_close_but_different_amounts_still_differ(self):
        # 量级换算本身是精确的，容差只用来吸收浮点误差，不能放过相差 0.1% 的不同金额
        self.bad("QuantumScape ended the quarter with $860.0 million in liquidity",
                 "We ended Q2 with $859.0M in liquidity")

    def test_c23_chinese_yi_vs_english_billion(self):
        self.ok("From January to July 2026, China had 52 publicly announced solid-state battery and core material "
                "investment projects totaling 53 billion yuan.",
                "2026年1-7月我国固态电池及核心材料公开投资项目达52个，总投资额达530亿元")

    def test_cross_language_combinations(self):
        pairs = [("总投资 530 亿元", "total 53 billion yuan"), ("53 billion yuan", "530亿元"),
                 ("5.3 trillion", "5.3 万亿"), ("5.3万亿元", "5.3 trillion yuan"), ("5.3 trillion won", "5.3조원"),
                 ("25조원", "25 trillion won"), ("100 억 원", "10 billion won"), ("1,200 万辆", "12 million vehicles"),
                 ("12 million units", "1200万台"), ("200 万元/吨", "2 million yuan/ton"), ("859 million", "$859.0M"),
                 ("$17 billion", "US$17B"), ("17 bn", "17 billion"), ("17 tn", "17 trillion"), ("4 thousand", "4000"),
                 ("$5m", "5 million"), ("3千万", "30 million"), ("2 百万", "2 million"), ("5 千亿", "500 billion"),
                 ("15 亿元", "十五亿元"), ("120 亿", "一百二十亿")]
        for claim, quote in pairs:
            with self.subTest(claim=claim, quote=quote):
                self.ok(claim, quote)

    def test_different_magnitude_or_value_is_flagged(self):
        self.bad("投资 10 亿元", "invest 1 million yuan", "10")
        self.bad("25 trillion won", "25 million won", "25")
        self.bad("53 billion yuan", "2026年总投资额达540亿元", "53")

    def test_rounding_follows_the_claims_precision(self):
        self.ok("17.0 billion", "170.5亿")   # 17.05 → 按一位小数四舍五入为 17.0
        self.ok("17 billion", "172亿")       # 17.2 → 按整数四舍五入为 17
        self.bad("17.0 billion", "172亿", "17")

    def test_claim_with_magnitude_accepts_the_same_plain_number(self):
        self.ok("投资 15 亿元", "投资 15（单位：亿元）")
        self.ok("1,200 万辆", "shipments of 1200")

    def test_plain_claim_number_follows_the_old_rule(self):
        self.ok("产能 530", "总投资额达530亿元")  # 声明不带量级词：仍只比数字本身
        self.bad("产能 53", "总投资额达530亿元", "53")

    def test_g_in_gwh_is_not_a_magnitude(self):
        self.bad("2GWh 产线", "a 2000000000 line", "2")

    def test_mwh_m_is_not_a_magnitude(self):
        self.bad("10 MWh", "10000000 Wh", "10")

    def test_lowercase_m_is_a_magnitude_only_after_a_currency_symbol(self):
        self.bad("5 m long", "5000000 long", "5")

    def test_chinese_numeral_claim_is_still_not_checked(self):
        self.ok("投资三千万元", "builds production lines")


class SourceDateTests(_Base):
    def test_c320_report_month_is_source_metadata(self):
        self.ok("SMM 7月报告称硫化物百吨级产线在Q3集中投产，某新能源大厂完成1吨级招标且中标价低于200万元/吨",
                "硫化物百吨级产线Q3集中投产，某新能源大厂完成1吨级招标(中标价低于200万元/吨)")

    def test_c321_report_month_is_source_metadata(self):
        self.ok("SMM 7月报告称蜂巢能源混合固液电池三季度量产，恩力动力2GWh电芯+2GWh Pack产能全面达产",
                "蜂巢能源混合固液电池三季度量产，恩力动力2GWh电芯+2GWh Pack产能全面达产")

    def test_report_verbs_after_the_month(self):
        for claim in ("9月报道称", "9月份报道称", "九月报告显示", "9月的报告称", "9月发布的报告称", "9月披露", "9月称",
                      "9月公告称", "9月研报称"):
            with self.subTest(claim=claim):
                self.ok(f"SMM {claim}甲公司量产电池", "甲公司量产电池")

    def test_report_year_and_month_are_both_source_metadata(self):
        self.ok("SMM 2026年6月报道称，丰田计划2027年推出首款搭载固态电池的纯电车型",
                "丰田计划2027年推出首款搭载固态电池的纯电车型")
        self.ok("中日新闻2023年6月报道，丰田的目标是2027～28年实用化全固态电池",
                "トヨタ自動車は、全固体電池について、２０２７〜２８年の実用化を目指す方針")
        self.bad("2026年6月丰田计划量产", "丰田计划量产，2027年", "2026", "6月")

    def test_a_real_month_event_is_still_checked(self):
        self.bad("甲公司 7 月发布新电池", "甲公司发布新电池", "7月")
        self.bad("甲公司 7 月投产", "甲公司投产", "7月")
        self.bad("甲公司 2027 年 3 月宣布量产", "甲公司宣布量产", "3月")

    def test_report_month_does_not_hide_the_other_numbers_or_times(self):
        self.bad("SMM 7月报告称产线在Q3投产", "产线在Q4投产", "Q3")
        self.bad("SMM 7月报告称产能 20 GWh", "产能 10 GWh", "20")

    def test_month_in_the_quote_is_unaffected(self):
        self.ok("3月投产", "3月报告称投产")
        self.ok("2027年3月投产", "2027年3月报道：3月投产")


class EnglishNumberWordTests(_Base):
    def test_c387_batch_three_of_six(self):
        self.ok("SK On大田中试线的现场验收测试（SAT）计划分6批进行，Solid Power CEO称当时正在进行第3批",
                "We're on batch three right now of the Site Acceptance Testing (SAT) of the planned six batches")

    def test_common_number_words_match_digits(self):
        pairs = [("1", "one unit"), ("12", "twelve units"), ("19", "nineteen units"), ("20", "twenty units"),
                 ("25", "twenty-five units"), ("25", "twenty five units"), ("30", "thirty units"),
                 ("90", "Ninety units"), ("100", "one hundred units"), ("100", "a hundred units"),
                 ("250", "two hundred fifty units"), ("250", "two hundred and fifty units")]
        for digits, quote in pairs:
            with self.subTest(quote=quote):
                self.ok(f"共 {digits} 个", quote)

    def test_number_word_with_magnitude(self):
        self.ok("投资 300 万美元", "invested three million dollars")
        self.ok("投资 3 million dollars", "invested three million dollars")
        self.ok("投资 12 billion yuan", "invested twelve billion yuan")
        self.bad("投资 3 million dollars", "invested thirty million dollars", "3 million")

    def test_a_different_number_word_is_still_flagged(self):
        self.bad("分 7 批进行", "the planned six batches", "7")
        self.bad("共 21 个", "twenty-five units", "21")
        self.bad("共 5 个", "twenty-five units", "5")   # twenty-five 不能拆成 20 和 5
        self.bad("共 20 个", "twenty-five units", "20")

    def test_number_words_inside_other_words_are_not_numbers(self):
        self.bad("共 1 个", "someone said so", "1")
        self.bad("共 2 个", "the stwo group", "2")
        self.bad("共 10 个", "tenant list", "10")


class ParenthesisedNegativeTests(_Base):
    def test_c374_negative_million_in_parentheses(self):
        q = "Solid Power reported revenue and grant income of ($0.3) million in the second quarter of 2026 and " \
            "$2.8 million during the first half of 2026."
        self.ok("Solid Power 2026年第二季度收入及补助为-30万美元，2026年上半年为280万美元", q)
        self.ok("Solid Power reported net loss of $0.3 million in the second quarter of 2026", q)
        self.ok("Solid Power's revenue was -0.3 million in Q2 2026", q)

    def test_other_magnitude_words_after_the_parenthesis(self):
        self.ok("亏损 1.2 billion 美元", "a loss of ($1.2) billion")
        self.ok("亏损 120万", "a loss of (1.2) million")

    def test_a_different_amount_is_still_flagged(self):
        self.bad("亏损 0.4 million", "a loss of ($0.3) million", "0.4")
        self.bad("亏损 0.3 billion", "a loss of ($0.3) million", "0.3")


class KoreanSplitThousandTests(_Base):
    def test_c489_4cheon_700eok(self):
        self.ok("SK On的4700亿韩元为到2025年对大田电池研究院的总投入",
                "2025년까지 대전 배터리연구원에 총 4천700억원을 투입")

    def test_cheon_and_baek_combinations(self):
        pairs = [("4000亿", "4천억원"), ("500亿", "5백억원"), ("3500亿", "3천5백억원"), ("3520亿", "3천5백20억원"),
                 ("3000万", "3천만원"), ("500万", "5백만원"), ("4700亿", "4천 700억원"), ("4700亿", "4,700억원"),
                 ("0.47 trillion won", "4천700억원"), ("470 billion won", "4천700억원")]
        for claim, quote in pairs:
            with self.subTest(claim=claim, quote=quote):
                self.ok(f"投入 {claim}", quote)

    def test_a_different_amount_is_still_flagged(self):
        self.bad("投入 4600亿", "총 4천700억원을 투입", "4600亿")
        self.bad("投入 4000亿", "총 4천700억원을 투입", "4000亿")
        self.bad("投入 470亿", "총 4천700억원을 투입", "470亿")
        self.bad("投入 4700万", "총 4천700억원을 투입", "4700万")


class SourceDateModifierTests(_Base):
    def test_c490_media_word_between_month_and_report_verb(self):
        self.ok("2026年7月韩媒报道SK On在大田未来技术院建成中试工厂并以2029年商业化为目标",
                "지난해 9월 대전 미래기술원에 파일럿 플랜트를 준공하고 2029년 상용화를 목표로 개발을 진행")

    def test_media_modifiers(self):
        for claim in ("7月韩媒报道", "7月外媒报道称", "7月日媒称", "7月据韩媒报道", "7月据报道", "7月媒体报道",
                      "2026年7月据外媒报道", "7月美媒披露"):
            with self.subTest(claim=claim):
                self.ok(f"{claim}甲公司量产电池", "甲公司量产电池")

    def test_c428_parenthesised_source_date(self):
        self.ok("Electrek（2025年11月）称丰田固态电池原计划2020年推出，之后改到2023年、2026年，现在说2028年前后（历史参考）",
                "It initially planned to introduce solid-state EV batteries in 2020, then pushed it to 2023, then "
                "2026, and now it's saying it will be around 2028.")

    def test_parenthesised_source_date_variants(self):
        for claim in ("Electrek(2025年11月)称", "路透（11月）报道", "路透[2025年11月]报道", "SMM（2026年7月）指出"):
            with self.subTest(claim=claim):
                self.ok(f"{claim}甲公司量产电池", "甲公司量产电池")

    def test_a_real_event_month_is_still_checked(self):
        self.bad("2026年7月宁德时代称2027年有望小批量生产", "宁德时代称2027年有望小批量生产", "7月")
        self.bad("7月韩媒工厂投产", "韩媒工厂投产", "7月")   # 修饰词后面没有报道类动词
        self.bad("甲公司产能达0.2GWh（2025年5月）", "甲公司产能达0.2GWh", "5月")   # 括号日期后面不是报道动词
        self.bad("甲公司（2025年5月）宣布投产", "甲公司宣布投产", "5月")
        self.bad("7月宁德时代媒体沟通会上称投产", "宁德时代媒体沟通会上称投产", "7月")

    def test_source_date_does_not_hide_other_times_or_numbers(self):
        self.bad("7月韩媒报道甲公司在Q3投产", "甲公司在Q4投产", "Q3")
        self.bad("Electrek（2025年11月）称产能 20 GWh", "产能 10 GWh", "20")


class RangeSharedMagnitudeTests(_Base):
    def test_c46_wan_after_a_range(self):
        self.ok("An industry forecast article projects 2026 semi-solid-state battery installations at "
                "600,000–700,000 vehicles (about 82GWh), with 500,000–600,000 vehicles concentrated in the second "
                "half.",
                "全年装车量预计60-70万辆（约82GWh），其中50–60万辆（约65–75GWh）集中在下半年")

    def test_magnitude_applies_to_both_ends(self):
        pairs = [("600,000–700,000", "60-70万辆"), ("600000-700000", "60~70万辆"), ("50万-60万", "50-60万"),
                 ("5–6 million", "5,000,000 to 6,000,000"), ("5,000,000–6,000,000", "5-6 million"),
                 ("$5–6M", "5-6 million"), ("500亿-600亿", "500-600亿"), ("500亿-600亿", "500至600亿")]
        for claim, quote in pairs:
            with self.subTest(claim=claim, quote=quote):
                self.ok(f"销量 {claim}", quote)

    def test_plain_claim_number_equal_to_a_scaled_quote_value(self):
        self.ok("销量 200000 辆", "销量 20万辆")
        self.ok("销量 200,000 辆", "销量 20万辆")

    def test_a_different_range_is_still_flagged(self):
        self.bad("销量 600,000–800,000", "60-70万辆", "800000")
        self.bad("销量 600,000–700,000", "60-80万辆", "700000")
        self.bad("销量 60,000–70,000", "60-70万辆", "60000")

    def test_magnitude_is_not_shared_without_a_range(self):
        self.bad("销量 600,000 辆", "60 辆和 70万辆", "600000")
        self.bad("销量 600,000 辆", "60，70万辆", "600000")

    def test_plain_claim_numbers_still_need_the_exact_value(self):
        self.bad("产能 53", "总投资额达530亿元", "53")
        self.bad("项目共 53 个", "项目达 52 个，总投资 530 亿元", "53")


class EndedYearTests(_Base):
    def test_c261_ended_2025(self):
        self.ok("QuantumScape 2025年底流动性为9.708亿美元", "We ended 2025 with $970.8M in liquidity")

    def test_ended_variants_are_year_end(self):
        for q in ("We ended 2025 with", "we ended the year with", "ending 2025 with", "ended fiscal 2025 with",
                  "The company ended FY2025 with", "ended fiscal year 2025 with"):
            with self.subTest(q=q):
                self.ok("2025年底流动性为 9 亿美元", f"{q} 900 million in liquidity")

    def test_ended_a_quarter_or_a_month_is_not_year_end(self):
        for q in ("We ended Q2 with", "We ended the quarter with", "We ended June with", "ended 2025 Q3 with",
                  "ended the year's third quarter with", "ended the second half with"):
            with self.subTest(q=q):
                self.bad("2025年底流动性为 9 亿美元", f"{q} 900 million in liquidity", "年底")

    def test_ended_year_does_not_match_other_months_or_quarters(self):
        self.bad("2025年6月流动性为 9 亿美元", "We ended 2025 with 900 million in liquidity", "6月")
        self.bad("2025年第三季度流动性为 9 亿美元", "We ended 2025 with 900 million in liquidity", "Q3")


class StillFlaggedRealCases(_Base):
    def test_c66_extra_numbers_not_in_the_quote(self):
        detail = self.bad("ProLogium's Gen4 cells deliver up to 400 Wh/kg and charge from 5% to 80% in 6.4 minutes; "
                          "Mercedes has priority access to them.", "an energy density of up to 400 Wh/kg", "80", "6.4")
        self.assertIn("数字", detail)

    def test_c12_number_not_in_the_quote(self):
        self.bad("Samsung SDI's investment plan totals 25 trillion won (about US$17 billion), with 16 trillion won "
                 "allocated to expanding the Ulsan plant.", "16 trillion won allocated to expanding the Ulsan plant",
                 "25", "17")

    def test_c17_second_quarter_vs_second_half(self):
        self.bad("三星 SDI 全固态电池 2027年第二季度 量产", "second half of 2027", "Q2")

    def test_real_number_mistake(self):
        self.bad("项目共 53 个", "公开投资项目达52个", "53")
        self.bad("项目共 53 个", "项目达 52 个，总投资 530 亿元", "53")


if __name__ == "__main__":
    unittest.main()
