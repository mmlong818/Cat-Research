"""V3 研究进度事件广播：多订阅者、断线重连回放、结束后订阅、缓冲上限、订阅者清理。"""
import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from api import app as app_mod
from api import security
from api.db.task_store import TaskStore
from api.events import BroadcastRegistry, EventBroadcaster

HEADERS = {security.TOKEN_HEADER: security.TOKEN}


def ev(kind: str, **data) -> dict:
    return {"type": kind, "data": data, "timestamp": "t"}


def drain(queue) -> list[dict]:
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


class BroadcasterTests(unittest.TestCase):
    def test_two_subscribers_receive_same_events(self):
        bc = EventBroadcaster()
        _, q1 = bc.subscribe()
        _, q2 = bc.subscribe()
        for i in range(3):
            bc.publish(ev("status", n=i))
        got1, got2 = drain(q1), drain(q2)
        self.assertEqual([e["data"]["n"] for e in got1], [0, 1, 2])
        self.assertEqual(got1, got2)

    def test_late_subscriber_gets_replay_then_live_without_gap_or_duplicate(self):
        bc = EventBroadcaster()
        bc.publish(ev("status", n=0))
        bc.publish(ev("status", n=1))
        replay, q = bc.subscribe()
        bc.publish(ev("status", n=2))
        self.assertEqual([e["data"]["n"] for e in replay], [0, 1])
        self.assertEqual([e["data"]["n"] for e in drain(q)], [2])

    def test_unsubscribe_removes_subscriber(self):
        bc = EventBroadcaster()
        _, q1 = bc.subscribe()
        _, q2 = bc.subscribe()
        bc.unsubscribe(q1)
        bc.unsubscribe(q1)  # 重复移除不报错
        bc.publish(ev("status"))
        self.assertEqual(bc.subscriber_count, 1)
        self.assertTrue(q1.empty())
        self.assertEqual(len(drain(q2)), 1)

    def test_buffer_is_capped_keeping_newest(self):
        bc = EventBroadcaster(max_buffer=5)
        for i in range(12):
            bc.publish(ev("status", n=i))
        replay, _ = bc.subscribe()
        self.assertEqual([e["data"]["n"] for e in replay], [7, 8, 9, 10, 11])

    def test_heartbeat_not_buffered_but_still_delivered_live(self):
        bc = EventBroadcaster()
        _, q = bc.subscribe()
        bc.publish(ev("heartbeat", elapsed=8))
        self.assertEqual(len(drain(q)), 1)
        replay, _ = bc.subscribe()
        self.assertEqual(replay, [])

    def test_end_marks_closed_and_stays_replayable(self):
        bc = EventBroadcaster()
        bc.publish(ev("started"))
        self.assertFalse(bc.closed)
        bc.publish(ev("end"))
        self.assertTrue(bc.closed)
        replay, _ = bc.subscribe()
        self.assertEqual([e["type"] for e in replay], ["started", "end"])

    def test_close_is_idempotent(self):
        bc = EventBroadcaster()
        bc.close()
        bc.close()
        replay, _ = bc.subscribe()
        self.assertEqual([e["type"] for e in replay], ["end"])

    def test_publish_from_threads_is_complete(self):
        bc = EventBroadcaster(max_buffer=1000)
        _, q = bc.subscribe()
        threads = [threading.Thread(target=lambda: [bc.publish(ev("status")) for _ in range(100)]) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(drain(q)), 500)


class RegistryTests(unittest.TestCase):
    def test_finished_broadcasters_purged_after_ttl_only(self):
        reg = BroadcastRegistry(ttl=100)
        with mock.patch("api.events.time.monotonic", return_value=0):
            old = reg.create("old")
            old.close()
            live = reg.create("live")
        with mock.patch("api.events.time.monotonic", return_value=50):
            reg.create("a")
            self.assertIs(reg.get("old"), old)
        with mock.patch("api.events.time.monotonic", return_value=200):
            reg.create("b")
        self.assertIsNone(reg.get("old"))
        self.assertIs(reg.get("live"), live)
        self.assertEqual(reg.active_count(), 3)  # live / a / b 都未结束


def parse_sse(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


class StreamEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = TaskStore(os.path.join(self.tmp, "t.db"))
        self.events = BroadcastRegistry()
        for name, obj in (("_store", self.store), ("_events", self.events)):
            p = mock.patch.object(app_mod, name, obj)
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(app_mod.app, base_url="http://127.0.0.1:8000")

    def read(self, task_id: str) -> list[dict]:
        with self.client.stream("GET", f"/api/research/{task_id}/stream", headers=HEADERS) as r:
            self.assertEqual(r.status_code, 200)
            return parse_sse("".join(r.iter_text()))

    def finished_task(self, status: str = "completed") -> str:
        self.store.reserve("t1", "问题", 2, scores=[1.5], current_cycle=2)
        bc = self.events.create("t1")
        bc.publish(ev("started", task_id="t1"))
        bc.publish(ev("status", status="researching"))
        bc.publish(ev("completed", session_id="s1"))
        bc.publish(ev("end"))
        self.store.merge("t1", status=status, result="很长的报告正文" * 100, session_id="s1")
        return "t1"

    def test_unknown_task_is_404(self):
        r = self.client.get("/api/research/nope/stream", headers=HEADERS)
        self.assertEqual(r.status_code, 404)

    def test_subscribe_after_finish_gets_snapshot_replay_and_end(self):
        events = self.read(self.finished_task())
        self.assertEqual([e["type"] for e in events],
                         ["ping", "snapshot", "started", "status", "completed", "end"])
        snap = events[1]["data"]
        self.assertEqual((snap["status"], snap["current_cycle"], snap["scores"]), ("completed", 2, [1.5]))
        self.assertEqual(snap["session_id"], "s1")
        self.assertNotIn("result", snap)  # 正文走 /result，不塞进快照

    def test_two_subscribers_see_identical_sequence(self):
        tid = self.finished_task()
        first, second = self.read(tid), self.read(tid)
        self.assertEqual(first[2:], second[2:])  # 快照自带的时间戳每次不同，其后的回放事件必须一致
        self.assertEqual(first[1]["data"], second[1]["data"])

    def test_task_only_in_store_after_restart_gets_snapshot_and_end(self):
        self.store.reserve("t2", "问题", 2, scores=[], current_cycle=0)
        self.store.mark_interrupted()
        events = self.read("t2")
        self.assertEqual([e["type"] for e in events], ["ping", "snapshot", "end"])
        self.assertEqual(events[1]["data"]["status"], "interrupted")

    def test_stopped_task_with_unfinished_thread_still_ends(self):
        self.store.reserve("t3", "问题", 2, scores=[], current_cycle=0)
        self.events.create("t3").publish(ev("started"))
        self.store.merge("t3", status="stopped")  # 线程尚未退出，广播器未发 end
        events = self.read("t3")
        self.assertEqual([e["type"] for e in events], ["ping", "snapshot", "started", "end"])

    def test_subscriber_removed_when_stream_closed(self):
        import asyncio

        async def scenario():
            self.store.reserve("t4", "问题", 2, scores=[], current_cycle=0)
            self.store.merge("t4", status="running")
            bc = self.events.create("t4")
            bc.publish(ev("started"))
            agen = app_mod._event_stream("t4")
            seen = [json.loads((await agen.__anext__())[6:])["type"] for _ in range(3)]
            self.assertEqual(seen, ["ping", "snapshot", "started"])
            self.assertEqual(bc.subscriber_count, 1)
            await agen.aclose()  # 客户端断开
            self.assertEqual(bc.subscriber_count, 0)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
