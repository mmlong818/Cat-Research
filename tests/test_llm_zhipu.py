"""智谱 GLM 提供方：请求构造、本地工具循环、json_object + 本地校验重试、错误码分类与退避、用量。"""
import asyncio
import json
import os
import unittest
from unittest import mock

import openai

from llm import keys
from llm.models import MODELS
from llm.providers import zhipu
from llm.providers.zhipu import ZhipuProvider
from llm.types import LLMBlockedError, LLMConfigError, LLMError, LLMPermanentError, LLMQuotaError, LLMRequest
from tests.llm_fakes import SECRET, FakeSleep, api_error, zp_client, zp_stream

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
VALID = json.dumps({"answer": "2026-08-26"})
SPEC = MODELS["glm-5.3"]


def _req(**kw):
    base = dict(prompt="问题", system="系统", model="glm-5.3")
    base.update(kw)
    return LLMRequest(**base)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        for p in (mock.patch.object(keys, "stored_config", return_value={}),
                  mock.patch.dict(os.environ, {"ZHIPU_API_KEY": SECRET})):
            p.start()
            self.addCleanup(p.stop)
        self.sleep = FakeSleep()
        self.searched: list = []
        self.fetched: list = []

    async def search(self, query, count, recency):
        self.searched.append(query)
        return {"results": [{"title": "GLM-5.3 发布", "link": "https://example.cn/glm", "content": "8 月 26 日"}]}

    async def fetch(self, url, max_chars):
        self.fetched.append(url)
        return {"url": url, "text": "正文", "original_chars": 2, "truncated": False}

    def run_with(self, outcomes, req, spec=SPEC):
        client, self.rec = zp_client(outcomes)
        provider = ZhipuProvider(make_client=lambda key: client, sleep=self.sleep,
                                 search=self.search, fetch=self.fetch)
        return asyncio.run(provider.run(req, spec))


class RequestTests(_Base):
    def test_structured_without_tools_uses_json_object_and_mapped_effort(self):
        r = self.run_with([zp_stream(VALID)], _req(schema=SCHEMA, effort="medium"))
        kw = self.rec.calls[0]
        self.assertEqual((kw["model"], kw["stream"]), ("glm-5.3", True))
        self.assertEqual(kw["response_format"], {"type": "json_object"})
        self.assertEqual(kw["extra_body"], {"thinking": {"type": "enabled"}, "reasoning_effort": "low"})
        self.assertEqual(kw["max_tokens"], SPEC.output_budget)
        self.assertNotIn("tools", kw)
        self.assertNotIn("tool_choice", kw)
        system = kw["messages"][0]
        self.assertEqual(system["role"], "system")
        self.assertTrue(system["content"].startswith("系统"))
        self.assertIn('"answer"', system["content"])
        self.assertEqual(r.data, {"answer": "2026-08-26"})

    def test_client_is_closed_after_success_and_failure(self):
        self.run_with([zp_stream("ok")], _req())
        self.assertEqual(self.rec.closed, 1)
        with self.assertRaises(LLMQuotaError):
            self.run_with([api_error(openai.RateLimitError, 429, "1113")], _req())
        self.assertEqual(self.rec.closed, 1)

    def test_default_client_targets_bigmodel_without_system_proxy(self):
        c = zhipu.make_client("k")
        self.assertEqual(str(c.base_url), zhipu.BASE_URL)
        self.assertEqual(c.max_retries, 0)  # 退避由本层负责


class ToolLoopTests(_Base):
    def test_search_then_answer(self):
        r = self.run_with([zp_stream(tool_calls=[("WebSearch", '{"query": "GLM-5.3 发布日期"}')]),
                           zp_stream(VALID)], _req(tools=("WebSearch", "WebFetch"), schema=SCHEMA))
        first, second = self.rec.calls
        self.assertEqual([t["function"]["name"] for t in first["tools"]], ["WebSearch", "WebFetch"])
        self.assertNotIn("response_format", first)
        self.assertEqual(self.searched, ["GLM-5.3 发布日期"])
        assistant, tool = second["messages"][2:4]
        self.assertEqual(assistant["tool_calls"][0]["function"]["arguments"], '{"query": "GLM-5.3 发布日期"}')
        self.assertEqual((tool["role"], tool["tool_call_id"]), ("tool", "call_0"))
        self.assertIn("example.cn", tool["content"])
        self.assertEqual((r.data["answer"], r.num_turns), ("2026-08-26", 2))
        self.assertEqual(r.model_usage["glm-5.3"]["webSearchRequests"], 1)

    def test_parallel_tool_calls_are_all_executed_in_order(self):
        self.run_with([zp_stream(tool_calls=[("WebSearch", '{"query": "a"}'),
                                             ("WebFetch", '{"url": "https://example.cn/x"}')]),
                       zp_stream("完成")], _req(tools=("WebSearch", "WebFetch")))
        msgs = self.rec.calls[1]["messages"]
        self.assertEqual([m.get("tool_call_id") for m in msgs[3:]], ["call_0", "call_1"])
        self.assertEqual((self.searched, self.fetched), (["a"], ["https://example.cn/x"]))

    def test_max_turns_exceeded(self):
        loop = [zp_stream(tool_calls=[("WebSearch", '{"query": "q"}')]) for _ in range(3)]
        with self.assertRaisesRegex(LLMError, "max_turns"):
            self.run_with(loop, _req(tools=("WebSearch",), max_turns=2))
        self.assertEqual(len(self.rec.calls), 2)


