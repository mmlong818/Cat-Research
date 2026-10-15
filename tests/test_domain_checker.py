"""来源评分：中文站点与同类英文站点同档（不额外加分、不额外压分）。"""
import unittest

from tools.domain_checker import assess_url


def score(url: str) -> int:
    return assess_url(url)["final_score"]


class ParityTests(unittest.TestCase):
    def test_government_tld_parity(self):
        self.assertEqual(score("https://www.csrc.gov.cn/a"), score("https://www.sec.gov/a"))

    def test_university_tld_parity(self):
        self.assertEqual(score("https://www.zju.edu.cn/a"), score("https://www.mit.edu/a"))

    def test_academic_tlds_recognized(self):
        r = assess_url("https://www.iop.ac.cn/a")
        self.assertEqual(r["category"], "academic")
        self.assertEqual(r["final_score"], score("https://www.ox.ac.uk/a"))
        self.assertEqual(score("https://www.cae.org.cn/a"), score("https://www.ieee.org/a"))

    def test_listed_tier_never_scores_below_unlisted_same_tld(self):
        self.assertGreaterEqual(score("https://www.tsinghua.edu.cn/a"), score("https://www.zju.edu.cn/a"))
        self.assertGreaterEqual(score("https://www.stanford.edu/a"), score("https://www.unknown-college.edu/a"))

    def test_xinhua_real_domains(self):
        for url in ("https://www.news.cn/a", "https://www.xinhuanet.com/a"):
            self.assertEqual(assess_url(url)["tier"], 2, url)

    def test_chinese_mainstream_outlets_same_tier_as_western_peers(self):
        western = assess_url("https://www.cnbc.com/a")["tier"]
        for url in ("https://www.cls.cn/a", "https://www.stcn.com/a", "https://www.thepaper.cn/a",
                    "https://www.people.com.cn/a", "https://www.21jingji.com/a"):
            self.assertEqual(assess_url(url)["tier"], western, url)

    def test_national_academy_and_database_tier1(self):
        self.assertEqual(assess_url("https://www.cas.cn/a")["tier"], 1)
        self.assertEqual(assess_url("https://kns.cnki.net/a")["tier"], 1)

    def test_portals_stay_unlisted_like_western_portals(self):
        self.assertEqual(assess_url("https://finance.sina.com.cn/a")["tier"],
                         assess_url("https://finance.yahoo.com/a")["tier"])


if __name__ == "__main__":
    unittest.main()
