"""M4 多模型接入：研究请求的配置档传到编排器、审计与会话列表含提供方、重放沿用原配置档、
澄清智能体与三个工具路由用设置里的默认配置档（或请求指定的提供方）。"""
import json
import os
import unittest
from unittest import mock

import config
import orchestrator as orch_mod
from agents.clarifier import ClarifierAgent
from api import app as app_mod
from api import config_store, security
from api.db.task_store import TaskStore
from llm.profiles import PROFILES, Profile, make_profile
from llm.types import LLMResult
from research.checkpoints import PHASES, Checkpoints
from research.params import resolve_params
from tests.test_settings import OPENAI_KEY, ZHIPU_KEY, SettingsCase

HEADERS = {security.TOKEN_HEADER: security.TOKEN}
OPENAI = Profile("openai", "gpt-6.1-sol", "gpt-6-luna")
ZHIPU = PROFILES["zhipu"]
CLAUDE = PROFILES["claude"]
_REAL_RUN = app_mod._run_research_task


class ApiCase(SettingsCase):
    """在设置隔离之上再隔离任务库；后台线程函数换成记录参数的假函数。"""

    def setUp(self):
        super().setUp()
        self.store = TaskStore(os.path.join(self.tmp, "tasks.db"))
        self.root = os.path.join(self.tmp, "workspace")
        os.makedirs(self.root)
        self.calls: list[dict] = []
        for p in (mock.patch.object(app_mod, "_store", self.store),
                  mock.patch.object(app_mod, "WORKSPACE_DIR", self.root),
                  mock.patch.object(app_mod, "_run_research_task", lambda *a, **k: self.calls.append(k))):
            p.start()
            self.addCleanup(p.stop)

    def start(self, **body):
        return self.client.post("/api/research", json={"question": "固态电池", **body}, headers=HEADERS)

    def created(self, res) -> dict:
        return self.store.audit_log(task_id=res.json()["task_id"])[0]["payload"]


