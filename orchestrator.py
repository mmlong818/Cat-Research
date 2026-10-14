"""
ResearchOrchestrator - 研究协调器
统一协调所有智能体的工作，管理完整的研究流程：
规划 → 研究 → 来源验证 → 声明台账（对账 + 事实核查）→ 分析 → 初稿
→ 评审/结论验证/补充研究（+对账裁决）/改写循环 → 置信度报告
本文件是入口与阶段流水线（含检查点、重放、工作空间与历史记录）；各阶段实现见 orchestration 包，
改进循环的停止与最优稿选择见 research.loop_policy，声明台账见 research.ledger。
"""
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime

# Windows GBK 控制台 emoji 兼容（reconfigure 原地修改；重新包装 buffer 会在旧包装被回收时关闭它）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import config as _config
from agents.llm_agent import ResearchStopped, read_text
from agents.planner import key_entities_of
from config import WORKSPACE_DIR  # 模型与循环参数在运行时读取 _config.*（API 可在运行中修改）
from orchestration.base import _Interrupted
from orchestration.finish import FinishMixin, _violations_appendix
from orchestration.improve import ImproveLoopMixin
from research.checkpoints import PHASES, Checkpoints, params_hash
from research.loop_policy import LoopPolicy, LoopState
from research.params import resolve_cycles, resolve_params
from tools.file_tools import (
    WorkspaceDeleted,
    append_to_log,
    read_json,
    write_file,
    write_json,
)

INTENT_STRATEGY_HINT = {
    "info_seeking":    "综合信息汇总，注重广度和来源多样性，覆盖主流观点与最新动态",
    "problem_solving": "聚焦问题根因与解决路径，注重深度分析，优先找到可执行的答案",
    "exploration":     "开放式探索，鼓励发现新方向与潜在机会，不限于已知框架",
    "optimization":    "多方案横向对比评估，注重客观数据与实测结果，找出最优选择",
    "task_completion": "产出结构化、可直接使用的成果，注重实用性和完整性",
}


