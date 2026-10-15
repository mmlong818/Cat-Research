"""改进循环中即时询问用户是否继续：提问时机、等待与超时、暂停/停止、orchestrator 接线、API 接口与审计、重放沿用设置。"""
import itertools
import os
import shutil
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

import orchestrator as orch_mod
from agents.llm_agent import ResearchStopped
from api import app as app_mod
from api import security
from api.db.task_store import TaskStore
from research.checkpoints import Checkpoints
from research.loop_ask import ASK_GAIN_BELOW, ASK_SCORE_AT_LEAST, ASK_TIMEOUT_S, LoopAsk, should_ask
from research.loop_policy import LoopPolicy, LoopState
from research.params import resolve_params
from tests.test_orchestrator import FakeAgents

HEADERS = {security.TOKEN_HEADER: security.TOKEN}
_REAL_RUN = app_mod._run_research_task
AGENTS = ("planner", "researcher", "analyst", "writer", "critic",
          "source_verifier", "fact_checker", "conclusion_validator", "reconciler")
POLICY = LoopPolicy(min_cycles=2, max_cycles=5)


def state_with(*scores) -> tuple[LoopState, float | None]:
    """依次记录评审分，返回 (状态, 最后一轮之前的最优分)。"""
    state, prev = LoopState(), None
    for i, s in enumerate(scores):
        prev = state.best_score
        state.record(i, s, f"review_{i + 1}.json", POLICY.min_gain)
    return state, prev


class ShouldAskTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((ASK_GAIN_BELOW, ASK_SCORE_AT_LEAST, ASK_TIMEOUT_S), (0.3, 7.8, 300))

    def test_not_asked_before_min_cycles(self):
        state, prev = state_with(7.9)
        self.assertFalse(should_ask(POLICY, state, prev))

    def test_not_asked_while_improving_fast_below_the_score_bar(self):
        state, prev = state_with(6.0, 7.0)  # 提升 1.0，最优 7.0 < 7.8
        self.assertFalse(should_ask(POLICY, state, prev))

    def test_asked_when_gain_is_small(self):
        state, prev = state_with(6.0, 6.2)
        self.assertTrue(should_ask(POLICY, state, prev))

    def test_asked_when_best_score_is_high_even_if_gain_is_large(self):
        state, prev = state_with(6.0, 7.9)
        self.assertTrue(should_ask(POLICY, state, prev))

    def test_a_worse_round_counts_as_zero_gain(self):
        state, prev = state_with(6.0, 6.5, 6.4)  # 最优分没变
        self.assertTrue(should_ask(POLICY, state, prev))

    def test_gain_exactly_at_the_bar_is_not_small(self):
        state, prev = state_with(6.0, 6.5)  # 提升 0.5
        self.assertFalse(should_ask(POLICY, state, prev))
        state, prev = state_with(6.0, 6.3)  # 提升 0.3，不算「小于 0.3」
        self.assertFalse(should_ask(POLICY, state, prev))

    def test_first_round_has_no_gain_baseline(self):
        policy = LoopPolicy(min_cycles=1, max_cycles=5)
        state, prev = state_with(6.0)
        self.assertFalse(should_ask(policy, state, prev))
        state, prev = state_with(7.8)
        self.assertTrue(should_ask(policy, state, prev))


class ManualClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def wait_until(cond, what="condition", limit=5.0):
    end = time.monotonic() + limit
    while not cond():
        if time.monotonic() > end:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(0.005)


