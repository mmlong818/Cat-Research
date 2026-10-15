"""运行中删除任务：后台线程还停在一次进行中的模型调用里，接口已经 rmtree 掉工作区；
线程随后醒来落盘，不得把会话目录重新建出来。用阻塞在「规划」里的假智能体让这个竞争每次都发生
（不靠 sleep 碰运气）。停止（不删除）则必须保留会话目录与记录。"""
import os
import threading
import time
from unittest import mock

import orchestrator as orch_mod
from agents.llm_agent import ResearchStopped, write_json_atomic
from api import app as app_mod
from api import security
from api.db.task_store import TaskStore
from tests.test_language import AGENTS
from tests.test_orchestrator import FakeAgents
from tests.test_settings import SettingsCase

HEADERS = {security.TOKEN_HEADER: security.TOKEN}
WAIT = 10


class BlockingAgents(FakeAgents):
    """规划阶段停在「进行中的模型调用」里；放行后像真实规划员一样落盘 03_plan.json 再返回。"""

    def __init__(self):
        super().__init__([6.0])
        self.in_flight = threading.Event()
        self.release = threading.Event()
        self.thread: threading.Thread | None = None

    def create_plan(self, ws, q, research_strategy=None, n_queries=None):
        self.thread = threading.current_thread()
        self.in_flight.set()
        assert self.release.wait(WAIT), "测试没有放行"
        plan = super().create_plan(ws, q, research_strategy, n_queries)
        write_json_atomic(os.path.join(ws, "03_plan.json"), plan)
        return plan


class ResponsiveAgents(BlockingAgents):
    """收到停止信号就退出，但收尾要等 exit_gate 放行（模拟需要一点时间才能退出的线程）。"""

    def __init__(self):
        super().__init__()
        self.exit_gate = threading.Event()
        self.orchestrator = None

    def create_plan(self, ws, q, research_strategy=None, n_queries=None):
        self.thread = threading.current_thread()
        self.in_flight.set()
        while not self.orchestrator._stop_event.is_set():
            time.sleep(0.01)
        assert self.exit_gate.wait(WAIT)
        raise ResearchStopped("[planner] 收到停止指令")


class RaceCase(SettingsCase):
    agents_cls: type[BlockingAgents] = BlockingAgents

    def setUp(self):
        super().setUp()
        self.agents = self.agents_cls()
        self.store = TaskStore(os.path.join(self.tmp, "tasks.db"))
        self.root = os.path.join(self.tmp, "workspace")
        os.makedirs(self.root)
        real = orch_mod.ResearchOrchestrator

        def factory(**kw):
            o = real(**kw)
            for name in AGENTS:
                setattr(o, name, self.agents)
            o._agents = []
            if isinstance(self.agents, ResponsiveAgents):
                self.agents.orchestrator = o
            return o

        for p in (mock.patch.object(app_mod, "_store", self.store),
                  mock.patch.object(app_mod, "WORKSPACE_DIR", self.root),
                  mock.patch.object(orch_mod, "WORKSPACE_DIR", self.root),
                  mock.patch.object(orch_mod, "ResearchOrchestrator", factory),
                  mock.patch.object(app_mod, "DELETE_JOIN_TIMEOUT", 0.3, create=True)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.finish_thread)

    def finish_thread(self):
        self.agents.release.set()
        if isinstance(self.agents, ResponsiveAgents):
            self.agents.exit_gate.set()
        if self.agents.thread:
            self.agents.thread.join(WAIT)

    def start_in_flight(self) -> tuple:
        """起一个真实的后台任务，等它停在规划的模型调用里；返回 (task_id, 工作区路径, 完整会话 ID)。"""
        res = self.client.post("/api/research", json={"question": "删除竞争测试", "depth": "quick"},
                               headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        task_id = res.json()["task_id"]
        self.addCleanup(app_mod._task_stop_events.pop, task_id, None)
        self.assertTrue(self.agents.in_flight.wait(WAIT), "任务没有进入规划")
        task = self.store.get(task_id)
        self.assertTrue(os.path.isdir(task["workspace"]))
        return task_id, task["workspace"], task["session_id"]

    def let_thread_finish(self):
        self.agents.release.set()
        self.agents.thread.join(WAIT)
        self.assertFalse(self.agents.thread.is_alive(), "后台线程没有结束")

    def assert_nothing_left(self, task_id):
        self.assertEqual(os.listdir(self.root), [], "会话目录被重新建出来了")
        self.assertIsNone(self.store.get(task_id))
        self.assertEqual(self.store.phases(task_id), [])


class DeleteRunningTaskTests(RaceCase):
    def test_delete_task_while_the_model_call_is_in_flight_leaves_no_directory(self):
        task_id, workspace, _ = self.start_in_flight()
        res = self.client.delete(f"/api/research/{task_id}", headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertFalse(os.path.exists(workspace))
        self.let_thread_finish()  # 线程醒来：落盘 03_plan.json、更新状态、写日志
        self.assert_nothing_left(task_id)

    def test_delete_session_while_the_model_call_is_in_flight_leaves_no_directory(self):
        task_id, workspace, session_id = self.start_in_flight()
        res = self.client.delete(f"/api/sessions/{session_id}", headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertFalse(os.path.exists(workspace))
        self.let_thread_finish()
        self.assertEqual(os.listdir(self.root), [], "会话目录被重新建出来了")

    def test_delete_session_also_stops_the_task_that_is_running_on_it(self):
        task_id, _, session_id = self.start_in_flight()
        self.assertFalse(app_mod._task_stop_events[task_id].is_set())
        self.client.delete(f"/api/sessions/{session_id}", headers=HEADERS)
        self.assertTrue(app_mod._task_stop_events[task_id].is_set())


class ResponsiveThreadTests(RaceCase):
    agents_cls = ResponsiveAgents

    def test_delete_waits_for_a_thread_that_exits_in_time(self):
        task_id, workspace, _ = self.start_in_flight()
        threading.Timer(0.8, self.agents.exit_gate.set).start()
        with mock.patch.object(app_mod, "DELETE_JOIN_TIMEOUT", 5.0, create=True):
            res = self.client.delete(f"/api/research/{task_id}", headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertFalse(self.agents.thread.is_alive(), "删除接口没有等线程退出就返回了")
        self.assert_nothing_left(task_id)
        self.assertFalse(os.path.exists(workspace))


class StopKeepsTheSessionTests(RaceCase):
    def test_stop_without_delete_keeps_directory_log_and_record(self):
        task_id, workspace, _ = self.start_in_flight()
        res = self.client.post(f"/api/research/{task_id}/stop", headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        self.let_thread_finish()
        self.assertTrue(os.path.isdir(workspace))
        with open(os.path.join(workspace, "00_session.json"), encoding="utf-8") as f:
            self.assertIn('"status": "stopped"', f.read())
        self.assertTrue(os.path.exists(os.path.join(workspace, "research_log.txt")))
        self.assertTrue(os.path.exists(os.path.join(workspace, "03_plan.json")))
        self.assertEqual(self.store.get(task_id)["status"], "stopped")
