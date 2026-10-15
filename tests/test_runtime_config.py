"""API 在运行时修改 config.* 后，新建的智能体/编排器必须使用新值（此前导入时即绑定，修改无效）。"""
import unittest
from unittest import mock

import config
import orchestrator as orch_mod
from agents.analyst import AnalystAgent
from agents.conclusion_validator import ConclusionValidatorAgent
from agents.critic import CriticAgent
from agents.fact_checker import FactCheckerAgent
from agents.planner import PlannerAgent
from agents.researcher import ResearcherAgent
from agents.source_verifier import SourceVerifierAgent
from agents.writer import WriterAgent

AGENTS = {
    "PLANNER_MODEL": PlannerAgent, "RESEARCHER_MODEL": ResearcherAgent,
    "ANALYST_MODEL": AnalystAgent, "WRITER_MODEL": WriterAgent,
    "CRITIC_MODEL": CriticAgent, "SOURCE_VERIFIER_MODEL": SourceVerifierAgent,
    "FACT_CHECKER_MODEL": FactCheckerAgent, "CONCLUSION_VALIDATOR_MODEL": ConclusionValidatorAgent,
}


class RuntimeConfigTests(unittest.TestCase):
    def test_agents_pick_up_runtime_model_change(self):
        for name, cls in AGENTS.items():
            with self.subTest(name), mock.patch.object(config, name, f"runtime-{name}"):
                self.assertEqual(cls().model, f"runtime-{name}")

    def test_loop_policy_picks_up_runtime_depth_change(self):
        o = orch_mod.ResearchOrchestrator()
        presets = {**config.DEPTH_PRESETS, "standard": {**config.DEPTH_PRESETS["standard"],
                                                        "min_cycles": 3, "max_cycles": 4}}
        with mock.patch.object(config, "DEPTH_PRESETS", presets):
            policy = o._loop_policy(None, "standard", None, None)
        self.assertEqual((policy.min_cycles, policy.max_cycles), (3, 4))


if __name__ == "__main__":
    unittest.main()
