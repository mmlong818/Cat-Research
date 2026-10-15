"""OpenAI 兼容端点：compat: 前缀路由与去前缀、请求构造、工具循环、response_format / reasoning_effort 被 400 拒绝后退回、
错误分类、缺配置、连通测试（probe）。"""
import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

import openai

from llm import keys, providers
from llm.models import get_spec
from llm.providers import compat
from llm.providers.compat import CompatProvider
from llm.types import LLMConfigError, LLMError, LLMPermanentError, LLMQuotaError, LLMRequest
from tests.llm_fakes import SECRET, FakeSleep, Recorder, api_error, zp_client, zp_stream

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
VALID = json.dumps({"answer": "ok"})
MODEL = "compat:my-model-v1"
SPEC = get_spec(MODEL)
STORED = {"compat_api_key": SECRET,
          "compat": {"base_url": "https://llm.example.com/v1", "core": MODEL, "support": "compat:small"}}


def _req(**kw):
    base = dict(prompt="问题", system="系统", model=MODEL)
    base.update(kw)
    return LLMRequest(**base)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.stored = dict(STORED)
        for p in (mock.patch.object(keys, "stored_config", side_effect=lambda: self.stored),
                  mock.patch.dict(os.environ, {"COMPAT_API_KEY": "", "COMPAT_BASE_URL": "", "SEARCH_BACKEND": ""})):
            p.start()
            self.addCleanup(p.stop)
        self.sleep = FakeSleep()
        self.searched: list = []

    async def search(self, query, count, recency):
        self.searched.append(query)
        return {"results": [{"title": "标题", "link": "https://example.com/a", "content": "内容"}]}

    async def fetch(self, url, max_chars):
        return {"url": url, "text": "正文", "original_chars": 2, "truncated": False}

    def run_with(self, outcomes, req, spec=SPEC):
        client, self.rec = zp_client(outcomes)
        provider = CompatProvider(make_client=lambda key: client, sleep=self.sleep, search=self.search,
                                  fetch=self.fetch)
        return asyncio.run(provider.run(req, spec))


class ModelRoutingTests(_Base):
    def test_prefixed_ids_get_a_generated_spec(self):
        self.assertEqual((SPEC.id, SPEC.provider, SPEC.web, SPEC.structured), (MODEL, "compat", "client_tools",
                                                                               "json_object"))
        self.assertEqual((SPEC.context, SPEC.max_output, SPEC.output_budget, SPEC.efforts, SPEC.max_concurrency),
                         (128_000, 0, 0, (), 3))

    def test_empty_model_name_is_a_config_error(self):
        with self.assertRaisesRegex(LLMConfigError, "缺少端点里的模型名"):
            get_spec("compat:")

    def test_registry_routes_compat_to_its_provider_only_for_compat_models(self):
        self.assertIsInstance(providers.get_provider("compat", SPEC), CompatProvider)
        with self.assertRaisesRegex(LLMConfigError, "不能经 zhipu 调用"):
            providers.get_provider("zhipu", SPEC)
        with self.assertRaisesRegex(LLMConfigError, "不能经 compat 调用"):
            providers.get_provider("compat", get_spec("glm-5.3"))

    def test_prefix_is_stripped_before_reaching_the_endpoint(self):
        r = self.run_with([zp_stream("好")], _req())
        self.assertEqual(self.rec.calls[0]["model"], "my-model-v1")
        self.assertIn(MODEL, r.model_usage)  # 用量按带前缀的 ID 记


class RequestTests(_Base):
    def test_effort_is_sent_as_reasoning_effort_and_no_max_tokens(self):
        self.run_with([zp_stream(VALID)], _req(schema=SCHEMA, effort="max"))
        kw = self.rec.calls[0]
        self.assertEqual((kw["response_format"], kw["reasoning_effort"]), ({"type": "json_object"}, "max"))
        for forbidden in ("max_tokens", "extra_body", "thinking", "tools"):
            self.assertNotIn(forbidden, kw)
        self.assertIn('"answer"', kw["messages"][0]["content"])

    def test_default_client_uses_the_configured_base_url_and_proxy_settings(self):
        c = compat.make_client("k")
        self.assertEqual(str(c.base_url), "https://llm.example.com/v1/")
        self.assertEqual(c.max_retries, 0)
        env_only = {"base_url": "", "core": "", "support": ""}
        self.stored = {"compat": env_only}
        with mock.patch.dict(os.environ, {"COMPAT_BASE_URL": "http://localhost:11434/v1"}):
            self.assertEqual(str(compat.make_client("k").base_url), "http://localhost:11434/v1/")
        self.assertTrue(compat.VENDOR.trust_env)

    def test_client_is_closed(self):
        self.run_with([zp_stream("ok")], _req())
        self.assertEqual(self.rec.closed, 1)


