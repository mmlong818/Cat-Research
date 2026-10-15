"""调用层分发：按 model 查注册表路由到提供方、统一本地 schema 校验、不可重试错误、按模型限制并发。"""
import asyncio
import unittest
from unittest import mock

from llm import client, providers
from llm.models import MODELS
from llm.types import LLMBlockedError, LLMConfigError, LLMError, LLMQuotaError, LLMRequest, LLMResult

SCHEMA = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}


def _result(data=None, text="ok"):
    return LLMResult(text=text, data=data, duration_ms=1, num_turns=1, session_id="")


class FakeProvider:
    def __init__(self, *outcomes, delay=0.0) -> None:
        self.outcomes = list(outcomes)
        self.calls: list = []
        self.delay = delay
        self.active = self.peak = 0

    async def run(self, req, spec):
        self.calls.append((req, spec))
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(self.delay)
            out = self.outcomes.pop(0) if self.outcomes else _result()
            if isinstance(out, BaseException):
                raise out
            return out
        finally:
            self.active -= 1


def _patch(test, **fakes):
    p = mock.patch.dict(providers.PROVIDERS, {name: (lambda f=f: f) for name, f in fakes.items()})
    p.start()
    test.addCleanup(p.stop)


class RoutingTests(unittest.TestCase):
    def test_model_selects_provider(self):
        zhipu, openai_ = FakeProvider(), FakeProvider()
        _patch(self, zhipu=zhipu, openai=openai_)
        client.call(LLMRequest(prompt="p", system="s", model="glm-5.3"))
        client.call(LLMRequest(prompt="p", system="s", model="gpt-6-luna"))
        self.assertEqual(zhipu.calls[0][1], MODELS["glm-5.3"])
        self.assertEqual(openai_.calls[0][1], MODELS["gpt-6-luna"])

    def test_unknown_model_fails_fast_without_calling_anything(self):
        fake = FakeProvider()
        _patch(self, claude=fake, zhipu=fake, openai=fake)
        with self.assertRaisesRegex(LLMConfigError, "注册表"):
            client.call(LLMRequest(prompt="p", system="s", model="m"))
        self.assertEqual(fake.calls, [])

    def test_explicit_transport_must_match_the_model_vendor(self):
        api = FakeProvider()
        _patch(self, anthropic=api)
        client.call(LLMRequest(prompt="p", system="s", model="claude-opus-5-5", provider="anthropic"))
        self.assertEqual(len(api.calls), 1)
        with self.assertRaisesRegex(LLMConfigError, "glm-5.3"):
            client.call(LLMRequest(prompt="p", system="s", model="glm-5.3", provider="anthropic"))

    def test_schema_is_validated_locally_and_invalid_data_is_retried(self):
        fake = FakeProvider(_result({"n": "not int"}), _result({"n": 3}))
        _patch(self, zhipu=fake)
        r = client.call(LLMRequest(prompt="p", system="s", model="glm-5.3", schema=SCHEMA))
        self.assertEqual((r.data, len(fake.calls)), ({"n": 3}, 2))

    def test_schema_violation_after_retries_raises(self):
        fake = FakeProvider(_result({"n": "x"}), _result({"n": "y"}))
        _patch(self, zhipu=fake)
        with self.assertRaisesRegex(LLMError, "schema"):
            client.call(LLMRequest(prompt="p", system="s", model="glm-5.3", schema=SCHEMA))

    def test_permanent_errors_are_not_retried(self):
        for exc in (LLMConfigError("no key"), LLMQuotaError("arrears"), LLMBlockedError("1301")):
            fake = FakeProvider(exc, _result())
            _patch(self, zhipu=fake)
            with self.subTest(type(exc).__name__), self.assertRaises(type(exc)):
                client.call(LLMRequest(prompt="p", system="s", model="glm-5.3", retries=2))
            self.assertEqual(len(fake.calls), 1)

    def test_timeout_applies_to_every_provider(self):
        _patch(self, zhipu=FakeProvider(delay=1))
        with self.assertRaisesRegex(LLMError, "超时"):
            client.call(LLMRequest(prompt="p", system="s", model="glm-5.3", timeout=0.05, retries=0))


class ConcurrencyTests(unittest.TestCase):
    def test_call_many_caps_concurrency_per_model(self):
        fake = FakeProvider(delay=0.05)
        _patch(self, zhipu=fake)
        reqs = [LLMRequest(prompt=str(i), system="s", model="glm-5.3") for i in range(8)]
        out = client.call_many(reqs, max_concurrency=8)
        self.assertEqual(len(out), 8)
        self.assertEqual(fake.peak, MODELS["glm-5.3"].max_concurrency)

    def test_caller_limit_still_applies_when_lower(self):
        fake = FakeProvider(delay=0.05)
        _patch(self, zhipu=fake)
        client.call_many([LLMRequest(prompt="p", system="s", model="glm-5.3-flash") for _ in range(6)],
                         max_concurrency=2)
        self.assertEqual(fake.peak, 2)

    def test_unknown_model_becomes_an_error_entry(self):
        _patch(self, zhipu=FakeProvider())
        out = client.call_many([LLMRequest(prompt="p", system="s", model="glm-5.3"),
                                LLMRequest(prompt="p", system="s", model="m")])
        self.assertIsInstance(out[0], LLMResult)
        self.assertIsInstance(out[1], LLMConfigError)


if __name__ == "__main__":
    unittest.main()
