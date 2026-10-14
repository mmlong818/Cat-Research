"""模型注册表（能力表）、推理强度映射与模型配置档。"""
import dataclasses
import unittest
from unittest import mock

import config
from llm.models import MODELS, get_spec, resolve_effort
from llm.profiles import PROFILES, Profile, default_profile, make_profile
from llm.types import LLMConfigError


class RegistryTests(unittest.TestCase):
    def test_profile_models_are_registered_under_their_provider(self):
        for name, p in PROFILES.items():
            for model in (p.core, p.support):
                with self.subTest(model):
                    self.assertEqual(get_spec(model).provider, name)

    def test_unknown_model_is_a_clear_config_error(self):
        for model in ("m", "gpt-unknown", "glm-9"):
            with self.subTest(model), self.assertRaises(LLMConfigError) as cm:
                get_spec(model)
            self.assertIn(model, str(cm.exception))
            self.assertIn("注册表", str(cm.exception))

    def test_unregistered_claude_ids_and_aliases_still_route_to_claude(self):
        for model in ("claude-opus-4-8", "opus", "sonnet"):
            with self.subTest(model):
                spec = get_spec(model)
                self.assertEqual((spec.provider, spec.id, spec.efforts), ("claude", model, ()))

    def test_capabilities_per_provider(self):
        self.assertEqual((MODELS["claude-sonnet-5-5"].web, MODELS["claude-sonnet-5-5"].structured),
                         ("native", "json_schema"))
        self.assertEqual((MODELS["gpt-6.1-sol"].web, MODELS["gpt-6.1-sol"].structured),
                         ("hosted_search", "strict_json_schema"))
        self.assertEqual((MODELS["glm-5.3"].web, MODELS["glm-5.3"].structured), ("client_tools", "json_object"))
        self.assertGreaterEqual(MODELS["gpt-6.1-sol"].output_budget, 25_000)  # 至少给推理预留 25K


class EffortTests(unittest.TestCase):
    def test_glm_always_uses_low(self):
        for e in ("low", "medium", "high", "xhigh", "max"):
            self.assertEqual(resolve_effort(MODELS["glm-5.3"], e), "low")

    def test_maps_to_nearest_supported_level_ties_go_up(self):
        spec = dataclasses.replace(MODELS["glm-5.3"], efforts=("low", "high", "max"))
        got = {e: resolve_effort(spec, e) for e in ("low", "medium", "high", "xhigh", "max")}
        self.assertEqual(got, {"low": "low", "medium": "high", "high": "high", "xhigh": "max", "max": "max"})

    def test_supported_levels_pass_through(self):
        for model in ("gpt-6.1-sol", "gpt-6-luna", "claude-opus-5-5"):
            for e in ("low", "medium", "high", "xhigh", "max"):
                self.assertEqual(resolve_effort(MODELS[model], e), e, model)

    def test_models_without_effort_get_none(self):
        self.assertIsNone(resolve_effort(get_spec("claude-opus-4-8"), "high"))


class ProfileTests(unittest.TestCase):
    def test_defaults_are_the_latest_models(self):
        self.assertEqual(PROFILES["claude"], Profile("claude", "claude-opus-5-5", "claude-sonnet-5-5"))
        self.assertEqual(PROFILES["openai"], Profile("openai", "gpt-6.1-sol", "gpt-6-luna"))
        self.assertEqual(PROFILES["zhipu"], Profile("zhipu", "glm-5.3", "glm-5.3-flash"))

    def test_roles_follow_config_split(self):
        p = PROFILES["zhipu"]
        for role in ("clarifier", "planner", "researcher", "analyst", "writer"):
            self.assertEqual(p.model_for(role), "glm-5.3")
        for role in ("critic", "source_verifier", "fact_checker", "conclusion_validator", "reconciler"):
            self.assertEqual(p.model_for(role), "glm-5.3-flash")
        with self.assertRaises(ValueError):
            p.model_for("nobody")

    def test_make_profile_validates_provider_and_models(self):
        self.assertEqual(make_profile("zhipu", core="glm-5.3-flashx").core, "glm-5.3-flashx")
        self.assertEqual(make_profile("openai").support, "gpt-6-luna")
        for args in (("zhipu", "gpt-6-luna"), ("nope",), ("openai", "m")):
            with self.subTest(args), self.assertRaises(ValueError):
                make_profile(*args)

    def test_default_profile_reads_current_config(self):
        with mock.patch.object(config, "CORE_MODEL", "glm-5.3"), \
                mock.patch.object(config, "SUPPORT_MODEL", "glm-5.3-flash"):
            self.assertEqual(default_profile(), Profile("zhipu", "glm-5.3", "glm-5.3-flash"))


if __name__ == "__main__":
    unittest.main()
