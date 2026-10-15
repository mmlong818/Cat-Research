"""V5 完整研究参数快照：用户覆盖值 + 深度档位合并成实际生效的参数，写入审计与会话元数据；max_queries 覆盖规划查询数。"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import config
import orchestrator as orch_mod
from api import app as app_mod
from api import security
from api.db.task_store import TaskStore
from research.checkpoints import Checkpoints
from research.params import resolve_params
from tests.test_depth import DepthFake

HEADERS = {security.TOKEN_HEADER: security.TOKEN}
AGENTS = ("planner", "researcher", "analyst", "writer", "critic",
          "source_verifier", "fact_checker", "conclusion_validator", "reconciler")


class ResolveParamsTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("CORE_MODEL", "core-x"), ("SUPPORT_MODEL", "support-y")):
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_snapshot_is_the_preset_plus_language_and_models(self):
        self.assertEqual(resolve_params("deep", "en"), {
            "depth": "deep", "language": "en", "ask_loop": False, "min_cycles": 2, "max_cycles": 5, "queries": 15,
            "supplements": 3, "source_supplement": True, "verify": 16, "recheck": 5,
            "provider": "unknown",  # 模型不在注册表里时提供方记为 unknown
            "core_model": "core-x", "support_model": "support-y",
            "search_backend": None})  # 只有 client_tools 提供方（智谱、兼容端点）才记搜索后端

    def test_defaults_to_default_depth_and_zh(self):
        snap = resolve_params()
        self.assertEqual((snap["depth"], snap["language"]), (config.DEFAULT_DEPTH, "zh"))
        self.assertEqual(snap["queries"], config.DEPTH_PRESETS[config.DEFAULT_DEPTH]["queries"])

    def test_explicit_cycles_and_queries_override_the_preset(self):
        snap = resolve_params("quick", min_cycles=2, max_cycles=4, max_queries=3)
        self.assertEqual((snap["min_cycles"], snap["max_cycles"], snap["queries"]), (2, 4, 3))
        self.assertEqual((snap["supplements"], snap["source_supplement"]), (0, False))  # 其余仍取档位

    def test_min_never_exceeds_max_and_non_positive_values_are_ignored(self):
        self.assertEqual(resolve_params("deep", min_cycles=4, max_cycles=3)["min_cycles"], 3)
        snap = resolve_params("standard", min_cycles=0, max_cycles=-1, max_queries=None)
        self.assertEqual((snap["min_cycles"], snap["max_cycles"], snap["queries"]), (2, 3, 10))

    def test_cycles_match_the_loop_policy_actually_used(self):
        with mock.patch("builtins.print"):
            o = orch_mod.ResearchOrchestrator()
        for depth in config.DEPTH_PRESETS:
            for mn, mx in ((None, None), (3, None), (None, 1), (4, 2), (0, 0), (1, 9)):
                snap, policy = resolve_params(depth, min_cycles=mn, max_cycles=mx), o._loop_policy(None, depth, mn, mx)
                self.assertEqual((snap["min_cycles"], snap["max_cycles"]), (policy.min_cycles, policy.max_cycles),
                                 (depth, mn, mx))


class OrchestratorSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        p = mock.patch.object(orch_mod, "WORKSPACE_DIR", self.root)
        p.start()
        self.addCleanup(p.stop)

    def orchestrator(self, fake):
        o = orch_mod.ResearchOrchestrator()
        for name in AGENTS:
            setattr(o, name, fake)
        o._agents = []
        return o

    def test_session_meta_records_the_resolved_params(self):
        o = self.orchestrator(DepthFake([6.0, 6.5]))
        o.run("固态电池", depth="quick", language="en", max_cycles=2, max_queries=4)
        with open(os.path.join(o.workspace, "00_session.json"), encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["resolved_params"], resolve_params("quick", "en", None, 2, 4))
        self.assertEqual((meta["resolved_params"]["max_cycles"], meta["resolved_params"]["queries"]), (2, 4))

    def test_max_queries_reaches_the_planner_and_survives_replay(self):
        fake = DepthFake([6.0])
        o = self.orchestrator(fake)
        o.run("固态电池", depth="quick", max_queries=3)
        self.assertEqual(fake.n_queries, 3)
        _, ctx, _ = Checkpoints(o.workspace).rollback("finish")
        self.assertEqual(ctx["params"]["max_queries"], 3)
        fake = DepthFake([6.0])
        self.orchestrator(fake).replay(o.workspace, "plan")
        self.assertEqual(fake.n_queries, 3)

    def test_without_override_the_planner_gets_the_preset_count(self):
        fake = DepthFake([6.0])
        self.orchestrator(fake).run("固态电池", depth="quick")
        self.assertEqual(fake.n_queries, 6)


class SnapshotApiTests(unittest.TestCase):
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

    def post(self, **body):
        return self.client.post("/api/research", json={"question": "固态电池", **body}, headers=HEADERS)

    def test_task_created_audit_carries_resolved_params(self):
        task_id = self.post(depth="quick", language="en", max_cycles=2, max_queries=3).json()["task_id"]
        payload = self.store.audit_log(task_id=task_id)[0]["payload"]
        self.assertEqual(payload["resolved_params"], resolve_params("quick", "en", None, 2, 3))
        self.assertEqual(self.calls[0]["max_queries"], 3)

    def test_max_queries_defaults_to_none(self):
        task_id = self.post().json()["task_id"]
        self.assertIsNone(self.calls[0]["max_queries"])
        payload = self.store.audit_log(task_id=task_id)[0]["payload"]
        self.assertEqual(payload["resolved_params"]["queries"], config.DEPTH_PRESETS["standard"]["queries"])

    def test_clarify_confirm_audit_carries_resolved_params(self):
        app_mod._clarify_sessions["c2"] = {"question": "固态电池", "history": [], "summary": {}, "turns": 1}
        self.addCleanup(app_mod._clarify_sessions.pop, "c2", None)
        res = self.client.post("/api/clarify/c2/confirm", json={"depth": "deep", "language": "en"}, headers=HEADERS)
        payload = self.store.audit_log(task_id=res.json()["task_id"])[0]["payload"]
        self.assertEqual(payload["resolved_params"], resolve_params("deep", "en"))

    def test_invalid_max_queries_is_rejected(self):
        for bad in (0, -1, 31, "many"):
            self.assertEqual(self.post(max_queries=bad).status_code, 422, bad)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.post(max_queries=1).status_code, 200)
        self.assertEqual(self.post(max_queries=30).status_code, 200)


if __name__ == "__main__":
    unittest.main()
