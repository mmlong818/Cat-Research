"""E7a 后端直接提供构建好的前端：/assets/*、/logo.png 返回文件本身，其余非 API 路径返回入口页。"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from api import app as app_mod


class StaticServingTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        self.static = os.path.join(root, "static")
        os.makedirs(os.path.join(self.static, "assets"))
        files = {"index.html": "<html><head></head><body>INDEX</body></html>",
                 "assets/app-1.js": "console.log(1)", "logo.png": "PNG"}
        for rel, text in files.items():
            with open(os.path.join(self.static, rel), "w", encoding="utf-8") as f:
                f.write(text)
        with open(os.path.join(root, "secret.txt"), "w", encoding="utf-8") as f:
            f.write("SECRET")
        p = mock.patch.object(app_mod, "STATIC_DIR", self.static)
        p.start()
        self.addCleanup(p.stop)
        self.client = TestClient(app_mod.app, base_url="http://127.0.0.1:8000")

    def test_assets_are_served_as_files(self):
        res = self.client.get("/assets/app-1.js")
        self.assertEqual(res.status_code, 200)
        self.assertIn("javascript", res.headers["content-type"])
        self.assertEqual(res.text, "console.log(1)")
        self.assertEqual(self.client.get("/logo.png").content, b"PNG")

    def test_spa_routes_get_index(self):
        res = self.client.get("/research")
        self.assertIn("INDEX", res.text)
        self.assertIn("cat-api-token", res.text)  # 入口页仍注入令牌

    def test_no_escape_from_static_dir(self):
        for path in ("/..%2Fsecret.txt", "/assets/..%2F..%2Fsecret.txt", "/%2e%2e/secret.txt"):
            with self.subTest(path):
                self.assertNotIn("SECRET", self.client.get(path).text)


if __name__ == "__main__":
    unittest.main()
