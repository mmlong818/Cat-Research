import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from claude_agent_sdk import ProcessError, ResultError, ResultMessage, SystemMessage

from llm import client
from llm.client import LLMError, LLMQuotaError, LLMRequest
from llm.providers import claude as claude_provider


def _result(**kw):
    base = dict(subtype="success", duration_ms=1200, duration_api_ms=1000, is_error=False,
                num_turns=2, session_id="s1", result="ok")
    base.update(kw)
    return ResultMessage(**base)


def _fake_query(*messages, delay=0.0):
    async def fake(prompt, options):
        if delay:
            await asyncio.sleep(delay)
        for m in messages:
            yield m
    return fake


REQ = LLMRequest(prompt="p", system="s", model="claude-opus-5-5")


class CallTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(claude_provider, "resolve_cli_path", return_value="claude.exe")
        p.start()
        self.addCleanup(p.stop)

    def _run(self, fake, req=REQ):
        with mock.patch.object(claude_provider, "query", fake):
            return client.call(req)

    def test_success_returns_text_and_usage(self):
        fake = _fake_query(SystemMessage(subtype="init", data={}),
                           _result(model_usage={"claude-opus-5-5": {}}))
        r = self._run(fake)
        self.assertEqual((r.text, r.num_turns), ("ok", 2))
        self.assertFalse(hasattr(r, "cost_usd"))
        self.assertIn("claude-opus-5-5", r.model_usage)

    def test_structured_output_returned_as_data(self):
        req = LLMRequest(prompt="p", system="s", model="claude-opus-5-5", schema={"type": "object"})
        r = self._run(_fake_query(_result(structured_output={"score": 8})), req)
        self.assertEqual(r.data, {"score": 8})

    def test_missing_structured_output_raises(self):
        req = LLMRequest(prompt="p", system="s", model="claude-opus-5-5", schema={"type": "object"})
        with self.assertRaisesRegex(LLMError, "structured_output"):
            self._run(_fake_query(_result()), req)

    def test_error_result_raises(self):
        fake = _fake_query(_result(subtype="error_max_turns", is_error=True, errors=["too many"]))
        with self.assertRaisesRegex(LLMError, "error_max_turns.*too many"):
            self._run(fake)

    def test_refusal_raises(self):
        with self.assertRaisesRegex(LLMError, "拒答"):
            self._run(_fake_query(_result(stop_reason="refusal")))

    def test_no_result_message_raises(self):
        with self.assertRaisesRegex(LLMError, "未返回 result"):
            self._run(_fake_query(SystemMessage(subtype="init", data={})))

    def test_timeout_raises(self):
        req = LLMRequest(prompt="p", system="s", model="claude-opus-5-5", timeout=0.05)
        with self.assertRaisesRegex(LLMError, "超时"):
            self._run(_fake_query(_result(), delay=1), req)

    def test_options_forward_schema_tools_and_isolation(self):
        seen = {}

        async def fake(prompt, options):
            seen["o"] = options
            yield _result(structured_output={})

        req = LLMRequest(prompt="p", system="sys", model="claude-opus-5-5", effort="high",
                         tools=["WebSearch"], schema={"type": "object"})
        self._run(fake, req)
        o = seen["o"]
        self.assertEqual(o.output_format, {"type": "json_schema", "schema": {"type": "object"}})
        self.assertEqual((o.tools, o.allowed_tools), (["WebSearch"], ["WebSearch"]))
        self.assertEqual((o.effort, o.setting_sources, o.cli_path), ("high", [], "claude.exe"))


class RetryTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(claude_provider, "resolve_cli_path", return_value="claude.exe")
        p.start()
        self.addCleanup(p.stop)

    def _flaky(self, failures):
        state = {"n": 0}

        async def fake(prompt, options):
            state["n"] += 1
            if state["n"] <= failures:
                yield _result(subtype="error_during_execution", is_error=True)
            else:
                yield _result(result="ok")
        return fake, state

    def test_retry_then_success(self):
        fake, state = self._flaky(1)
        with mock.patch.object(claude_provider, "query", fake):
            self.assertEqual(client.call(REQ).text, "ok")
        self.assertEqual(state["n"], 2)

    def test_exhausted_retries_raise(self):
        fake, state = self._flaky(5)
        req = LLMRequest(prompt="p", system="s", model="claude-opus-5-5", retries=2)
        with mock.patch.object(claude_provider, "query", fake), self.assertRaises(LLMError):
            client.call(req)
        self.assertEqual(state["n"], 3)


