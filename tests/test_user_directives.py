"""研究中途的用户补充要求：每个检查点取到的消息进入其后真正干活的智能体的提示词，之后持续有效；
进入时发出 user_message_applied。真实编排 + 真实智能体，只替换模型调用（tests/pipeline_llm.py）。"""
import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

import orchestrator as orch_mod
from research.directives import GUIDE, REVIEW_GUIDE, VALIDATION_GUIDE, Directives
from tests.pipeline_llm import ScriptedLLM, run_pipeline

HEADING = "## 用户补充要求"
M12 = "请把日韩厂商也纳入比较"
M23 = "检索时优先看政府公告与交易所披露"
M34 = "裁决矛盾时以官方产能公告为准"
M45 = "报告里加一节成本对比"
MC1 = "第二版请压缩篇幅"
MC2 = "补充欧洲厂商的进展"
UP_TO_45 = [M23, M34, M45]
NOT_DIRECTED = ("planner", "source_verifier", "reconciler", "cross_check")


def inject(o, kind, data):
    """在各检查点之前把消息放进队列（检查点紧跟在这些事件之后）。"""
    if kind == "plan":
        o._user_messages.append(M23)                                       # → 阶段2→3
    elif kind == "phase" and data["phase"] in (3.5, 4, 6):
        o._user_messages.append({3.5: M34, 4: M45, 6: MC1}[data["phase"]])  # → 阶段3→4 / 阶段4→5 / 改进循环第1轮
    elif kind == "review" and data["cycle"] == 1:
        o._user_messages.append(MC2)                                       # → 改进循环第2轮


def directives_in(prompt: str) -> list[str]:
    """提示词末尾「用户补充要求」小节里的消息（编号须从 1 连续）；没有该小节时为空。"""
    if HEADING not in prompt:
        return []
    section = prompt.split(HEADING, 1)[1]
    numbers = re.findall(r"【用户补充指令 (\d+)】", section)
    assert numbers == [str(i) for i in range(1, len(numbers) + 1)], numbers
    return re.findall(r"【用户补充指令 \d+】(.+)", section)


def events_of(events, kind):
    return [d for k, d in events if k == kind]


