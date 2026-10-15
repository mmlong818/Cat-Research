"""E4 审计日志：用户输入与关键决策（检查点、停止原因、最终稿选择）按任务/会话可追溯，且不随重放回滚或任务删除而丢失。"""
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

import orchestrator as orch_mod
from api import app as app_mod
from api import security
from api.db.task_store import TaskStore
from research.checkpoints import PHASES
from tests.test_orchestrator import FakeAgents

HEADERS = {security.TOKEN_HEADER: security.TOKEN}
_REAL_RUN = app_mod._run_research_task


class AuditStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = TaskStore(os.path.join(self.tmp, "tasks.db"))

    def test_entries_before_session_are_backfilled_and_survive_delete(self):
        self.store.reserve("t1", "q", limit=2)
        self.store.audit("t1", "task_created", {"question": "q"})
        self.store.attach_session("t1", "S1", "/ws/session_S1")
        self.store.audit("t1", "checkpoint", {"phase": "plan"})
        self.store.delete("t1")
        entries = self.store.audit_log(session_id="S1")
        self.assertEqual([e["kind"] for e in entries], ["task_created", "checkpoint"])
        self.assertEqual(entries[1]["payload"], {"phase": "plan"})
        self.assertEqual(self.store.audit_log(task_id="t1"), entries)


class OrchestratorDecisionEventsTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        p = mock.patch.object(orch_mod, "WORKSPACE_DIR", self.root)
        p.start()
        self.addCleanup(p.stop)

    def test_emits_checkpoint_loop_stop_and_final_selection(self):
        events = []
        o = orch_mod.ResearchOrchestrator(progress_callback=lambda t, d: events.append((t, d)))
        fake = FakeAgents([7.0, 8.0])
        fake.draft_texts = {0: "DRAFT-0 [C1]。", 1: "DRAFT-1 [C99]。"}
        for name in ("planner", "researcher", "analyst", "writer", "critic",
                     "source_verifier", "fact_checker", "conclusion_validator", "reconciler"):
            setattr(o, name, fake)
        o._agents = []
        o.run("固态电池", min_cycles=2, max_cycles=2)
        by_type = lambda t: [d for k, d in events if k == t]  # noqa: E731
        self.assertEqual([d["phase"] for d in by_type("checkpoint")], list(PHASES))
        self.assertEqual(by_type("loop_stop"), [{"cycle": 2, "reason": "已达最大轮数 2"}])
        final = by_type("final_selected")[0]
        self.assertEqual((final["draft"], final["best_scored_draft"]), (0, 1))
        self.assertEqual(final["violations"], {"0": 0, "1": 1})


class AuditApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = TaskStore(os.path.join(self.tmp, "tasks.db"))
        for p in (mock.patch.object(app_mod, "_store", self.store),
                  mock.patch.object(app_mod, "_run_research_task", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(app_mod.app, base_url="http://127.0.0.1:8000")

    def kinds(self, task_id):
        res = self.client.get(f"/api/research/{task_id}/audit", headers=HEADERS)
        return [e["kind"] for e in res.json()["entries"]]

    def test_user_actions_are_recorded_in_order(self):
        body = {"question": "固态电池", "research_strategy": "重视一手数据", "max_cycles": 3}
        task_id = self.client.post("/api/research", json=body, headers=HEADERS).json()["task_id"]
        app_mod._task_orchestrators[task_id] = SimpleNamespace(_user_messages=[])
        self.addCleanup(app_mod._task_orchestrators.pop, task_id, None)
        for path, payload in (("message", {"message": "多看 2026 年数据"}), ("pause", None),
                              ("resume", None), ("stop", None)):
            self.client.post(f"/api/research/{task_id}/{path}", json=payload, headers=HEADERS)
        self.assertEqual(self.kinds(task_id), ["task_created", "user_message", "pause_requested",
                                               "resume_requested", "stop_requested"])
        created = self.store.audit_log(task_id=task_id)[0]["payload"]
        self.assertEqual((created["source"], created["research_strategy"], created["max_cycles"]),
                         ("direct", "重视一手数据", 3))

    def test_engine_events_flow_through_callback(self):
        class FakeOrchestrator:
            interrupted = False

            def __init__(self, progress_callback, profile=None):
                self.cb, self.workspace, self.session_id = progress_callback, "/ws/session_S9", "S9"

            def run(self, question, **kw):
                self.cb("session", {"session_id": "S9", "workspace": self.workspace})
                self.cb("checkpoint", {"phase": "plan", "params_hash": "h"})
                self.cb("status", {"status": "planning"})  # 普通进度事件不进审计
                self.cb("final_selected", {"draft": 1})
                return "报告"

        self.store.reserve("t9", "q", limit=2)
        self.store.audit("t9", "task_created", {"source": "direct"})
        with mock.patch("orchestrator.ResearchOrchestrator", FakeOrchestrator):
            _REAL_RUN("t9", "q", None)  # 同步执行后台任务函数（setUp 里 patch 的是模块属性）
        res = self.client.get("/api/sessions/S9/audit", headers=HEADERS)
        self.assertEqual([e["kind"] for e in res.json()["entries"]],
                         ["task_created", "checkpoint", "final_selected", "task_finished"])
        self.assertEqual(res.json()["entries"][-1]["payload"]["status"], "completed")

    def test_user_message_applied_is_audited(self):
        """补充指令"已用上"（写进了哪个智能体的提示词）要进审计日志，广播器过期或重启后会话历史里仍能看到。"""
        applied = {"messages": ["重点对比个人版价格"], "phase": "阶段2→3", "agents": ["researcher"]}

        class FakeOrchestrator:
            interrupted = False

            def __init__(self, progress_callback, profile=None):
                self.cb, self.workspace, self.session_id = progress_callback, "/ws/session_S10", "S10"

            def run(self, question, **kw):
                self.cb("session", {"session_id": "S10", "workspace": self.workspace})
                self.cb("user_message_ack", {"messages": applied["messages"], "phase": applied["phase"]})
                self.cb("user_message_applied", applied)
                return "报告"

        self.store.reserve("t10", "q", limit=2)
        with mock.patch("orchestrator.ResearchOrchestrator", FakeOrchestrator):
            _REAL_RUN("t10", "q", None)
        entries = self.store.audit_log(session_id="S10")
        self.assertEqual([e["kind"] for e in entries], ["user_message_ack", "user_message_applied", "task_finished"])
        self.assertEqual(entries[1]["payload"], applied)

    def test_stopped_task_is_not_reported_completed(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)

        class Stubbed(orch_mod.ResearchOrchestrator):
            def __init__(self, progress_callback=None, profile=None):
                super().__init__(progress_callback, profile)
                fake = FakeAgents([7.0])
                for name in ("planner", "researcher", "analyst", "writer", "critic",
                             "source_verifier", "fact_checker", "conclusion_validator", "reconciler"):
                    setattr(self, name, fake)
                self._agents = []

        self.store.reserve("t5", "q", limit=2)
        stop = mock.MagicMock(is_set=lambda: True)
        with mock.patch.dict(app_mod._task_stop_events, {"t5": stop}), \
                mock.patch.object(orch_mod, "WORKSPACE_DIR", root), \
                mock.patch("orchestrator.ResearchOrchestrator", Stubbed):
            _REAL_RUN("t5", "q", None)
        self.assertEqual(self.store.get("t5")["status"], "stopped")
        self.assertEqual(self.store.audit_log(task_id="t5")[-1]["payload"]["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