class ResearchOrchestrator(ImproveLoopMixin, FinishMixin):
    """多智能体研究系统主协调器（接口供 main.py 与 api/app.py 使用）"""

    # ── 工作空间 ────────────────────────────────────────────────────────────

    def _create_workspace(self, question: str, extra: dict | None = None) -> str:
        """创建本次研究的工作空间"""
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        workspace = os.path.join(WORKSPACE_DIR, f"session_{self.session_id}")
        for subdir in ["04_research", "04_clarification", "06_drafts", "07_reviews",
                       "08_verification", "08_messages"]:
            os.makedirs(os.path.join(workspace, subdir), exist_ok=True)

        write_json(os.path.join(workspace, "00_session.json"), {
            "session_id": self.session_id,
            "created_at": datetime.now().isoformat(),
            "question": question,
            "status": "initialized",
            "model": self.profile.core,
            "provider": self.profile.provider,
            **(extra or {}),
        })
        write_file(os.path.join(workspace, "01_question.txt"), question)

        self.log_file = os.path.join(workspace, "research_log.txt")
        append_to_log(self.log_file, f"研究会话启动: {question}")
        print(f"\n📁 工作空间: {workspace}", flush=True)
        self._emit("session", {"session_id": self.session_id, "workspace": workspace})
        return workspace

    def _attach_workspace(self, workspace: str):
        """重放：接管已有会话的工作空间。"""
        self.workspace = workspace
        self.session_id = os.path.basename(os.path.normpath(workspace)).removeprefix("session_")
        self.log_file = os.path.join(workspace, "research_log.txt")
        self._emit("session", {"session_id": self.session_id, "workspace": workspace})

    # ── 入口 ────────────────────────────────────────────────────────────────

    def run(self, question: str, research_strategy: str | None = None,
            intent_meta: dict | None = None,
            pause_event=None, stop_event=None,
            min_cycles: int | None = None,
            max_cycles: int | None = None,
            depth: str | None = None,
            language: str = "zh",
            max_queries: int | None = None,
            ask_loop: bool = False,
            clarification: str | None = None):
        """执行完整的研究流程，返回最终报告正文（中断时返回提示文本）。

        depth：研究深度档（config.DEPTH_PRESETS），默认 config.DEFAULT_DEPTH。
        min_cycles / max_cycles：本次任务级别的轮数覆盖，优先于档位的轮数范围。
        language：最终报告的撰写语言（zh/en），写入检查点参数，重放沿用。
        max_queries：覆盖档位的规划查询数。ask_loop：改进循环中即时询问用户是否继续（需有界面应答，默认关）。
        clarification：委托时确认的补充说明；与研究问题分开存，进入提示词时接在问题后面。
        """
        self._prepare(pause_event, stop_event)
        print(f"\n{'='*70}\n🚀 多智能体研究系统启动（含质量验证流程）\n{'='*70}", flush=True)
        depth = depth or _config.DEFAULT_DEPTH
        policy = self._loop_policy(intent_meta, depth, min_cycles, max_cycles)
        params = {"question": question, "clarification": clarification,
                  "strategy": self._strategy(intent_meta, research_strategy),
                  "policy": asdict(policy), "depth": depth, "language": language,
                  "max_queries": max_queries, "ask_loop": ask_loop}
        self.workspace = self._create_workspace(question, {
            "clarification": clarification,
            "language": language,
            "resolved_params": resolve_params(depth, language, min_cycles, max_cycles, max_queries,
                                              self.profile, ask_loop)})
        return self._guarded({"params": params}, 0)

    def replay(self, workspace: str, from_phase: str | None = None, pause_event=None, stop_event=None):
        """在已有会话上重放：workspace 回滚到 from_phase 前一阶段的检查点后继续跑完。
        from_phase 为 None 时从断点续跑（第一个没有检查点的阶段）。沿用检查点里的问题、策略与轮数策略。"""
        self._prepare(pause_event, stop_event)
        start, ctx, old_hash = Checkpoints(workspace).rollback(from_phase)
        self._attach_workspace(workspace)
        runtime = ctx.pop("runtime")
        self._research_round, self._research_exhausted = runtime["research_round"], runtime["research_exhausted"]
        self._token_usage = runtime["token_usage"]
        self._directives.restore(runtime.get("directives"))  # 用户补充要求沿用；旧检查点没有该字段
        print(f"\n{'='*70}\n🔁 重放研究会话 {self.session_id}：从阶段 {PHASES[start]} 开始\n{'='*70}", flush=True)
        self._log(f"重放：从阶段 {PHASES[start]} 开始")
        if old_hash != self._params_hash(ctx["params"]):
            print("  [提示] 模型配置与检查点生成时不同，后续阶段将使用当前配置", flush=True)
            self._log("重放时模型配置已变更")
        return self._guarded(ctx, start)

    def _prepare(self, pause_event, stop_event):
        self._pause_event = pause_event
        self._stop_event = stop_event
        for agent in self._agents:
            agent.stop_event = stop_event
        self._started_at = time.time()

    def _guarded(self, ctx: dict, start: int) -> str:
        try:
            return self._pipeline(ctx, start)
        except (_Interrupted, ResearchStopped, WorkspaceDeleted) as e:  # 会话被删除时写盘处抛 WorkspaceDeleted
            print(f"\n🛑 任务已中断：{e}", flush=True)
            self.interrupted = True
            self._update_status("stopped")
            return "任务已中断"

    def _loop_policy(self, intent_meta, depth, min_cycles, max_cycles) -> LoopPolicy:
        preset = _config.DEPTH_PRESETS[depth]
        min_eff, max_eff = resolve_cycles(preset, min_cycles, max_cycles)
        intent = (intent_meta or {}).get("intent_type", "info_seeking")
        print(f"🎯 意图类型: {intent} | 研究深度: {depth} | 改进轮数: {min_eff}-{max_eff}", flush=True)
        return LoopPolicy(min_cycles=min_eff, max_cycles=max_eff,
                          quality_threshold=_config.QUALITY_THRESHOLD,
                          conclusion_threshold=_config.CONCLUSION_THRESHOLD,
                          no_gain_patience=_config.NO_GAIN_PATIENCE)

    def _strategy(self, intent_meta, research_strategy) -> str | None:
        hint = INTENT_STRATEGY_HINT.get((intent_meta or {}).get("intent_type", "info_seeking"), "")
        if not hint:
            return research_strategy
        line = f"研究策略偏向：{hint}"
        return f"{research_strategy}\n{line}" if research_strategy else line

    def _pipeline(self, ctx: dict, start: int) -> str:
        """按 PHASES 顺序执行各阶段；每个阶段完成后写检查点（ctx 为阶段间传递的可 JSON 化上下文）。"""
        checkpoints = Checkpoints(self._ws)
        digest = self._params_hash(ctx["params"])
        self._language = ctx["params"].get("language", "zh")  # V4 之前的检查点没有该字段
        for phase in PHASES[start:]:
            getattr(self, f"_step_{phase}")(ctx)
            runtime = {"research_round": self._research_round, "research_exhausted": self._research_exhausted,
                       "token_usage": self._token_usage, "directives": self._directives.batches}
            checkpoints.save(phase, {**{k: v for k, v in ctx.items() if k != "result"}, "runtime": runtime}, digest)
            self._emit("checkpoint", {"phase": phase, "params_hash": digest})
        return ctx["result"]

    def _params_hash(self, params: dict) -> str:
        return params_hash(params, {"core": self.profile.core, "support": self.profile.support})

    @staticmethod
    def _preset(ctx) -> dict:
        # E5 之前的检查点没有 depth，当时的行为等同 deep 档
        return _config.DEPTH_PRESETS[ctx["params"].get("depth", "deep")]

    def _step_clarify(self, ctx):
        ctx["q"] = self._phase_clarify(ctx["params"]["question"], ctx["params"].get("clarification"))

    def _step_plan(self, ctx):
        n_queries = ctx["params"].get("max_queries") or self._preset(ctx)["queries"]  # V5 之前的检查点没有该字段
        ctx["plan"] = self._phase_plan(ctx["q"], ctx["params"]["strategy"], n_queries)

    def _step_research(self, ctx):
        self._phase_research(ctx["plan"], ctx["q"])

    def _step_sources(self, ctx):
        ctx["sv"] = self._phase_verify_sources(ctx["plan"], ctx["q"], self._preset(ctx)["source_supplement"])

    def _step_ledger(self, ctx):
        ctx["fc"] = self._phase_ledger(self._preset(ctx)["verify"])

    def _step_analyze(self, ctx):
        self._phase_analyze(ctx["q"])

    def _step_draft(self, ctx):
        self._phase_first_draft(ctx["q"], key_entities_of(ctx["plan"]))

    def _step_improve(self, ctx):
        policy = LoopPolicy(**ctx["params"]["policy"])
        preset = self._preset(ctx)
        self.loop_ask.enabled = ctx["params"].get("ask_loop", False)  # 旧检查点没有该字段，按关闭处理
        state, validations = self._phase_improve(ctx["q"], ctx["plan"], ctx["sv"], ctx["fc"], policy,
                                                 preset["supplements"], preset["recheck"])
        ctx["loop"] = asdict(state)
        ctx["validations"] = {str(d): cv for d, cv in validations.items()}  # JSON 键只能是字符串

    def _step_finish(self, ctx):
        loop = ctx["loop"]
        state = LoopState(**{**loop, "reviewed": {int(d): s for d, s in loop["reviewed"].items()}})
        final = self._select_final(state)
        report_file = self._phase_confidence(ctx["sv"], ctx["fc"], ctx["validations"].get(str(final["draft"])))
        params = ctx["params"]
        ctx["result"] = self._phase_finish(params["question"], params["strategy"], state,
                                           ctx["sv"], ctx["fc"], report_file, final)

    # ── 收尾写盘 ────────────────────────────────────────────────────────────

    def _phase_finish(self, question, strategy, state: LoopState, sv, fc, report_file, final: dict) -> str:
        elapsed = time.time() - self._started_at
        final_file = os.path.join(self._ws, "09_final.md")
        draft, check = final["draft"], final["check"]
        score = state.reviewed.get(draft, 0.0)
        write_file(final_file, read_text(self._draft_path(draft)) + _violations_appendix(check, self._language)
                   + self._quality_appendix(read_json(report_file), state, draft, score))

        citations = {"cited_claims": len(check["cited"]), "violations": len(check["violations"]),
                     "numeric_coverage": check["numeric_coverage"]}
        self._emit("stats", {
            "cycles": state.completed,
            "claims_checked": fc["total_claims_checked"] if fc else 0,
            "total_sources": sv["total_sources"],
            "final_score": round(score, 1),
            "elapsed_seconds": round(elapsed),
            **citations,
        })
        self._update_status("completed", {
            "total_cycles": state.completed, "final_score": score,
            "final_draft": draft, "best_scored_draft": state.best_draft, "score_history": state.scores,
            "final_report": final_file, "elapsed_seconds": round(elapsed), "citations": citations,
            "token_usage": self._usage_summary(),
        })
        self._log(f"研究完成，共 {state.completed} 轮评审，最终采用第 {draft} 版（{score:.1f}）")
        self._append_history(question, strategy, state)
        print(f"\n{'='*70}\n🎊 研究完成！\n{'='*70}\n"
              f"📊 质量分数历程: {' → '.join(f'{s:.1f}' for s in state.scores)}\n"
              f"🏆 最终采用: 第 {draft} 版（{score:.1f}）| 引用 {citations['cited_claims']} 条声明，"
              f"违规 {citations['violations']} 处\n"
              f"⏱️  总耗时: {elapsed / 60:.1f} 分钟\n"
              f"📁 工作空间: {self._ws}\n📄 最终报告: {final_file}\n"
              f"📋 置信度报告: {report_file}", flush=True)
        return read_text(final_file)

    def _append_history(self, question, strategy, state: LoopState):
        entry = {"session_id": self.session_id, "timestamp": datetime.now().isoformat(),
                 "question": question, "research_strategy": strategy,
                 "final_score": state.best_score, "total_cycles": state.completed,
                 "score_history": state.scores, "best_score": state.best_score,
                 "workspace": self.workspace}
        try:
            with open(os.path.join(WORKSPACE_DIR, "research_history.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:
            print(f"  [警告] 历史记录写入失败: {e}", flush=True)
