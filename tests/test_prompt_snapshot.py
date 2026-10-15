"""提示词快照：没有用户补充要求时，完整流程中每个智能体收到的提示词与录制时逐字节相同。

快照 tests/snapshots/pipeline_prompts.json 记录每次模型请求的智能体（由系统提示词认出）、推理强度、工具、
轮数上限、是否结构化输出与提示词全文（运行日期换成占位符）。有意修改提示词后重新录制：
    RECORD_PROMPT_SNAPSHOT=1 python -m unittest tests.test_prompt_snapshot
"""
import json
import os
import shutil
import tempfile
import unittest

from tests.pipeline_llm import ScriptedLLM, run_pipeline

SNAPSHOT = os.path.join(os.path.dirname(__file__), "snapshots", "pipeline_prompts.json")


class PromptSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_prompts_without_user_directives_match_snapshot(self):
        llm = ScriptedLLM()
        _, events = run_pipeline(self.root, llm)
        actual = llm.snapshot()
        if os.environ.get("RECORD_PROMPT_SNAPSHOT"):
            os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
            with open(SNAPSHOT, "w", encoding="utf-8", newline="\n") as f:
                json.dump(actual, f, ensure_ascii=False, indent=1)
                f.write("\n")
            self.skipTest(f"已重新录制 {len(actual)} 次请求的提示词快照")
        with open(SNAPSHOT, encoding="utf-8") as f:
            expected = json.load(f)
        self.assertEqual([r["role"] for r in actual], [r["role"] for r in expected])
        for i, (got, want) in enumerate(zip(actual, expected, strict=True)):
            self.assertEqual(got, want, f"第 {i} 次请求（{want['role']}）与快照不一致")
        self.assertIn("completed", [d.get("status") for kind, d in events if kind == "status"])


if __name__ == "__main__":
    unittest.main()
