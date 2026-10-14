"""阶段 6：质量评审与改进循环（引用检查 → 评审 → 结论验证 → 停止判断 → 承重声明补核 → 补充研究 → 改写）。
停止条件与最优稿棘轮见 research.loop_policy，即时询问见 research.loop_ask。"""
import os

from agents.conclusion_validator import format_feedback
from agents.llm_agent import read_text
from agents.planner import key_entities_of
from orchestration.base import _pct
from orchestration.phases import PhasesMixin
from research.ledger import Ledger, format_violations
from research.loop_policy import LoopPolicy, LoopState, stop_reason

DIM_NAMES = {"completeness": "完整性", "accuracy": "准确性", "depth": "分析深度",
             "clarity": "逻辑清晰度", "usefulness": "实用价值", "sources": "信息来源",
             "simplicity": "简洁性"}


class ImproveLoopMixin(PhasesMixin):
    def _supplement_and_reconcile(self, plan: dict, queries: list, cycle: int):
        """循环内补充研究：新声明对账后立即裁决新出现的矛盾（保证停止前矛盾已处理）。"""
        round_num = self._supplement(plan, queries, f"第 {cycle} 轮")
        if round_num is None:
            return
        self._soft("声明对账", self.reconciler.reconcile, self._ws, since_round=round_num)
        self._soft("矛盾裁决", self.fact_checker.adjudicate, self._ws)

    def _phase_improve(self, q: str, plan: dict, sv: dict, fc: dict | None, policy: LoopPolicy,
                       max_supplements: int, recheck_budget: int):
        self._phase(6, f"🔄 阶段 6/8：质量评审与改进循环（{policy.min_cycles}-{policy.max_cycles} 轮）",
                    "improving", "评审优化")
        state, validations, current, supplements = LoopState(), {}, 0, 0
        entities = key_entities_of(plan)
        self._citations = {}
        for cycle in range(1, policy.max_cycles + 1):
            self._gate_directives(f"改进循环第{cycle}轮")
            print(f"\n{'─'*70}\n🔄 第 {cycle}/{policy.max_cycles} 轮：评审第 {current} 版\n{'─'*70}", flush=True)
            self._emit("cycle_start", {"cycle": cycle, "max": policy.max_cycles})
            self.loop_ask.round_start(cycle, state)
            self._citations[current] = self._annotate(current)
            reviewed = self._soft("评审", self.critic.review, self._ws, current, cycle,
                                 key_entities=entities, question=q)
            if reviewed is None:
                print(f"  [错误] 评审失败，结束改进循环，保留最优第 {state.best_draft} 版", flush=True)
                self._emit("loop_stop", {"cycle": cycle, "reason": "评审失败"})
                break
            review, review_file = reviewed
            score = self._record_review(state, current, review, review_file, cycle, policy)
            validations[current] = self._validate(current, sv, fc, cycle, q)
            cv = validations[current]
            reason = stop_reason(policy, state, score, cv["average_score"] if cv else None,
                                 blockers=self._blockers(current))
            if not reason:  # 本轮不停止：评审分在达标线附近徘徊时问用户是否还要再改一轮
                reason = self.loop_ask.consult(policy, state, cycle, score, self._citations, self._token_usage)
            if reason:
                print(f"\n🏁 结束改进循环：{reason}", flush=True)
                self._log(f"结束改进循环：{reason}")
                self._emit("loop_stop", {"cycle": cycle, "reason": reason})
                break
            if recheck_budget > 0:
                recheck_budget -= self._recheck_load_bearing(state, recheck_budget)
            if supplements < max_supplements and review["additional_research_needed"]:
                supplements += 1
                self._supplement_and_reconcile(plan, _to_queries(review["additional_research_needed"]), cycle)
            next_draft = self._rewrite(q, state, entities, validations.get(state.best_draft))
            if next_draft is None:
                self._emit("loop_stop", {"cycle": cycle, "reason": "改进写作失败"})
                break
            current = next_draft
        return state, validations

    def _recheck_load_bearing(self, state: LoopState, limit: int) -> int:
        """承重声明补核：最优稿中被引用最多、仍未核查且本应有一手记录的声明，按剩余预算独立核实并写回台账。
        放在「决定继续」之后、改写之前——只有紧接着还有一次改写时，核实结果（经声明表的状态）才能进入报告；
        返回消耗的预算（发起核实的条数，失败的也计入以封顶成本）。"""
        text = read_text(self._draft_path(state.best_draft))
        done = self._soft("承重声明补核", self.fact_checker.recheck, self._ws, text, limit) or []
        if done:
            print(f"   🔎 承重声明补核：独立核实第 {state.best_draft} 版中的 {len(done)} 条声明（{', '.join(done)}）",
                  flush=True)
            self._log(f"承重声明补核：{', '.join(done)}")
        return len(done)

    def _blockers(self, draft: int) -> int:
        """阻塞「质量达标」的问题数：本版引用违规 + 台账中未裁决的矛盾。"""
        n = len(self._citations[draft]["violations"]) + len(Ledger.load(self._ws).unresolved())
        if n:
            print(f"   ⛔ 阻塞项 {n} 个（引用违规或矛盾未裁决），本轮不能以质量达标结束", flush=True)
        return n

    def _record_review(self, state: LoopState, draft: int, review: dict, review_file: str,
                       cycle: int, policy: LoopPolicy) -> float:
        score = review["average_score"]
        self._display_review_summary(review, cycle)
        self._log(f"第 {cycle} 轮评审完成（第 {draft} 版），平均分: {score:.1f}")
        if state.record(draft, score, review_file, policy.min_gain):
            print(f"   ⭐ 新最优草稿: 第 {draft} 版（分数 {score:.1f}）", flush=True)
        else:
            print(f"   ↩️  未超过最优（{score:.2f}，最优 {state.best_score:.2f}），"
                  f"下一版基于第 {state.best_draft} 版改进", flush=True)
        return score

    def _validate(self, draft: int, sv: dict, fc: dict | None, cycle: int, q: str) -> dict | None:
        print(f"\n🔬 结论验证（第 {draft} 版）", flush=True)
        draft_file = os.path.join(self._ws, "06_drafts", f"draft_{draft}.md")
        result = self._soft("结论验证", self.conclusion_validator.validate_conclusions,
                            self._ws, draft_file=draft_file,
                            source_verification=sv, fact_check=fc, cycle=cycle, question=q)
        if result is None:
            return None
        cv = result[0]
        print(f"   验证结果: {cv['overall_verdict']}  平均分: {cv['average_score']:.1f}  "
              f"综合置信度: {_pct(cv['conclusion_confidence'])}", flush=True)
        self._log(f"结论验证完成: {cv['overall_verdict']}，平均分 {cv['average_score']:.1f}")
        return cv

    def _rewrite(self, q: str, state: LoopState, key_entities: list, cv: dict | None = None) -> int | None:
        """基于最优稿与其评审意见写新一版（编号单调递增）；失败返回 None。
        cv 为最优稿那一版的结论验证结果，其意见作为评审意见之外的补充一并交给写作者（没有时不附）。"""
        new = state.next_draft()
        print(f"\n✍️  改进报告：基于第 {state.best_draft} 版生成第 {new} 版", flush=True)
        issues = format_violations(self._citations.get(state.best_draft, {}).get("violations", []))
        out = self._soft("改进写作", self.writer.write_draft, self._ws, q, draft_num=new,
                         review_file=state.best_review_file, base_draft=state.best_draft,
                         citation_issues=issues, language=self._language, key_entities=key_entities,
                         validation_notes=format_feedback(cv))
        if out is None:
            print(f"  [错误] 改进写作失败，结束改进循环，保留最优第 {state.best_draft} 版", flush=True)
            return None
        print(f"✅ 第 {new} 版草稿完成（{os.path.getsize(out):,} 字节）", flush=True)
        self._log(f"第 {new} 版草稿完成")
        return new

    def _display_review_summary(self, review: dict, cycle: int):
        scores, avg = review["scores"], review["average_score"]
        print(f"\n📊 第 {cycle} 轮评审结果：\n   平均分：{avg:.1f}/10", flush=True)
        for dim, name in DIM_NAMES.items():
            v = scores.get(dim, 0)
            print(f"   {name:8s}: {'█' * int(v)}{'░' * (10 - int(v))} {v:.0f}/10", flush=True)
        issues = review["critical_issues"]
        high = sum(1 for i in issues if i["severity"] == "high")
        print(f"   关键问题：{len(issues)} 个（高优先级：{high} 个）", flush=True)
        print(f"   总体评价：{review['overall_assessment'][:100]}", flush=True)
        self._emit("review", {"cycle": cycle, "avg_score": avg, "scores": scores})


def _to_queries(requests: list) -> list:
    """评审的补充研究需求 → 研究员查询（保留所针对的声明编号与缺口说明，便于追溯）。"""
    return [{"query": r["topic"], "priority": "high", "category": "补充",
             "purpose": f"{r['reason']}（针对 {r['claim_id']}）" if r["claim_id"] else r["reason"]}
            for r in requests]
