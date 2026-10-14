"""设置 API 的兼容端点与搜索后端部分：GET 新字段、POST compat / search_backend / 新 key、compat/test、
启动前缺项的 400、00_session.json 的 search_backend、环境检查。"""
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import openai
from fastapi import HTTPException

import main
from api import config_store
from api.profile_resolver import resolve_profile, session_profile
from llm import keys
from llm.profiles import PROFILES, Profile, default_profile, make_profile
from llm.providers import compat
from research.params import resolve_params
from tests.llm_fakes import SECRET, api_error
from tests.test_settings import HEADERS, SettingsCase

BOCHA_KEY = "bocha-SECRET-1234567890wxyz"
TAVILY_KEY = "tvly-SECRET-1234567890abcd"
URL = "https://llm.example.com/v1"
ALL_MISSING = "请先在设置中填写 OpenAI 兼容端点 的 Base URL、OpenAI 兼容端点 的 API Key、智谱搜索 的 API Key"


def _configure(**extra):
    config_store.save_config({"compat_api_key": SECRET, "compat": {"base_url": URL, "core": "compat:big",
                                                                    "support": "compat:small"}, **extra})


class SettingsReadTests(SettingsCase):
    def test_compat_entry_when_nothing_is_configured(self):
        entry = self.get()["providers"]["compat"]
        self.assertEqual(entry, {"needs_key": True, "has_key": False, "key_source": "", "key_preview": "",
                                 "available": False, "defaults": {"core": "", "support": ""}, "models": [],
                                 "base_url": ""})

    def test_compat_entry_when_fully_configured(self):
        _configure()
        entry = self.get()["providers"]["compat"]
        self.assertEqual((entry["has_key"], entry["key_source"], entry["available"], entry["base_url"]),
                         (True, "keyring", True, URL))
        self.assertEqual(entry["key_preview"], f"...{SECRET[-4:]}")
        self.assertEqual(entry["defaults"], {"core": "compat:big", "support": "compat:small"})
        self.assertEqual(entry["models"], [
            {"id": "compat:big", "tier": "low", "input_price": 0.0, "cached_price": 0.0, "output_price": 0.0,
             "context": 128_000},
            {"id": "compat:small", "tier": "low", "input_price": 0.0, "cached_price": 0.0, "output_price": 0.0,
             "context": 128_000}])
        self.assertNotIn(SECRET, json.dumps(self.get()))

    def test_available_needs_all_of_base_url_key_core_and_support(self):
        for missing in ("compat_api_key", "base_url", "core", "support"):
            with self.subTest(missing):
                self._clear_compat()
                _configure()
                if missing == "compat_api_key":
                    config_store.save_config({"compat_api_key": ""})
                else:
                    section = {"base_url": URL, "core": "compat:big", "support": "compat:small"}
                    del section[missing]
                    config_store.save_config({"compat": section})
                self.assertFalse(self.get()["providers"]["compat"]["available"])

    def _clear_compat(self):
        config_store.save_config({"compat_api_key": "", "compat": {}})

    def test_base_url_may_come_from_the_environment(self):
        with mock.patch.dict("os.environ", {"COMPAT_BASE_URL": "http://localhost:11434/v1"}):
            self.assertEqual(self.get()["providers"]["compat"]["base_url"], "http://localhost:11434/v1")

    def test_search_section_defaults_to_zhipu_with_prices(self):
        search = self.get()["search"]
        self.assertEqual(search["backend"], "zhipu")
        self.assertEqual(search["backends"], {
            "zhipu": {"has_key": False, "key_source": "", "key_preview": "", "price_usd": 0.01},
            "bocha": {"has_key": False, "key_source": "", "key_preview": "", "price_usd": 0.005},
            "tavily": {"has_key": False, "key_source": "", "key_preview": "", "price_usd": 0.008}})

    def test_search_keys_report_source_and_preview(self):
        config_store.save_config({"bocha_api_key": BOCHA_KEY})
        with mock.patch.dict("os.environ", {"TAVILY_API_KEY": TAVILY_KEY}):
            backends = self.get()["search"]["backends"]
        self.assertEqual((backends["bocha"]["key_source"], backends["bocha"]["key_preview"]), ("keyring", "...wxyz"))
        self.assertEqual((backends["tavily"]["key_source"], backends["tavily"]["key_preview"]), ("env", "...abcd"))

    def test_models_endpoint_stays_static(self):
        grouped = self.client.get("/api/models", headers=HEADERS).json()["models"]
        self.assertEqual(list(grouped), ["claude", "openai", "zhipu"])


