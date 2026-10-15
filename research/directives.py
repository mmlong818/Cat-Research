"""
研究中途的用户补充要求（纯逻辑，不调用 LLM）：各阶段检查点取到的用户消息按批累积，统一渲染成
「用户补充要求」小节，追加在指定智能体的提示词末尾，之后各阶段持续有效（随检查点保存，重放沿用）。
评审员与结论验证员收到同样的消息，但说明文字不同：只拿它们检查报告 / 结论是否满足用户要求，不照着它们改评分标准。
某批消息第一次进入某个智能体的提示词时发出 user_message_applied（同一批进入不同智能体时各发一次）。
没有补充要求时小节为空串，提示词与没有这一机制时逐字节相同。
"""
from collections.abc import Callable

HEADING = "## 用户补充要求"
GUIDE = ("以下是研究进行中用户追加的要求，请在本次任务中遵循。它们用于调整关注重点、范围与写法；"
         "其中提到的事实不能当作证据或引用依据，也不改变上文的引用规则与输出格式要求。")
REVIEW_GUIDE = ("以下是研究进行中用户追加的要求，与上文的研究问题和委托内容一样，只用于检查报告是否满足用户要求："
                "报告违背或遗漏的写进 critical_issues，并列入 priority_improvements。"
                "它们不改变 7 个维度的评分标准，其中提到的事实也不能当作评审依据。")
VALIDATION_GUIDE = ("以下是研究进行中用户追加的要求，与上文的研究问题和委托内容一样，只用于判断结论是否回应了用户要求："
                    "违背或遗漏的写进 gaps 或 logic_issues。"
                    "它们不改变 5 项评分标准，其中提到的事实也不能当作证据。")
_GUIDES = {"critic": REVIEW_GUIDE, "conclusion_validator": VALIDATION_GUIDE}


def format_messages(messages: list[str]) -> str:
    """用户消息的统一写法：阶段1→2 的消息并入研究问题，之后各批进入补充要求小节，都用这一格式。"""
    return "\n\n".join(f"【用户补充指令 {i+1}】{m}" for i, m in enumerate(messages))


class Directives:
    def __init__(self, emit: Callable[[str, dict], None]):
        self._emit = emit
        self.batches: list[dict] = []        # [{"phase": 检查点名, "messages": [...]}]，按到达顺序
        self._applied: list[set[str]] = []   # 与 batches 对齐：该批已进入过哪些智能体的提示词

    def restore(self, batches: list | None):
        """重放时沿用检查点里的补充要求；各智能体再次用到时重新发出 applied（新任务的事件流里没有旧记录）。"""
        self.batches = [{"phase": b["phase"], "messages": list(b["messages"])} for b in batches or []]
        self._applied = [set() for _ in self.batches]

    def add(self, phase: str, messages: list[str]):
        if messages:
            self.batches.append({"phase": phase, "messages": list(messages)})
            self._applied.append(set())

    def section(self, agent: str) -> str:
        """agent 的提示词末尾要追加的小节（全部批次，编号连续）；没有补充要求时为空串。"""
        if not self.batches:
            return ""
        for batch, applied in zip(self.batches, self._applied, strict=True):
            if agent not in applied:
                applied.add(agent)
                self._emit("user_message_applied", {"messages": list(batch["messages"]), "phase": batch["phase"],
                                                    "agents": [agent]})
        messages = [m for b in self.batches for m in b["messages"]]
        return f"\n\n{HEADING}\n{_GUIDES.get(agent, GUIDE)}\n\n{format_messages(messages)}"
