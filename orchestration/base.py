"""
编排基础设施：智能体初始化、进度事件、阶段间检查点（停止 / 暂停 / 用户消息）、状态与日志、
非关键步骤降级，以及草稿路径与引用附录。各阶段的实现见同包的 phases / improve / finish。
"""
import os
import time
from collections.abc import Callable
from datetime import datetime
from functools import partial
from typing import Any

from agents.analyst import AnalystAgent
from agents.conclusion_validator import ConclusionValidatorAgent
from agents.critic import CriticAgent
from agents.fact_checker import FactCheckerAgent
from agents.llm_agent import ResearchStopped, read_text
from agents.planner import PlannerAgent
from agents.reconciler import ReconcilerAgent
from agents.researcher import ResearcherAgent
from agents.source_verifier import SourceVerifierAgent
from agents.writer import WriterAgent
from llm import LLMError
from llm.profiles import Profile, default_profile
from research.directives import Directives, format_messages
from research.ledger import Ledger, with_references
from research.loop_ask import LoopAsk
from tools.file_tools import append_to_log, is_workspace_deleted, read_json, write_file, write_json

# 接收「用户补充要求」的智能体：研究员（检索）、事实核查员（只用于矛盾裁决；独立核实不经 LLMAgent.request，
# 刻意不带任何先验材料）、分析师、写作者，以及评审员与结论验证员（只用来检查报告 / 结论是否满足用户要求，
# 评分标准不变，见 research.directives.REVIEW_GUIDE / VALIDATION_GUIDE）。阶段1→2 的消息并入研究问题；
# 来源验证员在阶段3→4 检查点之前已完成，对账员只做声明间比对，均不注入。
DIRECTED_ROLES = ("researcher", "fact_checker", "analyst", "writer", "critic", "conclusion_validator")


class _Interrupted(Exception):
    """检查点收到停止/暂停超时"""


def _pct(v, na: str = "N/A（未完成）") -> str:
    return f"{v:.0%}" if isinstance(v, (int, float)) else na