class ResearchStartTests(ApiCase):
    def test_without_overrides_the_saved_default_profile_is_used(self):
        config_store.save_config({"openai_api_key": OPENAI_KEY, "default_profile": {"provider": "openai"}})
        res = self.start(depth="quick")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.calls[0]["profile"], OPENAI)

    def test_without_settings_the_default_is_claude(self):
        self.assertEqual(self.start().status_code, 200)
        self.assertEqual(self.calls[0]["profile"], CLAUDE)

    def test_request_can_pick_a_provider_for_this_run_only(self):
        config_store.save_config({"zhipu_api_key": ZHIPU_KEY})
        res = self.start(provider="zhipu")
        self.assertEqual(self.calls[0]["profile"], ZHIPU)
        self.assertNotIn("default_profile", config_store.load_config())  # 不改设置里的默认
        self.assertEqual(self.created(res)["provider"], "zhipu")

    def test_request_can_pick_specific_models(self):
        config_store.save_config({"openai_api_key": OPENAI_KEY})
        self.start(provider="openai", core_model="gpt-6-astra", support_model="gpt-6-luna")
        self.assertEqual(self.calls[0]["profile"], Profile("openai", "gpt-6-astra", "gpt-6-luna"))

    def test_missing_key_is_a_400_before_any_task_is_created(self):
        for provider, label in (("zhipu", "智谱"), ("openai", "OpenAI")):
            res = self.start(provider=provider)
            self.assertEqual(res.status_code, 400, provider)
            self.assertEqual(res.json()["detail"], f"请先在设置中填写 {label} 的 API Key")
        self.assertEqual((self.calls, self.store.active_count(), self.store.list_tasks()), ([], 0, []))

    def test_default_provider_without_key_also_400(self):
        config_store.save_config({"default_profile": {"provider": "openai"}})
        self.assertEqual(self.start().status_code, 400)

    def test_bad_models_are_400(self):
        config_store.save_config({"openai_api_key": OPENAI_KEY})
        self.assertEqual(self.start(provider="openai", core_model="glm-5.3").status_code, 400)
        self.assertEqual(self.start(provider="gemini").status_code, 400)
        self.assertEqual(self.calls, [])

    def test_audit_and_task_record_carry_provider_and_models(self):
        config_store.save_config({"openai_api_key": OPENAI_KEY})
        res = self.start(provider="openai", depth="quick", language="en")
        payload = self.created(res)
        self.assertEqual((payload["provider"], payload["core_model"], payload["support_model"]),
                         ("openai", "gpt-6.1-sol", "gpt-6-luna"))
        self.assertEqual(payload["resolved_params"], resolve_params("quick", "en", profile=OPENAI))
        self.assertEqual(payload["resolved_params"]["provider"], "openai")
        task = self.store.get(res.json()["task_id"])
        self.assertEqual((task["provider"], task["core_model"]), ("openai", "gpt-6.1-sol"))

    def test_clarify_confirm_takes_the_same_options(self):
        config_store.save_config({"zhipu_api_key": ZHIPU_KEY})
        app_mod._clarify_sessions["c9"] = {"question": "固态电池", "history": [], "summary": {}, "turns": 1}
        self.addCleanup(app_mod._clarify_sessions.pop, "c9", None)
        res = self.client.post("/api/clarify/c9/confirm", json={"provider": "zhipu", "depth": "quick"},
                               headers=HEADERS)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.calls[0]["profile"], ZHIPU)
        payload = self.created(res)
        self.assertEqual((payload["provider"], payload["resolved_params"]["core_model"]), ("zhipu", "glm-5.3"))

    def test_clarify_confirm_without_key_is_400_and_keeps_the_session(self):
        app_mod._clarify_sessions["c8"] = {"question": "固态电池", "history": [], "summary": {}, "turns": 1}
        self.addCleanup(app_mod._clarify_sessions.pop, "c8", None)
        res = self.client.post("/api/clarify/c8/confirm", json={"provider": "openai"}, headers=HEADERS)
        self.assertEqual(res.status_code, 400)
        self.assertIn("c8", app_mod._clarify_sessions)


