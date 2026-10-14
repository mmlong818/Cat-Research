"""模型配置档（profile）传到编排器创建的各智能体，不改全局 config；用量统计含缓存输入。"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import config
import orchestrator as orch_mod
from agents.llm_agent import LLMAgent
from llm.profiles import PROFILES, make_profile
from llm.types import LLMResult
from research.params import resolve_params
from tests.test_orchestrator import FakeAgents

ROLES = {"planner": "core", "researcher": "core", "analyst": "core", "writer": "core",
         "critic": "support", "source_verifier": "support", "fact_checker": "support",
         "conclusion_validator": "support", "reconciler": "support"}


class _Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        for p in (mock.patch.object(orch_mod, "WORKSPACE_DIR", self.root), mock.patch("builtins.print")):
            p.start()
            self.addCleanup(p.stop)


class ProfileWiringTests(_Base):
    def test_agents_get_models_from_the_profile(self):
        for name, profile in PROFILES.items():
            o = orch_mod.ResearchOrchestrator(profile=profile)
            for attr, tier in ROLES.items():
                with self.subTest(provider=name, agent=attr):
                    self.assertEqual(getattr(o, attr).model, getattr(profile, tier))

    def test_without_profile_uses_current_config(self):
        with mock.patch.object(config, "CORE_MODEL", "gpt-6.1-sol"), \
                mock.patch.object(config, "SUPPORT_MODEL", "gpt-6-luna"):
            o = orch_mod.ResearchOrchestrator()
        self.assertEqual((o.profile.provider, o.planner.model, o.critic.model),
                         ("openai", "gpt-6.1-sol", "gpt-6-luna"))

    def test_concurrent_orchestrators_do_not_share_models_or_touch_config(self):
        before = (config.CORE_MODEL, config.SUPPORT_MODEL)
        a = orch_mod.ResearchOrchestrator(profile=PROFILES["zhipu"])
        b = orch_mod.ResearchOrchestrator(profile=PROFILES["openai"])
        self.assertEqual((a.researcher.model, b.researcher.model), ("glm-5.3", "gpt-6.1-sol"))
        self.assertEqual((config.CORE_MODEL, config.SUPPORT_MODEL), before)

    def test_run_records_profile_models_in_session_and_hash(self):
        profile = make_profile("zhipu", support="glm-5.3-flashx")
        o = orch_mod.ResearchOrchestrator(profile=profile)
        fake = FakeAgents([6.0, 6.5])
        for name in ROLES:
            setattr(o, name, fake)
        o._agents = []
        o.run("固态电池", max_cycles=2)
        with open(os.path.join(o.workspace, "00_session.json"), encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual((meta["model"], meta["provider"]), ("glm-5.3", "zhipu"))
        self.assertEqual(meta["resolved_params"], resolve_params(None, "zh", None, 2, None, profile=profile))
        self.assertEqual((meta["resolved_params"]["core_model"], meta["resolved_params"]["support_model"]),
                         ("glm-5.3", "glm-5.3-flashx"))
        default = orch_mod.ResearchOrchestrator()
        self.assertNotEqual(o._params_hash({"x": 1}), default._params_hash({"x": 1}))


class UsageReportTests(_Base):
    def test_token_usage_counts_cached_input_and_every_model(self):
        events = []
        agent = LLMAgent(name="测试", system_prompt="s", model="claude-opus-5-5")
        agent.stream_callback = lambda e, d: events.append((e, d))
        usage = {"claude-opus-5-5": {"inputTokens": 100, "cacheReadInputTokens": 900,
                                     "cacheCreationInputTokens": 50, "outputTokens": 30},
                 "claude-haiku-4-5": {"inputTokens": 10, "outputTokens": 5}}
        agent.report_usage(LLMResult(text="", data=None, duration_ms=1, num_turns=1,
                                     session_id="", model_usage=usage))
        data = events[-1][1]
        self.assertEqual((data["total_input"], data["cached_input"], data["total_output"]), (1060, 900, 35))
        self.assertNotIn("cost_usd", data)

    def test_orchestrator_accumulates_cached_input(self):
        o = orch_mod.ResearchOrchestrator(profile=PROFILES["claude"])
        o._token_usage = {"研究员": {"input": 1, "output": 1}}  # 旧检查点没有 cached_input
        o._emit("token_usage", {"agent": "研究员", "total_input": 10, "cached_input": 7, "total_output": 2})
        summary = o._usage_summary()
        self.assertEqual((summary["total_input"], summary["total_cached_input"]), (11, 7))
        self.assertNotIn("cost_usd", summary)
        self.assertNotIn("cost_usd", summary["by_agent"]["研究员"])


if __name__ == "__main__":
    unittest.main()
