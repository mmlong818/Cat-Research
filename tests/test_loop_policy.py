import unittest

from research.confidence import combine, component_scores, level
from research.loop_policy import FINAL_SCORE_TOLERANCE, LoopPolicy, LoopState, pick_final, stop_reason


def simulate(scores, policy, conclusion=7.0):
    """按新规则回放一组评审分：返回 (停在第几轮, 原因, 最优稿, 最优分)。"""
    state = LoopState()
    draft = 0
    for s in scores:
        state.record(draft, s, f"review_{state.completed + 1}.json", policy.min_gain)
        reason = stop_reason(policy, state, s, conclusion)
        if reason:
            return state.completed, reason, state.best_draft, state.best_score
        draft = state.next_draft()
    return state.completed, None, state.best_draft, state.best_score


POLICY = LoopPolicy(min_cycles=2, max_cycles=5)


class LoopPolicyTests(unittest.TestCase):
    def test_baseline_q1_stops_after_round_4_keeping_best(self):
        n, reason, best, score = simulate([6.8, 7.1, 7.3, 6.9, 6.4], POLICY)
        self.assertEqual((n, best, score), (4, 2, 7.3))
        self.assertIn("无增益", reason)

    def test_baseline_q2_stops_after_round_3_on_flat_score(self):
        n, reason, best, score = simulate([7.3, 8.1, 8.1, 7.1, 7.1], POLICY)
        self.assertEqual((n, score), (3, 8.1))
        self.assertIn("无增益", reason)

    def test_quality_exit_needs_both_thresholds(self):
        n, reason, _, _ = simulate([7.3, 8.1, 8.3], POLICY, conclusion=7.8)
        self.assertEqual(n, 2)
        self.assertIn("质量达标", reason)
        n, _, _, _ = simulate([7.3, 8.1, 8.3, 8.5], POLICY, conclusion=7.0)
        self.assertEqual(n, 4)  # 结论分不够，靠持续增益继续

    def test_missing_conclusion_never_counts_as_pass(self):
        n, reason, _, _ = simulate([8.5, 8.7, 8.9, 9.1, 9.3], POLICY, conclusion=None)
        self.assertEqual(n, 5)
        self.assertIn("最大轮数", reason)

    def test_min_cycles_respected_before_no_gain(self):
        n, _, _, _ = simulate([7.0, 6.0, 6.5], LoopPolicy(min_cycles=3, max_cycles=5))
        self.assertEqual(n, 3)

    def test_tie_moves_best_to_newer_draft_and_counts_as_no_gain(self):
        state = LoopState()
        state.record(0, 7.0, "r1", 0.1)
        self.assertTrue(state.record(1, 7.0, "r2", 0.1))
        self.assertEqual((state.best_draft, state.stale, state.best_review_file), (1, 1, "r2"))

    def test_draft_numbers_monotonic(self):
        state = LoopState()
        self.assertEqual([state.next_draft() for _ in range(3)], [1, 2, 3])


class BlockersAndFinalTests(unittest.TestCase):
    def test_blockers_prevent_quality_exit_but_not_other_stops(self):
        state = LoopState()
        for d, sc in enumerate([7.0, 8.5]):
            state.record(d, sc, "r", 0.1)
        self.assertIsNone(stop_reason(POLICY, state, 8.5, 8.0, blockers=2))
        self.assertIn("质量达标", stop_reason(POLICY, state, 8.5, 8.0, blockers=0))
        full = LoopState()
        for d in range(5):
            full.record(d, 9.0, "r", 0.1)
        self.assertIn("最大轮数", stop_reason(POLICY, full, 9.0, 8.0, blockers=3))

    def test_pick_final_prefers_clean_drafts(self):
        self.assertEqual(pick_final({0: 7.0, 1: 8.0, 2: 7.5}, {1: 2}), 2)
        self.assertEqual(pick_final({0: 7.0, 1: 7.0}, {}), 1)  # 同分取较新
        self.assertEqual(pick_final({0: 7.0, 1: 8.0}, {0: 1, 1: 3}), 1)  # 全有违规时取最高分


    def test_pick_final_all_violating_prefers_fewer_violations_within_tolerance(self):
        # 回归会话 20261003_035454：第 4 版 8.21 分/8 处违规，第 3 版 8.19 分/2 处，应选第 3 版
        scores = {0: 7.21, 1: 7.83, 2: 8.03, 3: 8.19, 4: 8.21}
        self.assertEqual(pick_final(scores, {0: 19, 1: 24, 2: 15, 3: 2, 4: 8}), 3)

    def test_pick_final_tolerance_window_is_closed_and_far_drafts_never_win(self):
        self.assertEqual(FINAL_SCORE_TOLERANCE, 0.2)
        self.assertEqual(pick_final({0: 8.0, 1: 8.2}, {0: 1, 1: 5}), 0)  # 恰好低 0.2：在窗口内
        self.assertEqual(pick_final({0: 7.99, 1: 8.2}, {0: 1, 1: 5}), 1)  # 低 0.21：窗口外，违规再少也不选

    def test_pick_final_all_violating_tie_breaks_by_score_then_newer(self):
        self.assertEqual(pick_final({0: 8.1, 1: 8.2}, {0: 3, 1: 3}), 1)  # 违规同数取分高
        self.assertEqual(pick_final({0: 8.2, 1: 8.2, 2: 8.2}, {0: 3, 1: 3, 2: 3}), 2)  # 全同取较新
        self.assertEqual(pick_final({0: 8.0, 1: 8.1, 2: 8.2}, {0: 1, 1: 1, 2: 4}), 1)

    def test_pick_final_clean_draft_wins_even_when_far_lower_and_single_version(self):
        self.assertEqual(pick_final({0: 6.0, 1: 8.5}, {1: 1}), 0)
        self.assertEqual(pick_final({0: 6.0, 1: 8.5, 2: 8.4}, {1: 1, 2: 0}), 2)
        self.assertEqual(pick_final({3: 7.0}, {3: 9}), 3)


SV = {"total_sources": 10, "summary": {"average_score": 80}}
FC = {"overall_confidence": 0.9}
CV = {"average_score": 7.0}


class ConfidenceTests(unittest.TestCase):
    def test_full_weights(self):
        r = combine(component_scores(SV, FC, CV))
        self.assertAlmostEqual(r["overall"], 0.8 * 0.25 + 0.9 * 0.35 + 0.7 * 0.40, places=3)
        self.assertEqual(r["missing"], [])

    def test_missing_part_renormalized_not_defaulted(self):
        r = combine(component_scores(SV, None, CV))
        self.assertAlmostEqual(r["overall"], (0.8 * 0.25 + 0.7 * 0.40) / 0.65, places=3)
        self.assertEqual(r["missing"], ["fact_accuracy"])

    def test_zero_sources_counts_as_missing(self):
        r = combine(component_scores({"total_sources": 0, "summary": {"average_score": 0}}, FC, CV))
        self.assertIn("source_quality", r["missing"])

    def test_all_missing(self):
        r = combine(component_scores(None, None, None))
        self.assertIsNone(r["overall"])
        self.assertEqual(level(r["overall"]), "unknown")


if __name__ == "__main__":
    unittest.main()