class OrchestratorBase:
    def __init__(self, progress_callback: Callable | None = None, profile: Profile | None = None):
        self.profile = profile or default_profile()  # 本任务的模型配置档；不传时取当前 config（不改全局变量）
        self.workspace: str | None = None
        self.session_id: str | None = None
        self.log_file: str | None = None
        self.progress_callback = progress_callback  # API 模式下的进度回调
        self._user_messages: list[str] = []          # 用户中途注入的消息列表（api/app.py 直接追加）
        self._pause_event = None          # threading.Event，None=不暂停，clear=暂停中
        self._stop_event = None           # threading.Event，set=立即停止
        self._token_usage: dict[str, dict[str, Any]] = {}  # 各 Agent 用量 {agent: {input, cached_input, output}}
        self._research_round = 0
        self._research_exhausted = False  # 补充研究零增益后置 True
        self._language = "zh"             # 报告语言，_pipeline 开始时按任务参数设置
        self._started_at: float = time.time()  # run/replay 开始时由 _prepare 重置
        self.interrupted = False          # 因停止/暂停超时而中断（run/replay 此时返回提示文本而非报告）
        self.loop_ask = LoopAsk(self._emit, lambda: (self._pause_event, self._stop_event))  # 改进循环中的询问
        self._directives = Directives(self._emit)   # 各检查点累积的用户补充要求，持续进入 DIRECTED_ROLES 的提示词
        self._question_batch: dict | None = None    # 阶段1→2 的消息（已并入研究问题），规划时发出 applied

        print("\n🔧 正在初始化智能体...", flush=True)
        role = self.profile.model_for
        self.planner = PlannerAgent(model=role("planner"))
        self.researcher = ResearcherAgent(model=role("researcher"))
        self.analyst = AnalystAgent(model=role("analyst"))
        self.writer = WriterAgent(model=role("writer"))
        self.critic = CriticAgent(model=role("critic"))
        self.source_verifier = SourceVerifierAgent(model=role("source_verifier"))
        self.fact_checker = FactCheckerAgent(model=role("fact_checker"))
        self.conclusion_validator = ConclusionValidatorAgent(model=role("conclusion_validator"))
        self.reconciler = ReconcilerAgent(model=role("reconciler"))
        self._agents = [self.planner, self.researcher, self.analyst, self.writer, self.critic,
                        self.source_verifier, self.fact_checker, self.conclusion_validator,
                        self.reconciler]
        for agent in self._agents:
            agent.stream_callback = self._emit
        for name in DIRECTED_ROLES:
            getattr(self, name).directives = partial(self._directives.section, name)
        print("✅ 所有智能体已就绪（含验证智能体）", flush=True)

    @property
    def _ws(self) -> str:
        """阶段方法使用的工作空间路径（run/replay 先于各阶段设置）"""
        if self.workspace is None:
            raise RuntimeError("工作空间尚未创建")
        return self.workspace

    def _emit(self, event_type: str, data: dict):
        """统计用量并转发进度事件（API 模式）"""
        if event_type == "token_usage":
            u = self._token_usage.setdefault(data.get("agent", "unknown"),
                                             {"input": 0, "cached_input": 0, "output": 0})
            u["input"] += data.get("total_input", 0)
            u["cached_input"] = u.get("cached_input", 0) + data.get("cached_input", 0)  # 旧检查点没有该字段
            u["output"] += data.get("total_output", 0)
        if self.progress_callback:
            self.progress_callback(event_type, data)

    def _checkpoint(self, phase_name: str) -> list[str] | None:
        """
        阶段间检查点：停止返回 None；暂停时阻塞等待恢复（最多 30 分钟）；
        返回本检查点取走的用户消息（并发出 user_message_ack），没有时为空列表。
        """
        if self._stop_event and self._stop_event.is_set():
            print(f"\n🛑 收到停止信号（阶段：{phase_name}），立即终止", flush=True)
            return None

        if self._pause_event is not None and not self._pause_event.is_set():
            self._emit("paused", {"phase": phase_name})
            print(f"\n⏸️  任务已暂停（阶段：{phase_name}），等待恢复...", flush=True)
            self._pause_event.wait(timeout=1800)
            if not self._pause_event.is_set():
                return None
            self._emit("resumed", {"phase": phase_name})
            print(f"\n▶️  任务已恢复（阶段：{phase_name}）", flush=True)

        if not self._user_messages:
            return []
        msgs = self._user_messages[:]
        del self._user_messages[:len(msgs)]  # 只删取走的：其间 API 线程新追加的留给下一个检查点
        combined = format_messages(msgs)
        self._emit("user_message_ack", {"messages": msgs, "phase": phase_name})
        print(f"\n💬 接收到用户指令（阶段 {phase_name}）：{combined[:100]}", flush=True)
        self._log(f"用户指令注入 at {phase_name}: {combined[:200]}")
        return msgs

    def _gate(self, phase_name: str) -> list[str]:
        msgs = self._checkpoint(phase_name)
        if msgs is None:
            raise _Interrupted(phase_name)
        return msgs

    def _gate_directives(self, phase_name: str):
        """检查点取到的用户消息并入累积的补充要求，此后持续进入 DIRECTED_ROLES 的提示词。"""
        self._directives.add(phase_name, self._gate(phase_name))

    def _log(self, message: str):
        if self.log_file:
            append_to_log(self.log_file, message)

    def _update_status(self, status: str, extra: dict | None = None):
        if not self.workspace or is_workspace_deleted(self.workspace):  # 会话已被删除：不再写状态，也不再广播
            return
        meta_file = os.path.join(self.workspace, "00_session.json")
        meta = read_json(meta_file) if os.path.exists(meta_file) else {}
        meta["status"] = status
        meta["last_updated"] = datetime.now().isoformat()
        if extra:
            meta.update(extra)
        write_json(meta_file, meta)
        self._emit("status", {"status": status, **(extra or {})})

    def _phase(self, num, title: str, status: str, name: str):
        print(f"\n{'='*70}\n{title}\n{'='*70}", flush=True)
        self._update_status(status)
        self._emit("phase", {"phase": num, "name": name})

    def _soft(self, what: str, fn, *args, **kwargs):
        """执行非关键步骤：调用失败只告警并返回 None；停止请求照常向上抛。"""
        try:
            return fn(*args, **kwargs)
        except ResearchStopped:
            raise
        except LLMError as e:
            print(f"  [警告] {what}失败: {e}", flush=True)
            self._log(f"{what}失败: {e}")
            return None

    def _draft_path(self, draft: int) -> str:
        return os.path.join(self._ws, "06_drafts", f"draft_{draft}.md")

    def _annotate(self, draft: int, verbose: bool = True) -> dict:
        """按当前台账重新生成草稿的「声明来源」附录并检查引用；返回检查结果。"""
        path = self._draft_path(draft)
        text, check = with_references(Ledger.load(self._ws), read_text(path), self._language)
        write_file(path, text)
        if verbose:
            cov = check["numeric_coverage"]
            print(f"   📎 第 {draft} 版引用：{len(check['cited'])} 条声明，数字句覆盖率 "
                  f"{'N/A' if cov is None else f'{cov:.0%}'}，违规 {len(check['violations'])} 处", flush=True)
        return check
