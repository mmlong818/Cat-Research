"""E1 安全基线：Host 校验（防 DNS rebinding）、本地令牌（防跨站请求）、密钥不明文落盘。"""
import json
import os
import tempfile
import unittest
from unittest import mock

import keyring
from fastapi.testclient import TestClient
from keyring.backend import KeyringBackend

from api import app as app_mod
from api import config_store, security

LOCAL = {"host": "127.0.0.1:8000"}


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app_mod.app, base_url="http://127.0.0.1:8000")

    def test_api_requires_token(self):
        self.assertEqual(self.client.get("/api/sessions").status_code, 401)

    def test_api_accepts_header_token(self):
        r = self.client.get("/api/sessions", headers={security.TOKEN_HEADER: security.TOKEN})
        self.assertEqual(r.status_code, 200)

    def test_wrong_token_rejected(self):
        r = self.client.get("/api/sessions", headers={security.TOKEN_HEADER: "nope"})
        self.assertEqual(r.status_code, 401)

    def test_query_token_only_for_get(self):
        self.assertEqual(self.client.get(f"/api/sessions?token={security.TOKEN}").status_code, 200)
        r = self.client.post(f"/api/research/stop-all?token={security.TOKEN}")
        self.assertEqual(r.status_code, 401)

    def test_health_is_exempt(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_foreign_host_rejected_everywhere(self):
        evil = TestClient(app_mod.app, base_url="http://evil.example:8000")
        self.assertEqual(evil.get("/").status_code, 403)  # 页面里有令牌，必须同样拦截
        self.assertEqual(evil.get("/api/health").status_code, 403)

    def test_index_page_carries_token(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
                f.write("<html><head><title>x</title></head><body></body></html>")
            with mock.patch.object(app_mod, "STATIC_DIR", d):
                html = self.client.get("/").text
        self.assertIn(f'<meta name="{security.TOKEN_META}" content="{security.TOKEN}">', html)

    def test_default_bind_is_loopback(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(security.bind_host(), "127.0.0.1")


class SecretStorageTests(unittest.TestCase):
    def setUp(self):
        self.ring = MemoryKeyring()
        keyring.set_keyring(self.ring)
        self.addCleanup(keyring.set_keyring, keyring.get_keyring())
        self.tmp = tempfile.mkdtemp()
        p = mock.patch.object(config_store, "_CONFIG_FILE", os.path.join(self.tmp, "user_config.json"))
        p.start()
        self.addCleanup(p.stop)

    def file_content(self):
        with open(config_store._CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)

    def test_api_key_goes_to_keyring_not_file(self):
        config_store.save_config({"anthropic_api_key": "sk-ant-secret", "core_model": "m"})
        self.assertNotIn("anthropic_api_key", self.file_content())
        self.assertEqual(self.file_content()["core_model"], "m")
        self.assertEqual(config_store.load_config()["anthropic_api_key"], "sk-ant-secret")

    def test_clearing_key_removes_it(self):
        config_store.save_config({"anthropic_api_key": "sk-ant-secret"})
        config_store.save_config({"anthropic_api_key": ""})
        self.assertEqual(config_store.load_config().get("anthropic_api_key", ""), "")

    def test_legacy_plaintext_key_is_migrated(self):
        with open(config_store._CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"anthropic_api_key": "sk-ant-old", "core_model": "m"}, f)
        self.assertEqual(config_store.load_config()["anthropic_api_key"], "sk-ant-old")
        self.assertNotIn("anthropic_api_key", self.file_content())


if __name__ == "__main__":
    unittest.main()
