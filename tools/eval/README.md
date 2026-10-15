# 回归评测

改动研究流程（提示词、核查规则、循环策略、模型）后，用固定问题跑一次研究，再与基线报告做盲评，判断是变好还是变差。

## 步骤

```bash
# 1. 用当前代码跑一次（deep 约 35–60 分钟，消耗所选提供方额度）
python -m tools.eval.run Q2 --depth deep            # 默认用设置里的默认提供方
python -m tools.eval.run Q2 --depth deep --provider zhipu

# 2. 与基线盲评（输出里 EVAL_RUN 的 final_draft 就是候选报告）
python -m tools.eval.judge Q2 workspace/session_XXXX/06_drafts/draft_N.md --baseline baseline_q2.md --out judge_q2.json
```

## 盲评做了什么

- **两两比较**：评审员 `claude-opus-5` 在两种顺序（AB、BA）下各评一次，消除位置偏差；五个维度打分（准确性与可核实性、完整性、分析深度、时效性、清晰度）并给出胜方与理由。报告先匿名化（去掉质量附录、版本号痕迹）。
- **事实抽查**：按固定种子从每份报告抽 5 条含数字的陈述，联网核实为 supported / contradicted / unverifiable。评审员核查偶尔会误读语境，结论要看 note 再采信。
- **客观指标**：字数、去重 URL 数、来源域名数、含数字句子的引用覆盖率。

评审员固定不换，否则历史分数不可比。单次运行有随机波动，一胜一负或分数差 0.5 以内不足以下结论。

## 基线

仓库不附带基线报告。先用改动前的代码对同一个问题跑一次，把它的最终稿当基线，再用 `--baseline` 指定；之后的改动都和同一份基线比，分数才可比。
