"""M4 设置：默认配置档与三家 API Key 的读写（key 只回预览）、配置档校验、缺 key 的 400、/api/models 分组。"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import keyring
from fastapi import HTTPException
from fastapi.testclient import TestClient

import config
from api import app as app_mod
from api import config_store, security
from api.profile_resolver import resolve_profile
from llm import keys
from llm.models import MODELS
from llm.profiles import PROFILES, Profile, default_profile
from tests import MemoryKeyring

HEADERS = {security.TOKEN_HEADER: security.TOKEN}
OPENAI_KEY = "sk-openai-SECRET-1234567890abcd"
ZHIPU_KEY = "zhipu-SECRET-0987654321.wxyz"
ENV_NAMES = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ZHIPU_API_KEY", "COMPAT_API_KEY", "COMPAT_BASE_URL",
             "BOCHA_API_KEY", "BOCHA_BASE_URL", "TAVILY_API_KEY", "SEARCH_BACKEND")


class SettingsCase(unittest.TestCase):
    """每个用例独立的配置文件与内存凭据库，环境变量里的 key 清空，默认模型固定为 Claude。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        old_ring = keyring.get_keyring()
        keyring.set_keyring(MemoryKeyring())
        self.addCleanup(keyring.set_keyring, old_ring)
        for p in (mock.patch.object(config_store, "_CONFIG_FILE", os.path.join(self.tmp, "user_config.json")),
                  mock.patch.dict(os.environ, dict.fromkeys(ENV_NAMES, "")),
                  mock.patch.object(config, "CORE_MODEL", "claude-opus-5-5"),
                  mock.patch.object(config, "SUPPORT_MODEL", "claude-sonnet-5-5")):
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(app_mod.app, base_url="http://127.0.0.1:8000")

    def file_content(self) -> dict:
        try:
            with open(config_store._CONFIG_FILE, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def get(self) -> dict:
        res = self.client.get("/api/settings", headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def post(self, body: dict):
        return self.client.post("/api/settings", json=body, headers=HEADERS)


class SettingsReadTests(SettingsCase):
    def test_default_profile_and_all_providers_are_listed(self):
        data = self.get()
        self.assertEqual(data["default_profile"],
                         {"provider": "claude", "core": "claude-opus-5-5", "support": "claude-sonnet-5-5"})
        self.assertEqual(list(data["providers"]), ["claude", "openai", "zhipu", "compat"])

    def test_claude_needs_no_key_but_others_do(self):
        providers = self.get()["providers"]
        self.assertEqual((providers["claude"]["needs_key"], providers["claude"]["available"]), (False, True))
        for name in ("openai", "zhipu", "compat"):
            p = providers[name]
            self.assertEqual((p["needs_key"], p["has_key"], p["available"], p["key_preview"], p["key_source"]),
                             (True, False, False, "", ""), name)

    def test_models_come_from_the_capability_table_per_provider(self):
        providers = self.get()["providers"]
        for name, p in providers.items():
            if name == "compat":
                continue  # 兼容端点的模型来自用户配置，见 test_compat_settings
            self.assertEqual([m["id"] for m in p["models"]], [i for i, s in MODELS.items() if s.provider == name])
            self.assertEqual(p["defaults"], {"core": PROFILES[name].core, "support": PROFILES[name].support})
        by_id = {m["id"]: m for m in providers["openai"]["models"]}
        self.assertEqual(set(by_id["gpt-6.1-sol"]), {"id", "context"})  # 不再带价格与价格档

    def test_models_endpoint_is_grouped_by_provider(self):
        res = self.client.get("/api/models", headers=HEADERS)
        self.assertEqual(res.status_code, 200)
        grouped = res.json()["models"]
        self.assertEqual(list(grouped), ["claude", "openai", "zhipu"])
        self.assertEqual([m["id"] for m in grouped["zhipu"]], ["glm-5.3", "glm-5.3-flash", "glm-5.3-flashx"])

    def test_settings_is_defined_only_in_the_settings_router(self):
        # app.py 里曾有一份重复定义（因路由器先注册而从未生效），现已删除：app 自己不应再有这个路径
        self.assertEqual([r for r in app_mod.app.routes if getattr(r, "path", "") == "/api/settings"], [])
        self.assertIn("providers", self.get())


class KeyStorageTests(SettingsCase):
    def test_key_is_stored_in_keyring_and_only_the_last_four_come_back(self):
        res = self.post({"api_keys": {"openai": OPENAI_KEY}})
        self.assertEqual(res.status_code, 200, res.text)
        openai = res.json()["providers"]["openai"]
        self.assertEqual((openai["has_key"], openai["available"], openai["key_source"]), (True, True, "keyring"))
        self.assertEqual(openai["key_preview"], "...abcd")
        self.assertNotIn(OPENAI_KEY, res.text)
        self.assertNotIn(OPENAI_KEY, self.client.get("/api/settings", headers=HEADERS).text)
        self.assertNotIn("openai_api_key", self.file_content())
        self.assertEqual(config_store.load_config()["openai_api_key"], OPENAI_KEY)

    def test_empty_string_leaves_the_key_unchanged(self):
        self.post({"api_keys": {"openai": OPENAI_KEY, "zhipu": ZHIPU_KEY}})
        data = self.post({"api_keys": {"openai": "", "zhipu": "   "}}).json()["providers"]
        self.assertEqual((data["openai"]["has_key"], data["zhipu"]["has_key"]), (True, True))
        self.assertEqual(data["zhipu"]["key_preview"], "...wxyz")

    def test_key_can_be_replaced(self):
        self.post({"api_keys": {"openai": OPENAI_KEY}})
        data = self.post({"api_keys": {"openai": "sk-new-0000"}}).json()["providers"]["openai"]
        self.assertEqual(data["key_preview"], "...0000")

    def test_clear_keys_field_and_delete_endpoint_remove_only_that_key(self):
        self.post({"api_keys": {"openai": OPENAI_KEY, "zhipu": ZHIPU_KEY}})
        data = self.post({"clear_keys": ["openai"]}).json()["providers"]
        self.assertEqual((data["openai"]["has_key"], data["zhipu"]["has_key"]), (False, True))
        res = self.client.delete("/api/settings/keys/zhipu", headers=HEADERS)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["providers"]["zhipu"]["has_key"])
        self.assertEqual(self.client.delete("/api/settings/keys/gemini", headers=HEADERS).status_code, 400)

    def test_anthropic_key_is_optional_and_lives_under_claude(self):
        data = self.post({"api_keys": {"claude": "sk-ant-abcdWXYZ"}}).json()["providers"]["claude"]
        self.assertEqual((data["has_key"], data["key_preview"], data["needs_key"]), (True, "...WXYZ", False))
        self.assertEqual(config_store.load_config()["anthropic_api_key"], "sk-ant-abcdWXYZ")

    def test_env_key_counts_but_is_marked_as_env(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": OPENAI_KEY}):
            openai = self.get()["providers"]["openai"]
            self.assertEqual((openai["has_key"], openai["key_source"], openai["key_preview"]),
                             (True, "env", "...abcd"))
            cleared = self.post({"clear_keys": ["openai"]}).json()["providers"]["openai"]
            self.assertEqual(cleared["key_source"], "env")  # 清不掉环境变量里的 key

    def test_unknown_provider_in_key_fields_is_rejected(self):
        self.assertEqual(self.post({"api_keys": {"gemini": "k"}}).status_code, 400)
        self.assertEqual(self.post({"clear_keys": ["gemini"]}).status_code, 400)

    def test_secret_store_failure_is_a_400_with_a_hint_not_the_key(self):
        from keyring.errors import KeyringError
        with mock.patch.object(keyring, "set_password", side_effect=KeyringError("no backend")):
            res = self.post({"api_keys": {"openai": OPENAI_KEY}})
        self.assertEqual(res.status_code, 400)
        self.assertNotIn(OPENAI_KEY, res.text)


class DefaultProfileTests(SettingsCase):
    def test_default_profile_is_persisted_and_used_everywhere(self):
        res = self.post({"api_keys": {"openai": OPENAI_KEY},
                         "default_profile": {"provider": "openai", "core": "gpt-6.1-sol", "support": "gpt-6-luna"}})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["default_profile"],
                         {"provider": "openai", "core": "gpt-6.1-sol", "support": "gpt-6-luna"})
        self.assertEqual(self.file_content()["default_profile"],
                         {"provider": "openai", "core": "gpt-6.1-sol", "support": "gpt-6-luna"})
        self.assertEqual(default_profile(), Profile("openai", "gpt-6.1-sol", "gpt-6-luna"))
        self.assertEqual(self.get()["default_profile"]["provider"], "openai")

    def test_missing_models_fall_back_to_the_providers_defaults(self):
        self.post({"api_keys": {"zhipu": ZHIPU_KEY}, "default_profile": {"provider": "zhipu"}})
        self.assertEqual(default_profile(), PROFILES["zhipu"])
        self.post({"default_profile": {"provider": "zhipu", "support": "glm-5.3-flashx"}})
        self.assertEqual(default_profile(), Profile("zhipu", "glm-5.3", "glm-5.3-flashx"))

    def test_models_must_be_in_the_chosen_providers_capability_table(self):
        bad = [{"provider": "claude", "core": "gpt-6.1-sol"},      # 属于别家
               {"provider": "openai", "support": "glm-5.3-flash"},
               {"provider": "claude", "core": "opus"},               # 别名不在能力表里
               {"provider": "claude", "support": "claude-made-up"},
               {"provider": "gemini"}]
        self.post({"api_keys": {"openai": OPENAI_KEY}})
        for profile in bad:
            res = self.post({"default_profile": profile})
            self.assertEqual(res.status_code, 400, profile)
        self.assertNotIn("default_profile", self.file_content())

    def test_provider_without_key_cannot_become_default(self):
        res = self.post({"default_profile": {"provider": "openai"}})
        self.assertEqual(res.status_code, 400)
        self.assertIn("请先在设置中填写 OpenAI 的 API Key", res.json()["detail"])
        self.assertIn("智谱", self.post({"default_profile": {"provider": "zhipu"}}).json()["detail"])
        self.assertNotIn("default_profile", self.file_content())

    def test_key_and_profile_in_one_request_succeed_but_a_bad_profile_saves_nothing(self):
        res = self.post({"api_keys": {"openai": OPENAI_KEY}, "default_profile": {"provider": "openai"}})
        self.assertEqual(res.status_code, 200, res.text)
        self.client.delete("/api/settings/keys/openai", headers=HEADERS)
        bad = self.post({"api_keys": {"openai": OPENAI_KEY},
                         "default_profile": {"provider": "openai", "core": "glm-5.3"}})
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(self.get()["providers"]["openai"]["has_key"])  # 校验失败时连 key 也不写

    def test_claude_default_needs_no_key(self):
        res = self.post({"default_profile": {"provider": "claude", "core": "claude-opus-5",
                                             "support": "claude-sonnet-5"}})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(default_profile().core, "claude-opus-5")

    def test_legacy_core_model_setting_still_picks_the_default(self):
        config_store.save_config({"core_model": "claude-opus-5"})
        self.assertEqual(default_profile(), Profile("claude", "claude-opus-5", "claude-sonnet-5-5"))

    def test_invalid_saved_profile_falls_back_to_config(self):
        config_store.save_config({"default_profile": {"provider": "openai", "core": "glm-5.3"}})
        self.assertEqual(default_profile(), Profile("claude", "claude-opus-5-5", "claude-sonnet-5-5"))


class ResolveProfileTests(SettingsCase):
    def detail(self, **kw) -> str:
        with self.assertRaises(HTTPException) as cm:
            resolve_profile(**kw)
        self.assertEqual(cm.exception.status_code, 400)
        return cm.exception.detail

    def test_no_arguments_gives_the_saved_default(self):
        self.assertEqual(resolve_profile(), Profile("claude", "claude-opus-5-5", "claude-sonnet-5-5"))
        config_store.save_config({"openai_api_key": OPENAI_KEY,
                                  "default_profile": {"provider": "openai", "core": "gpt-6-luna"}})
        self.assertEqual(resolve_profile(), Profile("openai", "gpt-6-luna", "gpt-6-luna"))

    def test_missing_key_is_a_chinese_400_for_openai_and_zhipu(self):
        self.assertEqual(self.detail(provider="openai"), "请先在设置中填写 OpenAI 的 API Key")
        self.assertEqual(self.detail(provider="zhipu"), "请先在设置中填写 智谱 的 API Key")

    def test_key_from_environment_is_enough(self):
        with mock.patch.dict(os.environ, {"ZHIPU_API_KEY": ZHIPU_KEY}):
            self.assertEqual(resolve_profile(provider="zhipu"), PROFILES["zhipu"])

    def test_switching_provider_uses_that_providers_defaults_not_the_saved_models(self):
        config_store.save_config({"openai_api_key": OPENAI_KEY, "zhipu_api_key": ZHIPU_KEY,
                                  "default_profile": {"provider": "openai", "core": "gpt-6-luna"}})
        self.assertEqual(resolve_profile(provider="zhipu"), PROFILES["zhipu"])
        self.assertEqual(resolve_profile(provider="openai"), Profile("openai", "gpt-6-luna", "gpt-6-luna"))

    def test_explicit_models_override_and_are_validated(self):
        config_store.save_config({"openai_api_key": OPENAI_KEY})
        self.assertEqual(resolve_profile(provider="openai", core="gpt-6-astra", support="gpt-6-luna"),
                         Profile("openai", "gpt-6-astra", "gpt-6-luna"))
        self.assertEqual(resolve_profile(core="claude-opus-5").core, "claude-opus-5")  # 不传 provider 沿用默认提供方
        self.assertIn("claude-opus-5-5", self.detail(provider="openai", core="claude-opus-5-5"))
        self.detail(provider="gemini")
        self.detail(provider="claude", core="opus")

    def test_claude_never_needs_a_key(self):
        self.assertEqual(resolve_profile(provider="claude").provider, "claude")

    def test_invalid_config_models_give_400_not_500(self):
        with mock.patch.object(config, "CORE_MODEL", "no-such-model"):
            self.detail()


class KeyHelperTests(SettingsCase):
    def test_missing_key_label(self):
        self.assertIsNone(keys.missing_key_label("claude"))
        self.assertIsNone(keys.missing_key_label("unknown"))
        self.assertEqual((keys.missing_key_label("openai"), keys.missing_key_label("zhipu")), ("OpenAI", "智谱"))
        config_store.save_config({"openai_api_key": OPENAI_KEY})
        self.assertIsNone(keys.missing_key_label("openai"))


if __name__ == "__main__":
    unittest.main()
