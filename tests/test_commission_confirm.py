"""委托确认：接受委托台改过的研究问题与研究目标；会话里研究问题与补充说明分开存，
补充说明不再拼在问题后面（编排器在提示词里仍按原写法拼接，各智能体收到的提示词不变）。"""
import glob
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from agents.clarifier import summary_to_brief
from api import app as app_mod
from api import security
from api.db.task_store import TaskStore
from tests.pipeline_llm import QUESTION, ScriptedLLM, run_pipeline

HEADERS = {security.TOKEN_HEADER: security.TOKEN}
SUMMARY = {"objective": "模型猜的目标", "scope": "个人版与团队版", "key_aspects": ["月费", "超额计费"],
           "timeframe": "2026-10", "depth": "", "angle": "", "exclude": "企业私有部署", "search_hints": [],
           "intent_type": "optimization", "dimensions": {"urgency": 0.5, "specificity": 0.8, "complexity": 0.3}}
BRIEF = "研究目标：看清各家量产时间表\n研究范围：中日韩电池厂"
_REAL_RUN = app_mod._run_research_task


class SummaryToBriefTests(unittest.TestCase):
    def test_goal_is_the_first_line(self):
        brief, _ = summary_to_brief(SUMMARY, "只要官方价格", goal="看清定价差异")
        self.assertEqual(brief.splitlines(), ["研究目标：看清定价差异", "研究范围：个人版与团队版",
                                              "重点方面：月费、超额计费", "时间范围：2026-10", "排除内容：企业私有部署",
                                              "用户补充：只要官方价格"])

    def test_without_goal_the_brief_is_unchanged(self):
        brief, intent = summary_to_brief(SUMMARY, "只要官方价格")
        self.assertEqual(brief, "研究范围：个人版与团队版\n重点方面：月费、超额计费\n时间范围：2026-10\n"
                                "排除内容：企业私有部署\n用户补充：只要官方价格")
        self.assertEqual(intent["intent_type"], "optimization")


class ConfirmApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = TaskStore(os.path.join(self.tmp, "tasks.db"))
        self.calls = []
        for p in (mock.patch.object(app_mod, "_store", self.store),
                  mock.patch.object(app_mod, "_run_research_task", lambda *a, **k: self.calls.append((a, k)))):
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(app_mod.app, base_url="http://127.0.0.1:8000")
        app_mod._clarify_sessions["cq"] = {"question": "原来的问题", "history": [], "summary": SUMMARY, "turns": 1}
        self.addCleanup(app_mod._clarify_sessions.pop, "cq", None)

    def confirm(self, **body) -> str:
        res = self.client.post("/api/clarify/cq/confirm", json=body, headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["task_id"]

    def test_edited_question_and_goal_reach_the_research(self):
        task_id = self.confirm(question=" 改过的问题 ", goal=" 看清定价差异 ", extra_note="只要官方价格")
        (_, question, clarification, *_), _ = self.calls[0]
        self.assertEqual(question, "改过的问题")
        self.assertTrue(clarification.startswith("研究目标：看清定价差异\n研究范围：个人版与团队版"))
        self.assertTrue(clarification.endswith("用户补充：只要官方价格"))
        self.assertEqual(self.store.get(task_id)["question"], "改过的问题")
        payload = self.store.audit_log(task_id=task_id)[0]["payload"]
        self.assertEqual((payload["question"], payload["goal"]), ("改过的问题", " 看清定价差异 "))

    def test_blank_question_and_goal_keep_the_clarified_question(self):
        task_id = self.confirm(question="  ", goal="")
        (_, question, clarification, *_), _ = self.calls[0]
        self.assertEqual(question, "原来的问题")
        self.assertNotIn("研究目标", clarification)
        self.assertEqual(self.store.get(task_id)["question"], "原来的问题")


class RunTaskTests(unittest.TestCase):
    """后台线程把研究问题与补充说明分开交给编排器，不再自己拼接。"""

    def test_clarification_is_passed_separately(self):
        seen = {}

        class FakeOrchestrator:
            interrupted = False
            workspace, session_id = "/ws/session_S1", "S1"

            def __init__(self, progress_callback=None, profile=None):
                pass

            def run(self, question, **kwargs):
                seen["question"], seen["kwargs"] = question, kwargs
                return "报告"

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        store = TaskStore(os.path.join(tmp, "tasks.db"))
        store.reserve("t1", "问题", limit=2)
        with mock.patch.object(app_mod, "_store", store), \
                mock.patch("orchestrator.ResearchOrchestrator", FakeOrchestrator):
            _REAL_RUN("t1", "问题", BRIEF)
        self.assertEqual(seen["question"], "问题")
        self.assertEqual(seen["kwargs"]["clarification"], BRIEF)


class CliClarifyTests(unittest.TestCase):
    """命令行交互澄清同样把补充说明单独交给编排器，不拼在问题后面。"""

    def test_clarify_returns_the_brief_apart_from_the_question(self):
        import main
        turn = {"message": "可以开始", "summary": SUMMARY, "ready": True, "confidence": 0.9, "history": []}
        with mock.patch("agents.clarifier.ClarifierAgent.start", return_value=turn), \
                mock.patch("builtins.print"):
            brief, intent = main.clarify("原来的问题")
        self.assertEqual(brief, summary_to_brief(SUMMARY)[0])
        self.assertEqual(intent["intent_type"], "optimization")


class SessionStorageTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def run_with_brief(self):
        llm = ScriptedLLM()
        o, _ = run_pipeline(self.root, llm, clarification=BRIEF)
        return o, llm

    def read(self, o, *parts):
        with open(os.path.join(o.workspace, *parts), encoding="utf-8") as f:
            return f.read()

    def test_question_and_clarification_are_stored_apart(self):
        o, _ = self.run_with_brief()
        meta = json.loads(self.read(o, "00_session.json"))
        self.assertEqual((meta["question"], meta["clarification"]), (QUESTION, BRIEF))
        self.assertEqual(self.read(o, "01_question.txt"), QUESTION)
        clar = json.loads(self.read(o, "04_clarification", "clarification.json"))
        self.assertEqual(clar["original_question"], QUESTION)
        self.assertEqual(clar["final_question"], f"{QUESTION}\n\n补充说明：{BRIEF}")

    def test_agents_still_get_the_brief_after_the_question(self):
        _, llm = self.run_with_brief()
        for role in ("planner", "analyst", "writer"):
            self.assertIn(f"## 研究问题\n{QUESTION}\n\n补充说明：{BRIEF}\n", llm.prompts(role)[0], role)

    def test_without_clarification_nothing_is_appended(self):
        llm = ScriptedLLM()
        o, _ = run_pipeline(self.root, llm)
        self.assertNotIn("补充说明", llm.prompts("planner")[0])
        self.assertIsNone(json.loads(self.read(o, "00_session.json"))["clarification"])

    def test_replay_of_a_checkpoint_with_the_brief_inside_the_question(self):
        """改动前的检查点：补充说明拼在 params.question 里、没有 clarification 字段；重放时提示词不变。"""
        o, llm = self.run_with_brief()
        for path in glob.glob(os.path.join(o.workspace, ".checkpoints", "*", "state.json")):
            with open(path, encoding="utf-8") as f:
                record = json.load(f)
            params = record["state"]["params"]
            params["question"] = f"{QUESTION}\n\n补充说明：{params.pop('clarification')}"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False)
        replayed = ScriptedLLM()
        run_pipeline(self.root, replayed, replay_from="plan", workspace=o.workspace)
        for role in ("planner", "analyst", "critic"):
            self.assertEqual(replayed.prompts(role)[0], llm.prompts(role)[0], role)


if __name__ == "__main__":
    unittest.main()
