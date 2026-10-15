"""W2 覆盖主体清单：planner 产出 key_entities，写作/改写逐一覆盖，评审查遗漏并提补充研究；旧计划缺字段按空处理。"""
import json
import shutil
import tempfile
import unittest
from unittest import mock

import orchestrator as orch_mod
from agents.critic import CriticAgent
from agents.planner import PLAN_SCHEMA, PLANNER_SYSTEM_PROMPT, PlannerAgent, key_entities_of
from agents.writer import WriterAgent
from tests.test_orchestrator import FakeAgents
from tests.test_research_agents import _WS, PLAN, _ok

ENTITIES = [{"name": "宝马", "why": "欧洲主要车企，与 Solid Power 合作"},
            {"name": "现代", "why": "韩国主要车企，公布全固态时间表"}]
REVIEW = {"scores": {k: 8 for k in ("completeness", "accuracy", "depth", "clarity", "usefulness", "sources",
                                    "simplicity")},
          "strengths": [], "critical_issues": [], "missing_content": [], "additional_research_needed": [],
          "overall_assessment": "ok", "priority_improvements": []}


class PlanSchemaTests(unittest.TestCase):
    def test_key_entities_is_a_required_strict_array_of_name_and_why(self):
        prop = PLAN_SCHEMA["properties"]["key_entities"]
        self.assertEqual(prop["type"], "array")
        self.assertEqual(sorted(prop["items"]["properties"]), ["name", "why"])
        self.assertIn("key_entities", PLAN_SCHEMA["required"])
        self.assert_strict(PLAN_SCHEMA)  # additionalProperties:false 且 required 全列

    def assert_strict(self, schema, path="$"):
        if schema.get("type") == "object":
            self.assertIs(schema.get("additionalProperties"), False, path)
            self.assertEqual(sorted(schema["required"]), sorted(schema["properties"]), path)
            for key, sub in schema["properties"].items():
                self.assert_strict(sub, f"{path}.{key}")
        elif schema.get("type") == "array":
            self.assert_strict(schema["items"], f"{path}[]")

    def test_prompts_ask_for_enumerated_subjects_and_query_coverage(self):
        for needle in ("key_entities", "主要厂商", "各主要地区", "空数组", "search_queries", "合并", "high 或 medium"):
            self.assertIn(needle, PLANNER_SYSTEM_PROMPT)


class PlannerPromptTests(_WS):
    def test_create_plan_prompt_requires_queries_to_cover_the_entities(self):
        self.patch_call(_ok(data={**PLAN, "key_entities": ENTITIES}))
        plan = PlannerAgent().create_plan(self.ws, "2026年全球固态电池量产进展与主要厂商时间表")
        self.assertEqual(plan["key_entities"], ENTITIES)
        self.assertIn("key_entities", self.reqs[0].prompt)
        self.assertEqual(json.loads(self.read("03_plan.json"))["key_entities"], ENTITIES)


class KeyEntitiesOfTests(unittest.TestCase):
    def test_missing_none_and_malformed_become_empty_or_filtered(self):
        self.assertEqual(key_entities_of({}), [])
        self.assertEqual(key_entities_of({"key_entities": None}), [])
        self.assertEqual(key_entities_of({"key_entities": "宝马"}), [])
        self.assertEqual(key_entities_of(None), [])
        self.assertEqual(key_entities_of({"key_entities": [{"why": "x"}, {"name": " "}, "x", ENTITIES[0]]}),
                         [ENTITIES[0]])


class WriterEntitiesTests(_WS):
    def prompt(self, **kw):
        self.put("05_analysis.md", "分析A")
        self.put("06_drafts/draft_0.md", "上一版D0")
        self.patch_call(_ok(text="# 报告"))
        WriterAgent().write_draft(self.ws, "问题", **kw)
        return self.reqs[0].prompt

    def test_draft_and_rewrite_list_every_entity_and_demand_explicit_gaps(self):
        for kw in ({"draft_num": 0}, {"draft_num": 1}):
            p = self.prompt(key_entities=ENTITIES, **kw)
            for needle in ("必须覆盖的主体", "宝马", "欧洲主要车企", "现代", "逐一覆盖", "公开信息不足"):
                self.assertIn(needle, p)

    def test_no_entities_means_no_block(self):
        for entities in (None, []):
            self.assertNotIn("必须覆盖的主体", self.prompt(draft_num=0, key_entities=entities))
            self.assertNotIn("必须覆盖的主体", self.prompt(draft_num=1, key_entities=entities))


class CriticEntitiesTests(_WS):
    def prompt(self, **kw):
        self.put("06_drafts/draft_0.md", "草稿")
        self.patch_call(_ok(data=REVIEW))
        CriticAgent().review(self.ws, 0, 1, question="问题", **kw)
        return self.reqs[0].prompt

    def test_critic_receives_the_list_and_is_told_to_raise_research_for_omissions(self):
        p = self.prompt(key_entities=ENTITIES)
        for needle in ("必须覆盖的主体", "宝马", "现代", "missing_content", "additional_research_needed",
                       "公开信息不足"):
            self.assertIn(needle, p)

    def test_no_entities_means_no_block(self):
        self.assertNotIn("必须覆盖的主体", self.prompt())
        self.assertNotIn("必须覆盖的主体", self.prompt(key_entities=[]))

    def test_completeness_dimension_mentions_the_entity_list(self):
        from agents.critic import CRITIC_SYSTEM_PROMPT
        self.assertIn("主体清单", CRITIC_SYSTEM_PROMPT)


class OrchestratorEntitiesTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        p = mock.patch.object(orch_mod, "WORKSPACE_DIR", self.root)
        p.start()
        self.addCleanup(p.stop)

    def run_with(self, fake, **kw):
        o = orch_mod.ResearchOrchestrator()
        for name in ("planner", "researcher", "analyst", "writer", "critic",
                     "source_verifier", "fact_checker", "conclusion_validator", "reconciler"):
            setattr(o, name, fake)
        o._agents = []
        return o, o.run("固态电池", **kw)

    def test_entities_reach_first_draft_rewrites_and_every_review(self):
        fake = FakeAgents([6.0, 7.0])
        fake.plan_entities = ENTITIES
        self.run_with(fake, min_cycles=2, max_cycles=2)
        self.assertEqual(fake.writer_entities, [ENTITIES, ENTITIES])  # 初稿 + 一次改写
        self.assertEqual(fake.critic_entities, [ENTITIES, ENTITIES])

    def test_old_plan_without_key_entities_is_treated_as_empty(self):
        fake = FakeAgents([6.0, 7.0])  # 默认计划没有 key_entities 字段
        self.run_with(fake, min_cycles=2, max_cycles=2)
        self.assertEqual(fake.writer_entities, [[], []])
        self.assertEqual(fake.critic_entities, [[], []])

    def test_replay_from_an_old_checkpoint_plan_still_works(self):
        fake = FakeAgents([6.0, 7.0])
        o, _ = self.run_with(fake, min_cycles=2, max_cycles=2)
        again = FakeAgents([6.0, 7.0])
        again.plan_entities = ENTITIES  # 重放不重跑规划：检查点里的旧计划没有该字段
        replayer = orch_mod.ResearchOrchestrator()
        for name in ("planner", "researcher", "analyst", "writer", "critic",
                     "source_verifier", "fact_checker", "conclusion_validator", "reconciler"):
            setattr(replayer, name, again)
        replayer._agents = []
        replayer.replay(o.workspace, "improve")
        self.assertEqual(again.critic_entities, [[], []])


if __name__ == "__main__":
    unittest.main()
