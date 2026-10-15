"""阶段 1–5：澄清落盘、规划、网络研究（含快速失败重试与补充研究）、来源验证、声明台账、分析、初稿。"""
import os

from orchestration.base import OrchestratorBase
from research.directives import format_messages
from research.ledger import Ledger
from tools.file_tools import write_json

MIN_RESEARCH_BYTES = 1000   # 首轮研究内容低于此值视为失败，触发重试


class PhasesMixin(OrchestratorBase):
    def _phase_clarify(self, question: str, clarification: str | None = None) -> str:
        """澄清由调用方（API 的 ClarifierAgent / main.py 交互模式）在 run 之前完成，这里只落盘；
        委托时确认的补充说明接在问题后面，随问题进入各智能体的提示词。"""
        self._phase(1, "📝 阶段 1/8：意图识别与澄清", "clarifying", "问题澄清")
        final = f"{question}\n\n补充说明：{clarification}" if clarification else question
        write_json(os.path.join(self._ws, "04_clarification", "clarification.json"),
                   {"original_question": question, "analysis": "", "final_question": final})
        self._log(f"研究方向确认: {final[:200]}")
        gate = "阶段1→2"
        msgs = self._gate(gate)
        if msgs:  # 并入研究问题，随问题进入规划师、分析师、写作者与评审员的提示词
            self._question_batch = {"phase": gate, "messages": msgs}
        extra = format_messages(msgs)
        return f"{final}\n\n{extra}" if extra else final

    def _phase_plan(self, q: str, strategy: str | None, n_queries: int) -> dict:
        self._phase(2, "📋 阶段 2/8：研究规划", "planning", "研究规划")
        if self._question_batch:
            self._emit("user_message_applied", {**self._question_batch, "agents": ["planner"]})
            self._question_batch = None
        plan = self.planner.create_plan(self._ws, q, research_strategy=strategy, n_queries=n_queries)
        n_queries = len(plan["search_queries"])
        print(f"\n✅ 研究计划完成：{len(plan['key_aspects'])} 个研究维度，{n_queries} 个搜索查询", flush=True)
        self._log(f"研究计划创建完成，{n_queries} 个搜索查询")
        self._emit("plan", {**{k: plan.get(k) for k in ("objective", "domain", "key_aspects",
                                                         "search_queries", "expected_output",
                                                         "depth_requirement")},
                            "total_queries": n_queries})
        self._gate_directives("阶段2→3")
        return plan

    def _next_round(self) -> int:
        self._research_round += 1
        return self._research_round

    def _research_bytes(self) -> int:
        d = os.path.join(self._ws, "04_research")
        return sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d)
                   if os.path.isfile(os.path.join(d, f))) if os.path.isdir(d) else 0

    def _supplement(self, plan: dict, queries: list, label: str):
        """补充研究：失败只告警。某轮没有带来任何新声明后，不再做补充研究（零增益研究停止）。"""
        if self._research_exhausted:
            print(f"  [研究员] 上一轮补充研究未产生新声明，跳过{label}补充研究", flush=True)
            return None
        round_num = self._next_round()
        done = self._soft(f"{label}补充研究", self.researcher.research, self._ws, plan,
                          round_num=round_num, additional_queries=queries)
        ran = done is not None and os.path.exists(done)  # 查询全部执行过时研究员会跳过、不写文件
        if ran and Ledger.load(self._ws).new_claims_in_round(round_num) == 0:
            self._research_exhausted = True
            self._log(f"第 {round_num} 轮补充研究未产生新声明，停止后续补充研究")
        return round_num if ran else None

    def _phase_research(self, plan: dict, q: str):
        self._phase(3, "🔍 阶段 3/8：网络研究", "researching", "网络研究")
        self.researcher.research(self._ws, plan, round_num=self._next_round())
        print("\n✅ 第1轮研究完成", flush=True)
        self._log("第1轮研究完成")

        for retry in range(2):
            size = self._research_bytes()
            if size >= MIN_RESEARCH_BYTES:
                return
            print(f"\n⚠️  研究内容不足（{size} 字节），重试 {retry + 1}/2...", flush=True)
            self._supplement(plan, [q], "快速失败重试")
        if self._research_bytes() < MIN_RESEARCH_BYTES:
            print("  [警告] 重试后研究内容仍不足，继续后续流程", flush=True)

    def _phase_verify_sources(self, plan: dict, q: str, supplement: bool) -> dict:
        self._phase(3.5, "🔎 阶段 3.5/8：来源可信度验证", "verifying_sources", "来源验证")
        sv, _ = self.source_verifier.verify_sources(self._ws)
        s = sv["summary"]
        print(f"\n✅ 来源验证完成：{sv['total_sources']} 个来源\n"
              f"   高可信: {s['high_confidence_count']}  中等: {s['medium_confidence_count']}  "
              f"低可信: {s['low_confidence_count']}\n"
              f"   整体质量: {s['overall_quality']}  平均分: {s['average_score']:.1f}/100", flush=True)
        self._log(f"来源验证完成，整体质量: {s['overall_quality']}")
        if supplement and s["overall_quality"] in ("poor", "fair"):
            print("\n⚠️  来源质量不佳，触发补充研究...", flush=True)
            self._supplement(plan, [f"权威来源 {q[:40]}"], "来源质量")
        self._gate_directives("阶段3→4")
        return sv

    def _phase_ledger(self, verify_limit: int) -> dict | None:
        """声明台账：全量对账（去重、找矛盾）→ 裁决矛盾 + 独立核实关键声明。均为非关键步骤。"""
        self._phase(3.8, "📒 阶段 3.8/8：声明台账（对账 + 事实核查）", "fact_checking", "事实核查")
        self._soft("声明对账", self.reconciler.reconcile, self._ws, since_round=0)
        result = self._soft("事实核查", self.fact_checker.check_facts, self._ws, limit=verify_limit)
        ledger = Ledger.load(self._ws)
        print(f"✅ 台账：{len(ledger.citable())} 条可引用声明，{len(ledger.sources)} 个来源，"
              f"{len(ledger.contradictions)} 处矛盾（未决 {len(ledger.unresolved())}）", flush=True)
        if result is None:
            return None
        fc = result[0]
        print(f"✅ 事实核查：独立核实 {fc['total_claims_checked']} 条，置信度 {fc['overall_confidence']:.0%}",
              flush=True)
        self._log(f"事实核查完成：{fc['fact_check_summary']}")
        return fc

    def _phase_analyze(self, q: str):
        self._phase(4, "🧐 阶段 4/8：分析综合", "analyzing", "分析综合")
        self.analyst.analyze(self._ws, q)
        print("\n✅ 分析完成", flush=True)
        self._log("分析综合完成")
        self._gate_directives("阶段4→5")

    def _phase_first_draft(self, q: str, key_entities: list):
        self._phase(5, "✍️  阶段 5/8：初稿写作", "writing", "初稿写作")
        self.writer.write_draft(self._ws, q, draft_num=0, language=self._language, key_entities=key_entities)
        print("\n✅ 初稿完成", flush=True)
        self._log("初稿写作完成")