class StructuredRepairTests(_Base):
    def test_invalid_json_is_repaired_with_error_feedback(self):
        r = self.run_with([zp_stream("这不是 JSON"), zp_stream(VALID)], _req(schema=SCHEMA))
        last = self.rec.calls[1]["messages"][-2:]
        self.assertEqual([m["role"] for m in last], ["assistant", "user"])
        self.assertIn("不符合", last[1]["content"])
        self.assertEqual(r.data["answer"], "2026-08-26")

    def test_gives_up_after_two_repairs(self):
        with self.assertRaisesRegex(LLMError, "JSON"):
            self.run_with([zp_stream('{"wrong": 1}')] * 3, _req(schema=SCHEMA))
        self.assertEqual(len(self.rec.calls), 3)


class ErrorTests(_Base):
    def test_rate_limit_codes_back_off(self):
        r = self.run_with([api_error(openai.RateLimitError, 429, "1302"), api_error(openai.RateLimitError, 429, "1305"),
                           zp_stream("ok")], _req())
        self.assertEqual((r.text, len(self.sleep.delays)), ("ok", 2))

    def test_network_error_finish_is_retried(self):
        r = self.run_with([zp_stream("半", finish="network_error"), zp_stream("ok")], _req())
        self.assertEqual((r.text, len(self.sleep.delays)), ("ok", 1))

    def test_arrears_and_usage_cap_are_quota_errors_without_retry(self):
        for code in ("1113", "1308"):
            with self.subTest(code), self.assertRaises(LLMQuotaError):
                self.run_with([api_error(openai.RateLimitError, 429, code)], _req())
        self.assertEqual(self.sleep.delays, [])

    def test_content_safety_is_blocked_without_retry(self):
        with self.assertRaises(LLMBlockedError):
            self.run_with([api_error(openai.BadRequestError, 400, "1301")], _req())
        with self.assertRaises(LLMBlockedError):
            self.run_with([zp_stream("", finish="sensitive")], _req())
        self.assertEqual(self.sleep.delays, [])

    def test_truncated_output_raises(self):
        with self.assertRaisesRegex(LLMError, "截断"):
            self.run_with([zp_stream("半截", finish="length")], _req())

    def test_missing_key_is_clear_and_does_not_leak(self):
        with mock.patch.dict(os.environ, {"ZHIPU_API_KEY": ""}), self.assertRaises(LLMConfigError) as cm:
            asyncio.run(ZhipuProvider(make_client=lambda k: None).run(_req(), SPEC))
        self.assertIn("ZHIPU_API_KEY", str(cm.exception))
        self.assertIn("设置", str(cm.exception))

    def test_auth_error_never_echoes_the_key(self):
        err = api_error(openai.AuthenticationError, 401, "1000", message=f"令牌 {SECRET} 无效")
        with self.assertRaises(LLMConfigError) as cm:
            self.run_with([err], _req())
        self.assertNotIn(SECRET, str(cm.exception))

    def test_other_errors_redact_an_echoed_key(self):
        err = api_error(openai.BadRequestError, 400, "1214", message=f"参数非法 key={SECRET} tail={SECRET[-6:]}")
        with self.assertRaises(LLMPermanentError) as cm:
            self.run_with([err], _req())
        self.assertIn("1214", str(cm.exception))
        self.assertNotIn(SECRET, str(cm.exception))
        self.assertNotIn(SECRET[-6:], str(cm.exception))


class UsageTests(_Base):
    def test_usage_accumulates_over_the_loop(self):
        r = self.run_with([zp_stream(tool_calls=[("WebSearch", '{"query": "q"}')], prompt=1000, cached=200,
                                     completion=300),
                           zp_stream("答", prompt=1500, cached=1000, completion=100)], _req(tools=("WebSearch",)))
        u = r.model_usage["glm-5.3"]
        self.assertEqual((u["inputTokens"], u["cacheReadInputTokens"], u["outputTokens"]), (1300, 1200, 400))
        self.assertEqual(u["webSearchRequests"], 1)
        self.assertNotIn("costUSD", u)


if __name__ == "__main__":
    unittest.main()
