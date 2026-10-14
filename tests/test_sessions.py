"""V6 会话列表合并 task_store 与 workspace（状态/深度/语言/阶段/错误、分页、仅有任务记录的失败任务）与阶段记录接口。"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from api import app as app_mod
from api import security
from api.db.task_store import TaskStore

HEADERS = {security.TOKEN_HEADER: security.TOKEN}


class SessionsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "workspace")
        os.makedirs(self.root)
        self.store = TaskStore(os.path.join(self.tmp, "tasks.db"))
        for p in (mock.patch.object(app_mod, "_store", self.store),
                  mock.patch.object(app_mod, "WORKSPACE_DIR", self.root)):
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(app_mod.app, base_url="http://127.0.0.1:8000")

    def workspace(self, sid, created_at, status="completed", **meta):
        path = os.path.join(self.root, f"session_{sid}")
        os.makedirs(path)
        with open(os.path.join(path, "00_session.json"), "w", encoding="utf-8") as f:
            json.dump({"session_id": sid, "created_at": created_at, "question": f"问题 {sid}", "status": status,
                       **meta}, f, ensure_ascii=False)
        return path

    def task(self, task_id, status, sid=None, path=None, error=None, phases=(), replay=False, **state):
        """登记一个任务：phases 为 (阶段号, 名称) 列表，最后一个阶段随任务状态收尾。"""
        self.store.reserve(task_id, f"任务 {task_id}", limit=99, session_id=sid if replay else None, **state)
        if sid and not replay:
            self.store.attach_session(task_id, sid, path)
        for num, name in phases:
            self.store.start_phase(task_id, num, name)
        self.store.merge(task_id, status=status, error=error)
        if phases and status != "running":
            self.store.finish_phase(task_id, status, error)

    def sessions(self, **params):
        res = self.client.get("/api/sessions", params=params, headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def by_id(self, data):
        return {s["session_id"] or s["task_id"]: s for s in data["sessions"]}


class SessionListTests(SessionsTestCase):
    def test_completed_session_keeps_legacy_fields_and_adds_task_info(self):
        path = self.workspace("20261001_000001", "2026-10-01T00:00:01", final_score=8.1, total_cycles=3,
                              language="en", resolved_params={"depth": "deep"})
        self.task("t1", "completed", "20261001_000001", path, phases=[(6, "评审优化")])
        s = self.by_id(self.sessions())["20261001_000001"]
        self.assertEqual((s["question"], s["status"], s["created_at"], s["final_score"], s["total_cycles"]),
                         ("问题 20261001_000001", "completed", "2026-10-01T00:00:01", 8.1, 3))
        self.assertEqual((s["task_id"], s["depth"], s["language"], s["error"]), ("t1", "deep", "en", None))
        self.assertEqual((s["current_phase"], s["phase_key"]), ("评审优化", "improve"))

    def test_failed_session_shows_status_error_and_failing_phase(self):
        path = self.workspace("20261001_000002", "2026-10-01T00:00:02", status="researching")
        self.task("t2", "failed", "20261001_000002", path, error="LLM 超时", phases=[(2, "研究规划"), (3, "网络研究")])
        s = self.by_id(self.sessions())["20261001_000002"]
        self.assertEqual((s["status"], s["error"], s["phase_key"]), ("failed", "LLM 超时", "research"))

    def test_failed_task_without_workspace_is_listed_by_task_id(self):
        self.task("t3", "failed", error="CLI 不可用", depth="quick", language="en")
        s = self.by_id(self.sessions())["t3"]
        self.assertEqual((s["session_id"], s["task_id"], s["status"], s["error"]), ("", "t3", "failed", "CLI 不可用"))
        self.assertEqual((s["depth"], s["language"], s["question"]), ("quick", "en", "任务 t3"))
        self.assertTrue(s["created_at"])

    def test_active_task_is_running_and_stale_workspace_is_interrupted(self):
        path = self.workspace("20261001_000004", "2026-10-01T00:00:04", status="writing")
        self.task("t4", "running", "20261001_000004", path, phases=[(5, "初稿写作")])
        self.workspace("20261001_000005", "2026-10-01T00:00:05", status="writing")  # 没有任务记录，也没写完
        self.workspace("20261001_000006", "2026-10-01T00:00:06", status="stopped")
        got = self.by_id(self.sessions())
        self.assertEqual(got["20261001_000004"]["status"], "running")
        self.assertEqual((got["20261001_000005"]["status"], got["20261001_000005"]["task_id"]), ("interrupted", None))
        self.assertEqual(got["20261001_000006"]["status"], "stopped")

    def test_latest_task_decides_status_for_replayed_session(self):
        path = self.workspace("20261001_000007", "2026-10-01T00:00:07")
        self.task("t7a", "completed", "20261001_000007", path, phases=[(6, "评审优化")])
        self.task("t7b", "failed", "20261001_000007", error="重放失败", phases=[(6, "评审优化")], replay=True)
        s = self.by_id(self.sessions())["20261001_000007"]
        self.assertEqual((s["task_id"], s["status"], s["error"]), ("t7b", "failed", "重放失败"))

    def test_task_whose_session_was_deleted_is_not_listed(self):
        self.task("t8", "completed", "20261001_000008", os.path.join(self.root, "session_20261001_000008"))
        self.assertEqual(self.sessions()["sessions"], [])

    def test_legacy_session_defaults_to_zh_and_unknown_depth(self):
        self.workspace("20261001_000009", "2026-10-01T00:00:09")
        s = self.by_id(self.sessions())["20261001_000009"]
        self.assertEqual((s["language"], s["depth"], s["status"]), ("zh", None, "completed"))

    def test_newest_first_and_pagination(self):
        for i in range(1, 6):
            self.workspace(f"2026100{i}_000000", f"2026-10-0{i}T00:00:00")
        everything = self.sessions()
        self.assertEqual((everything["total"], everything["limit"], everything["offset"]), (5, 50, 0))
        ids = [s["session_id"] for s in everything["sessions"]]
        self.assertEqual(ids, sorted(ids, reverse=True))
        page = self.sessions(limit=2, offset=1)
        self.assertEqual([s["session_id"] for s in page["sessions"]], ids[1:3])
        self.assertEqual(page["total"], 5)
        self.assertEqual(self.sessions(offset=9)["sessions"], [])

    def test_task_only_entry_sorts_by_creation_time_and_lists_beyond_20(self):
        for i in range(25):
            self.workspace(f"20260901_0000{i:02d}", f"2026-09-01T00:00:{i:02d}")
        self.task("t9", "failed", error="x")
        data = self.sessions(limit=100)
        self.assertEqual(data["total"], 26)  # 不再只返回前 20 条
        self.assertEqual(data["sessions"][0]["task_id"], "t9")  # 最新创建的任务排最前

    def test_invalid_paging_is_rejected(self):
        for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
            res = self.client.get("/api/sessions", params=params, headers=HEADERS)
            self.assertEqual(res.status_code, 422, params)

    def test_entry_carries_cycles_and_elapsed_from_session_meta_without_cost(self):
        self.workspace("20261001_000012", "2026-10-01T00:00:12", total_cycles=5, elapsed_seconds=4073,
                       token_usage={"total_input": 13378092, "cost_usd": 31.553})
        s = self.by_id(self.sessions())["20261001_000012"]
        self.assertEqual((s["total_cycles"], s["elapsed_seconds"]), (5, 4073))
        self.assertNotIn("cost_usd", s)  # 旧会话里残留的 cost_usd 不再透出

    def test_entry_without_usage_or_with_broken_usage_has_null_stats(self):
        self.workspace("20261001_000013", "2026-10-01T00:00:13")
        self.workspace("20261001_000014", "2026-10-01T00:00:14", token_usage="坏的")
        got = self.by_id(self.sessions())
        for sid in ("20261001_000013", "20261001_000014"):
            s = got[sid]
            self.assertEqual((s["total_cycles"], s["elapsed_seconds"]), (None, None), sid)
            self.assertNotIn("cost_usd", s)

    def test_task_only_entry_has_null_elapsed(self):
        self.task("t10", "failed", error="x")
        s = self.by_id(self.sessions())["t10"]
        self.assertIsNone(s["elapsed_seconds"])
        self.assertNotIn("cost_usd", s)

    def test_entry_carries_final_draft_and_citations_from_session_meta(self):
        """卷宗封面要写「终稿取第 N 版、引用违规、带数字句子的挂声明比例」，这些只在 00_session.json 里。"""
        self.workspace("20261001_000015", "2026-10-01T00:00:15", final_draft=4, best_scored_draft=3,
                       citations={"cited_claims": 251, "violations": 0, "numeric_coverage": 0.753})
        s = self.by_id(self.sessions())["20261001_000015"]
        self.assertEqual((s["final_draft"], s["best_scored_draft"]), (4, 3))
        self.assertEqual(s["citations"], {"cited_claims": 251, "violations": 0, "numeric_coverage": 0.753})

    def test_partial_citations_fill_missing_keys_with_null(self):
        self.workspace("20261001_000016", "2026-10-01T00:00:16", final_draft=0, citations={"cited_claims": 12})
        s = self.by_id(self.sessions())["20261001_000016"]
        self.assertEqual((s["final_draft"], s["best_scored_draft"]), (0, None))
        self.assertEqual(s["citations"], {"cited_claims": 12, "violations": None, "numeric_coverage": None})

    def test_missing_or_broken_final_fields_are_null(self):
        self.workspace("20261001_000017", "2026-10-01T00:00:17")
        self.workspace("20261001_000018", "2026-10-01T00:00:18", citations="坏的")
        self.task("t11", "failed", error="x")
        got = self.by_id(self.sessions())
        for key in ("20261001_000017", "20261001_000018", "t11"):
            s = got[key]
            self.assertEqual((s["final_draft"], s["best_scored_draft"], s["citations"]), (None, None, None), key)

    def test_in_progress_session_without_active_task_is_interrupted(self):
        """档案柜：00_session.json 还停在改进等进行中的状态，但任务库里已没有对应的活动任务 → 已中断（可续办）。"""
        self.workspace("20261001_000019", "2026-10-01T00:00:19", status="improving")  # 任务库里没有记录
        path = self.workspace("20261001_000020", "2026-10-01T00:00:20", status="improving")
        self.task("t12", "deleted", "20261001_000020", path)  # 只剩已删除的任务记录
        got = self.by_id(self.sessions())
        for sid in ("20261001_000019", "20261001_000020"):
            self.assertEqual(got[sid]["status"], "interrupted", sid)

    def test_entry_carries_overall_confidence_from_confidence_report(self):
        """档案柜每行要显示可信度：取 08_verification/confidence_report.json 的 overall_confidence。"""
        path = self.workspace("20261001_000021", "2026-10-01T00:00:21")
        os.makedirs(os.path.join(path, "08_verification"))
        with open(os.path.join(path, "08_verification", "confidence_report.json"), "w", encoding="utf-8") as f:
            json.dump({"overall_confidence": 0.689, "confidence_level": "medium"}, f)
        broken = self.workspace("20261001_000022", "2026-10-01T00:00:22")
        os.makedirs(os.path.join(broken, "08_verification"))
        with open(os.path.join(broken, "08_verification", "confidence_report.json"), "w", encoding="utf-8") as f:
            f.write("{坏的")
        self.workspace("20261001_000023", "2026-10-01T00:00:23")
        self.task("t13", "failed", error="x")
        got = self.by_id(self.sessions())
        self.assertEqual(got["20261001_000021"]["confidence"], 0.689)
        for key in ("20261001_000022", "20261001_000023", "t13"):
            self.assertIsNone(got[key]["confidence"], key)

    def test_question_is_listed_in_full(self):
        """档案柜要显示完整问题，不能在接口里截断。"""
        question = "固态电池" * 40
        self.workspace("20261001_000024", "2026-10-01T00:00:24", question=question)
        self.assertEqual(self.by_id(self.sessions())["20261001_000024"]["question"], question)


class ReviewsApiTests(SessionsTestCase):
    """卷宗「过程」页：每轮评审的 7 维评分、平均分、优点、关键问题与下一版要改的点。"""

    SCORES = {"completeness": 7, "accuracy": 7, "depth": 7.5, "clarity": 8, "usefulness": 7.5, "sources": 6,
              "simplicity": 6.5}

    def review(self, path, n, **extra):
        os.makedirs(os.path.join(path, "07_reviews"), exist_ok=True)
        data = {"cycle": n, "scores": self.SCORES, "average_score": 7.07, "strengths": ["口径清楚"],
                "critical_issues": [{"issue": "来源弱", "severity": "high", "suggestion": "换一手来源"}],
                "priority_improvements": ["补现代汽车"], "overall_assessment": "合格", "missing_content": ["卫蓝"],
                **extra}
        with open(os.path.join(path, "07_reviews", f"review_{n}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def reviews(self, sid):
        res = self.client.get(f"/api/sessions/{sid}/reviews", headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["reviews"]

    def test_lists_rounds_in_numeric_order_with_requested_fields(self):
        path = self.workspace("20261001_000020", "2026-10-01T00:00:20")
        for n in (10, 2, 1):
            self.review(path, n, average_score=7.0 + n / 100)
        got = self.reviews("20261001_000020")
        self.assertEqual([r["cycle"] for r in got], [1, 2, 10])
        self.assertEqual(set(got[0]), {"cycle", "scores", "average_score", "strengths", "critical_issues",
                                        "priority_improvements"})
        self.assertEqual((got[0]["scores"], got[0]["average_score"]), (self.SCORES, 7.01))
        self.assertEqual(got[0]["critical_issues"][0]["severity"], "high")
        self.assertEqual((got[0]["strengths"], got[0]["priority_improvements"]), (["口径清楚"], ["补现代汽车"]))

    def test_cycle_falls_back_to_file_number_and_missing_lists_are_empty(self):
        path = self.workspace("20261001_000021", "2026-10-01T00:00:21")
        os.makedirs(os.path.join(path, "07_reviews"))
        with open(os.path.join(path, "07_reviews", "review_3.json"), "w", encoding="utf-8") as f:
            json.dump({"scores": self.SCORES, "average_score": 7.5}, f)
        (r,) = self.reviews("20261001_000021")
        self.assertEqual((r["cycle"], r["strengths"], r["critical_issues"], r["priority_improvements"]),
                         (3, [], [], []))

    def test_skips_broken_and_unrelated_files(self):
        path = self.workspace("20261001_000022", "2026-10-01T00:00:22")
        self.review(path, 1)
        with open(os.path.join(path, "07_reviews", "review_2.json"), "w", encoding="utf-8") as f:
            f.write("{坏的")
        with open(os.path.join(path, "07_reviews", "review_x.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        with open(os.path.join(path, "07_reviews", "notes.txt"), "w", encoding="utf-8") as f:
            f.write("x")
        self.assertEqual([r["cycle"] for r in self.reviews("20261001_000022")], [1])

    def test_session_without_reviews_is_empty_and_unknown_session_is_404(self):
        self.workspace("20261001_000023", "2026-10-01T00:00:23")
        self.assertEqual(self.reviews("20261001_000023"), [])
        res = self.client.get("/api/sessions/nope/reviews", headers=HEADERS)
        self.assertEqual(res.status_code, 404)

    def test_requires_api_token(self):
        self.workspace("20261001_000024", "2026-10-01T00:00:24")
        res = self.client.get("/api/sessions/20261001_000024/reviews")
        self.assertEqual(res.status_code, 401)


class PhaseLogTests(SessionsTestCase):
    def test_lists_phases_per_task_oldest_first_with_failure_reason(self):
        path = self.workspace("20261001_000010", "2026-10-01T00:00:10")
        self.task("p1", "completed", "20261001_000010", path, phases=[(1, "问题澄清"), (2, "研究规划")])
        self.task("p2", "failed", "20261001_000010", error="事实核查崩溃",
                  phases=[(3.5, "来源验证"), (3.8, "事实核查")], replay=True, replay_from="sources")
        log = self.client.get("/api/sessions/20261001_000010/phase-log", headers=HEADERS).json()
        self.assertEqual([t["task_id"] for t in log["tasks"]], ["p1", "p2"])
        first, second = log["tasks"]
        self.assertEqual([(p["phase_key"], p["status"]) for p in first["phases"]],
                         [("clarify", "completed"), ("plan", "completed")])
        self.assertEqual((second["status"], second["replay_from"], second["error"]),
                         ("failed", "sources", "事实核查崩溃"))
        sources, ledger = second["phases"]
        self.assertEqual((sources["phase_key"], sources["status"]), ("sources", "completed"))
        self.assertEqual((ledger["phase_key"], ledger["status"], ledger["error"]), ("ledger", "failed", "事实核查崩溃"))
        self.assertTrue(ledger["started_at"] and ledger["finished_at"])

    def test_accepts_a_task_id_for_sessions_that_never_got_a_workspace(self):
        self.task("p3", "failed", error="启动失败", phases=[(1, "问题澄清")])
        log = self.client.get("/api/sessions/p3/phase-log", headers=HEADERS).json()
        self.assertEqual([t["task_id"] for t in log["tasks"]], ["p3"])
        self.assertEqual(log["tasks"][0]["phases"][0]["error"], "启动失败")

    def test_session_without_task_records_has_an_empty_log_and_unknown_id_is_404(self):
        self.workspace("20261001_000011", "2026-10-01T00:00:11")
        res = self.client.get("/api/sessions/20261001_000011/phase-log", headers=HEADERS)
        self.assertEqual((res.status_code, res.json()["tasks"]), (200, []))
        res = self.client.get("/api/sessions/nope/phase-log", headers=HEADERS)
        self.assertEqual(res.status_code, 404)

    def test_audit_falls_back_to_task_id(self):
        self.task("p4", "failed", error="启动失败")
        self.store.audit("p4", "task_finished", {"status": "failed"})
        res = self.client.get("/api/sessions/p4/audit", headers=HEADERS)
        self.assertEqual([e["kind"] for e in res.json()["entries"]], ["task_finished"])


class TaskCreationStateTests(unittest.TestCase):
    """新任务把 depth/language 记进任务状态，供没有 workspace 的失败任务展示。"""

    def test_direct_task_state_has_depth_and_language(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        store = TaskStore(os.path.join(tmp, "tasks.db"))
        with mock.patch.object(app_mod, "_store", store), \
                mock.patch.object(app_mod, "_run_research_task", lambda *a, **k: None):
            client = TestClient(app_mod.app, base_url="http://127.0.0.1:8000")
            tid = client.post("/api/research", json={"question": "q", "depth": "deep", "language": "en"},
                              headers=HEADERS).json()["task_id"]
        self.assertEqual((store.get(tid)["depth"], store.get(tid)["language"]), ("deep", "en"))


if __name__ == "__main__":
    unittest.main()