class SettingsWriteTests(SettingsCase):
    def test_compat_settings_are_saved_and_models_get_the_prefix(self):
        res = self.post({"compat": {"base_url": f" {URL} ", "core": "big-model", "support": "compat:small"}})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.file_content()["compat"], {"base_url": URL, "core": "compat:big-model",
                                                         "support": "compat:small"})
        entry = res.json()["providers"]["compat"]
        self.assertEqual((entry["base_url"], entry["defaults"]["core"]), (URL, "compat:big-model"))

    def test_partial_update_keeps_other_fields_and_empty_string_clears(self):
        self.post({"compat": {"base_url": URL, "core": "a", "support": "b"}})
        self.post({"compat": {"core": "c"}})
        self.assertEqual(self.file_content()["compat"], {"base_url": URL, "core": "compat:c", "support": "compat:b"})
        self.post({"compat": {"support": "  "}})
        self.assertEqual(self.file_content()["compat"], {"base_url": URL, "core": "compat:c"})

    def test_base_url_must_be_http_or_https(self):
        for bad in ("ftp://x.example/v1", "llm.example.com/v1", "javascript:alert(1)", "http://"):
            res = self.post({"compat": {"base_url": bad}})
            self.assertEqual(res.status_code, 400, bad)
        self.assertNotIn("compat", self.file_content())
        self.assertEqual(self.post({"compat": {"base_url": "http://127.0.0.1:8000/v1"}}).status_code, 200)

    def test_prefix_without_a_model_name_is_rejected(self):
        self.assertEqual(self.post({"compat": {"core": "compat:"}}).status_code, 400)

    def test_search_backend_and_new_keys(self):
        res = self.post({"search_backend": "bocha", "api_keys": {"bocha": BOCHA_KEY, "tavily": TAVILY_KEY,
                                                                  "compat": SECRET}})
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["search"]["backend"], "bocha")
        self.assertTrue(data["search"]["backends"]["bocha"]["has_key"])
        self.assertEqual(data["search"]["backends"]["tavily"]["key_preview"], "...abcd")
        self.assertTrue(data["providers"]["compat"]["has_key"])
        self.assertEqual(self.file_content()["search"], {"backend": "bocha"})
        for secret in (BOCHA_KEY, TAVILY_KEY, SECRET):
            self.assertNotIn(secret, res.text)
            self.assertNotIn(secret, json.dumps(self.file_content()))
        self.assertEqual(config_store.load_config()["bocha_api_key"], BOCHA_KEY)

    def test_search_backend_must_be_one_of_the_three(self):
        self.assertEqual(self.post({"search_backend": "google"}).status_code, 400)
        self.assertNotIn("search", self.file_content())

    def test_changing_the_backend_keeps_other_search_settings(self):
        config_store.save_config({"search": {"backend": "zhipu", "bocha_base_url": "https://b.example/s"}})
        self.post({"search_backend": "tavily"})
        self.assertEqual(self.file_content()["search"], {"backend": "tavily", "bocha_base_url": "https://b.example/s"})

    def test_clear_keys_accepts_the_new_names(self):
        self.post({"api_keys": {"bocha": BOCHA_KEY, "compat": SECRET}})
        data = self.post({"clear_keys": ["bocha", "compat"]}).json()
        self.assertFalse(data["search"]["backends"]["bocha"]["has_key"])
        self.assertFalse(data["providers"]["compat"]["has_key"])
        self.assertEqual(self.client.delete("/api/settings/keys/tavily", headers=HEADERS).status_code, 200)

    def test_compat_can_become_the_default_profile_in_one_request(self):
        res = self.post({"api_keys": {"compat": SECRET, "zhipu": "zk-0000"},
                         "compat": {"base_url": URL, "core": "big", "support": "small"},
                         "default_profile": {"provider": "compat"}})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["default_profile"], {"provider": "compat", "core": "compat:big",
                                                         "support": "compat:small"})
        self.assertEqual(default_profile(), Profile("compat", "compat:big", "compat:small"))

    def test_compat_default_profile_lists_everything_that_is_missing(self):
        res = self.post({"default_profile": {"provider": "compat", "core": "compat:a", "support": "compat:b"}})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["detail"], ALL_MISSING)
        self.assertNotIn("default_profile", self.file_content())

    def test_compat_default_profile_without_models_is_a_400(self):
        res = self.post({"api_keys": {"compat": SECRET}, "compat": {"base_url": URL},
                         "default_profile": {"provider": "compat"}})
        self.assertEqual(res.status_code, 400)
        self.assertIn("核心模型与辅助模型", res.json()["detail"])
        self.assertFalse(self.get()["providers"]["compat"]["has_key"])  # 校验失败时什么都不写

    def test_compat_models_must_carry_the_prefix_in_the_default_profile(self):
        _configure()
        self.assertEqual(self.post({"default_profile": {"provider": "claude", "core": "compat:big"}}).status_code, 400)
        self.assertEqual(self.post({"default_profile": {"provider": "compat", "core": "big"}}).status_code, 400)

    def test_zhipu_default_needs_the_selected_search_backends_key_only_for_client_tools_providers(self):
        self.post({"api_keys": {"zhipu": "zk-0000"}, "search_backend": "bocha"})
        res = self.post({"default_profile": {"provider": "zhipu"}})
        self.assertEqual((res.status_code, res.json()["detail"]), (400, "请先在设置中填写 博查搜索 的 API Key"))
        self.assertEqual(self.post({"default_profile": {"provider": "claude"}}).status_code, 200)
        self.assertEqual(self.post({"api_keys": {"bocha": BOCHA_KEY},
                                    "default_profile": {"provider": "zhipu"}}).status_code, 200)


