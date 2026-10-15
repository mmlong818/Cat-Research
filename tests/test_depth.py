"""E5 研究深度分档：quick / standard / deep 决定查询数、评审轮数与补充研究上限。"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import orchestrator as orch_mod
from api import app as app_mod
from api import security
from api.db.task_store import TaskStore
from tests.test_orchestrator import FakeAgents

HEADERS = {security.TOKEN_HEADER: security.TOKEN}


class DepthFake(FakeAgents):
    def __init__(self, scores, quality="excellent"):
        super().__init__(scores)
        self.claim_rounds = set(range(1, 20))  # 每轮都有新声明，不触发零增益研究停止
        self.quality = quality
        self.n_queries = None

    def create_plan(self, ws, q, research_strategy=None, n_queries=None):
        self.n_queries = n_queries
        return super().create_plan(ws, q, research_strategy)

    def verify_sources(self, ws):
        sv, path = super().verify_sources(ws)
        sv["summary"]["overall_quality"] = self.quality
        return sv, path

    def loop_supplements(self):
        return sum(1 for _, qs in self.research_rounds if qs and isinstance(qs[0], dict))  # 评审意见转成的查询

    def source_supplements(self):
        return sum(1 for _, qs in self.research_rounds if qs and str(qs[0]).startswith("权威来源"))


class DepthOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        p = mock.patch.object(orch_mod, "WORKSPACE_DIR", self.root)
        p.start()
        self.addCleanup(p.stop)

    def run_with(self, fake, **kw):
        o = orch_mod.ResearchOrchestrator()
        for name in ("planner", "researcher", "analyst", "writer", "critic",
                     "source_verifier", "fact_checker", "conclusion_validator", "reconciler"):
            setattr(o, name, fake)
        o._agents = []
        o.run("固态电池", **kw)
        return o

    def test_quick(self):
        fake = DepthFake([6.0, 6.5], quality="poor")
        self.run_with(fake, depth="quick")
        self.assertEqual(fake.n_queries, 6)
        self.assertEqual(len(fake.writes), 1)  # 只评审初稿一轮，不改写
        self.assertEqual((fake.loop_supplements(), fake.source_supplements()), (0, 0))

    def test_standard_is_default(self):
        fake = DepthFake([6.0, 6.5, 7.0, 7.5], quality="poor")
        self.run_with(fake)
        self.assertEqual(fake.n_queries, 10)
        self.assertEqual(len(fake.writes), 3)  # 3 轮评审：初稿 + 2 次改写
        self.assertEqual((fake.loop_supplements(), fake.source_supplements()), (2, 1))

    def test_deep_caps_supplements(self):
        fake = DepthFake([6.0, 6.5, 7.0, 7.5, 7.9])
        self.run_with(fake, depth="deep")
        self.assertEqual(fake.n_queries, 15)
        self.assertEqual(len(fake.writes), 5)
        self.assertEqual(fake.loop_supplements(), 3)  # 前 4 轮都想补充，上限 3 次

    def test_explicit_cycles_override_tier(self):
        fake = DepthFake([6.0, 6.5, 7.0])
        self.run_with(fake, depth="quick", min_cycles=2, max_cycles=2)
        self.assertEqual(len(fake.writes), 2)
        self.assertEqual(fake.loop_supplements(), 0)  # 补充上限仍由档位决定

    def test_verify_limit_follows_the_depth_tier(self):
        for depth, limit in (("quick", 8), ("standard", 12), ("deep", 16)):
            fake = DepthFake([6.0] * 6)
            self.run_with(fake, depth=depth)
            self.assertEqual(fake.verify_limits, [limit], depth)

    def test_depth_is_kept_in_params(self):
        o = self.run_with(DepthFake([6.0]), depth="quick")
        from research.checkpoints import Checkpoints
        _, ctx, _ = Checkpoints(o.workspace).rollback("finish")
        self.assertEqual(ctx["params"]["depth"], "quick")


class DepthApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = TaskStore(os.path.join(self.tmp, "tasks.db"))
        self.calls = []
        for p in (mock.patch.object(app_mod, "_store", self.store),
                  mock.patch.object(app_mod, "_run_research_task", lambda *a, **k: self.calls.append(k))):
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(app_mod.app, base_url="http://127.0.0.1:8000")

    def test_depth_is_passed_and_audited(self):
        res = self.client.post("/api/research", json={"question": "固态电池", "depth": "deep"}, headers=HEADERS)
        task_id = res.json()["task_id"]
        self.assertEqual(self.calls[0]["depth"], "deep")
        self.assertEqual(self.store.audit_log(task_id=task_id)[0]["payload"]["depth"], "deep")

    def test_default_and_invalid_depth(self):
        self.client.post("/api/research", json={"question": "固态电池"}, headers=HEADERS)
        self.assertEqual(self.calls[0]["depth"], "standard")
        res = self.client.post("/api/research", json={"question": "q", "depth": "huge"}, headers=HEADERS)
        self.assertEqual(res.status_code, 422)


if __name__ == "__main__":
    unittest.main()