class ProfileReachesOrchestratorTests(ApiCase):
    """后台线程函数里：profile 原样交给编排器；用假编排器捕获。"""

    def run_task(self, **kw):
        seen = {}

        class FakeOrchestrator:
            interrupted = False
            workspace, session_id = "/ws/session_S1", "S1"

            def __init__(self, progress_callback=None, profile=None):
                seen["profile"] = profile

            def run(self, question, **kwargs):
                seen["run"] = kwargs
                return "报告"

            def replay(self, workspace, from_phase, **kwargs):
                seen["replay"] = (workspace, from_phase)
                return "报告"

        self.store.reserve("t1", "q", limit=2)
        with mock.patch("orchestrator.ResearchOrchestrator", FakeOrchestrator):
            _REAL_RUN("t1", "q", None, **kw)
        return seen

    def test_profile_is_passed_to_the_orchestrator(self):
        self.assertEqual(self.run_task(profile=ZHIPU)["profile"], ZHIPU)

    def test_replay_passes_the_profile_too(self):
        seen = self.run_task(profile=OPENAI, replay={"workspace": "/w", "from_phase": "plan"})
        self.assertEqual((seen["profile"], seen["replay"]), (OPENAI, ("/w", "plan")))

    def test_real_orchestrator_agents_use_the_models_and_session_records_provider(self):
        with mock.patch("builtins.print"), mock.patch.object(orch_mod, "WORKSPACE_DIR", self.root):
            o = orch_mod.ResearchOrchestrator(profile=ZHIPU)
            o.workspace = o._create_workspace("q", {"resolved_params": resolve_params(profile=ZHIPU)})
        self.assertEqual((o.planner.model, o.critic.model), ("glm-5.3", "glm-5.3-flash"))
        with open(os.path.join(o.workspace, "00_session.json"), encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual((meta["provider"], meta["resolved_params"]["provider"],
                          meta["resolved_params"]["core_model"]), ("zhipu", "zhipu", "glm-5.3"))


class ReplayProfileTests(ApiCase):
    SID = "20260101_000000"

    def setUp(self):
        super().setUp()
        self.ws = os.path.join(self.root, f"session_{self.SID}")
        os.makedirs(self.ws)
        for phase in PHASES[:3]:
            Checkpoints(self.ws).save(phase, {"params": {"question": "q"}}, params_hash="h")

    def meta(self, **fields):
        with open(os.path.join(self.ws, "00_session.json"), "w", encoding="utf-8") as f:
            json.dump({"session_id": self.SID, "question": "q", **fields}, f)

    def replay(self):
        return self.client.post(f"/api/sessions/{self.SID}/replay", json={}, headers=HEADERS)

    def test_replay_keeps_the_original_profile_not_the_current_default(self):
        self.meta(provider="zhipu", resolved_params={"core_model": "glm-5.3", "support_model": "glm-5.3-flashx"})
        config_store.save_config({"zhipu_api_key": ZHIPU_KEY, "openai_api_key": OPENAI_KEY,
                                  "default_profile": {"provider": "openai"}})
        res = self.replay()
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.calls[0]["profile"], Profile("zhipu", "glm-5.3", "glm-5.3-flashx"))
        created = self.store.audit_log(task_id=res.json()["task_id"])[0]["payload"]
        self.assertEqual((created["source"], created["provider"], created["support_model"]),
                         ("replay", "zhipu", "glm-5.3-flashx"))

    def test_session_without_provider_replays_with_claude_even_if_default_is_openai(self):
        self.meta()  # 没有提供方字段的会话
        config_store.save_config({"openai_api_key": OPENAI_KEY, "default_profile": {"provider": "openai"}})
        self.assertEqual(self.replay().status_code, 200)
        self.assertEqual(self.calls[0]["profile"], CLAUDE)

    def test_missing_workspace_meta_defaults_to_claude(self):
        self.assertEqual(self.replay().status_code, 200)
        self.assertEqual(self.calls[0]["profile"], CLAUDE)

    def test_replay_of_a_zhipu_session_without_key_is_400_and_creates_no_task(self):
        self.meta(provider="zhipu", resolved_params={"core_model": "glm-5.3", "support_model": "glm-5.3-flash"})
        res = self.replay()
        self.assertEqual(res.status_code, 400)
        self.assertIn("智谱", res.json()["detail"])
        self.assertEqual((self.calls, self.store.list_tasks()), ([], []))


class SessionListProviderTests(ApiCase):
    def test_sessions_show_provider_and_models(self):
        ws = os.path.join(self.root, "session_S1")
        os.makedirs(ws)
        with open(os.path.join(ws, "00_session.json"), "w", encoding="utf-8") as f:
            json.dump({"session_id": "S1", "created_at": "2026-10-02T10:00:00", "question": "q", "status": "completed",
                       "provider": "openai", "resolved_params": {"depth": "quick", "provider": "openai",
                                                                 "core_model": "gpt-6.1-sol",
                                                                 "support_model": "gpt-6-luna"}}, f)
        legacy = os.path.join(self.root, "session_S0")
        os.makedirs(legacy)
        with open(os.path.join(legacy, "00_session.json"), "w", encoding="utf-8") as f:
            json.dump({"session_id": "S0", "created_at": "2026-10-01T10:00:00", "question": "old",
                       "status": "completed", "model": "claude-opus-5-5"}, f)
        self.store.reserve("tf", "没建成工作空间", limit=9, provider="zhipu", core_model="glm-5.3")
        self.store.merge("tf", status="failed", error="boom")
        res = self.client.get("/api/sessions", headers=HEADERS).json()["sessions"]
        by_id = {s["session_id"] or s["task_id"]: s for s in res}
        self.assertEqual((by_id["S1"]["provider"], by_id["S1"]["core_model"], by_id["S1"]["support_model"]),
                         ("openai", "gpt-6.1-sol", "gpt-6-luna"))
        self.assertIsNone(by_id["S0"]["provider"])
        self.assertEqual((by_id["tf"]["provider"], by_id["tf"]["core_model"]), ("zhipu", "glm-5.3"))