class CompatTestEndpointTests(SettingsCase):
    def call(self, body, outcome):
        client = mock.Mock()
        calls = []

        async def create(**kw):
            calls.append(kw)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        async def close():
            return None

        client.chat.completions.create, client.close = create, close
        made = []

        def make(url, key):
            made.append((url, key))
            return client

        with mock.patch.object(compat, "make_probe_client", make):
            res = self.client.post("/api/settings/compat/test", json=body, headers=HEADERS)
        return res, made, calls

    @staticmethod
    def reply(tool_calls):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=tool_calls))])

    def test_uses_saved_settings_when_the_body_is_empty(self):
        _configure()
        res, made, calls = self.call({}, self.reply([object()]))
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual((data["ok"], data["tool_calls"]), (True, True))
        self.assertEqual(set(data), {"ok", "tool_calls", "latency_ms", "detail"})
        self.assertEqual(made, [(URL, SECRET)])
        self.assertEqual(calls[0]["model"], "big")  # 去掉 compat: 前缀

    def test_body_values_override_saved_ones_and_nothing_is_saved(self):
        res, made, calls = self.call({"base_url": "http://other.example/v1", "api_key": "tmp-key-9999",
                                      "model": "compat:x"}, self.reply([object()]))
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual((made, calls[0]["model"]), ([("http://other.example/v1", "tmp-key-9999")], "x"))
        self.assertEqual(self.file_content(), {})
        self.assertNotIn("compat_api_key", config_store.load_config())

    def test_model_without_tool_calls_is_not_ok(self):
        _configure()
        data = self.call({}, self.reply(None))[0].json()
        self.assertEqual((data["ok"], data["tool_calls"]), (False, False))
        self.assertIn("该模型不支持工具调用，无法用于研究", data["detail"])

    def test_endpoint_errors_come_back_as_ok_false_without_the_key(self):
        _configure()
        res, _, _ = self.call({}, api_error(openai.AuthenticationError, 401, None, message=f"bad {SECRET}"))
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["ok"])
        self.assertNotIn(SECRET, res.text)

    def test_missing_pieces_and_bad_urls_are_400(self):
        res, made, _ = self.call({}, self.reply([object()]))
        self.assertEqual(res.status_code, 400)
        self.assertIn("Base URL", res.json()["detail"])
        self.assertEqual(made, [])
        res, made, _ = self.call({"base_url": "ftp://x", "api_key": "k", "model": "m"}, self.reply([object()]))
        self.assertEqual((res.status_code, made), (400, []))


