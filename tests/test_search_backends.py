"""联网搜索后端：博查 / Tavily 的请求与解析、缺字段宽容、限流退避、额度与 Key 无效不重试、recency 映射；
后端注册表与所选后端解析。"""
import asyncio
import json
import os
import unittest
from unittest import mock

import requests  # type: ignore[import-untyped]  # 未安装 types-requests 存根

from llm import keys
from llm.search import BACKENDS, base, bocha, get_search, selected_backend, tavily
from llm.types import LLMConfigError
from tests.llm_fakes import SECRET, FakeSleep

BOCHA_OK = {"code": 200, "data": {"webPages": {"value": [
    {"name": "标题", "url": "https://a.cn/x", "siteName": "甲站", "datePublished": "2026-08-26T08:00:00+08:00",
     "summary": "摘" * 2000, "snippet": "短"}]}}}


class Poster:
    """按剧本依次返回 (状态码, JSON)，记录每次请求。"""

    def __init__(self, *replies) -> None:
        self.replies = list(replies)
        self.sent: list[tuple[str, dict, dict]] = []

    def __call__(self, url, headers, payload, **_):
        self.sent.append((url, headers, payload))
        return self.replies.pop(0)


def run(coro):
    return asyncio.run(coro)


class _Isolated(unittest.TestCase):
    def setUp(self) -> None:
        for p in (mock.patch.object(keys, "stored_config", return_value={}),
                  mock.patch.dict(os.environ, {"BOCHA_BASE_URL": "", "SEARCH_BACKEND": ""})):
            p.start()
            self.addCleanup(p.stop)
        self.sleep = FakeSleep()


class BochaTests(_Isolated):
    def search(self, poster, query="q", count=8, recency="noLimit"):
        return run(bocha.bocha_search("KEY", query, count, recency, post=poster, sleep=self.sleep))

    def test_request_shape_and_parsed_results(self):
        poster = Poster((200, BOCHA_OK))
        out = self.search(poster, "长" * 100, 99, "oneWeek")
        url, headers, payload = poster.sent[0]
        self.assertEqual(url, "https://api.bochaai.com/v1/web-search")
        self.assertEqual(headers["Authorization"], "Bearer KEY")
        self.assertEqual(payload, {"query": "长" * 100, "count": 50, "freshness": "oneWeek", "summary": True})
        item = out["results"][0]
        self.assertEqual((item["title"], item["link"], item["media"]), ("标题", "https://a.cn/x", "甲站"))
        self.assertEqual(item["publish_date"], "2026-08-26T08:00:00+08:00")
        self.assertEqual(len(item["content"]), base.SEARCH_SNIPPET_CHARS)  # 取 summary 并截断
        self.assertEqual(set(item), {"title", "link", "media", "publish_date", "content"})

    def test_missing_fields_are_tolerated(self):
        body = {"data": {"webPages": {"value": [{"url": "https://b.cn"}, {"name": "n", "snippet": "片段"}, "脏数据"]}}}
        out = self.search(Poster((200, body)))
        self.assertEqual(out["results"], [{"link": "https://b.cn"}, {"title": "n", "content": "片段"}])
        for empty in ({"code": 200}, {"code": 200, "data": None}, {"data": {"webPages": None}}, {"data": {}}):
            self.assertEqual(self.search(Poster((200, empty))), {"results": []}, empty)

    def test_recency_is_passed_through_and_unknown_falls_back(self):
        for recency in ("oneDay", "oneWeek", "oneMonth", "oneYear", "noLimit"):
            poster = Poster((200, BOCHA_OK))
            self.search(poster, recency=recency)
            self.assertEqual(poster.sent[0][2]["freshness"], recency)
        poster = Poster((200, BOCHA_OK))
        self.search(poster, recency="lastCentury")
        self.assertEqual(poster.sent[0][2]["freshness"], "noLimit")
        self.search(poster := Poster((200, BOCHA_OK)), count=0)
        self.assertEqual(poster.sent[0][2]["count"], 1)

    def test_rate_limit_and_server_errors_back_off_then_succeed(self):
        poster = Poster((429, {"code": 429, "msg": "请求过快"}), (503, {}), (200, BOCHA_OK))
        out = self.search(poster)
        self.assertEqual((len(out["results"]), len(self.sleep.delays), len(poster.sent)), (1, 2, 3))

    def test_exhausted_retries_report_an_error_instead_of_raising(self):
        out = self.search(Poster(*[(500, {})] * 4))
        self.assertIn("暂时不可用", out["error"])
        self.assertEqual(len(self.sleep.delays), 3)

    def test_invalid_key_no_balance_and_bad_params_are_not_retried(self):
        for status, msg in ((401, "Invalid API KEY"), (403, "余额不足"), (400, "参数错误")):
            with self.subTest(status):
                poster = Poster((status, {"code": status, "msg": msg}))
                out = self.search(poster)
                self.assertIn(str(status), out["error"])
                self.assertIn(msg, out["error"])
                self.assertEqual(len(poster.sent), 1)
        self.assertEqual(self.sleep.delays, [])

    def test_outer_code_other_than_200_is_a_failure_even_with_http_200(self):
        out = self.search(Poster((200, {"code": 403, "msg": "余额不足", "data": {"webPages": {"value": [{}]}}})))
        self.assertIn("余额不足", out["error"])
        poster = Poster((200, {"code": 429, "msg": "限流"}), (200, BOCHA_OK))
        self.assertEqual(len(self.search(poster)["results"]), 1)  # 外层 429 同样退避重试
        self.assertEqual(len(self.sleep.delays), 1)

    def test_base_url_can_be_overridden_by_config_or_environment(self):
        with mock.patch.dict(os.environ, {"BOCHA_BASE_URL": "https://env.example/search"}):
            self.assertEqual(bocha.search_url(), "https://env.example/search")
            with mock.patch.object(keys, "stored_config",
                                   return_value={"search": {"bocha_base_url": "https://cfg.example/s"}}):
                self.assertEqual(bocha.search_url(), "https://cfg.example/s")  # user_config 优先于环境变量

    def test_network_exception_is_reported_without_details(self):
        def boom(*a):
            raise requests.ConnectionError("dns failure for host")
        out = self.search(boom)
        self.assertEqual(out, {"error": "搜索请求失败：ConnectionError"})

    def test_default_transport_ignores_the_system_proxy(self):
        fake = mock.MagicMock()
        fake.return_value.__enter__.return_value.post.return_value = mock.Mock(
            status_code=200, json=lambda: {"code": 200})
        with mock.patch.object(base.requests, "Session", fake):
            base.http_post("https://x", {}, {})
        self.assertIs(fake.return_value.__enter__.return_value.trust_env, False)