class ToolLoopTests(_Base):
    def test_search_then_answer_without_echoing_reasoning(self):
        r = self.run_with([zp_stream(tool_calls=[("WebSearch", '{"query": "找资料"}')]), zp_stream(VALID)],
                          _req(tools=("WebSearch", "WebFetch"), schema=SCHEMA))
        first, second = self.rec.calls
        self.assertEqual([t["function"]["name"] for t in first["tools"]], ["WebSearch", "WebFetch"])
        self.assertNotIn("response_format", first)
        assistant, tool = second["messages"][2:4]
        self.assertNotIn("reasoning_content", assistant)  # 部分端点会拒收回传的思考内容
        self.assertEqual((tool["role"], tool["tool_call_id"]), ("tool", "call_0"))
        self.assertEqual((self.searched, r.data, r.num_turns), (["找资料"], {"answer": "ok"}, 2))
        self.assertEqual(r.model_usage[MODEL]["webSearchRequests"], 1)

    def test_max_turns_exceeded(self):
        loop = [zp_stream(tool_calls=[("WebSearch", '{"query": "q"}')]) for _ in range(3)]
        with self.assertRaisesRegex(LLMError, "max_turns"):
            self.run_with(loop, _req(tools=("WebSearch",), max_turns=2))


class ResponseFormatFallbackTests(_Base):
    def bad_request(self):
        return api_error(openai.BadRequestError, 400, None, "response_format is not supported")

    def test_rejected_response_format_is_dropped_for_the_retry(self):
        r = self.run_with([self.bad_request(), zp_stream(VALID)], _req(schema=SCHEMA))
        first, second = self.rec.calls
        self.assertIn("response_format", first)
        self.assertNotIn("response_format", second)
        self.assertIn('"answer"', second["messages"][0]["content"])  # schema 仍在系统提示词里
        self.assertEqual((r.data, self.sleep.delays), ({"answer": "ok"}, []))  # 不退避、不当作永久错误

    def test_later_repairs_in_the_same_request_do_not_send_it_again(self):
        r = self.run_with([self.bad_request(), zp_stream("不是 JSON"), zp_stream(VALID)], _req(schema=SCHEMA))
        self.assertEqual(["response_format" in c for c in self.rec.calls], [True, False, False])
        self.assertEqual(r.data, {"answer": "ok"})

    def test_local_validation_still_applies_after_the_fallback(self):
        with self.assertRaisesRegex(LLMError, "输出不合格"):
            self.run_with([self.bad_request(), *[zp_stream('{"wrong": 1}')] * 3], _req(schema=SCHEMA))

    def test_bad_request_with_nothing_left_to_drop_is_a_permanent_error(self):
        with self.assertRaises(LLMPermanentError):
            self.run_with([self.bad_request()] * 4, _req(schema=SCHEMA))
        self.assertEqual([(c.get("response_format"), c.get("reasoning_effort")) for c in self.rec.calls],
                         [({"type": "json_object"}, "medium"), (None, "medium"), (None, "low"), (None, None)])

    def test_bad_request_without_droppable_params_is_not_swallowed(self):
        with self.assertRaises(LLMPermanentError) as cm:
            self.run_with([self.bad_request()] * 3, _req(tools=("WebSearch",)))
        self.assertIn("OpenAI 兼容端点", str(cm.exception))
        self.assertEqual(len(self.rec.calls), 3)


class EffortFallbackTests(_Base):
    def bad_request(self):
        return api_error(openai.BadRequestError, 400, None, "reasoning_effort medium is not supported")

    def test_rejected_effort_falls_back_to_low_for_the_rest_of_the_request(self):
        r = self.run_with([self.bad_request(), zp_stream(tool_calls=[("WebSearch", '{"query": "q"}')]),
                           zp_stream("答")], _req(tools=("WebSearch",), effort="medium"))
        self.assertEqual([c["reasoning_effort"] for c in self.rec.calls], ["medium", "low", "low"])
        self.assertEqual((r.text, self.sleep.delays), ("答", []))

    def test_rejected_low_is_dropped(self):
        r = self.run_with([self.bad_request(), self.bad_request(), zp_stream("答")],
                          _req(tools=("WebSearch",), effort="high"))
        self.assertEqual([c.get("reasoning_effort") for c in self.rec.calls], ["high", "low", None])
        self.assertEqual(r.text, "答")

    def test_response_format_is_dropped_before_effort(self):
        r = self.run_with([self.bad_request(), self.bad_request(), zp_stream(VALID)], _req(schema=SCHEMA))
        self.assertEqual([(c.get("response_format"), c.get("reasoning_effort")) for c in self.rec.calls],
                         [({"type": "json_object"}, "medium"), (None, "medium"), (None, "low")])
        self.assertEqual(r.data, {"answer": "ok"})


