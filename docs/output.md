中文 · [English](output.en.md) · [返回 README](../README.md)

# 输出结构

每次研究在 `workspace/` 下生成一个会话目录：

```
workspace/session_20261007_133450/
├── 00_session.json               # 会话元信息（状态、模型、耗时、用量）
├── 01_question.txt               # 研究问题与委托补充说明
├── 03_plan.json                  # 检索计划
├── 04_clarification/             # 澄清结果
├── 04_research/                  # 各轮原始搜索数据与网页内容
├── 05_analysis.md                # 综合分析
├── 06_drafts/                    # 各版草稿（draft_0.md 为初稿，末尾附「声明来源」）
├── 07_reviews/                   # 每轮评审（7 项分数）
├── 08_verification/
│   ├── ledger.json               # 声明台账（来源 S* / 声明 C* / 矛盾 X* 及裁决）
│   ├── source_verification.json  # 来源评估
│   ├── fact_check.json           # 独立核实与矛盾裁决
│   ├── conclusion_validation.json
│   ├── confidence_report.json    # 置信度报告
│   └── verified_registry.json    # 已执行查询的缓存
├── 09_final.md                   # 终稿
├── research_log.txt              # 运行日志
└── .checkpoints/                 # 每个阶段完成后的快照，用于续办与重放
```

任务状态保存在项目根的 `research_tasks.db`，服务重启后仍可查询；重启前未结束的任务标记为 `interrupted`。
