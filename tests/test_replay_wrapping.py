"""停止之后、后台线程真正退出之前，续办（重放）返回 409「上一个线程还在收尾，请稍后再试」，
免得两个线程同时写一个工作空间；线程退出后即可续办。仍在运行（没停）的任务沿用原来的「已有任务在运行」。"""
from api import app as app_mod
from tests.test_delete_race import HEADERS, WAIT, RaceCase, ResponsiveAgents

WRAPPING = "上一个线程还在收尾，请稍后再试"


class ReplayWhileWrappingUpTests(RaceCase):
    agents_cls = ResponsiveAgents

    def replay(self, session_id: str):
        return self.client.post(f"/api/sessions/{session_id}/replay", json={}, headers=HEADERS)

    def test_replay_is_refused_until_the_stopped_thread_exits(self):
        task_id, _, session_id = self.start_in_flight()
        self.assertEqual(self.client.post(f"/api/research/{task_id}/stop", headers=HEADERS).status_code, 200)
        self.assertTrue(self.agents.thread.is_alive())

        res = self.replay(session_id)
        self.assertEqual(res.status_code, 409, res.text)
        self.assertEqual(res.json()["detail"], WRAPPING)

        self.agents.exit_gate.set()
        self.agents.thread.join(WAIT)
        res = self.replay(session_id)
        self.assertEqual(res.status_code, 200, res.text)
        new_id = res.json()["task_id"]
        self.addCleanup(app_mod._task_stop_events.pop, new_id, None)
        thread = app_mod._task_threads.get(new_id)
        self.client.post(f"/api/research/{new_id}/stop", headers=HEADERS)
        if thread:
            thread.join(WAIT)
            self.assertFalse(thread.is_alive())

    def test_a_task_that_is_still_running_keeps_the_busy_message(self):
        _, _, session_id = self.start_in_flight()
        res = self.replay(session_id)
        self.assertEqual(res.status_code, 409, res.text)
        self.assertNotEqual(res.json()["detail"], WRAPPING)
        self.assertIn("已有任务在运行", res.json()["detail"])
