"""结论验证员的意见进入改写：写作者改写时除评审意见外，还收到最优稿那一版的验证意见
（improvement_instructions、gaps、logic_issues），单独成节、放在评审意见之后，以评审员意见为主。
没有验证结果时提示词与没有这一机制时逐字节相同。真实编排 + 真实智能体，只替换模型调用（tests/pipeline_llm.py）。"""
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

import config
from agents import llm_agent
from agents.conclusion_validator import format_feedback
from agents.writer import WriterAgent
from llm import LLMError, LLMResult
from tests.pipeline_llm import REVIEW_KEYS, ScriptedLLM, _number, _ok, run_pipeline

HEADING = "## 结论验证员的意见"
CV = {"improvement_instructions": "补充成本数据；说明样品与量产的区别",
      "gaps": [{"gap": "缺少欧洲厂商", "importance": "high", "suggestion": "补一节欧洲进展"},
               {"gap": "时间线不完整", "importance": "low", "suggestion": "列出各年节点"}],
      "logic_issues": ["由样品能量密度直接推出量产结论，跳步"],
      "missing_perspectives": ["车企采购视角"]}


class FeedbackFormatTests(unittest.TestCase):
    def test_no_validation_gives_empty_string(self):
        self.assertEqual(format_feedback(None), "")
        self.assertEqual(format_feedback({}), "")
        self.assertEqual(format_feedback({"improvement_instructions": " ", "gaps": [], "logic_issues": []}), "")

    def test_contains_instructions_gaps_with_importance_and_suggestion_and_logic_issues(self):
        text = format_feedback(CV)
        self.assertTrue(text.startswith(HEADING))
        for needle in (CV["improvement_instructions"], "[high] 缺少欧洲厂商", "补一节欧洲进展",
                       "[low] 时间线不完整", "列出各年节点", CV["logic_issues"][0]):
            self.assertIn(needle, text)

    def test_missing_perspectives_are_left_out(self):
        self.assertNotIn("车企采购视角", format_feedback(CV))

    def test_states_priority_and_that_facts_in_it_are_no_evidence(self):
        text = format_feedback(CV)
        for needle in ("以上文的评审意见为主", "仅作补充", "冲突时听评审员的", "证据与局限性", "不能当作证据"):
            self.assertIn(needle, text)

    def test_empty_parts_are_skipped(self):
        text = format_feedback({"improvement_instructions": "只有指示", "gaps": [], "logic_issues": []})
        self.assertIn("只有指示", text)
        self.assertNotIn("缺口", text)
        self.assertNotIn("逻辑问题", text)


class WriterPromptTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, True)
        os.makedirs(os.path.join(self.ws, "06_drafts"))
        os.makedirs(os.path.join(self.ws, "07_reviews"))
        with open(os.path.join(self.ws, "06_drafts", "draft_0.md"), "w", encoding="utf-8") as f:
            f.write("上一版正文")
        with open(os.path.join(self.ws, "07_reviews", "review_1.json"), "w", encoding="utf-8") as f:
            f.write('{"marker": "评审意见REVIEW"}')
        self.prompts: list[str] = []
        p = mock.patch.object(llm_agent, "call", self.fake_call)
        p.start()
        self.addCleanup(p.stop)

    def fake_call(self, req):
        self.prompts.append(req.prompt)
        return LLMResult(text="# 新报告", data=None, duration_ms=0, num_turns=1, session_id="s",
                         model_usage={})

    def rewrite(self, **kw) -> str:
        WriterAgent().write_draft(self.ws, "问题", draft_num=1, base_draft=0,
                                  review_file=os.path.join(self.ws, "07_reviews", "review_1.json"),
                                  citation_issues="- [C9] 引用违规", **kw)
        return self.prompts[-1]

    def test_section_follows_review_and_citation_issues_and_precedes_materials(self):
        prompt = self.rewrite(validation_notes=format_feedback(CV))
        self.assertEqual(prompt.count(HEADING), 1)
        self.assertLess(prompt.index("评审意见REVIEW"), prompt.index(HEADING))
        self.assertLess(prompt.index("上一版的引用问题"), prompt.index(HEADING))
        self.assertLess(prompt.index(HEADING), prompt.index("## 分析报告"))
        self.assertLess(prompt.index(HEADING), prompt.index("## 改进要求"))

    def test_without_notes_prompt_is_unchanged(self):
        plain = self.rewrite()
        self.assertEqual(self.rewrite(validation_notes=""), plain)
        self.assertNotIn("结论验证员", plain)

    def test_initial_draft_never_carries_the_section(self):
        WriterAgent().write_draft(self.ws, "问题", draft_num=0, validation_notes=format_feedback(CV))
        self.assertNotIn(HEADING, self.prompts[-1])


