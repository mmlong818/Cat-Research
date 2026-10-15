"""OpenAI（Responses API）提供方：请求构造、托管联网、结构化输出及降级、退避重试、用量、密钥不泄露。"""
import asyncio
import json
import os
import unittest
from unittest import mock

import openai

from llm import keys
from llm.models import MODELS
from llm.providers.openai_responses import OpenAIProvider
from llm.types import LLMBlockedError, LLMConfigError, LLMError, LLMPermanentError, LLMQuotaError, LLMRequest
from tests.llm_fakes import SECRET, FakeSleep, api_error, oa_client, oa_response

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"},
                   "items": {"type": "array", "items": {"type": "object", "properties": {"t": {"type": "string"}},
                                                         "required": ["t"]}}},
    "required": ["answer", "items"],
}
VALID = json.dumps({"answer": "a", "items": [{"t": "x"}]})
SPEC = MODELS["gpt-6.1-sol"]


def _req(**kw):
    base = dict(prompt="问题", system="系统", model="gpt-6.1-sol")
    base.update(kw)
    return LLMRequest(**base)


class _Base(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.object(keys, "stored_config", return_value={}),
                  mock.patch.dict(os.environ, {"OPENAI_API_KEY": SECRET})):
            p.start()
            self.addCleanup(p.stop)
        self.sleep = FakeSleep()

    def run_with(self, outcomes, req, spec=SPEC):
        client, self.rec = oa_client(outcomes)
        provider = OpenAIProvider(make_client=lambda key, timeout: client, sleep=self.sleep)
        return asyncio.run(provider.run(req, spec))


class RequestTests(_Base):
    def test_web_search_and_strict_schema_request(self):
        self.run_with([oa_response(VALID)], _req(effort="xhigh", tools=("WebSearch", "WebFetch"),
                                                 schema=SCHEMA, max_turns=12))
        kw = self.rec.calls[0]
        self.assertEqual((kw["model"], kw["input"]), ("gpt-6.1-sol", "问题"))
        self.assertTrue(kw["instructions"].startswith("系统"))
        self.assertIn("web_search", kw["instructions"])
        self.assertEqual(kw["reasoning"], {"effort": "xhigh"})
        self.assertEqual(kw["tools"], [{"type": "web_search"}])
        self.assertEqual(kw["include"], ["web_search_call.action.sources"])
        self.assertEqual(kw["max_tool_calls"], 12)
        self.assertIs(kw["store"], False)
        self.assertGreaterEqual(kw["max_output_tokens"], 25_000)
        fmt = kw["text"]["format"]
        self.assertEqual((fmt["type"], fmt["strict"]), ("json_schema", True))
        self.assertIs(fmt["schema"]["additionalProperties"], False)
        self.assertIs(fmt["schema"]["properties"]["items"]["items"]["additionalProperties"], False)
        self.assertNotIn("additionalProperties", SCHEMA)  # 不改调用方的 schema

    def test_plain_request_has_no_tools_or_format(self):
        r = self.run_with([oa_response("你好")], _req())
        kw = self.rec.calls[0]
        for key in ("tools", "include", "text", "max_tool_calls"):
            self.assertNotIn(key, kw)
        self.assertEqual((r.text, r.data, r.num_turns), ("你好", None, 1))

    def test_schema_with_optional_property_is_not_strict(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
                  "required": ["a"]}
        self.run_with([oa_response('{"a": "x"}')], _req(schema=schema))
        self.assertIs(self.rec.calls[0]["text"]["format"]["strict"], False)

    def test_client_is_closed_after_success_and_failure(self):
        self.run_with([oa_response("ok")], _req())
        self.assertEqual(self.rec.closed, 1)
        with self.assertRaises(LLMPermanentError):
            self.run_with([api_error(openai.BadRequestError, 400)], _req())
        self.assertEqual(self.rec.closed, 1)

    def test_unsupported_tool_is_config_error(self):
        with self.assertRaisesRegex(LLMConfigError, "Bash"):
            self.run_with([], _req(tools=("Bash",)))