class SDKExceptionTests(unittest.TestCase):
    """SDK 在错误结果后抛 ResultError/ProcessError：必须转成 LLMError（真实运行中曾直接击穿编排层）。"""

    def setUp(self):
        p = mock.patch.object(claude_provider, "resolve_cli_path", return_value="claude.exe")
        p.start()
        self.addCleanup(p.stop)

    def _raising(self, exc):
        state = {"n": 0}

        async def fake(prompt, options):
            state["n"] += 1
            yield _result(subtype="success", is_error=True)
            raise exc
        return fake, state

    def test_session_limit_becomes_quota_error_without_retry(self):
        exc = ResultError("Claude Code returned an error result: You've hit your session limit", exit_code=1)
        fake, state = self._raising(exc)
        with mock.patch.object(claude_provider, "query", fake), self.assertRaises(LLMQuotaError):
            client.call(REQ)
        self.assertEqual(state["n"], 1)

    def test_other_process_error_becomes_llm_error_and_retries(self):
        fake, state = self._raising(ProcessError("boom", exit_code=1))
        with mock.patch.object(claude_provider, "query", fake), self.assertRaises(LLMError) as cm:
            client.call(REQ)
        self.assertNotIsInstance(cm.exception, LLMQuotaError)
        self.assertEqual(state["n"], 2)


class CallManyTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(claude_provider, "resolve_cli_path", return_value="claude.exe")
        p.start()
        self.addCleanup(p.stop)

    def test_runs_in_parallel_and_keeps_order_with_failures(self):
        async def fake(prompt, options):
            await asyncio.sleep(0.2)
            if prompt == "bad":
                yield _result(subtype="error_during_execution", is_error=True)
            else:
                yield _result(result=prompt)

        reqs = [LLMRequest(prompt=p, system="s", model="claude-opus-5-5") for p in ("a", "bad", "c")]
        with mock.patch.object(claude_provider, "query", fake):
            t0 = time.monotonic()
            out = client.call_many(reqs, max_concurrency=3)
            elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 0.5)
        self.assertEqual((out[0].text, out[2].text), ("a", "c"))
        self.assertIsInstance(out[1], LLMError)


class ResolveCliPathTests(unittest.TestCase):
    def test_env_var_wins(self):
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            path = f.name
        self.addCleanup(os.unlink, path)
        with mock.patch.dict(os.environ, {claude_provider.CLI_PATH_ENV: path}):
            self.assertEqual(claude_provider.resolve_cli_path(), path)

    def test_env_var_missing_file_raises(self):
        with mock.patch.dict(os.environ, {claude_provider.CLI_PATH_ENV: "Z:/nope/claude.exe"}), \
                self.assertRaisesRegex(LLMError, "不存在"):
            claude_provider.resolve_cli_path()

    def test_windows_cmd_resolves_to_npm_native_exe(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / claude_provider._NPM_NATIVE_EXE
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"")
            with mock.patch.object(claude_provider.os.environ, "get", return_value=None), \
                 mock.patch.object(claude_provider.shutil, "which", return_value=str(Path(d) / "claude.CMD")), \
                 mock.patch.object(claude_provider.sys, "platform", "win32"):
                self.assertEqual(claude_provider.resolve_cli_path(), str(exe))

    def test_windows_cmd_without_native_exe_raises(self):
        with mock.patch.object(claude_provider.os.environ, "get", return_value=None), \
             mock.patch.object(claude_provider.shutil, "which", return_value="C:/x/claude.CMD"), \
             mock.patch.object(claude_provider.sys, "platform", "win32"), self.assertRaisesRegex(LLMError, "批处理"):
            claude_provider.resolve_cli_path()


if __name__ == "__main__":
    unittest.main()