TAVILY_OK = {"results": [
    {"title": "T", "url": "https://www.example.com/a/b", "content": "c" * 2000, "published_date": "2026-08-26",
     "score": 0.9, "raw_content": None}]}


class TavilyTests(_Isolated):
    def search(self, poster, query="q", count=8, recency="noLimit"):
        return run(tavily.tavily_search("KEY", query, count, recency, post=poster, sleep=self.sleep))

    def test_request_shape_and_parsed_results(self):
        poster = Poster((200, TAVILY_OK))
        out = self.search(poster, "q", 99, "noLimit")
        url, headers, payload = poster.sent[0]
        self.assertEqual(url, "https://api.tavily.com/search")
        self.assertEqual(headers["Authorization"], "Bearer KEY")
        self.assertEqual(payload, {"query": "q", "max_results": 20, "search_depth": "basic",
                                   "include_published_date": True})
        item = out["results"][0]
        self.assertEqual((item["title"], item["link"], item["media"]), ("T", "https://www.example.com/a/b",
                                                                        "example.com"))
        self.assertEqual(item["publish_date"], "2026-08-26")
        self.assertEqual(len(item["content"]), base.SEARCH_SNIPPET_CHARS)
        self.assertEqual(set(item), {"title", "link", "media", "publish_date", "content"})

    def test_recency_mapping(self):
        cases = {"oneDay": "day", "oneWeek": "week", "oneMonth": "month", "oneYear": "year"}
        for recency, time_range in cases.items():
            poster = Poster((200, TAVILY_OK))
            self.search(poster, recency=recency)
            self.assertEqual(poster.sent[0][2]["time_range"], time_range, recency)
        for recency in ("noLimit", "bogus"):
            poster = Poster((200, TAVILY_OK))
            self.search(poster, recency=recency)
            self.assertNotIn("time_range", poster.sent[0][2], recency)

    def test_missing_fields_are_tolerated(self):
        out = self.search(Poster((200, {"results": [{"url": "not a url"}, {"title": "仅标题"}, None]})))
        self.assertEqual(out["results"], [{"link": "not a url"}, {"title": "仅标题"}])
        self.assertEqual(self.search(Poster((200, {}))), {"results": []})

    def test_rate_limit_backs_off_then_succeeds(self):
        poster = Poster((429, {"detail": {"error": "Too many requests"}}), (502, {}), (200, TAVILY_OK))
        out = self.search(poster)
        self.assertEqual((len(out["results"]), len(self.sleep.delays)), (1, 2))

    def test_key_quota_and_parameter_errors_are_not_retried(self):
        cases = ((401, {"detail": {"error": "Unauthorized: missing or invalid API key."}}),
                 (432, {"detail": {"error": "plan limit exceeded"}}), (433, {"detail": {"error": "pay-as-you-go"}}),
                 (400, {"detail": {"error": "Query is too short"}}), (422, {"detail": "validation error"}))
        for status, body in cases:
            with self.subTest(status):
                poster = Poster((status, body))
                out = self.search(poster)
                self.assertIn(f"HTTP {status}", out["error"])
                self.assertEqual(len(poster.sent), 1)
        self.assertEqual(self.sleep.delays, [])

    def test_default_transport_allows_the_system_proxy(self):
        fake = mock.MagicMock()
        fake.return_value.__enter__.return_value.post.return_value = mock.Mock(
            status_code=200, json=lambda: TAVILY_OK)
        with mock.patch.object(base.requests, "Session", fake):
            out = run(tavily.tavily_search("KEY", "q", sleep=self.sleep))
        self.assertIs(fake.return_value.__enter__.return_value.trust_env, True)
        self.assertEqual(len(out["results"]), 1)