class _ScoredLLM(ScriptedLLM):
    """评审分逐轮 6.0 / 5.0 / 5.5：第 1 版（draft_0）始终是最优稿；验证意见带上轮次，便于认出取的是哪一轮的。"""
    SCORES = {1: 6.0, 2: 5.0, 3: 5.5}

    def __init__(self, validator_fails: bool = False):
        super().__init__()
        self.validator_fails = validator_fails

    def _critic(self, prompt):
        cycle = _number(r"这是第 (\d+) 轮评审", prompt, 1)
        return _ok({"scores": dict.fromkeys(REVIEW_KEYS, self.SCORES[cycle]), "strengths": [],
                    "critical_issues": [], "missing_content": [], "additional_research_needed": [],
                    "overall_assessment": "尚可", "priority_improvements": []})

    def _conclusion_validator(self, prompt):
        if self.validator_fails:
            raise LLMError("down")
        cycle = _number(r"验证（第 (\d+) 轮）", prompt, 1)
        data = super()._conclusion_validator(prompt).data
        data["improvement_instructions"] = f"VAL-C{cycle}-INSTR"
        data["gaps"] = [{"gap": f"VAL-C{cycle}-GAP", "importance": "high", "suggestion": "补"}]
        data["logic_issues"] = [f"VAL-C{cycle}-LOGIC"]
        return _ok(data)


class RewriteWiringTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        # 评审分没涨也继续满 3 轮，才会出现「最优稿不是最新稿」
        patience = mock.patch.object(config, "NO_GAIN_PATIENCE", 3)
        patience.start()
        self.addCleanup(patience.stop)

    def rewrite_prompts(self, llm) -> list[str]:
        run_pipeline(self.root, llm)
        return [p for p in llm.prompts("writer") if "请根据评审意见改进" in p]

    def test_rewrite_uses_the_validation_of_the_best_draft_not_the_latest(self):
        prompts = self.rewrite_prompts(_ScoredLLM())
        self.assertEqual(len(prompts), 2)  # 3 轮评审，最后一轮不改写
        for prompt in prompts:  # 两次改写都基于最优稿 draft_0，即第 1 轮的验证
            for part in ("INSTR", "GAP", "LOGIC"):
                self.assertIn(f"VAL-C1-{part}", prompt)
                self.assertNotIn(f"VAL-C2-{part}", prompt)
                self.assertNotIn(f"VAL-C3-{part}", prompt)

    def test_validation_comes_after_the_review_in_the_pipeline_prompt(self):
        prompt = self.rewrite_prompts(_ScoredLLM())[0]
        self.assertLess(prompt.index("## 评审意见"), prompt.index(HEADING))

    def test_failed_validation_leaves_the_rewrite_prompt_byte_identical(self):
        with_cv = self.rewrite_prompts(_ScoredLLM())
        shutil.rmtree(self.root)
        os.makedirs(self.root)
        without_cv = self.rewrite_prompts(_ScoredLLM(validator_fails=True))
        self.assertEqual(len(without_cv), len(with_cv))
        for prompt in without_cv:
            self.assertNotIn(HEADING, prompt)
        section = re.compile(rf"\n\n{HEADING}.*?(?=\n\n## 分析报告)", re.S)
        self.assertEqual([section.sub("", p) for p in with_cv], without_cv)

    def test_last_round_does_not_rewrite_so_it_has_no_effect(self):
        llm = _ScoredLLM()
        run_pipeline(self.root, llm)
        self.assertEqual(len(llm.prompts("conclusion_validator")), 3)
        self.assertEqual(sum(HEADING in p for p in llm.prompts("writer")), 2)


if __name__ == "__main__":
    unittest.main()