class ErrorTests(_Base):
    def test_auth_error_never_echoes_the_key(self):
        err = api_error(openai.AuthenticationError, 401, None, message=f"bad key {SECRET}")
        with self.assertRaises(LLMConfigError) as cm:
            self.run_with([err], _req())
        self.assertIn("OpenAI 兼容端点 API Key 无效", str(cm.exception))
        self.assertNotIn(SECRET, str(cm.exception))

    def test_insufficient_quota_is_a_quota_error_without_retry(self):
        with self.assertRaises(LLMQuotaError):
            self.run_with([api_error(openai.RateLimitError, 429, "insufficient_quota")], _req())
        self.assertEqual(self.sleep.delays, [])

    def test_rate_limit_and_server_errors_back_off(self):
        r = self.run_with([api_error(openai.RateLimitError, 429, "rate_limit_exceeded"),
                           api_error(openai.InternalServerError, 503), zp_stream("ok")], _req())
        self.assertEqual((r.text, len(self.sleep.delays)), ("ok", 2))

    def test_unknown_model_is_a_config_error(self):
        with self.assertRaisesRegex(LLMConfigError, "不认识该模型或接口"):
            self.run_with([api_error(openai.NotFoundError, 404, "model_not_found")], _req())

    def test_other_errors_redact_an_echoed_key(self):
        err = api_error(openai.BadRequestError, 400, None, message=f"参数非法 key={SECRET}")
        with self.assertRaises(LLMPermanentError) as cm:
            self.run_with([err] * 3, _req(tools=("WebSearch",)))
        self.assertNotIn(SECRET, str(cm.exception))


class MissingConfigTests(_Base):
    def test_missing_key_names_the_field_and_environment_variable(self):
        self.stored = {k: v for k, v in STORED.items() if k != "compat_api_key"}
        with self.assertRaises(LLMConfigError) as cm:
            asyncio.run(CompatProvider(make_client=lambda k: None).run(_req(), SPEC))
        self.assertIn("COMPAT_API_KEY", str(cm.exception))
        self.assertIn("设置", str(cm.exception))

    def test_missing_base_url_is_a_clear_config_error(self):
        self.stored = {"compat_api_key": SECRET}
        with self.assertRaisesRegex(LLMConfigError, "COMPAT_BASE_URL"):
            asyncio.run(CompatProvider().run(_req(), SPEC))

    def test_selected_search_backend_without_key_fails_before_any_request(self):
        self.stored = {**STORED, "search": {"backend": "bocha"}}
        client, rec = zp_client([])
        provider = CompatProvider(make_client=lambda k: client, sleep=self.sleep)
        with self.assertRaisesRegex(LLMConfigError, "BOCHA_API_KEY"):
            asyncio.run(provider.run(_req(tools=("WebSearch",)), SPEC))
        self.assertEqual(rec.calls, [])

    def test_no_search_key_needed_when_the_request_has_no_web_tools(self):
        self.stored = {**STORED, "search": {"backend": "tavily"}}
        client, _ = zp_client([zp_stream("ok")])
        r = asyncio.run(CompatProvider(make_client=lambda k: client, sleep=self.sleep).run(_req(), SPEC))
        self.assertEqual(r.text, "ok")


class FakeCompletions:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def _probe_client(outcome):
    rec = Recorder([])
    completions = FakeCompletions(outcome)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions), close=rec.close), completions


def _response(tool_calls):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=tool_calls))])


class ProbeTests(unittest.TestCase):
    def probe(self, outcome, model=MODEL):
        client, completions = _probe_client(outcome)
        self.completions = completions
        return asyncio.run(compat.probe("https://llm.example.com/v1", SECRET, model, make=lambda u, k: client))

    def test_tool_calls_mean_ok(self):
        out = self.probe(_response([SimpleNamespace(id="c1")]))
        self.assertEqual((out["ok"], out["tool_calls"]), (True, True))
        self.assertIsInstance(out["latency_ms"], int)
        kw = self.completions.calls[0]
        self.assertEqual((kw["model"], [t["function"]["name"] for t in kw["tools"]]), ("my-model-v1", ["WebSearch"]))
        self.assertNotIn("max_tokens", kw)

    def test_no_tool_calls_means_not_usable_for_research(self):
        for calls in (None, []):
            out = self.probe(_response(calls))
            self.assertEqual((out["ok"], out["tool_calls"]), (False, False))
            self.assertIn("该模型不支持工具调用，无法用于研究", out["detail"])
        self.assertFalse(self.probe(SimpleNamespace(choices=[]))["ok"])

    def test_errors_are_reported_without_the_key(self):
        auth = api_error(openai.AuthenticationError, 401, None, message=f"bad key {SECRET}")
        out = self.probe(auth)
        self.assertEqual((out["ok"], out["tool_calls"]), (False, False))
        self.assertIn("API Key 无效", out["detail"])
        out = self.probe(api_error(openai.BadRequestError, 400, None, message=f"tools unsupported {SECRET}"))
        self.assertNotIn(SECRET, json.dumps(out))
        out = self.probe(openai.APIConnectionError(message="connection reset", request=None))
        self.assertIn("无法连接端点", out["detail"])

    def test_probe_client_has_a_short_timeout_and_the_given_base_url(self):
        c = compat.make_probe_client("https://other.example.com/v1", "k")
        self.assertEqual(str(c.base_url), "https://other.example.com/v1/")
        self.assertEqual(c.timeout, compat.PROBE_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