class RegistryTests(_Isolated):
    def test_backends_and_labels(self):
        self.assertEqual(list(BACKENDS), ["zhipu", "bocha", "tavily"])
        self.assertEqual([b.label for b in BACKENDS.values()], ["智谱搜索", "博查搜索", "Tavily 搜索"])

    def test_selected_backend_config_beats_environment_beats_default(self):
        self.assertEqual(selected_backend(), "zhipu")
        with mock.patch.dict(os.environ, {"SEARCH_BACKEND": "tavily"}):
            self.assertEqual(selected_backend(), "tavily")
            with mock.patch.object(keys, "stored_config", return_value={"search": {"backend": "bocha"}}):
                self.assertEqual(selected_backend(), "bocha")

    def test_get_search_binds_the_key_and_reports_label(self):
        with mock.patch.object(keys, "stored_config", return_value={"bocha_api_key": SECRET}):
            fn, label = get_search("bocha", sleep=self.sleep)
        self.assertEqual(label, "博查搜索")
        poster = Poster((200, BOCHA_OK))
        with mock.patch.object(bocha, "http_post", poster):
            out = run(fn("q", 3, "oneDay"))
        self.assertEqual(poster.sent[0][1]["Authorization"], f"Bearer {SECRET}")
        self.assertEqual(len(out["results"]), 1)

    def test_errors_never_echo_the_key(self):
        with mock.patch.object(keys, "stored_config", return_value={"tavily_api_key": SECRET}):
            fn, _ = get_search("tavily", sleep=self.sleep)
        poster = Poster((401, {"detail": {"error": f"bad key {SECRET}"}}))
        with mock.patch.object(tavily, "http_post", poster):
            out = run(fn("q", 3, "noLimit"))
        self.assertIn("error", out)
        self.assertNotIn(SECRET, json.dumps(out))

    def test_unknown_backend_and_missing_key_are_config_errors(self):
        with self.assertRaisesRegex(LLMConfigError, "未知联网搜索后端"):
            get_search("duckduckgo")
        with self.assertRaisesRegex(LLMConfigError, "BOCHA_API_KEY"):
            get_search("bocha")


if __name__ == "__main__":
    unittest.main()
