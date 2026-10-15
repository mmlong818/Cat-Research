"""删除任务：任务记录指向的会话目录已经不在了（被手动删除或会话已删除），照样删掉任务记录，不再 404；
审计记录按原设计只追加，不随任务删除。"""
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


class DeleteWithoutWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = TaskStore(os.path.join(self.root, "tasks.db"))
        for p in (mock.patch.object(app_mod, "_store", self.store),
                  mock.patch.object(app_mod, "WORKSPACE_DIR", os.path.join(self.root, "workspace"))):
            p.start()
            self.addCleanup(p.stop)
        os.makedirs(app_mod.WORKSPACE_DIR)
        self.client = TestClient(app_mod.app, base_url="http://127.0.0.1:8000")

    def finished_task(self, task_id: str, session_id: str):
        gone = os.path.join(app_mod.WORKSPACE_DIR, f"session_{session_id}")  # 从未建出或已被删掉
        self.store.reserve(task_id, "问题", 5, session_id=session_id)
        self.store.merge(task_id, status="completed", workspace=gone)
        self.store.start_phase(task_id, 1, "问题澄清")
        self.store.audit(task_id, "task_created", {"question": "问题"})

    def test_task_whose_workspace_is_gone_is_deleted(self):
        self.finished_task("t1", "20261007_075937")
        res = self.client.delete("/api/research/t1", headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIsNone(self.store.get("t1"))
        self.assertEqual(self.store.phases("t1"), [])

    def test_audit_entries_are_kept(self):
        self.finished_task("t2", "20261007_075937")
        self.client.delete("/api/research/t2", headers=HEADERS)
        self.assertEqual([e["kind"] for e in self.store.audit_log(task_id="t2")], ["task_created", "delete_requested"])

    def test_other_sessions_are_left_alone(self):
        other = os.path.join(app_mod.WORKSPACE_DIR, "session_20261003_173109")
        os.makedirs(other)
        self.finished_task("t3", "20261007_075937")
        self.client.delete("/api/research/t3", headers=HEADERS)
        self.assertTrue(os.path.isdir(other))


if __name__ == "__main__":
    unittest.main()
