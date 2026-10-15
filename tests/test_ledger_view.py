"""E6a 台账只读视图：报告页展示矛盾裁决（双方声明、来源、裁决理由与证据）。"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from api import app as app_mod
from api import security
from research.ledger import Ledger

HEADERS = {security.TOKEN_HEADER: security.TOKEN}


def build_ledger(ws: str) -> Ledger:
    ledger = Ledger.load(ws)
    a, _ = ledger.add_claim("2027 年量产", "https://a.com/1", "A 站")
    b, _ = ledger.add_claim("2030 年量产", "https://b.com/1", "B 站")
    c, _ = ledger.add_claim("成本 150 美元/kWh", "https://a.com/2")
    d, _ = ledger.add_claim("成本 200 美元/kWh", "https://c.com/1")
    ledger.resolve(ledger.add_contradiction(a, b, "量产时间"), b, "官方公告为 2030", "https://gov.cn/x")
    ledger.add_contradiction(c, d, "成本")
    ledger.save()
    return ledger


class LedgerViewTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, True)

    def test_view_contains_both_sides_and_resolution(self):
        view = build_ledger(self.ws).view()
        self.assertEqual(view["counts"], {"claims": 4, "citable": 3, "sources": 4, "contradictions": 2,
                                          "unresolved": 1})
        x1, x2 = view["contradictions"]
        self.assertEqual((x1["id"], x1["topic"]), ("X1", "量产时间"))
        self.assertEqual([c["status"] for c in x1["claims"]], ["overruled", "supported"])
        self.assertEqual(x1["claims"][0]["sources"],
                         [{"id": "S1", "url": "https://a.com/1", "title": "A 站", "published": ""}])
        self.assertEqual(x1["resolution"], {"sides_with": "C2", "reason": "官方公告为 2030",
                                            "evidence_url": "https://gov.cn/x"})
        self.assertIsNone(x2["resolution"])

    def test_empty_ledger(self):
        view = Ledger.load(self.ws).view()
        self.assertEqual((view["contradictions"], view["claims"]), ([], []))

    def test_claims_list_skips_merged_and_sorts_numerically(self):
        ledger = Ledger.load(self.ws)
        ids = [ledger.add_claim(f"声明 {i}", f"https://a.com/{i}", f"站 {i}")[0] for i in range(1, 12)]
        ledger.merge(ids[0], ids[1])  # C2 并入 C1
        ledger.set_status(ids[9], "supported")
        claims = ledger.view()["claims"]
        self.assertEqual([c["id"] for c in claims], ["C1"] + [f"C{i}" for i in range(3, 12)])
        self.assertNotIn("merged", {c["status"] for c in claims})
        c10 = next(c for c in claims if c["id"] == "C10")
        self.assertEqual(c10["status"], "supported")
        self.assertEqual(c10["text"], "声明 10")
        self.assertEqual(c10["sources"], [{"id": "S10", "url": "https://a.com/10", "title": "站 10", "published": ""}])
        self.assertEqual(len(next(c for c in claims if c["id"] == "C1")["sources"]), 2)  # 合并后来源并入

    def test_claims_carry_quotes_note_and_source_published_date(self):
        """卷宗旁注要展示原文引语、核查备注与来源发布日期。"""
        ledger = Ledger.load(self.ws)
        cid, _ = ledger.add_claim("CATL targets 2027", "https://a.com/1", "A 站", published="2026-09-30",
                                  quote="small-batch production is planned for 2027")
        ledger.set_status(cid, "supported", "官方公告证实")
        claim = ledger.view()["claims"][0]
        self.assertEqual(claim["quotes"], {"S1": "small-batch production is planned for 2027"})
        self.assertEqual(claim["note"], "官方公告证实")
        self.assertEqual(claim["sources"], [{"id": "S1", "url": "https://a.com/1", "title": "A 站",
                                             "published": "2026-09-30"}])

    def test_claims_without_quotes_get_empty_dict(self):
        ledger = Ledger.load(self.ws)
        ledger.add_claim("无引语的旧声明", "https://a.com/1")
        claim = ledger.view()["claims"][0]
        self.assertEqual((claim["quotes"], claim["note"]), ({}, ""))

    def test_contradiction_sides_carry_quotes_and_note(self):
        x1 = build_ledger(self.ws).view()["contradictions"][0]
        self.assertEqual({k for c in x1["claims"] for k in c}, {"id", "text", "status", "sources", "quotes", "note"})


class LedgerApiTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        p = mock.patch.object(app_mod, "WORKSPACE_DIR", self.root)
        p.start()
        self.addCleanup(p.stop)
        self.client = TestClient(app_mod.app, base_url="http://127.0.0.1:8000")

    def test_session_ledger(self):
        ws = os.path.join(self.root, "session_20261001_000001")
        build_ledger(ws)
        res = self.client.get("/api/sessions/20261001_000001/ledger", headers=HEADERS)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["counts"]["contradictions"], 2)

    def test_session_ledger_lists_claims(self):
        ws = os.path.join(self.root, "session_20261001_000001")
        build_ledger(ws)
        claims = self.client.get("/api/sessions/20261001_000001/ledger", headers=HEADERS).json()["claims"]
        self.assertEqual([c["id"] for c in claims], ["C1", "C2", "C3", "C4"])

    def test_unknown_session(self):
        res = self.client.get("/api/sessions/nope/ledger", headers=HEADERS)
        self.assertEqual(res.status_code, 404)


class ReportTokenUsageTests(unittest.TestCase):
    """V1：报告接口带出 00_session.json 的 token_usage，历史会话也能看到用量。"""

    USAGE = {"total_input": 10, "total_output": 20, "total": 30,
             "by_agent": {"研究员": {"input": 10, "output": 20}}}

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        p = mock.patch.object(app_mod, "WORKSPACE_DIR", self.root)
        p.start()
        self.addCleanup(p.stop)
        self.client = TestClient(app_mod.app, base_url="http://127.0.0.1:8000")
        self.ws = os.path.join(self.root, "session_20261001_000002")
        os.makedirs(self.ws)
        with open(os.path.join(self.ws, "09_final.md"), "w", encoding="utf-8") as f:
            f.write("# 报告")

    def _write_session(self, text: str):
        with open(os.path.join(self.ws, "00_session.json"), "w", encoding="utf-8") as f:
            f.write(text)

    def _report(self) -> dict:
        res = self.client.get("/api/sessions/20261001_000002/report", headers=HEADERS)
        self.assertEqual(res.status_code, 200)
        return res.json()

    def test_report_includes_token_usage(self):
        self._write_session(json.dumps({"question": "q", "token_usage": self.USAGE}, ensure_ascii=False))
        self.assertEqual(self._report()["token_usage"], self.USAGE)

    def test_report_without_usage_is_null(self):
        self._write_session(json.dumps({"question": "q"}))
        self.assertIsNone(self._report()["token_usage"])

    def test_report_with_missing_or_broken_session_file_is_null(self):
        self.assertIsNone(self._report()["token_usage"])
        self._write_session("{坏的")
        self.assertIsNone(self._report()["token_usage"])


if __name__ == "__main__":
    unittest.main()
