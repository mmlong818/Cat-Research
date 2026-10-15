"""委托台的澄清接口：ClarifierAgent 走同步的 llm.client.call（内部 asyncio.run），
接口必须把它放到线程里跑，不能在 FastAPI 的事件循环里直接调用（否则 asyncio.run 报错、接口 500，且会卡住事件循环）。"""
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from api import app as app_mod
from api import security
from llm.types import LLMResult

HEADERS = {security.TOKEN_HEADER: security.TOKEN}
SUMMARY = {"objective": "对比定价", "scope": "个人版", "key_aspects": ["月费"], "timeframe": "2026-10", "depth": "速览",
           "angle": "价格", "exclude": "", "search_hints": [], "intent_type": "optimization",
           "dimensions": {"urgency": 0.5, "specificity": 0.8, "complexity": 0.3}}


async def fake_acall(req):
    """替换真正的模型调用，保留 call() → asyncio.run(acall()) 这条同步路径"""
    data = {"message": "先确认两点", "summary": SUMMARY, "ready": False, "confidence": 0.6}
    return LLMResult(text="", data=data, duration_ms=0, num_turns=1, session_id="")


class ClarifyApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app_mod.app, base_url="http://127.0.0.1:8000")
        p = mock.patch("llm.client.acall", fake_acall)
        p.start()
        self.addCleanup(p.stop)

    def test_start_and_reply_run_the_sync_llm_call_off_the_event_loop(self):
        res = self.client.post("/api/clarify", json={"question": "2026年10月主流AI编程助手的定价对比"}, headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.addCleanup(app_mod._clarify_sessions.pop, body["clarify_id"], None)
        self.assertEqual((body["message"], body["summary"]["objective"]), ("先确认两点", "对比定价"))
        reply = self.client.post(f"/api/clarify/{body['clarify_id']}/message", json={"message": "只看个人版"},
                                 headers=HEADERS)
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertEqual(reply.json()["turns"], 2)


if __name__ == "__main__":
    unittest.main()
