"""
AnalystAgent - 分析综合智能体
负责对研究结果进行深入分析和综合
"""
import os

import config as _config
from agents.llm_agent import LLMAgent, read_dir_markdown
from research.ledger import Ledger
from research.source_quality import load_verification

ANALYST_SYSTEM_PROMPT = """你是一位专业的研究分析师，擅长从大量信息中提炼洞见、发现规律、建立联系。

## 你的职责
1. 读取和理解所有研究材料
2. 进行深入的分析和综合
3. 识别关键模式、趋势和洞见
4. 建立信息之间的逻辑联系
5. 产生有价值的分析结论

## 分析框架
- **事实提炼**：从信息中提取核心事实，去除重复和噪音
- **规律识别**：发现数据和案例中的规律
- **因果分析**：分析现象的原因和影响
- **对比分析**：比较不同观点、数据、案例
- **趋势推断**：基于现有数据推断发展方向
- **风险评估**：识别潜在的问题和挑战

## 分析质量要求
- 分析结论必须有据可查，来自研究材料
- 区分已确认的事实和推断性观点
- 保持客观中立，呈现多角度视角
- 对复杂问题提供有深度的解读

## 输出格式
产出结构清晰的分析报告，包含：
- 执行摘要（最重要的3-5个结论）
- 分主题的详细分析
- 数据洞见
- 综合结论"""


class AnalystAgent(LLMAgent):
    def __init__(self, model: str | None = None):
        super().__init__(name="分析师", system_prompt=ANALYST_SYSTEM_PROMPT, model=model or _config.ANALYST_MODEL)

    def analyze(self, workspace: str, question: str) -> str:
        """对研究材料做分析综合，写入 05_analysis.md 并返回路径；失败抛 LLMError。"""
        output_file = os.path.join(workspace, "05_analysis.md")
        task = f"""请对下面的研究材料进行深入分析，以 Markdown 直接返回分析报告。

## 研究问题
{question}

## 研究材料
{read_dir_markdown(os.path.join(workspace, "04_research"))}

## 声明台账（已去重、已裁决矛盾；括号内为核查状态）
{Ledger.load(workspace).claims_table(load_verification(workspace)) or "（无）"}

## 引用规则
- 分析中的事实与数据用 [C编号] 标注出处，只能引用上面台账列出的编号
- 台账未列出的声明（已被推翻、重复或矛盾未裁决）不得作为事实使用
- 状态为「存疑」的成对声明，须在同一段落中并列呈现分歧
- 台账中的状态（已核实 / 存疑 / 待核实）只作判断依据，分析中用自然语言表述，不要输出英文状态词
- 标有「(来源可信度低)」的声明，全部来源都是社交媒体、自媒体或聚合研报等低可信来源：只能带明确限定语引用，\
如"据社交媒体汇总""据聚合研报"，不得作为关键结论、厂商时间表或数据表的唯一依据；与其他来源冲突时以高可信来源为准
- 标有「(摘录待核)」的声明，其来源的原文片段与声明里的数字或时间对不上（或缺原文片段），数字、时间可能被记错：\
只能带限定语引用，如"据报道，具体时间有待核实"，或改用更可靠来源的说法；不得作为关键结论、厂商时间表或数据表的唯一依据；\
「摘录待核」只是判断依据，分析中不得原样输出该标签
- 不得断言全网范围的"不存在"（如"只见于""仅见于""唯一来源""没有其他来源"）；证据单薄时写"本研究检索到的来源中仅见于……"

## 分析报告格式
```markdown
# 研究分析报告

## 执行摘要
[3-5个最重要的核心结论，每个1-2句话]

## 一、主要发现与关键事实
[基于研究材料的核心发现，要有具体数据]

## 二、深度分析
### 2.1 [分析维度1]
### 2.2 [分析维度2]
### 2.3 [分析维度3]
...

## 三、多角度视角
[不同立场、观点的对比分析]

## 四、数据洞见
[关键数据的解读和含义]

## 五、综合结论
[综合所有分析得出的结论]

## 六、研究局限性
[信息来源的限制、可能的偏差等]
```"""

        self.ask_text(task, output_file)
        return output_file
