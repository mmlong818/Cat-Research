"""本地联网工具（GLM 工具循环用）：正文提取、截断如实报告、拒绝内网地址、智谱搜索参数与退避、工具分发。"""
import asyncio
import functools
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from llm import tools_local
from llm.tools_local import ToolRunner, extract_text, fetch_page, function_tools, is_public_url, zhipu_search
from llm.types import LLMConfigError
from tests.llm_fakes import FakeSleep

HTML = """<html><head><title>标题</title><style>.x{color:red}</style><script>var secret=1;</script></head>
<body><nav>导航菜单</nav><h1>GLM-5.3 发布</h1><p>智谱于 2026 年 8 月 26 日发布。</p>
<p>第二段&amp;实体</p><footer>版权</footer></body></html>"""


def _public(host):
    return True


class ExtractTests(unittest.TestCase):
    def test_keeps_body_text_drops_scripts_styles_and_chrome(self):
        text = extract_text(HTML)
        self.assertIn("GLM-5.3 发布", text)
        self.assertIn("8 月 26 日发布", text)
        self.assertIn("第二段&实体", text)
        for junk in ("secret", "color:red", "导航菜单", "版权"):
            self.assertNotIn(junk, text)


class FetchTests(unittest.TestCase):
    def fetch(self, url, body, max_chars=20):
        seen = []

        def get(u):
            seen.append(u)
            return 200, "text/html; charset=utf-8", body

        out = asyncio.run(fetch_page(url, max_chars, get=get, check=lambda u: is_public_url(u, resolve=_public)))
        return out, seen

    def test_truncation_reports_the_original_length(self):
        body = "<p>" + "字" * 100 + "</p>"
        out, _ = self.fetch("https://example.cn/a", body)
        self.assertEqual((len(out["text"]), out["original_chars"], out["truncated"]), (20, 100, True))

    def test_short_page_is_not_marked_truncated(self):
        out, _ = self.fetch("https://example.cn/a", "<p>短</p>")
        self.assertEqual((out["text"], out["truncated"]), ("短", False))

    def test_private_and_non_http_urls_are_refused_without_fetching(self):
        for url in ("http://127.0.0.1:8000/api", "http://localhost/x", "file:///etc/passwd",
                    "http://10.0.0.5/", "http://[::1]/", "http://169.254.169.254/latest"):
            with self.subTest(url):
                out, seen = self.fetch(url, "<p>x</p>")
                self.assertIn("error", out)
                self.assertEqual(seen, [])

    def test_redirects_are_followed_and_each_hop_is_rechecked(self):
        class Resp:
            def __init__(self, location=None, body=b""):
                self.is_redirect = location is not None
                self.headers = {"location": location} if location else {"content-type": "text/html"}
                self.status_code, self.encoding = (302 if location else 200), None
                self.raw = SimpleNamespace(read=lambda n, decode_content: body)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        hops = {"https://a.example/": Resp("/next"), "https://a.example/next": Resp("http://127.0.0.1/admin"),
                "https://b.example/": Resp(body=b'<meta charset="gbk"><p>\xd6\xd0\xce\xc4</p>')}
        session = SimpleNamespace(get=lambda url, **kw: hops[url])
        fake = mock.MagicMock()
        fake.return_value.__enter__.return_value = session
        check = functools.partial(is_public_url, resolve=_public)
        with mock.patch.object(tools_local.requests, "Session", fake):
            blocked = asyncio.run(fetch_page("https://a.example/", 100, check=check))
            ok = asyncio.run(fetch_page("https://b.example/", 100, check=check))
        self.assertIn("127.0.0.1", blocked["error"])
        self.assertEqual(ok["text"], "中文")  # 按页面声明的 gbk 解码

    def test_hostnames_resolving_to_private_addresses_are_refused(self):
        def resolve(host):
            return host != "intranet.example.com"
        self.assertFalse(is_public_url("https://intranet.example.com/", resolve=resolve))
        self.assertTrue(is_public_url("https://example.com/", resolve=resolve))


class SearchTests(unittest.TestCase):
    def test_payload_and_trimmed_results(self):
        sent = []

        def post(url, headers, payload):
            sent.append((url, headers, payload))
            return 200, {"search_result": [{"title": "t", "link": "https://a.cn", "content": "c" * 2000,
                                            "media": "m", "publish_date": "2026-08-26", "icon": "i", "refer": "1"}]}

        out = asyncio.run(zhipu_search("KEY", "长" * 100, 99, "oneMonth", post=post, sleep=FakeSleep()))
        url, headers, payload = sent[0]
        self.assertEqual(url, tools_local.ZHIPU_SEARCH_URL)
        self.assertEqual(headers["Authorization"], "Bearer KEY")
        self.assertEqual((len(payload["search_query"]), payload["search_engine"]), (70, "search_pro"))
        self.assertEqual((payload["count"], payload["search_recency_filter"]), (20, "oneMonth"))
        item = out["results"][0]
        self.assertEqual(set(item), {"title", "link", "content", "media", "publish_date"})
        self.assertLessEqual(len(item["content"]), tools_local.SEARCH_SNIPPET_CHARS)

    def test_concurrency_limit_backs_off(self):
        replies = [(429, {"error": {"code": "1701", "message": "并发超限"}}), (200, {"search_result": []})]
        sleep = FakeSleep()
        out = asyncio.run(zhipu_search("KEY", "q", 5, "noLimit", post=lambda *a: replies.pop(0), sleep=sleep))
        self.assertEqual((out, len(sleep.delays)), ({"results": []}, 1))

    def test_failure_is_reported_to_the_model_not_raised(self):
        out = asyncio.run(zhipu_search("KEY", "q", 5, "noLimit",
                                       post=lambda *a: (401, {"error": {"code": "1000", "message": "bad"}}),
                                       sleep=FakeSleep()))
        self.assertIn("error", out)
        self.assertNotIn("KEY", json.dumps(out))


class RunnerTests(unittest.TestCase):
    def runner(self):
        async def search(query, count, recency):
            return {"results": [query, count, recency]}

        async def fetch(url, max_chars):
            return {"url": url, "max": max_chars}
        return ToolRunner(search=search, fetch=fetch)

    def test_dispatch_defaults_and_counters(self):
        r = self.runner()
        out = json.loads(asyncio.run(r.run("WebSearch", '{"query": "q"}')))
        self.assertEqual(out["results"], ["q", 8, "noLimit"])
        json.loads(asyncio.run(r.run("WebFetch", '{"url": "https://a.cn", "max_chars": 999999}')))
        self.assertEqual((r.searches, r.fetches), (1, 1))

    def test_bad_calls_return_errors_to_the_model(self):
        r = self.runner()
        for name, args in (("Bash", "{}"), ("WebSearch", "not json"), ("WebSearch", '{"q": 1}')):
            with self.subTest(name=name, args=args):
                self.assertIn("error", json.loads(asyncio.run(r.run(name, args))))

    def test_function_tools_only_for_known_names(self):
        self.assertEqual([t["function"]["name"] for t in function_tools(("WebFetch", "WebSearch"))],
                         ["WebFetch", "WebSearch"])
        with self.assertRaisesRegex(LLMConfigError, "Bash"):
            function_tools(("Bash",))


if __name__ == "__main__":
    unittest.main()
