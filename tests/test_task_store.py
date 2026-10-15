"""E2 任务持久化：状态落 SQLite，重启后仍可查询；并发启动不超过上限。"""
import os
import tempfile
import threading
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from api import app as app_mod
from api import security
from api.db.task_store import TaskStore

HEADERS = {security.TOKEN_HEADER: security.TOKEN}


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "tasks.db")
        self.store = TaskStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_state_survives_new_instance(self):
        self.assertIsNone(self.store.reserve("t1", "问题", limit=2))
        self.store.merge("t1", status="completed", result="报告", scores=[7.5, 8.2])
        reopened = TaskStore(self.path).get("t1")
        self.assertEqual(reopened["status"], "completed")
        self.assertEqual(reopened["result"], "报告")
        self.assertEqual(reopened["scores"], [7.5, 8.2])
        self.assertEqual(reopened["question"], "问题")

    def test_restart_marks_unfinished_interrupted(self):
        self.store.reserve("run", "q", limit=5)
        self.store.merge("run", status="running")
        self.store.reserve("pend", "q", limit=5)
        self.store.reserve("done", "q", limit=5)
        self.store.merge("done", status="completed")
        self.assertEqual(TaskStore(self.path).mark_interrupted(), 2)
        self.assertEqual(self.store.get("run")["status"], "interrupted")
        self.assertEqual(self.store.get("pend")["status"], "interrupted")
        self.assertEqual(self.store.get("done")["status"], "completed")

    def test_concurrent_reserve_respects_limit(self):
        barrier = threading.Barrier(10)
        results = []

        def worker(i):
            barrier.wait()
            results.append(self.store.reserve(f"t{i}", "q", limit=2))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(None), 2)
        self.assertEqual(self.store.active_count(), 2)

    def test_phases_recorded_in_order(self):
        self.store.reserve("t1", "q", limit=1)
        self.store.start_phase("t1", 1, "规划")
        self.store.start_phase("t1", 2, "研究")
        self.store.finish_phase("t1", "failed", "boom")
        phases = self.store.phases("t1")
        self.assertEqual([(p["phase"], p["status"]) for p in phases],
                         [("规划", "completed"), ("研究", "failed")])
        self.assertEqual(phases[1]["error"], "boom")

    def test_delete_removes_task_and_phases(self):
        self.store.reserve("t1", "q", limit=1)
        self.store.start_phase("t1", 1, "规划")
        self.store.delete("t1")
        self.assertIsNone(self.store.get("t1"))
        self.assertEqual(self.store.phases("t1"), [])


class ResearchApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "tasks.db")
        self.patches = [
            mock.patch.object(app_mod, "_store", TaskStore(self.path)),
            mock.patch.object(app_mod, "_run_research_task", lambda *a, **k: None),
        ]
        for p in self.patches:
            p.start()
        self.client = TestClient(app_mod.app, base_url="http://127.0.0.1:8000")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def _start(self):
        return self.client.post("/api/research", json={"question": "q"}, headers=HEADERS)

    def test_pending_tasks_count_toward_limit(self):
        codes = [self._start().status_code for _ in range(app_mod.MAX_CONCURRENT_TASKS + 1)]
        self.assertEqual(codes[-1], 429)
        self.assertTrue(all(c == 200 for c in codes[:-1]))

    def test_status_readable_after_restart(self):
        task_id = self._start().json()["task_id"]
        app_mod._store.merge(task_id, status="completed", result="终稿")
        with mock.patch.object(app_mod, "_store", TaskStore(self.path)):
            res = self.client.get(f"/api/research/{task_id}/result", headers=HEADERS)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["result"], "终稿")


if __name__ == "__main__":
    unittest.main()