class LoopAskTests(unittest.TestCase):
    def setUp(self):
        self.events: list[tuple[str, dict]] = []
        self.pause = threading.Event()
        self.pause.set()
        self.stop = threading.Event()
        self.clock = ManualClock()
        self.ask = LoopAsk(lambda t, d: self.events.append((t, d)), lambda: (self.pause, self.stop),
                           clock=self.clock, poll_s=0.005)
        self.ask.enabled = True
        self.state, _ = state_with(6.0, 6.2)
        self.before = state_with(6.0)[0]  # 本轮评审前的状态（最优分 6.0）
        self.usage = {"writer": {"input": 1}}  # consult 的 usage 参数

    def start(self):
        """在线程里发起询问；返回 (线程, 结果字典)。"""
        out: dict = {}

        def target():
            try:
                self.ask.round_start(2, self.before)
                out["reason"] = self.ask.consult(POLICY, self.state, 2, 6.2, {1: {"violations": ["v"]}}, self.usage)
            except BaseException as e:  # noqa: BLE001
                out["error"] = e
        t = threading.Thread(target=target, daemon=True)
        t.start()
        wait_until(lambda: self.ask.pending is not None or "reason" in out or "error" in out, "decision to open")
        self.addCleanup(t.join, 5)
        return t, out

    def kinds(self):
        return [k for k, _ in self.events]

    def test_disabled_never_asks(self):
        self.ask.enabled = False
        self.ask.round_start(2, self.state)
        self.assertIsNone(self.ask.consult(POLICY, self.state, 2, 6.2, {}, self.usage))
        self.assertEqual(self.events, [])

    def test_not_due_never_asks(self):
        state = LoopState()
        self.ask.round_start(1, state)
        state.record(0, 7.9, "r1", 0.1)
        self.assertIsNone(self.ask.consult(POLICY, state, 1, 7.9, {}, self.usage))  # 未到最少轮数
        self.assertEqual(self.events, [])

    def test_continue_answer(self):
        t, out = self.start()
        info = self.ask.pending
        self.assertTrue(self.ask.answer("continue"))
        t.join(5)
        self.assertIsNone(out["reason"])
        self.assertEqual(self.kinds(), ["loop_decision", "loop_decision_resolved"])
        self.assertEqual(self.events[1][1]["choice"], "continue")
        self.assertEqual((info["cycle"], info["max_cycles"], info["best_score"], info["violations"]), (2, 5, 6.2, 1))
        self.assertIsNone(self.ask.pending)

    def test_stop_answer_returns_the_stop_reason(self):
        t, out = self.start()
        self.ask.answer("stop")
        t.join(5)
        self.assertEqual(out["reason"], "用户选择结束改进（当前最优 6.2）")
        self.assertEqual(self.events[-1][1]["choice"], "stop")
        self.assertEqual(self.events[-1][1]["best_score"], 6.2)

    def test_event_payload(self):
        t, out = self.start()
        data = self.events[0][1]
        self.assertEqual(data["timeout_s"], ASK_TIMEOUT_S)
        self.assertEqual(data["deadline"], self.clock.now + ASK_TIMEOUT_S)
        self.assertEqual((data["cycle"], data["max_cycles"], data["best_draft"], data["score"]), (2, 5, 1, 6.2))
        self.assertAlmostEqual(data["gain"], 0.2)
        self.ask.answer("continue")
        t.join(5)

    def test_timeout_continues_without_real_waiting(self):
        t, out = self.start()
        self.clock.now += ASK_TIMEOUT_S - 1
        time.sleep(0.05)
        self.assertIsNotNone(self.ask.pending)  # 还没到
        self.clock.now += 2
        t.join(5)
        self.assertIsNone(out["reason"])
        self.assertEqual(self.events[-1][1]["choice"], "timeout")

    def test_answer_when_nothing_is_pending_is_refused(self):
        self.assertFalse(self.ask.answer("continue"))

    def test_second_answer_is_refused(self):
        t, out = self.start()
        self.assertTrue(self.ask.answer("continue"))
        self.assertFalse(self.ask.answer("stop"))
        t.join(5)
        self.assertIsNone(out["reason"])

    def test_invalid_choice_is_refused(self):
        t, out = self.start()
        self.assertFalse(self.ask.answer("whatever"))
        self.ask.answer("continue")
        t.join(5)

    def test_stop_event_interrupts_the_wait(self):
        t, out = self.start()
        self.stop.set()
        t.join(5)
        self.assertIsInstance(out["error"], ResearchStopped)
        self.assertEqual(self.events[-1][1]["choice"], "aborted")
        self.assertIsNone(self.ask.pending)

    def test_pause_freezes_the_countdown(self):
        t, out = self.start()
        self.clock.now += 100
        time.sleep(0.05)
        self.pause.clear()
        wait_until(lambda: "loop_decision_timer" in self.kinds(), "paused timer event")
        paused_evt = [d for k, d in self.events if k == "loop_decision_timer"][-1]
        self.assertTrue(paused_evt["paused"])
        self.assertAlmostEqual(paused_evt["remaining_s"], ASK_TIMEOUT_S - 100, delta=1)
        self.assertTrue(self.ask.pending["paused"])
        self.clock.now += 1000  # 暂停期间过去再久（未超暂停上限）也不计超时
        time.sleep(0.05)
        self.assertIsNotNone(self.ask.pending)
        self.pause.set()
        wait_until(lambda: not [d for k, d in self.events if k == "loop_decision_timer"][-1]["paused"], "resume event")
        resumed = [d for k, d in self.events if k == "loop_decision_timer"][-1]
        self.assertAlmostEqual(resumed["remaining_s"], ASK_TIMEOUT_S - 100, delta=1)
        self.assertAlmostEqual(resumed["deadline"], self.clock.now + ASK_TIMEOUT_S - 100, delta=1)
        self.clock.now += ASK_TIMEOUT_S  # 恢复后才继续倒计时
        t.join(5)
        self.assertEqual(self.events[-1][1]["choice"], "timeout")

    def test_pause_longer_than_the_checkpoint_limit_aborts(self):
        t, out = self.start()
        self.pause.clear()
        wait_until(lambda: "loop_decision_timer" in self.kinds())
        self.clock.now += 1801
        t.join(5)
        self.assertIsInstance(out["error"], ResearchStopped)
        self.assertEqual(self.events[-1][1]["choice"], "aborted")

    def test_answering_while_paused_still_works(self):
        t, out = self.start()
        self.pause.clear()
        wait_until(lambda: "loop_decision_timer" in self.kinds())
        self.assertTrue(self.ask.answer("stop"))
        t.join(5)
        self.assertIn("用户选择结束改进", out["reason"])

    def test_estimates_use_average_round_time(self):
        self.state = LoopState()
        usage = {"writer": {"input": 1}}
        for cycle, (score, took) in enumerate([(6.0, 600), (6.5, 1000), (6.6, 0)], start=1):
            self.ask.round_start(cycle, self.state)
            self.state.record(cycle - 1, score, f"r{cycle}", 0.1)
            if cycle < 3:
                self.clock.now += took
        out: dict = {}
        t = threading.Thread(target=lambda: out.update(r=self.ask.consult(POLICY, self.state, 3, 6.6, {}, usage)))
        t.start()
        wait_until(lambda: self.ask.pending is not None)
        data = self.events[0][1]
        self.assertEqual(data["est_seconds"], 800)  # (600 + 1000) / 2
        self.assertNotIn("est_cost_usd", data)
        self.ask.answer("continue")
        t.join(5)

    def test_estimates_are_omitted_without_finished_rounds(self):
        t, out = self.start()
        data = self.events[0][1]
        self.assertIsNone(data["est_seconds"])
        self.assertNotIn("est_cost_usd", data)
        self.ask.answer("continue")
        t.join(5)


class OrchestratorAskTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        p = mock.patch.object(orch_mod, "WORKSPACE_DIR", self.root)
        p.start()
        self.addCleanup(p.stop)

    def orchestrator(self, fake, answer="continue", on_event=None):
        """answer：收到 loop_decision 时自动给出的回答（None 表示不回答）。"""
        self.events: list[tuple[str, dict]] = []

        def cb(kind, data):
            self.events.append((kind, data))
            if kind == "loop_decision" and answer:
                o.loop_ask.answer(answer)
            if on_event:
                on_event(kind, data)
        o = orch_mod.ResearchOrchestrator(progress_callback=cb)
        for name in AGENTS:
            setattr(o, name, fake)
        o._agents = []
        return o

    def of(self, kind):
        return [d for k, d in self.events if k == kind]

    def test_asks_only_when_due_and_continue_keeps_looping(self):
        fake = FakeAgents([6.0, 6.2, 7.0, 7.9, 8.0])
        o = self.orchestrator(fake, "continue")
        o.run("固态电池", min_cycles=2, max_cycles=5, ask_loop=True)
        asks = self.of("loop_decision")
        self.assertEqual([a["cycle"] for a in asks], [2, 4])  # 第 1 轮未到最少轮数、第 3 轮快速提升、第 5 轮是最后一轮
        self.assertEqual([r["choice"] for r in self.of("loop_decision_resolved")], ["continue", "continue"])
        self.assertEqual(self.of("loop_stop"), [{"cycle": 5, "reason": "已达最大轮数 5"}])

    def test_decision_event_carries_the_facts(self):
        fake = FakeAgents([6.0, 6.2, 7.0])
        o = self.orchestrator(fake, "stop")
        o.run("固态电池", min_cycles=2, max_cycles=5, ask_loop=True)
        a = self.of("loop_decision")[0]
        self.assertEqual((a["cycle"], a["max_cycles"], a["best_draft"], a["best_score"], a["score"], a["violations"]),
                         (2, 5, 1, 6.2, 6.2, 0))
        self.assertAlmostEqual(a["gain"], 0.2)
        self.assertIn("est_seconds", a)
        self.assertNotIn("est_cost_usd", a)
        self.assertNotIn("cost_usd", self.of("stats")[0])
        self.assertEqual(a["timeout_s"], ASK_TIMEOUT_S)

    def test_stop_choice_ends_the_loop_and_final_draft_is_still_selected(self):
        fake = FakeAgents([7.0, 7.2, 8.0])
        fake.draft_texts = {0: "DRAFT-0 [C1]。", 1: "DRAFT-1 [C99]。"}  # 最优稿（第 1 版）有引用违规
        o = self.orchestrator(fake, "stop")
        result = o.run("固态电池", min_cycles=2, max_cycles=5, ask_loop=True)
        self.assertEqual(self.of("loop_stop"), [{"cycle": 2, "reason": "用户选择结束改进（当前最优 7.2）"}])
        self.assertEqual([w[0] for w in fake.writes], [0, 1])  # 初稿 + 第 1 轮后的改写；第 2 轮选择结束后不再改写
        self.assertTrue(result.startswith("DRAFT-0"))  # 最终稿选择照常：避开有违规的最优分稿
        self.assertFalse(o.interrupted)
        final = self.of("final_selected")[0]
        self.assertEqual((final["draft"], final["best_scored_draft"]), (0, 1))

    def test_stop_choice_skips_supplement_and_recheck_of_that_round(self):
        baseline = FakeAgents([7.0, 7.2, 7.5])
        baseline.claim_rounds = {1, 2, 3}  # 每轮补充研究都有新声明，补充研究不会被零增益规则跳过
        self.orchestrator(baseline, None).run("固态电池", depth="standard", min_cycles=2, max_cycles=3)
        self.assertTrue(baseline.recheck_calls)  # 不提问时第 2 轮之后会补核、补充研究、改写
        fake = FakeAgents([7.0, 7.2, 7.5])
        fake.claim_rounds = {1, 2, 3}
        self.orchestrator(fake, "stop").run("固态电池", depth="standard", min_cycles=2, max_cycles=3, ask_loop=True)
        self.assertEqual(len(fake.recheck_calls), len(baseline.recheck_calls) - 1)
        self.assertEqual(len(fake.research_rounds), len(baseline.research_rounds) - 1)
        self.assertEqual([w[0] for w in fake.writes], [w[0] for w in baseline.writes][:-1])

    def test_timeout_continues_like_no_question(self):
        fake = FakeAgents([7.0, 7.2, 7.5])
        o = self.orchestrator(fake, answer=None)
        ticks = itertools.count(0, 400)  # 每次读时钟前进 400 秒：第一次轮询就超时
        o.loop_ask._clock = lambda: next(ticks)
        o.loop_ask._poll_s = 0
        o.run("固态电池", min_cycles=2, max_cycles=3, ask_loop=True)
        self.assertEqual([r["choice"] for r in self.of("loop_decision_resolved")], ["timeout"])
        self.assertEqual(self.of("loop_stop"), [{"cycle": 3, "reason": "已达最大轮数 3"}])
        self.assertEqual([w[0] for w in fake.writes], [0, 1, 2])  # 超时后照常改写，与不提问一致

    def test_task_stop_during_the_wait_interrupts_the_task(self):
        fake = FakeAgents([7.0, 7.2, 7.5])
        stop = threading.Event()
        o = self.orchestrator(fake, answer=None, on_event=lambda k, d: stop.set() if k == "loop_decision" else None)
        result = o.run("固态电池", min_cycles=2, max_cycles=5, ask_loop=True, stop_event=stop)
        self.assertTrue(o.interrupted)
        self.assertEqual(result, "任务已中断")
        self.assertEqual([r["choice"] for r in self.of("loop_decision_resolved")], ["aborted"])
        self.assertEqual([w[0] for w in fake.writes], [0, 1])  # 第 2 轮提问处被停止，不再改写

    def test_no_question_when_the_round_stops_the_loop(self):
        fake = FakeAgents([7.0, 7.0])  # 零增益：本轮即停止
        o = self.orchestrator(fake, "continue")
        o.run("固态电池", min_cycles=2, max_cycles=5, ask_loop=True)
        self.assertEqual(self.of("loop_decision"), [])
        self.assertIn("无增益", self.of("loop_stop")[0]["reason"])

    def test_no_question_on_the_last_round(self):
        fake = FakeAgents([7.0, 7.2])
        o = self.orchestrator(fake, "continue")
        o.run("固态电池", min_cycles=2, max_cycles=2, ask_loop=True)
        self.assertEqual(self.of("loop_decision"), [])

    def test_ask_off_by_default_behaves_as_before(self):
        fake = FakeAgents([7.0, 7.2, 7.5])
        o = self.orchestrator(fake, "stop")
        o.run("固态电池", min_cycles=2, max_cycles=3)
        self.assertEqual(self.of("loop_decision"), [])
        self.assertEqual(self.of("loop_stop"), [{"cycle": 3, "reason": "已达最大轮数 3"}])

    def test_ask_setting_is_recorded_in_params_and_session(self):
        o = self.orchestrator(FakeAgents([7.0, 7.2]), "continue")
        o.run("固态电池", min_cycles=2, max_cycles=2, ask_loop=True)
        _, ctx, _ = Checkpoints(o.workspace).rollback("finish")
        self.assertIs(ctx["params"]["ask_loop"], True)
        import json
        with open(os.path.join(o.workspace, "00_session.json"), encoding="utf-8") as f:
            self.assertIs(json.load(f)["resolved_params"]["ask_loop"], True)

    def test_replay_keeps_the_ask_setting_and_old_checkpoints_mean_off(self):
        o = self.orchestrator(FakeAgents([7.0, 7.2, 7.5]), "continue")
        o.run("固态电池", min_cycles=2, max_cycles=3, ask_loop=True)
        o2 = self.orchestrator(FakeAgents([7.0, 7.2, 7.5]), "continue")
        o2.replay(o.workspace, "improve")
        self.assertEqual([a["cycle"] for a in self.of("loop_decision")], [2])  # 沿用开启

        import glob
        import json
        for path in glob.glob(os.path.join(o.workspace, ".checkpoints", "*", "state.json")):
            with open(path, encoding="utf-8") as f:
                record = json.load(f)
            record["state"]["params"].pop("ask_loop", None)  # 模拟没有该字段的旧检查点
            with open(path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False)
        o3 = self.orchestrator(FakeAgents([7.0, 7.2, 7.5]), "continue")
        o3.replay(o.workspace, "improve")
        self.assertEqual(self.of("loop_decision"), [])


