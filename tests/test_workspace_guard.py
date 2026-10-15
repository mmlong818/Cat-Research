"""已删除的工作区不得被写函数重新建出来：标记后各写盘入口都拒绝（抛 WorkspaceDeleted / 日志静默跳过），
没有标记的目录（包括正在首次创建的新工作区）照常写。"""
import os
import shutil
import tempfile
import unittest

import orchestrator as orch_mod
from agents.llm_agent import write_json_atomic, write_text_atomic
from api.db.task_store import TaskStore
from research.checkpoints import Checkpoints
from research.ledger import Ledger
from tools.file_tools import (
    WorkspaceDeleted,
    append_to_log,
    is_workspace_deleted,
    mark_workspace_deleted,
    write_file,
    write_json,
)
from tools.verification_registry import save_registry


class WorkspaceGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ws = os.path.join(self.tmp, "session_20261003_000001")

    def path(self, *parts) -> str:
        return os.path.join(self.ws, *parts)

    def test_unmarked_workspace_is_created_on_first_write(self):
        write_json_atomic(self.path("03_plan.json"), {"a": 1})
        write_text_atomic(self.path("04_research", "round_1.md"), "x")
        write_file(self.path("06_drafts", "draft_0.md"), "x")
        write_json(self.path("00_session.json"), {"a": 1})
        self.assertTrue(append_to_log(self.path("research_log.txt"), "hi"))
        ledger = Ledger.load(self.ws)
        ledger.save()
        save_registry(self.ws, {})
        for rel in ("03_plan.json", "04_research/round_1.md", "06_drafts/draft_0.md", "00_session.json",
                    "research_log.txt", "08_verification/ledger.json"):
            self.assertTrue(os.path.exists(self.path(rel)), rel)

    def test_marked_workspace_refuses_every_writer_and_stays_absent(self):
        mark_workspace_deleted(self.ws)
        self.assertTrue(is_workspace_deleted(self.path("08_verification", "ledger.json")))
        writers = {
            "write_json_atomic": lambda: write_json_atomic(self.path("03_plan.json"), {}),
            "write_text_atomic": lambda: write_text_atomic(self.path("04_research", "r.md"), "x"),
            "write_file": lambda: write_file(self.path("09_final.md"), "x"),
            "write_json": lambda: write_json(self.path("00_session.json"), {}),
            "ledger.save": lambda: Ledger.load(self.ws).save(),
            "save_registry": lambda: save_registry(self.ws, {}),
            "checkpoints.save": lambda: Checkpoints(self.ws).save("clarify", {}, "h"),
        }
        for name, write in writers.items():
            with self.assertRaises(WorkspaceDeleted, msg=name):
                write()
        self.assertFalse(append_to_log(self.path("research_log.txt"), "late log"))
        self.assertFalse(os.path.exists(self.ws), "已删除的工作区被重新建出来了")

    def test_other_workspaces_are_not_affected(self):
        mark_workspace_deleted(self.ws)
        sibling = f"{self.ws}2"  # 只是名字以它开头
        write_json_atomic(os.path.join(sibling, "03_plan.json"), {})
        self.assertTrue(os.path.exists(os.path.join(sibling, "03_plan.json")))

    def test_orchestrator_status_update_on_a_deleted_workspace_writes_nothing(self):
        events = []
        o = orch_mod.ResearchOrchestrator(progress_callback=lambda kind, data: events.append(kind))
        o.workspace = self.ws
        mark_workspace_deleted(self.ws)
        o._update_status("stopped")
        o.log_file = self.path("research_log.txt")
        o._log("late log")
        self.assertFalse(os.path.exists(self.ws))
        self.assertEqual(events, [])


class StartPhaseOfDeletedTaskTests(unittest.TestCase):
    def test_start_phase_after_the_task_was_deleted_leaves_no_row(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        store = TaskStore(os.path.join(tmp, "tasks.db"))
        store.reserve("t1", "q", limit=1)
        store.start_phase("t1", 1, "规划")
        store.delete("t1")
        store.start_phase("t1", 2, "研究")  # 线程晚于删除接口才报告阶段
        self.assertEqual(store.phases("t1"), [])


if __name__ == "__main__":
    unittest.main()
