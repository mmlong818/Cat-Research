"""
综合置信度：来源质量 25% + 事实准确 35% + 结论有效 40%

缺失（上游失败）的部分不用默认值填充，而是从计算中剔除并对剩余权重归一化，
在结果的 missing 中列出。三部分全缺时 overall 为 None。
"""

WEIGHTS = {"source_quality": 0.25, "fact_accuracy": 0.35, "conclusion_validity": 0.40}


def component_scores(source_verification: dict | None, fact_check: dict | None,
                     conclusion_validation: dict | None) -> dict:
    """各部分归一到 0-1；缺失为 None。没有来源的来源验证视为缺失。"""
    sv, fc, cv = source_verification, fact_check, conclusion_validation
    return {
        "source_quality": sv["summary"]["average_score"] / 100 if sv and sv.get("total_sources", 0) > 0 else None,
        "fact_accuracy": float(fc["overall_confidence"]) if fc else None,
        "conclusion_validity": cv["average_score"] / 10 if cv else None,
    }


def combine(scores: dict) -> dict:
    present = {k: v for k, v in scores.items() if v is not None}
    total_w = sum(WEIGHTS[k] for k in present)
    overall = (sum(WEIGHTS[k] * v for k, v in present.items()) / total_w) if present else None
    return {
        "overall": round(overall, 3) if overall is not None else None,
        "weights_used": {k: round(WEIGHTS[k] / total_w, 3) for k in present} if present else {},
        "missing": [k for k, v in scores.items() if v is None],
    }


def level(overall: float | None) -> str:
    if overall is None:
        return "unknown"
    return "high" if overall >= 0.75 else "medium" if overall >= 0.55 else "low"
