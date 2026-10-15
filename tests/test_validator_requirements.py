"""结论验证员知道用户的全部要求：原问题、委托时确认的补充说明与研究中途的补充指令，
只用来判断结论是否回应了这些要求（遵循要求的取舍不算「不全面」，违背的写进 gaps / logic_issues），
5 项评分标准与输出 schema 不变。真实编排 + 真实智能体，只替换模型调用（tests/pipeline_llm.py）。"""
import shutil
import tempfile
import unittest

from agents.conclusion_validator import SCORE_KEYS, VALIDATION_SCHEMA
from research.directives import GUIDE, REVIEW_GUIDE, VALIDATION_GUIDE
from tests.pipeline_llm import QUESTION, ScriptedLLM, run_pipeline
from tests.test_critic_requirements import BRIEF
from tests.test_user_directives import HEADING, M12, MC1, MC2, UP_TO_45, directives_in, inject


class ValidatorRequirementsTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def validator_prompts(self, **kw) -> list[str]:
        llm = ScriptedLLM()
        run_pipeline(self.root, llm, **kw)
        prompts = llm.prompts("conclusion_validator")
        self.assertEqual(len(prompts), 3)  # 剧本：每轮评审后各验证一次
        return prompts

    def test_validator_sees_the_question_and_the_commission_in_its_own_section(self):
        for prompt in self.validator_prompts(clarification=BRIEF):
            self.assertIn(f"## 用户的研究问题与委托内容\n{QUESTION}\n\n补充说明：{BRIEF}", prompt)

    def test_validator_sees_every_mid_run_instruction(self):
        prompts = self.validator_prompts(on_event=inject, before_run=lambda o: o._user_messages.append(M12))
        self.assertEqual([directives_in(p) for p in prompts],
                         [[*UP_TO_45, MC1], [*UP_TO_45, MC1, MC2], [*UP_TO_45, MC1, MC2]])
        for prompt in prompts:
            self.assertIn(f"【用户补充指令 1】{M12}", prompt.split(HEADING)[0])  # 阶段1→2 的那批随研究问题进来

    def test_directives_reach_the_validator_under_its_own_guide(self):
        section = self.validator_prompts(on_event=inject)[0].split(HEADING, 1)[1]
        self.assertIn(VALIDATION_GUIDE, section)
        self.assertNotIn(GUIDE, section)
        self.assertNotIn(REVIEW_GUIDE, section)

    def test_guide_says_purpose_scoring_unchanged_and_facts_are_no_evidence(self):
        for needle in ("只用于判断结论是否回应了用户要求", "gaps", "logic_issues", "5 项评分标准", "不能当作证据"):
            self.assertIn(needle, VALIDATION_GUIDE)

    def test_prompt_tells_the_validator_how_to_treat_trade_offs_and_violations(self):
        prompt = self.validator_prompts()[0]
        for needle in ("不算「覆盖全面性」不足", "不要因此扣分", "违背或遗漏", "gaps", "logic_issues",
                       "不改变 5 项评分标准"):
            self.assertIn(needle, prompt)

    def test_requirements_come_before_the_plan_and_the_draft(self):
        prompt = self.validator_prompts(clarification=BRIEF)[0]
        self.assertLess(prompt.index(BRIEF), prompt.index("## 研究计划"))
        self.assertLess(prompt.index(BRIEF), prompt.index("## 待验证的草稿"))

    def test_schema_and_scoring_dimensions_unchanged(self):
        self.assertEqual(SCORE_KEYS, ["evidence_sufficiency", "logical_rigor", "coverage_completeness",
                                      "practical_value", "limitations_acknowledged"])
        self.assertEqual(list(VALIDATION_SCHEMA["properties"]),
                         ["validation_scores", "strengths", "gaps", "logic_issues", "missing_perspectives",
                          "overall_verdict", "improvement_instructions"])
        self.assertEqual(VALIDATION_SCHEMA["required"], list(VALIDATION_SCHEMA["properties"]))
        self.assertEqual(list(VALIDATION_SCHEMA["properties"]["gaps"]["items"]["properties"]),
                         ["gap", "importance", "suggestion"])


if __name__ == "__main__":
    unittest.main()
