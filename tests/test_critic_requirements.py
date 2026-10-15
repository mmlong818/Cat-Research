"""评审员知道用户的全部要求：原问题、委托时确认的补充说明（研究目标、范围、排除内容、特别要求）与研究中途的补充指令，
只用来检查报告是否满足这些要求（违背的写进 critical_issues 与 priority_improvements），7 维评分标准不变。
真实编排 + 真实智能体，只替换模型调用（tests/pipeline_llm.py）。"""
import shutil
import tempfile
import unittest

from research.directives import GUIDE, REVIEW_GUIDE
from tests.pipeline_llm import QUESTION, ScriptedLLM, run_pipeline
from tests.test_user_directives import HEADING, M12, MC1, MC2, UP_TO_45, directives_in, inject

BRIEF = "研究目标：看清各家量产时间表\n研究范围：中日韩电池厂\n排除内容：实验室样品\n用户补充：结论先给时间线"


class CriticRequirementsTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def critic_prompts(self, **kw) -> list[str]:
        llm = ScriptedLLM()
        run_pipeline(self.root, llm, **kw)
        prompts = llm.prompts("critic")
        self.assertEqual(len(prompts), 3)  # 剧本：3 轮评审
        return prompts

    def test_critic_sees_the_question_and_the_commission(self):
        for prompt in self.critic_prompts(clarification=BRIEF):
            self.assertIn(f"{QUESTION}\n\n补充说明：{BRIEF}", prompt)

    def test_critic_sees_every_mid_run_instruction(self):
        prompts = self.critic_prompts(on_event=inject, before_run=lambda o: o._user_messages.append(M12))
        self.assertEqual([directives_in(p) for p in prompts],
                         [[*UP_TO_45, MC1], [*UP_TO_45, MC1, MC2], [*UP_TO_45, MC1, MC2]])
        for prompt in prompts:
            self.assertIn(f"【用户补充指令 1】{M12}", prompt.split(HEADING)[0])  # 阶段1→2 的那批随研究问题进来

    def test_directives_reach_the_critic_as_requirements_to_check_not_as_instructions(self):
        prompt = self.critic_prompts(on_event=inject)[0]
        section = prompt.split(HEADING, 1)[1]
        self.assertIn(REVIEW_GUIDE, section)
        self.assertNotIn(GUIDE, section)

    def test_prompt_states_the_purpose_and_where_violations_go(self):
        prompt = self.critic_prompts()[0]
        for needle in ("只用于检查报告是否满足用户要求", "不改变", "7 个维度的评分标准",
                       "critical_issues", "priority_improvements"):
            self.assertIn(needle, prompt)

    def test_question_comes_before_the_draft(self):
        prompt = self.critic_prompts(clarification=BRIEF)[0]
        self.assertLess(prompt.index(BRIEF), prompt.index("## 待评审草稿"))


if __name__ == "__main__":
    unittest.main()