class StructuredFallbackTests(_Base):
    def test_web_search_with_schema_rejected_falls_back_to_prompt_mode(self):
        r = self.run_with([api_error(openai.BadRequestError, 400, message="text.format not supported with tools"),
                           oa_response(VALID)], _req(tools=("WebSearch",), schema=SCHEMA))
        second = self.rec.calls[1]
        self.assertNotIn("text", second)
        self.assertIn('"items"', second["instructions"])  # schema 写进提示词
        self.assertEqual(r.data, json.loads(VALID))

    def test_prompt_mode_repairs_invalid_json(self):
        r = self.run_with([api_error(openai.BadRequestError, 400), oa_response("不是 JSON"), oa_response(VALID)],
                          _req(tools=("WebSearch",), schema=SCHEMA))
        third = self.rec.calls[2]["input"]
        self.assertEqual([m["role"] for m in third], ["user", "assistant", "user"])
        self.assertIn("不符合", third[-1]["content"])
        self.assertEqual((r.data["answer"], r.num_turns), ("a", 2))

    def test_bad_request_without_tools_is_permanent(self):
        with self.assertRaises(LLMPermanentError):
            self.run_with([api_error(openai.BadRequestError, 400)], _req(schema=SCHEMA))
        self.assertEqual(len(self.rec.calls), 1)


class RetryTests(_Base):
    def test_rate_limit_and_server_errors_back_off_then_succeed(self):
        r = self.run_with([api_error(openai.RateLimitError, 429), api_error(openai.InternalServerError, 500),
                           oa_response("ok")], _req())
        self.assertEqual(r.text, "ok")
        self.assertEqual(len(self.sleep.delays), 2)
        self.assertTrue(5 <= self.sleep.delays[0] <= 6 and 15 <= self.sleep.delays[1] <= 18, self.sleep.delays)

    def test_exhausted_backoff_is_a_retryable_llm_error(self):
        with self.assertRaises(LLMError) as cm:
            self.run_with([api_error(openai.RateLimitError, 429)] * 4, _req())
        self.assertNotIsInstance(cm.exception, LLMPermanentError)
        self.assertEqual(len(self.sleep.delays), 3)

    def test_insufficient_quota_is_not_retried(self):
        with self.assertRaises(LLMQuotaError):
            self.run_with([api_error(openai.RateLimitError, 429, code="insufficient_quota")], _req())
        self.assertEqual(self.sleep.delays, [])


class KeyTests(_Base):
    def test_auth_error_never_echoes_the_key(self):
        err = api_error(openai.AuthenticationError, 401, message=f"Incorrect API key provided: {SECRET}")
        with self.assertRaises(LLMConfigError) as cm:
            self.run_with([err], _req())
        self.assertNotIn(SECRET, str(cm.exception))
        self.assertNotIn(SECRET[-6:], str(cm.exception))
        self.assertIsNone(cm.exception.__cause__)
        self.assertTrue(cm.exception.__suppress_context__)

    def test_missing_key_points_to_settings(self):
        made = []
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}), self.assertRaises(LLMConfigError) as cm:
            asyncio.run(OpenAIProvider(make_client=lambda k, t: made.append(k)).run(_req(), SPEC))
        self.assertIn("设置", str(cm.exception))
        self.assertIn("OPENAI_API_KEY", str(cm.exception))
        self.assertEqual(made, [])


class ResultTests(_Base):
    def test_usage_counts_and_no_cost_fields(self):
        r = self.run_with([oa_response("ok", input_tokens=100_000, cached=40_000, output=10_000, reasoning=3_000,
                                       searches=2)], _req(tools=("WebSearch",)))
        u = r.model_usage["gpt-6.1-sol"]
        self.assertEqual((u["inputTokens"], u["cacheReadInputTokens"], u["outputTokens"]), (60_000, 40_000, 10_000))
        self.assertEqual((u["reasoningOutputTokens"], u["webSearchRequests"]), (3_000, 2))
        self.assertNotIn("costUSD", u)
        self.assertFalse(hasattr(r, "cost_usd"))

    def test_incomplete_and_refusal(self):
        with self.assertRaisesRegex(LLMError, "max_output_tokens"):
            self.run_with([oa_response("半截", status="incomplete", reason="max_output_tokens")], _req())
        with self.assertRaises(LLMBlockedError):
            self.run_with([oa_response("", status="incomplete", reason="content_filter")], _req())
        with self.assertRaisesRegex(LLMError, "拒答"):
            self.run_with([oa_response(refusal="I can't help")], _req())


if __name__ == "__main__":
    unittest.main()
