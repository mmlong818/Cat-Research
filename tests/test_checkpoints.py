"""阶段检查点与重放：每阶段结束快照 workspace；从任一阶段回滚重跑；同一会话不可并发重放。"""
import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import orchestrator as orch_mod
from api import app as app_mod
from api import security
from api.db.task_store import TaskStore
from research.checkpoints import PHASES, Checkpoints
from research.ledger import Ledger
from tests.test_orchestrator import FakeAgents

AGENTS = ("planner", "researcher", "analyst", "writer", "critic",
          "source_verifier", "fact_checker", "conclusion_validator", "reconciler")


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class CheckpointStoreTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, True)
        self.ck = Checkpoints(self.ws)

    def _save_upto(self, n):
        for i, phase in enumerate(PHASES[:n]):
            _write(os.path.join(self.ws, "out", f"{phase}.txt"), phase)
            self.ck.save(phase, {"params": {}, "step": i}, params_hash="h")

    def test_rollback_restores_files_and_drops_later_checkpoints(self):
        self._save_upto(4)
        _write(os.path.join(self.ws, "out", "plan.txt"), "被后续阶段改写")
        start, ctx, _ = self.ck.rollback("research")
        self.assertEqual((PHASES[start], ctx["step"]), ("research", 1))
        self.assertEqual(sorted(os.listdir(os.path.join(self.ws, "out"))), ["clarify.txt", "plan.txt"])
        with open(os.path.join(self.ws, "out", "plan.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "plan")
        self.assertEqual([c["phase"] for c in self.ck.list()], ["clarify", "plan"])

    def test_resolve_defaults_to_first_phase_without_checkpoint(self):
        self._save_upto(3)
        self.assertEqual(PHASES[self.ck.resolve(None)], "sources")

    def test_resolve_rejects_invalid_requests(self):
        self._save_upto(3)
        for bad in ("nope", "clarify", "analyze"):  # 未知阶段 / 需从头开始 / 前一阶段无检查点
            with self.assertRaises(ValueError):
                self.ck.resolve(bad)
        self._save_upto(len(PHASES))
        with self.assertRaises(ValueError):  # 已全部完成，没有可续跑的阶段
            self.ck.resolve(None)

    def test_resolve_without_checkpoints(self):
        with self.assertRaises(ValueError):
            self.ck.resolve(None)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        p = mock.patch.object(orch_mod, "WORKSPACE_DIR", self.root)
        p.start()
        self.addCleanup(p.stop)

    def make(self, fake):
        o = orch_mod.ResearchOrchestrator()
        for name in AGENTS:
            setattr(o, name, fake)
        o._agents = []
        return o

    def test_interrupted_run_resumes_without_redoing_finished_phases(self):
        stop = threading.Event()
        fake = FakeAgents([6.0, 7.0])
        real_analyze = fake.analyze
        fake.analyze = lambda ws, q: (real_analyze(ws, q), stop.set())
        o = self.make(fake)
        self.assertEqual(o.run("固态电池", stop_event=stop, min_cycles=2, max_cycles=2), "任务已中断")
        self.assertEqual([c["phase"] for c in Checkpoints(o.workspace).list()], list(PHASES[:5]))

        fake2 = FakeAgents([6.0, 7.0])
        fake2.create_plan = mock.Mock(side_effect=AssertionError("规划不应重跑"))
        result = self.make(fake2).replay(o.workspace)
        self.assertTrue(result.startswith("DRAFT-1"))
        self.assertEqual(fake2.research_rounds[0][0], 2)  # 研究轮次编号接着断点前继续
        with open(os.path.join(o.workspace, "00_session.json"), encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual((meta["status"], meta["total_cycles"]), ("completed", 2))

    def test_replay_from_improve_rolls_back_drafts_and_ledger(self):
        fake = FakeAgents([6.0, 6.5, 7.0])
        fake.claim_rounds = {1, 2, 3}
        o = self.make(fake)
        o.run("固态电池", min_cycles=2, max_cycles=3)  # 3 轮评审，草稿 0-2，补充研究 2 轮
        self.assertEqual(len(Ledger.load(o.workspace).claims), 3)

        fake2 = FakeAgents([9.0, 5.0])  # 沿用检查点里的轮数策略：第 2 轮无增益即停
        fake2.claim_rounds = set()
        result = self.make(fake2).replay(o.workspace, from_phase="improve")
        drafts = sorted(os.listdir(os.path.join(o.workspace, "06_drafts")))
        self.assertEqual(drafts, ["draft_0.md", "draft_1.md"])  # 旧的第 2 版已随回滚删除
        self.assertTrue(result.startswith("DRAFT-0"))  # 新一轮评审里 9.0 的那版
        self.assertEqual(len(Ledger.load(o.workspace).claims), 1)  # 旧补充轮次的声明已回滚


class ReplayApiTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.ws = os.path.join(self.root, "session_20260101_000000")
        os.makedirs(self.ws)
        ck = Checkpoints(self.ws)
        for phase in PHASES[:3]:
            ck.save(phase, {"params": {"question": "q"}}, params_hash="h")
        store = TaskStore(os.path.join(self.root, "tasks.db"))
        for p in (mock.patch.object(app_mod, "_store", store),
                  mock.patch.object(app_mod, "WORKSPACE_DIR", self.root),
                  mock.patch.object(app_mod, "_run_research_task", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(app_mod.app, base_url="http://127.0.0.1:8000")
        self.headers = {security.TOKEN_HEADER: security.TOKEN}

    def replay(self, body=None, sid="20260101_000000"):
        return self.client.post(f"/api/sessions/{sid}/replay", json=body or {}, headers=self.headers)

    def test_lists_checkpoints(self):
        res = self.client.get("/api/sessions/20260101_000000/checkpoints", headers=self.headers)
        self.assertEqual([c["phase"] for c in res.json()["checkpoints"]], list(PHASES[:3]))
        self.assertEqual(res.json()["resume_from"], "sources")

    def test_replay_starts_task_and_second_replay_is_refused(self):
        first = self.replay()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["from_phase"], "sources")
        self.assertEqual(self.replay({"from_phase": "plan"}).status_code, 409)
        self.assertEqual(self.replay(sid="0101_0000").status_code, 409)  # 部分 ID 也指向同一会话

    def test_replay_validation(self):
        self.assertEqual(self.replay({"from_phase": "analyze"}).status_code, 400)
        self.assertEqual(self.replay(sid="nope").status_code, 404)


if __name__ == "__main__":
    unittest.main()
