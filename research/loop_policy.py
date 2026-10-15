"""
改进循环的决策逻辑（纯函数，便于测试）

- 最优稿棘轮：分数 >= 最优分时记为新最优稿，下一版总是基于最优稿改写
- 草稿编号单调递增，被评审过的版本不会被覆盖
- 停止条件（均需先完成 min_cycles 轮）：
  1. 质量达标：评审分 >= quality_threshold 且结论验证分 >= conclusion_threshold，
     且没有阻塞项（草稿引用违规、台账中未裁决的矛盾）
  2. 零增益：连续 no_gain_patience 轮分数没有超过此前最优分 min_gain 以上
  3. 达到 max_cycles（最后一轮评审后不再改写，因为不会再被评审）
- 最终稿：无违规稿中取最高分；全部有违规时在分数相近（FINAL_SCORE_TOLERANCE）的草稿里取违规最少者
"""
from dataclasses import dataclass, field

# 全部草稿都有引用违规时，只在评审分不低于最高分减去此值的草稿里挑违规最少者
FINAL_SCORE_TOLERANCE = 0.2


@dataclass
class LoopPolicy:
    min_cycles: int
    max_cycles: int
    quality_threshold: float = 8.0
    conclusion_threshold: float = 7.5
    no_gain_patience: int = 1
    min_gain: float = 0.1


@dataclass
class LoopState:
    best_draft: int = 0
    best_score: float | None = None
    best_review_file: str | None = None
    scores: list[float] = field(default_factory=list)
    reviewed: dict[int, float] = field(default_factory=dict)   # 草稿编号 -> 评审分
    stale: int = 0
    last_draft: int = 0

    @property
    def completed(self) -> int:
        return len(self.scores)

    def record(self, draft_num: int, score: float, review_file: str, min_gain: float) -> bool:
        """记录一次评审结果，返回该草稿是否成为最优稿。"""
        self.scores.append(score)
        self.reviewed[draft_num] = score
        if self.best_score is not None and score - self.best_score < min_gain:
            self.stale += 1
        else:
            self.stale = 0
        if self.best_score is None or score >= self.best_score:
            self.best_draft, self.best_score, self.best_review_file = draft_num, score, review_file
            return True
        return False

    def next_draft(self) -> int:
        self.last_draft += 1
        return self.last_draft


def stop_reason(policy: LoopPolicy, state: LoopState, score: float,
                conclusion_avg: float | None, blockers: int = 0) -> str | None:
    """本轮评审与结论验证之后是否停止；返回停止原因，继续则返回 None。

    blockers：本轮草稿的引用违规数 + 台账中未裁决的矛盾数；大于 0 时不允许「质量达标」提前结束。
    """
    if state.completed >= policy.max_cycles:
        return f"已达最大轮数 {policy.max_cycles}"
    if state.completed < policy.min_cycles:
        return None
    if (score >= policy.quality_threshold and conclusion_avg is not None
            and conclusion_avg >= policy.conclusion_threshold and blockers == 0):
        return (f"质量达标（评审 {score:.1f} ≥ {policy.quality_threshold}，"
                f"结论 {conclusion_avg:.1f} ≥ {policy.conclusion_threshold}）")
    if state.stale >= policy.no_gain_patience:
        return f"连续 {state.stale} 轮无增益（最优 {state.best_score:.1f}）"
    return None


def pick_final(reviewed: dict[int, float], violations: dict[int, int]) -> int:
    """最终稿：存在无引用违规的草稿时，取其中评审分最高者（同分取较新）；
    全部有违规时，在评审分不低于「最高分 - FINAL_SCORE_TOLERANCE」的草稿里取违规数最少者，
    违规数同则取评审分高者，再同取较新（与上面一致，也与最优稿棘轮的同分规则一致：较新的版本含更多补充研究与修订）。"""
    clean = {d: s for d, s in reviewed.items() if violations.get(d, 0) == 0}
    if clean:
        return max(clean, key=lambda d: (clean[d], d))
    floor = max(reviewed.values()) - FINAL_SCORE_TOLERANCE - 1e-9  # 容差避免 8.2 - 0.2 之类的浮点误差
    near = [d for d, s in reviewed.items() if s >= floor]
    return min(near, key=lambda d: (violations[d], -reviewed[d], -d))
