"""用户停止与任务失败分开：停止（含全部停止、删除）发 stopped 事件，不再复用 error；error 只表示失败。"""
import os
import shutil
import tempfile
import threading
import unittest
from queue import Empty
from unittest import mock

from fastapi.testclient import TestClient

from api import app as app_mod
from api import security
from api.db.task_store import TaskStore
from api.events import BroadcastRegistry

HEADERS = {security.TOKEN_HEADER: security.TOKEN}


class StopEventTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = TaskStore(os.path.join(self.tmp, "tasks.db"))
        self.events = BroadcastRegistry()
        for p in (mock.patch.object(app_mod, "_store", self.store),
                  mock.patch.object(app_mod, "_events", self.events),
                  mock.patch.object(app_mod, "WORKSPACE_DIR", self.tmp)):
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(app_mod.app, base_url="http://127.0.0.1:8000")

    def running_task(self, task_id: str):
        """登记一个运行中的任务（没有后台线程），返回订阅它事件的队列。"""
        self.store.reserve(task_id, "问题", 5)
        self.store.merge(task_id, status="running")
        for registry in (app_mod._task_stop_events, app_mod._task_pause_events):
            registry[task_id] = threading.Event()
            self.addCleanup(registry.pop, task_id, None)
        _, queue = self.events.create(task_id).subscribe()
        return queue

    @staticmethod
    def drain(queue) -> list:
        out: list = []
        while True:
            try:
                event = queue.get_nowait()
            except Empty:
                return out
            out.append((event["type"], event["data"]))

    def test_stop_emits_stopped_not_error(self):
        queue = self.running_task("t1")
        self.assertEqual(self.client.post("/api/research/t1/stop", headers=HEADERS).status_code, 200)
        self.assertEqual(self.drain(queue), [("stopped", {"reason": "user"})])
        self.assertTrue(app_mod._task_stop_events["t1"].is_set())

    def test_stop_all_emits_stopped_for_every_running_task(self):
        queues = {tid: self.running_task(tid) for tid in ("t2", "t3")}
        res = self.client.post("/api/research/stop-all", headers=HEADERS)
        self.assertEqual(res.json()["stopped"], 2)
        for queue in queues.values():
            self.assertEqual(self.drain(queue), [("stopped", {"reason": "user"})])

    def test_delete_emits_stopped_with_reason_deleted(self):
        queue = self.running_task("t4")
        self.assertEqual(self.client.delete("/api/research/t4", headers=HEADERS).status_code, 200)
        self.assertEqual(self.drain(queue), [("stopped", {"reason": "deleted"}), ("end", {})])
        self.assertIsNone(self.store.get("t4"))


if __name__ == "__main__":
    unittest.main()
