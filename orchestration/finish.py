"""阶段 7–8 的计算部分：用最终台账选定终稿、综合置信度报告、报告附录（引用问题与研究质量）、用量汇总。"""
import os
from datetime import datetime

from orchestration.base import OrchestratorBase, _pct
from research.confidence import combine, component_scores, level
from research.ledger import QUALITY_HEADINGS, VIOLATIONS_HEADINGS, format_violations, heading_for
from research.loop_policy import LoopState, pick_final
from tools.file_tools import write_json

# 研究质量报告附录里的固定文字（随报告语言；标题见 research.ledger.QUALITY_HEADINGS）
QUALITY_TEXT = {
    "zh": {"na": "N/A（未完成）", "dimension": "维度", "score": "评分", "overall": "综合置信度",
           "source": "来源质量", "fact": "事实准确度", "conclusion": "结论有效性", "rounds": "评审轮数",
           "final": "最终评审分", "rounds_value": "{n} 轮", "final_value": "{score:.1f}/10（第 {draft} 版）",
           "footer": "本报告由多智能体研究系统自动生成，包含来源验证、事实核查和结论验证流程"},
    "en": {"na": "N/A (incomplete)", "dimension": "Dimension", "score": "Score", "overall": "Overall confidence",
           "source": "Source quality", "fact": "Fact accuracy", "conclusion": "Conclusion validity",
           "rounds": "Review rounds", "final": "Final review score", "rounds_value": "{n}",
           "final_value": "{score:.1f}/10 (draft {draft})",
           "footer": "This report was generated automatically by a multi-agent research system, "
                     "including source verification, fact checking and conclusion validation"},
}


class FinishMixin(OrchestratorBase):
    def _select_final(self, state: LoopState) -> dict:
        """用最终台账复查每一版评审过的草稿，按 pick_final 选：无违规者取最高分；全有违规时在分数相近者中取违规最少。"""
        if not state.reviewed:
            self._emit("final_selected", {"draft": 0, "best_scored_draft": None, "reason": "没有评审过的草稿"})
            return {"draft": 0, "check": self._annotate(0, verbose=False)}
        checks = {d: self._annotate(d, verbose=False) for d in state.reviewed}
        violations = {d: len(c["violations"]) for d, c in checks.items()}
        final = pick_final(state.reviewed, violations)
        if final != state.best_draft:
            print(f"\n📌 最终稿选第 {final} 版：最优分的第 {state.best_draft} 版存在引用违规", flush=True)
        self._emit("final_selected", {"draft": final, "best_scored_draft": state.best_draft,
                                      "scores": {str(d): s for d, s in state.reviewed.items()},
                                      "violations": {str(d): n for d, n in violations.items()}})
        return {"draft": final, "check": checks[final]}

    def _phase_confidence(self, sv: dict, fc: dict | None, cv: dict | None) -> str:
        """综合置信度报告（针对最终采用的最优稿）；缺失部分剔除后归一化。"""
        self._phase(7, "📊 阶段 7/8：生成置信度报告", "confidence_report", "置信度报告")
        report = build_confidence_report(sv, fc, cv)
        report_file = os.path.join(self._ws, "08_verification", "confidence_report.json")
        write_json(report_file, report)
        self._emit("confidence_report", report)
        print(f"✅ 置信度报告生成完成（综合 {_pct(report['overall_confidence'])}"
              f"{'，缺失: ' + ', '.join(report['missing']) if report['missing'] else ''}）", flush=True)
        self._log("置信度报告生成完成")
        return report_file

    def _quality_appendix(self, conf: dict, state: LoopState, draft: int, score: float) -> str:
        bd = conf["breakdown"]
        t = QUALITY_TEXT.get(self._language, QUALITY_TEXT["zh"])
        na = t["na"]
        return f"""

---
## {heading_for(QUALITY_HEADINGS, self._language)}

| {t['dimension']} | {t['score']} |
|------|------|
| {t['overall']} | {_pct(conf['overall_confidence'], na)} |
| {t['source']} | {bd['source_quality']['quality_rating'] or na} |
| {t['fact']} | {_pct(bd['fact_accuracy']['score'], na)} |
| {t['conclusion']} | {_pct(bd['conclusion_validity']['score'], na)} |
| {t['rounds']} | {t['rounds_value'].format(n=state.completed)} |
| {t['final']} | {t['final_value'].format(score=score, draft=draft)} |

*{t['footer']}*
"""

    def _usage_summary(self) -> dict:
        total_in = sum(u["input"] for u in self._token_usage.values())
        total_out = sum(u["output"] for u in self._token_usage.values())
        cached = sum(u.get("cached_input", 0) for u in self._token_usage.values())
        return {"total_input": total_in, "total_cached_input": cached, "total_output": total_out,
                "total": total_in + total_out,
                "by_agent": self._token_usage}


def _violations_appendix(check: dict, language: str = "zh") -> str:
    """最终稿仍有引用违规时如实列出（所有评审过的版本都有违规时才会出现）。"""
    if not check["violations"]:
        return ""
    return (f"\n\n## {heading_for(VIOLATIONS_HEADINGS, language)}\n"
            f"{format_violations(check['violations'], language)}\n")


def build_confidence_report(sv: dict | None, fc: dict | None, cv: dict | None) -> dict:
    """置信度报告（字段与前端 ConfidenceReport 兼容；缺失部分 score 为 None、weight 标"未完成"）。"""
    scores = component_scores(sv, fc, cv)
    combined = combine(scores)
    w = combined["weights_used"]

    def weight(k):
        return f"{w[k]:.0%}" if k in w else "未完成"

    sv_summary = (sv or {}).get("summary", {})
    return {
        "generated_at": datetime.now().isoformat(),
        "overall_confidence": combined["overall"],
        "confidence_level": level(combined["overall"]),
        "missing": combined["missing"],
        "breakdown": {
            "source_quality": {"weight": weight("source_quality"), "score": scores["source_quality"],
                               "average_domain_score": sv_summary.get("average_score"),
                               "quality_rating": sv_summary.get("overall_quality"),
                               "high_confidence_sources": sv_summary.get("high_confidence_count", 0)},
            "fact_accuracy": {"weight": weight("fact_accuracy"), "score": scores["fact_accuracy"],
                              "claims_checked": fc["total_claims_checked"] if fc else 0,
                              "disputed_claims_count": len(fc["disputed_claims"]) if fc else 0,
                              "degraded": bool(fc and fc.get("degraded"))},
            "conclusion_validity": {"weight": weight("conclusion_validity"),
                                    "score": scores["conclusion_validity"],
                                    "average_validation_score": cv["average_score"] if cv else None,
                                    "overall_verdict": cv["overall_verdict"] if cv else None},
        },
        "top_sources": (sv or {}).get("top_sources", []),
        "disputed_claims": fc["disputed_claims"][:5] if fc else [],
        "gaps": cv["gaps"] if cv else [],
        "recommended_improvements": cv["improvement_instructions"] if cv else "",
    }
