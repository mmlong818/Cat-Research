"""V4 报告输出语言：language 随任务传到写作环节，写入检查点（重放沿用）、会话元数据与审计。"""
import glob
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import orchestrator as orch_mod
from agents.writer import WriterAgent
from api import app as app_mod
from api import security
from api.db.task_store import TaskStore
from research.checkpoints import Checkpoints
from tests.test_orchestrator import FakeAgents
from tests.test_research_agents import _WS, _ok

HEADERS = {security.TOKEN_HEADER: security.TOKEN}
AGENTS = ("planner", "researcher", "analyst", "writer", "critic",
          "source_verifier", "fact_checker", "conclusion_validator", "reconciler")


class LanguageOrchestratorTests(unittest.TestCase):
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

    def test_language_reaches_first_draft_and_rewrites_and_is_recorded(self):
        fake = FakeAgents([6.0, 7.0])
        o = self.orchestrator(fake)
        o.run("固态电池", min_cycles=2, max_cycles=2, language="en")
        self.assertEqual(fake.languages, ["en", "en"])  # 初稿 + 一次改写
        with open(os.path.join(o.workspace, "00_session.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["language"], "en")
        _, ctx, _ = Checkpoints(o.workspace).rollback("finish")
        self.assertEqual(ctx["params"]["language"], "en")

    def test_default_language_is_zh(self):
        fake = FakeAgents([6.0])
        o = self.orchestrator(fake)
        o.run("固态电池", depth="quick")
        self.assertEqual(fake.languages, ["zh"])
        with open(os.path.join(o.workspace, "00_session.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["language"], "zh")

    def test_replay_keeps_language_and_old_checkpoints_default_to_zh(self):
        o = self.orchestrator(FakeAgents([6.0, 7.0]))
        o.run("固态电池", min_cycles=2, max_cycles=2, language="en")

        fake = FakeAgents([6.0, 7.0])
        self.orchestrator(fake).replay(o.workspace, "improve")
        self.assertEqual(fake.languages, ["en"])  # 沿用检查点里的语言

        for path in glob.glob(os.path.join(o.workspace, ".checkpoints", "*", "state.json")):
            with open(path, encoding="utf-8") as f:
                record = json.load(f)
            record["state"]["params"].pop("language", None)  # 模拟没有该字段的旧检查点
            with open(path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False)
        fake = FakeAgents([6.0, 7.0])
        self.orchestrator(fake).replay(o.workspace, "improve")
        self.assertEqual(fake.languages, ["zh"])


class LanguageApiTests(unittest.TestCase):
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

    def test_language_is_passed_and_audited(self):
        res = self.client.post("/api/research", json={"question": "固态电池", "language": "en"}, headers=HEADERS)
        task_id = res.json()["task_id"]
        self.assertEqual(self.calls[0]["language"], "en")
        self.assertEqual(self.store.audit_log(task_id=task_id)[0]["payload"]["language"], "en")

    def test_default_and_invalid_language(self):
        task_id = self.client.post("/api/research", json={"question": "固态电池"}, headers=HEADERS).json()["task_id"]
        self.assertEqual(self.calls[0]["language"], "zh")
        self.assertEqual(self.store.audit_log(task_id=task_id)[0]["payload"]["language"], "zh")
        res = self.client.post("/api/research", json={"question": "q", "language": "fr"}, headers=HEADERS)
        self.assertEqual(res.status_code, 422)

    def test_clarify_confirm_passes_language(self):
        app_mod._clarify_sessions["c1"] = {"question": "固态电池", "history": [], "summary": {}, "turns": 1}
        self.addCleanup(app_mod._clarify_sessions.pop, "c1", None)
        res = self.client.post("/api/clarify/c1/confirm", json={"language": "en"}, headers=HEADERS)
        self.assertEqual(self.calls[0]["language"], "en")
        self.assertEqual(self.store.audit_log(task_id=res.json()["task_id"])[0]["payload"]["language"], "en")


class WriterLanguageTests(_WS):
    def prompt(self, **kw):
        self.put("05_analysis.md", "分析A")
        self.put("06_drafts/draft_0.md", "上一版D0")
        self.patch_call(_ok(text="# 报告"))
        WriterAgent().write_draft(self.ws, "问题", **kw)
        return self.reqs[0].prompt

    def test_english_adds_language_instruction_to_draft_and_rewrite(self):
        for kw in ({"draft_num": 0}, {"draft_num": 1}):
            p = self.prompt(language="en", **kw)
            self.assertIn("Write the entire report in English", p)
            self.assertIn("original language", p)
            self.assertIn("[C", p)  # 引用规则仍在

    def test_chinese_is_unchanged(self):
        self.assertNotIn("English", self.prompt(draft_num=0))
        self.assertNotIn("English", self.prompt(draft_num=1, language="zh"))


if __name__ == "__main__":
    unittest.main()