def fake_clarify_call(seen: list):
    def fake(req):
        seen.append(req.model)
        data = {"message": "m", "summary": {}, "ready": False, "confidence": 0.1}
        return LLMResult(text="", data=data, duration_ms=0, num_turns=1, session_id="")
    return fake


class ClarifierProfileTests(ApiCase):
    def ask(self, agent: ClarifierAgent) -> list:
        seen: list = []
        with mock.patch("agents.clarifier.call", fake_clarify_call(seen)):
            agent.start("固态电池")
        return seen

    def test_uses_the_given_profiles_core_model(self):
        self.assertEqual(self.ask(ClarifierAgent(make_profile("openai"))), ["gpt-6.1-sol"])
        self.assertEqual(self.ask(ClarifierAgent(ZHIPU)), ["glm-5.3"])

    def test_defaults_to_the_saved_default_profile_not_config_core_model(self):
        config_store.save_config({"default_profile": {"provider": "claude", "core": "claude-opus-5"}})
        self.assertEqual(self.ask(ClarifierAgent()), ["claude-opus-5"])
        self.assertEqual(config.CORE_MODEL, "claude-opus-5-5")  # 全局 config 没被改

    def test_clarify_api_uses_request_profile_for_start_and_reply(self):
        config_store.save_config({"zhipu_api_key": ZHIPU_KEY})
        seen: list = []
        with mock.patch("agents.clarifier.call", fake_clarify_call(seen)):
            res = self.client.post("/api/clarify", json={"question": "固态电池", "provider": "zhipu"}, headers=HEADERS)
            self.assertEqual(res.status_code, 200, res.text)
            self.addCleanup(app_mod._clarify_sessions.pop, res.json()["clarify_id"], None)
            reply = self.client.post(f"/api/clarify/{res.json()['clarify_id']}/message", json={"message": "近半年"},
                                     headers=HEADERS)
            self.assertEqual(reply.status_code, 200, reply.text)
        self.assertEqual(seen, ["glm-5.3", "glm-5.3"])

    def test_clarify_api_missing_key_is_400(self):
        res = self.client.post("/api/clarify", json={"question": "固态电池", "provider": "openai"}, headers=HEADERS)
        self.assertEqual(res.status_code, 400)
        self.assertIn("OpenAI", res.json()["detail"])


class StartupPreflightTests(SettingsCase):
    def check(self) -> list:
        import main
        return main.check_environment()[0]

    def test_claude_default_requires_the_cli(self):
        from llm import LLMError
        with mock.patch("llm.providers.claude.resolve_cli_path", side_effect=LLMError("找不到 claude")):
            self.assertEqual(self.check(), ["找不到 claude"])

    def test_non_claude_default_skips_the_cli_and_checks_the_key(self):
        config_store.save_config({"default_profile": {"provider": "openai"}})
        with mock.patch("llm.providers.claude.resolve_cli_path", side_effect=AssertionError("不该检查 CLI")):
            errors = self.check()
        self.assertEqual(len(errors), 1)
        self.assertIn("OpenAI", errors[0])
        config_store.save_config({"openai_api_key": OPENAI_KEY})
        with mock.patch("llm.providers.claude.resolve_cli_path", side_effect=AssertionError("不该检查 CLI")):
            self.assertEqual(self.check(), [])
        self.assertNotIn(OPENAI_KEY, "".join(errors))


if __name__ == "__main__":
    unittest.main()