class PreflightTests(SettingsCase):
    def detail(self, **kw) -> str:
        with self.assertRaises(HTTPException) as cm:
            resolve_profile(**kw)
        self.assertEqual(cm.exception.status_code, 400)
        return cm.exception.detail

    def test_compat_without_models_says_so(self):
        self.assertIn("核心模型与辅助模型", self.detail(provider="compat"))

    def test_compat_lists_each_missing_item(self):
        config_store.save_config({"compat": {"core": "compat:a", "support": "compat:b"}})
        self.assertEqual(self.detail(provider="compat"), ALL_MISSING)
        config_store.save_config({"compat": {"base_url": URL, "core": "compat:a", "support": "compat:b"},
                                  "search": {"backend": "tavily"}, "tavily_api_key": TAVILY_KEY})
        self.assertEqual(self.detail(provider="compat"), "请先在设置中填写 OpenAI 兼容端点 的 API Key")

    def test_search_backend_key_is_required_for_client_tools_providers(self):
        _configure(search={"backend": "tavily"})
        self.assertEqual(self.detail(provider="compat"), "请先在设置中填写 Tavily 搜索 的 API Key")
        config_store.save_config({"tavily_api_key": TAVILY_KEY})
        self.assertEqual(resolve_profile(provider="compat"), Profile("compat", "compat:big", "compat:small"))

    def test_zhipu_with_a_third_party_backend_needs_that_key_too(self):
        config_store.save_config({"zhipu_api_key": "zk-0000", "search": {"backend": "bocha"}})
        self.assertEqual(self.detail(provider="zhipu"), "请先在设置中填写 博查搜索 的 API Key")
        self.assertEqual(resolve_profile(provider="claude").provider, "claude")  # Claude 自带联网，不看搜索后端

    def test_zhipu_backend_for_compat_needs_the_zhipu_key(self):
        _configure()
        self.assertEqual(self.detail(provider="compat"), "请先在设置中填写 智谱搜索 的 API Key")

    def test_unknown_backend_is_reported(self):
        _configure(search={"backend": "nope"})
        self.assertIn("有效的联网搜索后端", self.detail(provider="compat"))

    def test_explicit_compat_models_must_carry_the_prefix_but_any_name_is_accepted(self):
        _configure(search={"backend": "zhipu"}, zhipu_api_key="zk-0000")
        self.assertEqual(resolve_profile(provider="compat", core="compat:other-model").core, "compat:other-model")
        with self.assertRaises(HTTPException):
            resolve_profile(provider="compat", core="other-model")

    def test_make_profile_recognises_the_prefix_for_compat_only(self):
        self.assertEqual(make_profile("compat", "compat:a", "compat:b"), Profile("compat", "compat:a", "compat:b"))
        for provider in ("claude", "openai", "zhipu"):
            with self.assertRaisesRegex(ValueError, "属于 compat"):
                make_profile(provider, "compat:a")
        with self.assertRaisesRegex(ValueError, "属于 zhipu"):
            make_profile("compat", "glm-5.3", "compat:b")
        self.assertNotIn("compat", PROFILES)  # 兼容端点的配置档取自用户配置，没有固定默认值

    def test_session_replay_keeps_the_compat_profile(self):
        with tempfile.TemporaryDirectory() as ws:
            with open(os.path.join(ws, "00_session.json"), "w", encoding="utf-8") as f:
                json.dump({"provider": "compat", "resolved_params": {"core_model": "compat:a",
                                                                     "support_model": "compat:b"}}, f)
            _configure(zhipu_api_key="zk-0000")
            self.assertEqual(session_profile(ws), Profile("compat", "compat:a", "compat:b"))


class RecordedParamsAndEnvironmentTests(SettingsCase):
    def test_resolved_params_record_the_search_backend_for_client_tools_providers(self):
        config_store.save_config({"search": {"backend": "tavily"}})
        self.assertEqual(resolve_params(profile=Profile("zhipu", "glm-5.3", "glm-5.3-flash"))["search_backend"],
                         "tavily")
        self.assertEqual(resolve_params(profile=Profile("compat", "compat:a", "compat:b"))["search_backend"],
                         "tavily")
        self.assertIsNone(resolve_params(profile=PROFILES["claude"])["search_backend"])
        self.assertIsNone(resolve_params(profile=PROFILES["openai"])["search_backend"])

    def test_check_environment_reports_what_is_missing_for_a_compat_default(self):
        config_store.save_config({"default_profile": {"provider": "compat", "core": "compat:a",
                                                      "support": "compat:b"}})
        errors, _ = main.check_environment()
        self.assertTrue(any("compat" in e and "Base URL" in e and "API Key" in e for e in errors), errors)
        _configure(zhipu_api_key="zk-0000")
        config_store.save_config({"default_profile": {"provider": "compat", "core": "compat:a",
                                                      "support": "compat:b"}})
        self.assertEqual(main.check_environment()[0], [])

    def test_key_helpers(self):
        self.assertEqual(keys.selected_search_backend(), "zhipu")
        self.assertEqual(keys.missing_requirements("claude"), [])
        self.assertEqual(keys.missing_requirements("openai"), ["OpenAI 的 API Key"])
        self.assertEqual(keys.missing_requirements("zhipu"), ["智谱 的 API Key"])  # 搜索后端同为智谱，不重复


if __name__ == "__main__":
    unittest.main()