class _Pipeline(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def run_with_messages(self):
        self.llm = ScriptedLLM()
        return run_pipeline(self.root, self.llm, on_event=inject,
                            before_run=lambda o: o._user_messages.append(M12))


class DirectiveDeliveryTests(_Pipeline):
    def test_each_gate_reaches_the_agents_that_work_after_it_and_stays_in_effect(self):
        self.run_with_messages()
        got = {role: [directives_in(p) for p in self.llm.prompts(role)]
               for role in ("researcher", "fact_checker", "analyst", "writer", "critic", "conclusion_validator")}
        self.assertEqual(got["researcher"], [[M23], [*UP_TO_45, MC1], [*UP_TO_45, MC1, MC2]])  # 首轮 + 两次补充研究
        self.assertEqual(got["fact_checker"], [[M23, M34]])                                   # 台账阶段的矛盾裁决
        self.assertEqual(got["analyst"], [[M23, M34]])
        self.assertEqual(got["writer"], [UP_TO_45, [*UP_TO_45, MC1], [*UP_TO_45, MC1, MC2]])  # 初稿 + 两次改写
        self.assertEqual(got["critic"], [[*UP_TO_45, MC1], [*UP_TO_45, MC1, MC2], [*UP_TO_45, MC1, MC2]])  # 每轮评审
        self.assertEqual(got["conclusion_validator"], got["critic"])                          # 每轮验证，与评审同批

    def test_section_is_appended_at_the_end_of_the_prompt(self):
        self.run_with_messages()
        first_draft = self.llm.prompts("writer")[0]
        self.assertTrue(first_draft.endswith(f"【用户补充指令 1】{M23}\n\n【用户补充指令 2】{M34}\n\n"
                                             f"【用户补充指令 3】{M45}"))
        self.assertEqual(first_draft.count(HEADING), 1)

    def test_other_agents_prompts_carry_no_section(self):
        self.run_with_messages()
        for role in NOT_DIRECTED:
            for prompt in self.llm.prompts(role):
                self.assertNotIn(HEADING, prompt, role)
                self.assertNotIn(M23, prompt, role)

    def test_message_before_planning_still_joins_the_research_question(self):
        self.run_with_messages()
        q_with_message = f"【用户补充指令 1】{M12}"
        self.assertIn(q_with_message, self.llm.prompts("planner")[0])
        self.assertIn(q_with_message, self.llm.prompts("analyst")[0].split(HEADING)[0])

    def test_ack_keeps_its_meaning_one_per_gate_that_read_messages(self):
        _, events = self.run_with_messages()
        self.assertEqual([(d["phase"], d["messages"]) for d in events_of(events, "user_message_ack")],
                         [("阶段1→2", [M12]), ("阶段2→3", [M23]), ("阶段3→4", [M34]), ("阶段4→5", [M45]),
                          ("改进循环第1轮", [MC1]), ("改进循环第2轮", [MC2])])

    def test_applied_is_emitted_when_a_batch_first_enters_each_agent(self):
        _, events = self.run_with_messages()
        applied = [(d["phase"], d["agents"], d["messages"]) for d in events_of(events, "user_message_applied")]
        self.assertEqual(applied, [
            ("阶段1→2", ["planner"], [M12]),
            ("阶段2→3", ["researcher"], [M23]),
            ("阶段2→3", ["fact_checker"], [M23]), ("阶段3→4", ["fact_checker"], [M34]),
            ("阶段2→3", ["analyst"], [M23]), ("阶段3→4", ["analyst"], [M34]),
            ("阶段2→3", ["writer"], [M23]), ("阶段3→4", ["writer"], [M34]), ("阶段4→5", ["writer"], [M45]),
            ("阶段2→3", ["critic"], [M23]), ("阶段3→4", ["critic"], [M34]), ("阶段4→5", ["critic"], [M45]),
            ("改进循环第1轮", ["critic"], [MC1]),
            ("阶段2→3", ["conclusion_validator"], [M23]), ("阶段3→4", ["conclusion_validator"], [M34]),
            ("阶段4→5", ["conclusion_validator"], [M45]), ("改进循环第1轮", ["conclusion_validator"], [MC1]),
            ("阶段3→4", ["researcher"], [M34]), ("阶段4→5", ["researcher"], [M45]),
            ("改进循环第1轮", ["researcher"], [MC1]),
            ("改进循环第1轮", ["writer"], [MC1]),
            ("改进循环第2轮", ["critic"], [MC2]), ("改进循环第2轮", ["conclusion_validator"], [MC2]),
            ("改进循环第2轮", ["researcher"], [MC2]),
            ("改进循环第2轮", ["writer"], [MC2]),
        ])

    def test_applied_follows_the_ack_of_the_same_batch(self):
        _, events = self.run_with_messages()
        kinds = [(k, d.get("phase")) for k, d in events if k in ("user_message_ack", "user_message_applied")]
        self.assertIn("user_message_applied", [k for k, _ in kinds])
        for i, (kind, phase) in enumerate(kinds):
            if kind == "user_message_applied":
                self.assertIn(("user_message_ack", phase), kinds[:i])

    def test_without_messages_nothing_is_applied(self):
        llm = ScriptedLLM()
        _, events = run_pipeline(self.root, llm)
        self.assertEqual(events_of(events, "user_message_applied"), [])
        self.assertFalse(any(HEADING in req.prompt for _, req in llm.requests))


class DirectiveReplayTests(_Pipeline):
    def test_replay_restores_directives_from_the_checkpoint(self):
        o, _ = self.run_with_messages()
        llm = ScriptedLLM()
        _, events = run_pipeline(self.root, llm, replay_from="draft", workspace=o.workspace)
        self.assertEqual(directives_in(llm.prompts("writer")[0]), UP_TO_45)  # 阶段4→5 之前的三批都在
        self.assertEqual([(d["phase"], d["agents"]) for d in events_of(events, "user_message_applied")][:3],
                         [("阶段2→3", ["writer"]), ("阶段3→4", ["writer"]), ("阶段4→5", ["writer"])])
        self.assertEqual(events_of(events, "user_message_ack"), [])  # 重放没有新消息，不会再确认

    def test_replay_of_a_checkpoint_without_directives_still_works(self):
        o, _ = run_pipeline(self.root, ScriptedLLM())
        state_file = os.path.join(o.workspace, ".checkpoints", "06_analyze", "state.json")
        with open(state_file, encoding="utf-8") as f:
            record = json.load(f)
        record["state"]["runtime"].pop("directives", None)  # 改动前生成的检查点没有该字段
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
        llm = ScriptedLLM()
        o2, events = run_pipeline(self.root, llm, replay_from="draft", workspace=o.workspace)
        self.assertFalse(o2.interrupted)
        self.assertEqual(events_of(events, "user_message_applied"), [])
        self.assertFalse(any(HEADING in req.prompt for _, req in llm.requests))


class DirectivesTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.d = Directives(lambda kind, data: self.events.append((kind, data)))

    def test_empty_section_is_an_empty_string_and_emits_nothing(self):
        self.d.add("阶段2→3", [])
        self.assertEqual(self.d.section("writer"), "")
        self.assertEqual(self.events, [])

    def test_section_numbers_all_batches_in_arrival_order(self):
        self.d.add("阶段2→3", ["甲", "乙"])
        self.d.add("阶段3→4", ["丙"])
        expected = f"\n\n{HEADING}\n{GUIDE}\n\n【用户补充指令 1】甲\n\n【用户补充指令 2】乙\n\n【用户补充指令 3】丙"
        self.assertEqual(self.d.section("writer"), expected)

    def test_critic_gets_the_same_messages_under_the_review_guide(self):
        self.d.add("阶段2→3", ["甲"])
        self.assertEqual(self.d.section("critic"), f"\n\n{HEADING}\n{REVIEW_GUIDE}\n\n【用户补充指令 1】甲")

    def test_validator_gets_the_same_messages_under_the_validation_guide(self):
        self.d.add("阶段2→3", ["甲"])
        self.assertEqual(self.d.section("conclusion_validator"),
                         f"\n\n{HEADING}\n{VALIDATION_GUIDE}\n\n【用户补充指令 1】甲")

    def test_applied_once_per_batch_and_agent(self):
        self.d.add("阶段2→3", ["甲"])
        self.d.section("researcher")
        self.d.section("researcher")
        self.d.add("阶段3→4", ["乙"])
        self.d.section("researcher")
        self.d.section("analyst")
        self.assertEqual([(d["phase"], d["agents"]) for _, d in self.events],
                         [("阶段2→3", ["researcher"]), ("阶段3→4", ["researcher"]),
                          ("阶段2→3", ["analyst"]), ("阶段3→4", ["analyst"])])
        self.assertTrue(all(kind == "user_message_applied" for kind, _ in self.events))

    def test_restore_keeps_batches_and_reapplies(self):
        self.d.add("阶段2→3", ["甲"])
        self.d.section("writer")
        restored = Directives(lambda kind, data: self.events.append((kind, data)))
        restored.restore(json.loads(json.dumps(self.d.batches)))
        self.assertEqual(restored.section("writer"), self.d.section("writer"))
        self.assertEqual(len(self.events), 2)  # 原对象一次 + 重放后的新对象一次
        restored.restore(None)
        self.assertEqual(restored.section("writer"), "")


class _LateAppend(list):
    """取走待处理消息的那一刻，API 线程恰好又追加了一条（确定性地模拟两步之间的线程切换）。"""

    def __getitem__(self, i):
        out = super().__getitem__(i)
        if isinstance(i, slice) and "late" not in self:
            self.append("late")
        return out


class CheckpointQueueTests(unittest.TestCase):
    def test_message_appended_while_the_gate_drains_the_queue_is_kept_for_the_next_gate(self):
        events = []
        with mock.patch("builtins.print"):
            o = orch_mod.ResearchOrchestrator(progress_callback=lambda k, d: events.append((k, d)))
        o._user_messages = _LateAppend(["first"])
        o._gate("阶段2→3")
        self.assertEqual(events_of(events, "user_message_ack"), [{"messages": ["first"], "phase": "阶段2→3"}])
        self.assertEqual(list(o._user_messages), ["late"])


if __name__ == "__main__":
    unittest.main()
