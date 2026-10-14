"""
改进循环中的「即时询问」：评审分在达标线附近徘徊时，问用户是否还要再改一轮。

- 提问时机（should_ask，纯函数）：已完成最少轮数、本轮没有触发停止，且
  「本轮最优分提升 < ASK_GAIN_BELOW」或「当前最优分 >= ASK_SCORE_AT_LEAST」；快速提升中不打断
- 等待（LoopAsk.consult）：最长 ASK_TIMEOUT_S，超时按「继续」处理（与不提问时的行为一致）；
  暂停期间冻结倒计时，暂停超过 PAUSE_LIMIT_S 与检查点一样视为中断；停止任务立即打断等待
- 回答由 API 线程调用 answer() 送入，等待线程用 threading.Event 轮询（时钟可注入，测试不必真等）
"""
import threading
import time
from collections.abc import Callable

from agents.llm_agent import ResearchStopped
from research.loop_policy import LoopPolicy, LoopState

ASK_GAIN_BELOW = 0.3        # 本轮最优分提升小于此值：收益在变小，值得问一句
ASK_SCORE_AT_LEAST = 7.8    # 最优分已接近达标线（8.0）：可能值得就此收手
ASK_TIMEOUT_S = 300         # 提问后无人回答多久自动继续
PAUSE_LIMIT_S = 1800        # 等待决定期间暂停超过此时长按中断处理（同 orchestrator._checkpoint）
CHOICES = ("continue", "stop")

Controls = Callable[[], tuple[threading.Event | None, threading.Event | None]]


def should_ask(policy: LoopPolicy, state: LoopState, prev_best: float | None) -> bool:
    """调用时本轮评审已记录进 state，且 stop_reason 为 None。prev_best：本轮评审前的最优分（首轮为 None）。"""
    if state.completed < policy.min_cycles or state.best_score is None:
        return False
    small_gain = prev_best is not None and round(state.best_score - prev_best, 6) < ASK_GAIN_BELOW
    return small_gain or state.best_score >= ASK_SCORE_AT_LEAST


class LoopAsk:
    def __init__(self, emit: Callable[[str, dict], None], controls: Controls = lambda: (None, None),
                 timeout_s: float = ASK_TIMEOUT_S, clock: Callable[[], float] = time.time, poll_s: float = 0.25):
        self.enabled = False
        self._emit, self._controls = emit, controls
        self._timeout_s, self._clock, self._poll_s = timeout_s, clock, poll_s
        self._lock = threading.Lock()
        self._answered = threading.Event()
        self._info: dict | None = None            # 等待中的决定；None = 当前没有在等
        self._choice: str | None = None
        self._deadline = 0.0
        self._frozen: float | None = None         # 暂停中时剩余秒数
        self._rounds: list[float] = []            # 已完成各轮的耗时（秒）
        self._mark: float | None = None
        self._prev_best: float | None = None

    # ── 每轮开头调用：记录起点，顺带结算上一轮的耗时 ──────────────────

    def round_start(self, cycle: int, state: LoopState) -> None:
        now = self._clock()
        if cycle == 1:
            self._rounds = []
        elif self._mark is not None:
            self._rounds.append(now - self._mark)
        self._mark, self._prev_best = now, state.best_score

    def _estimate(self) -> dict:
        if not self._rounds:
            return {"est_seconds": None}
        return {"est_seconds": round(sum(self._rounds) / len(self._rounds))}

    # ── 回答与查询（API 线程） ──────────────────────────────────────────────

    @property
    def pending(self) -> dict | None:
        """等待中的决定（含倒计时状态），供快照恢复提示卡；没有在等则为 None。"""
        with self._lock:
            return None if self._info is None else {**self._info, **self._timer_view()}

    def answer(self, choice: str) -> bool:
        """送入用户的决定；当前没有在等（或已回答过、选项非法）返回 False。"""
        with self._lock:
            if choice not in CHOICES or self._info is None or self._choice is not None:
                return False
            self._choice = choice
            self._answered.set()
            return True

    def _timer_view(self) -> dict:
        remaining = self._frozen if self._frozen is not None else max(0.0, self._deadline - self._clock())
        return {"paused": self._frozen is not None, "remaining_s": round(remaining, 1), "deadline": self._deadline}

    # ── 决策点（编排线程） ──────────────────────────────────────────────────

    def consult(self, policy: LoopPolicy, state: LoopState, cycle: int, score: float,
                citations: dict[int, dict], usage: dict) -> str | None:
        """citations：orchestrator 的 {草稿编号: 引用检查结果}，取最优稿的违规数展示给用户。
        需要提问时发出 loop_decision 并等待；用户选择结束返回停止原因，继续/超时返回 None；
        等待中任务被停止则抛 ResearchStopped。"""
        prev = self._prev_best
        if not (self.enabled and should_ask(policy, state, prev)):
            return None
        best = state.best_score or 0.0
        info = {"cycle": cycle, "max_cycles": policy.max_cycles, "best_draft": state.best_draft,
                "best_score": round(best, 2), "score": round(score, 2),
                "gain": None if prev is None else round(best - prev, 3),
                "violations": len(citations.get(state.best_draft, {}).get("violations", [])),
                "timeout_s": self._timeout_s, **self._estimate()}
        started = self._clock()
        with self._lock:
            self._info, self._choice, self._frozen = info, None, None
            self._deadline = started + self._timeout_s
            self._answered.clear()
        self._emit("loop_decision", self.pending or info)
        choice = self._finish(self._wait(cycle))
        self._emit("loop_decision_resolved", {"cycle": cycle, "choice": choice, "best_score": info["best_score"],
                                               "waited_s": round(self._clock() - started, 1)})
        if choice == "aborted":
            raise ResearchStopped("等待用户决定时任务被停止")
        return f"用户选择结束改进（当前最优 {best:.1f}）" if choice == "stop" else None

    def _finish(self, choice: str) -> str:
        """关闭等待。超时的瞬间用户恰好点了按钮时，以用户的选择为准。"""
        with self._lock:
            if choice == "timeout" and self._choice:
                choice = self._choice
            self._info = self._frozen = None
        return choice

    def _wait(self, cycle: int) -> str:
        remaining, last, paused_for, paused = float(self._timeout_s), self._clock(), 0.0, False
        while True:
            pause_ev, stop_ev = self._controls()
            if stop_ev is not None and stop_ev.is_set():
                return "aborted"
            with self._lock:
                if self._choice:
                    return self._choice
            now = self._clock()
            dt, last = now - last, now
            is_paused = pause_ev is not None and not pause_ev.is_set()
            if is_paused:
                paused_for += dt
                if paused_for > PAUSE_LIMIT_S:
                    return "aborted"
            else:
                paused_for, remaining = 0.0, remaining - dt
                if remaining <= 0:
                    return "timeout"
            if is_paused != paused:
                paused = is_paused
                with self._lock:
                    self._frozen = remaining if paused else None
                    self._deadline = now + remaining
                self._emit("loop_decision_timer", {"cycle": cycle, **self._timer_view()})
            self._answered.wait(self._poll_s)