class ResolveParamsAskTests(unittest.TestCase):
    def test_snapshot_records_ask_loop(self):
        self.assertIs(resolve_params("deep", "zh")["ask_loop"], False)
        self.assertIs(resolve_params("deep", "zh", ask_loop=True)["ask_loop"], True)


class LoopDecisionApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = TaskStore(os.path.join(self.tmp, "tasks.db"))
        self.calls: list[dict] = []
        for p in (mock.patch.object(app_mod, "_store", self.store),
                  mock.patch.object(app_mod, "_run_research_task", lambda *a, **k: self.calls.append(k))):
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(app_mod.app, base_url="http://127.0.0.1:8000")
        self.ask = LoopAsk(lambda t, d: None, lambda: (None, None), clock=ManualClock(), poll_s=0.005)
        self.ask.enabled = True
        app_mod._task_orchestrators["ld1"] = SimpleNamespace(loop_ask=self.ask)
        self.addCleanup(app_mod._task_orchestrators.pop, "ld1", None)

    def post(self, choice, task="ld1"):
        return self.client.post(f"/api/research/{task}/loop-decision", json={"choice": choice}, headers=HEADERS)

    def test_409_when_the_task_is_not_waiting(self):
        res = self.post("continue")
        self.assertEqual(res.status_code, 409)

    def test_200_when_waiting_and_the_wait_receives_the_choice(self):
        state, _ = state_with(6.0, 6.2)
        out: dict = {}

        def waiter():
            self.ask.round_start(2, state)
            out["reason"] = self.ask.consult(POLICY, state, 2, 6.2, {}, {})
        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        wait_until(lambda: self.ask.pending is not None)
        res = self.post("stop")
        t.join(5)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["choice"], "stop")
        self.assertIn("用户选择结束改进", out["reason"])
        self.assertEqual(self.post("stop").status_code, 409)  # 已经决定过

    def test_invalid_choice_is_422_and_unknown_task_404(self):
        self.assertEqual(self.post("maybe").status_code, 422)
        self.assertEqual(self.post("continue", task="nope").status_code, 404)

    def test_snapshot_carries_the_pending_decision(self):
        state, _ = state_with(6.0, 6.2)
        t = threading.Thread(target=lambda: (self.ask.round_start(2, state),
                                             self.ask.consult(POLICY, state, 2, 6.2, {}, {})), daemon=True)
        t.start()
        wait_until(lambda: self.ask.pending is not None)
        self.store.reserve("ld1", "q", limit=2)
        snap = app_mod._task_snapshot("ld1")["data"]
        self.assertEqual(snap["loop_decision"]["cycle"], 2)
        self.assertIn("remaining_s", snap["loop_decision"])
        self.ask.answer("continue")
        t.join(5)
        self.assertNotIn("loop_decision", app_mod._task_snapshot("ld1")["data"])

    def test_start_passes_and_audits_ask_loop(self):
        res = self.client.post("/api/research", json={"question": "固态电池", "ask_loop": True}, headers=HEADERS)
        task_id = res.json()["task_id"]
        self.assertIs(self.calls[-1]["ask_loop"], True)
        created = self.store.audit_log(task_id=task_id)[0]["payload"]
        self.assertIs(created["ask_loop"], True)
        self.assertIs(created["resolved_params"]["ask_loop"], True)

    def test_api_default_is_off(self):
        task_id = self.client.post("/api/research", json={"question": "固态电池"}, headers=HEADERS).json()["task_id"]
        self.assertIs(self.calls[-1]["ask_loop"], False)
        self.assertIs(self.store.audit_log(task_id=task_id)[0]["payload"]["ask_loop"], False)

    def test_resolved_decision_event_is_audited_as_loop_decision(self):
        class FakeOrchestrator:
            interrupted = False

            def __init__(self, progress_callback, profile=None):
                self.cb, self.workspace, self.session_id = progress_callback, "/ws/session_S7", "S7"

            def run(self, question, **kw):
                self.cb("loop_decision", {"cycle": 2, "best_score": 7.2})  # 提问本身只推送给前端
                self.cb("loop_decision_resolved", {"cycle": 2, "choice": "stop", "best_score": 7.2})
                return "报告"

        self.store.reserve("t7", "q", limit=2)
        with mock.patch("orchestrator.ResearchOrchestrator", FakeOrchestrator):
            _REAL_RUN("t7", "q", None)  # 同步执行后台任务函数（setUp 里 patch 的是模块属性）
        entries = [e for e in self.store.audit_log(task_id="t7") if e["kind"] == "loop_decision"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["payload"], {"cycle": 2, "choice": "stop", "best_score": 7.2})


if __name__ == "__main__":
    unittest.main()
