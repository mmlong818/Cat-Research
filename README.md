<div align="center">

# 🐱 Cat-Research · 多智能体深度研究系统

**让 AI 像专业研究员一样思考、搜索、验证、迭代**

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Claude Agent SDK](https://img.shields.io/badge/Powered%20by-Claude%20Agent%20SDK-D97757?style=flat-square)](https://github.com/anthropics/claude-agent-sdk-python)

[中文](#-中文文档) · [English](#-english-documentation)

</div>

---

## 📖 中文文档

### 项目简介

**Cat-Research** 是一个基于多智能体协作的深度研究系统。它将一个研究问题自动分解为多个专业阶段，由职责各异的 AI 智能体协同完成，最终交付一份经过来源权威性验证、事实交叉核查、结论逻辑验证的高质量研究报告。

> 当前版本基于 Claude Agent SDK。早期的智谱 GLM / OpenAI 兼容版本保留在 tag [`v1-glm`](https://github.com/mmlong818/Cat-Research/tree/v1-glm)。

不同于普通的 AI 问答，Cat-Research 会：

- 🔍 **主动搜索**：借助 Claude Code 内置的 WebSearch / WebFetch 工具实时获取并抓取网络信息，自动按时效过滤（优先近 3 个月）
- 🔗 **验证来源**：4 级 Tier 分类 + 0–100 分域名评分 + 4 档置信度等级
- 📒 **声明台账**：把研究中的每条事实拆成带编号的声明并关联来源，自动去重（含中英文同义表述）、找出互相矛盾的声明；报告正文以 `[C编号]` 引用，文末自动附「声明来源」
- ✅ **核查事实**：每处矛盾独立联网裁决，关键数字类声明独立核实；程序逐段检查报告，不允许引用被推翻或未裁决的声明
- 🔄 **迭代改进**：强制执行最少 2 轮、最多 5 轮质量改进循环，配合棘轮机制保留最优版本
- 📊 **置信度报告**：最终输出综合质量评分（来源 25% + 事实 35% + 结论 40%）

---

### 系统架构

```
用户提问
   │
   ▼
┌─────────────────────────────────────────────────────┐
│                    Orchestrator                     │
│                   （研究协调器）                     │
└─────────────────────────────────────────────────────┘
   │
   ├─→ [阶段 1]   🗣️  Clarifier          意图识别与问题澄清
   │
   ├─→ [阶段 2]   📋  Planner            研究规划（生成 10–16 个多语言搜索查询）
   │
   ├─→ [阶段 3]   🔍  Researcher         网络搜索 + 网页抓取 + 研究笔记与结构化声明（入台账）
   │
   ├─→ [阶段 3.5] 🔎  SourceVerifier     来源权威性评估（Tier 1–4 + 0–100 分）
   │
   ├─→ [阶段 3.8] 📒  Reconciler         声明对账：去重 + 找出互相矛盾的声明
   │              🔬  FactChecker        逐处裁决矛盾 + 独立核实关键声明
   │
   ├─→ [阶段 4]   🧐  Analyst            综合分析（基于已裁决的声明台账）
   │
   ├─→ [阶段 5]   ✍️  Writer             初稿撰写（事实以 [C编号] 引用台账）
   │
   └─→ [阶段 6]   🔄  质量改进循环（≥ 2 轮，最多 5 轮）
           ├─→ 📎 引用检查            重建「声明来源」附录，检查被推翻 / 未裁决 / 未成对的引用
           ├─→ 🎯 Critic              多维评审（7 项评分，满分 10）
           ├─→ ✔️ ConclusionValidator  结论验证（5 项评分）
           ├─→ 🏁 停止判断            评审 ≥ 8.0 且结论 ≥ 7.5 且无引用违规与未决矛盾 / 连续 1 轮无增益 / 达到上限
           ├─→ 🔍 Researcher          补充研究（仅前 3 轮，评审要求时；新声明随即对账、裁决）
           └─→ ✍️ Writer              基于最优稿改写，修正引用违规，并参考该稿的结论验证意见
   │
   ▼
最终研究报告（09_final.md，取无引用违规的最优稿）+ 置信度报告（08_verification/confidence_report.json）
```

---

### 10 大智能体

| 智能体 | 职责 |
|--------|------|
| 🗣️ **Clarifier**（澄清者） | 识别用户意图，判断是否需要澄清，自动调整研究方向与深度 |
| 📋 **Planner**（规划师） | 将问题分解为 10–16 个多语言搜索查询，按时效与领域分层排列 |
| 🔍 **Researcher**（研究员） | 使用 Claude Code 内置的 WebSearch / WebFetch 执行网络搜索与网页抓取，查询按 3 个一组、最多 4 组并行执行，聚合多源原始数据 |
| 🔎 **SourceVerifier**（来源验证员） | 对每个来源打 Tier 1–4 标签并给出 0–100 分域名评分，识别不可靠来源 |
| 🧐 **Analyst**（分析师） | 整合原始资料，提炼关键发现，进行因果、趋势、对比分析 |
| ✍️ **Writer**（写作者） | 撰写结构化研究报告，根据评审反馈多轮迭代优化；改写时另收到结论验证员对最优稿的意见（改进指示、缺口、逻辑问题），以评审意见为主、验证意见为补充 |
| 🎯 **Critic**（评审员） | 从完整性、准确性、深度、清晰性等 7 个维度对报告打分，并对照用户的研究问题、委托内容与中途补充指令检查报告是否满足要求 |
| 📒 **Reconciler**（对账员） | 比对新旧声明，合并重复（含中英文同义表述），找出互相矛盾的声明对 |
| 🔬 **FactChecker**（事实核查员） | 逐处联网裁决矛盾（胜出方 / 两方都不可靠），独立核实最多 8 条关键数字类声明，给出 0.0–1.0 置信度 |
| ✔️ **ConclusionValidator**（结论验证员） | 验证结论的逻辑严密性、全面性与实用价值（5 项评分），并对照用户的研究问题、委托内容与中途补充指令判断结论是否回应了用户要求（遵循要求所作的取舍不扣「覆盖全面性」分，违背的写进 gaps / logic_issues）；其改进指示、gaps 与 logic_issues 在改写时交给写作者 |

---

### 项目结构

```
Cat-Research/
├── main.py                  # 命令行入口
├── run_api.py               # Web UI + API 服务入口
├── orchestrator.py          # 研究编排器（主流程控制）
├── config.py                # 全局配置（模型 / 研究质量参数）
├── requirements.txt         # Python 依赖
├── settings.example.json    # 配置模板
│
├── orchestration/           # 编排器的分阶段实现（ResearchOrchestrator 由这几部分组成）
│   ├── base.py              # 基础设施：智能体初始化、进度事件、阶段间检查点（停止 / 暂停 / 用户消息）
│   ├── phases.py            # 阶段 1–5：澄清落盘、规划、网络研究、来源验证、声明台账、分析、初稿
│   ├── improve.py           # 阶段 6：评审与改进循环
│   └── finish.py            # 阶段 7–8：选定终稿、置信度报告、报告附录与用量汇总
│
├── llm/                     # 统一 LLM 调用层（按模型路由到 Claude / OpenAI / 智谱）
│   ├── client.py            # 对外接口：同步/并行调用、超时与重试、本地 schema 校验
│   ├── models.py            # 模型注册表（能力表：价格、推理强度、联网与结构化方式、并发上限）
│   ├── profiles.py          # 模型配置档：提供方 + 核心/辅助模型，按角色分配给智能体
│   ├── tools_local.py       # 本地联网工具（智谱 Search API + 网页正文抓取），供 GLM 工具循环使用
│   └── providers/           # claude（claude-agent-sdk）/ anthropic（API Key）/ openai / zhipu
│
├── agents/                  # 所有智能体实现
│   ├── llm_agent.py         # 智能体基类
│   ├── clarifier.py         # 澄清者
│   ├── planner.py           # 规划师
│   ├── researcher.py        # 研究员
│   ├── analyst.py           # 分析师
│   ├── writer.py            # 写作者
│   ├── critic.py            # 评审员
│   ├── source_verifier.py   # 来源验证员
│   ├── fact_checker.py      # 事实核查员（矛盾裁决 + 独立核实）
│   ├── reconciler.py        # 对账员
│   └── conclusion_validator.py  # 结论验证员
│
├── research/                # 纯逻辑模块（不调用 LLM）
│   ├── ledger.py            # 声明台账与引用检查规则
│   ├── loop_policy.py       # 改进循环停止条件、最优稿棘轮与最终稿选择
│   ├── directives.py        # 研究中途的用户补充要求：按批累积，注入研究员 / 事实核查员 / 分析师 / 写作者 / 评审员 / 结论验证员的提示词
│   └── confidence.py        # 综合置信度加权计算
│
├── api/                     # FastAPI Web 服务
│   ├── app.py               # FastAPI 应用 + 核心路由
│   └── routes/              # config 路由（设置、默认配置档、API Key）
│
├── tools/                   # 工具模块
│   ├── fact_tools.py        # 单条声明独立交叉核实
│   ├── file_tools.py        # 文件读写工具
│   ├── domain_checker.py    # 域名权威性检测
│   └── verification_registry.py  # 已执行查询的缓存注册表
│
├── tests/                   # unittest 测试（python -m unittest discover -s tests -t .）
├── frontend/                # Web UI 前端源码
└── workspace/               # 研究输出目录（每次研究独立文件夹）
```

---

### 快速开始

#### 1. 克隆项目

```bash
git clone https://github.com/mmlong818/Cat-Research.git
cd Cat-Research
```

#### 2. 安装依赖

```bash
pip install -r requirements.txt
```

#### 3. 安装并登录 Claude Code

所有智能体通过 [claude-agent-sdk](https://github.com/anthropics/claude-agent-sdk-python) 调用本机的 Claude Code，复用其登录状态（即你的 Claude 订阅额度），**不需要单独申请 API Key**。

```bash
npm install -g @anthropic-ai/claude-code
claude auth login
```

> Windows 提示：npm 安装的 `claude.CMD` 无法直接被 SDK 调用，程序会自动改用 npm 包内的原生
> `claude.exe`（`node_modules/@anthropic-ai/claude-code/bin/claude.exe`）。若找不到，可设置环境变量
> `CLAUDE_CLI_PATH` 指向该文件。

（可选）如需覆盖默认模型，复制 `settings.example.json` 为 `settings.json` 并编辑：

```json
{
  "core_model": "claude-opus-5-5",
  "support_model": "claude-sonnet-5-5"
}
```

也可通过环境变量配置（优先级高于 settings.json，详见 `.env.example`）：

```bash
export CORE_MODEL=claude-opus-5-5
export SUPPORT_MODEL=claude-sonnet-5-5
```

#### 4. 启动研究

**方式一：命令行直接提问**

```bash
python main.py "2025年大模型行业有哪些重要进展？"
```

**方式二：命令行交互模式**

```bash
python main.py
# 按提示输入研究问题，随后进入最多 4 轮澄清对话（直接回车即开始研究）
# 确认开始后预计耗时约 45-80 分钟（取决于问题复杂度与改进轮数）
```

**方式三：Web UI + REST API 服务**

```bash
python run_api.py
# 访问 http://localhost:8000
```

---

### 输出结构

每次研究会在 `workspace/` 目录下生成独立会话文件夹：

```
workspace/session_20250322_143022/
├── 00_session.json               # 会话元信息（状态、模型、耗时等）
├── 01_question.txt               # 原始研究问题
├── 03_plan.json                  # 研究规划（搜索查询列表）
├── 04_clarification/
│   └── clarification.json        # 意图澄清结果
├── 04_research/                  # 各轮原始搜索数据与网页内容（round_N.md）
├── 05_analysis.md                # 综合分析报告
├── 06_drafts/                    # 各轮草稿历史（draft_N.md，末尾附「声明来源」）
├── 07_reviews/                   # 评审记录（review_N.json，含 7 维度分数）
├── 08_verification/               # 所有验证结果
│   ├── ledger.json                 # 📒 声明台账（来源 S* / 声明 C* / 矛盾 X* 及裁决）
│   ├── source_verification.json    # 来源权威性评估
│   ├── fact_check.json             # 事实核查结果（独立核实 + 矛盾裁决统计）
│   ├── conclusion_validation.json  # 结论验证结果
│   ├── confidence_report.json      # 📊 综合置信度报告
│   └── verified_registry.json      # 已执行查询的缓存注册表
├── 09_final.md                   # 📄 最终研究报告（无引用违规的最优稿 + 声明来源）
└── research_log.txt              # 运行日志
```

---

### API 端点

启动 `python run_api.py` 后可访问以下接口：

**研究任务**

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/research` | 启动研究任务 |
| `GET` | `/api/research/{id}/stream` | SSE 流式获取实时进度 |
| `GET` | `/api/research/{id}/status` | 查询任务当前状态 |
| `GET` | `/api/research/{id}/result` | 获取已完成任务的结果 |
| `GET` | `/api/research/{id}/audit` | 任务审计日志：用户输入与操作、检查点、循环停止原因、最终稿选择 |
| `POST` | `/api/research/{id}/message` | 向正在运行的任务注入消息 |
| `POST` | `/api/research/{id}/pause` | 暂停任务 |
| `POST` | `/api/research/{id}/resume` | 恢复任务 |
| `POST` | `/api/research/{id}/stop` | 停止任务（SSE 发 `stopped` 事件，与失败的 `error` 分开） |
| `DELETE` | `/api/research/{id}` | 停止并删除任务（会话目录已不在时也删除任务记录；审计记录保留） |

**会话管理**

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/sessions` | 获取历史研究会话列表 |
| `GET` | `/api/sessions/{id}/report` | 获取会话最终报告 |
| `GET` | `/api/sessions/{id}/plan` | 获取会话研究计划 |
| `GET` | `/api/sessions/{id}/reviews` | 每轮评审：7 维评分、平均分、优点、关键问题、下一版要改的点 |
| `GET` | `/api/sessions/{id}/phases` | 获取会话各阶段内容 |
| `GET` | `/api/sessions/{id}/checkpoints` | 列出已完成阶段的检查点与默认续跑起点 |
| `POST` | `/api/sessions/{id}/replay` | 从指定阶段重放（`{"from_phase": "improve"}`；省略则从断点续跑）；停止后旧线程还没退出时返回 409 |
| `GET` | `/api/sessions/{id}/audit` | 会话审计日志（含所有重放任务） |
| `DELETE` | `/api/sessions/{id}` | 删除会话及工作区 |

任务状态保存在 `research_tasks.db`，服务重启后仍可查询；重启前未结束的任务标记为 `interrupted`。
每个阶段（clarify → plan → research → sources → ledger → analyze → draft → improve → finish）完成后，工作区会快照到 `.checkpoints/`；重放时该阶段之后的草稿、评审与声明台账一并回滚，同一会话同时只能有一个任务。

**澄清对话**

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/clarify` | 开始意图澄清会话 |
| `POST` | `/api/clarify/{id}/message` | 继续澄清对话 |
| `POST` | `/api/clarify/{id}/confirm` | 确认问题并启动研究（可带改过的 `question` 与研究目标 `goal`） |

**系统**

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/config` | 获取当前系统配置 |
| `POST` | `/api/config` | 运行时更新系统配置 |
| `GET` | `/api/settings` | 默认配置档、各提供方 Key 状态（仅末 4 位预览）与可选模型 |
| `POST` | `/api/settings` | 更新默认配置档与 API Key（`default_profile`、`api_keys`，空字符串表示不改；`clear_keys` 删除） |
| `DELETE` | `/api/settings/keys/{provider}` | 清除某家的 API Key（claude / openai / zhipu） |
| `GET` | `/api/models` | 能力表里的模型，按提供方分组 |
| `GET` | `/` | Web UI 界面 |
| `GET` | `/docs` | Swagger 交互式 API 文档 |

---

### 配置说明

环境变量（完整示例见 `.env.example`；模型项优先级高于 `settings.json`）：

```env
# ── 模型选择（通过本机 Claude Code 调用，无需 API Key）────────────────
CORE_MODEL=claude-opus-5-5      # 核心模型（规划/研究/分析/写作/澄清）
SUPPORT_MODEL=claude-sonnet-5-5 # 辅助模型（评审/来源验证/事实核查/结论验证）

# 原生 claude 可执行文件路径（Windows 上 npm 安装的 claude.CMD 无法使用时需要）
# CLAUDE_CLI_PATH=C:\path\to\claude.exe

# ── API 服务 ──────────────────────────────────────────────────────
API_HOST=127.0.0.1              # 默认只监听本机；局域网访问需显式改为 0.0.0.0
CAT_ALLOWED_HOSTS=              # 允许的额外主机名（逗号分隔），局域网访问时填写
CAT_API_AUTH=1                  # /api/* 需要本地令牌；开发模式（vite 代理）可设 0
API_PORT=8000
CORS_ORIGINS=http://localhost:8000
```

> 安全说明：服务启动时生成本地令牌，注入到 Web UI 页面，前端自动携带；其他网站受同源策略限制读不到它。
> 所有请求都校验 Host 头（防 DNS rebinding）。Web UI 里填写的 API Key 存入系统凭据库（Windows 凭据管理器），不写入明文文件。

研究质量参数是 `config.py` 中的常量（不读取环境变量），需要调整时直接修改：

```python
MAX_IMPROVEMENT_CYCLES = 5    # 最多改进轮数
MIN_IMPROVEMENT_CYCLES = 2    # 最少改进轮数（按澄清出的复杂度可调整；API 可按任务指定）
QUALITY_THRESHOLD = 8.0       # 评审分提前停止阈值（满分 10）
CONCLUSION_THRESHOLD = 7.5    # 结论验证平均分达标线
NO_GAIN_PATIENCE = 1          # 连续多少轮评审分未超过最优分即停止
```

---

### 模型

默认全部智能体调用都经由 `claude-agent-sdk` 转发给本机已登录的 Claude Code（订阅额度，无需 API Key）：

| 角色 | 默认模型 | 负责的智能体 |
|------|----------|--------------|
| 核心模型 | `claude-opus-5-5` | Clarifier、Planner、Researcher、Analyst、Writer |
| 辅助模型 | `claude-sonnet-5-5` | Critic、SourceVerifier、Reconciler、FactChecker、ConclusionValidator |

可通过环境变量 `CORE_MODEL` / `SUPPORT_MODEL`，或 `settings.json` 中的 `core_model` / `support_model` 覆盖。

也可以换用其他提供方的模型（调用层按模型 ID 自动路由，需要对应的 API Key：设置页存入系统凭据库，
或环境变量 `OPENAI_API_KEY` / `ZHIPU_API_KEY`）：

| 提供方 | 核心 / 辅助（默认） | 联网 | 结构化输出 |
|--------|--------------------|------|------------|
| OpenAI | `gpt-6.1-sol` / `gpt-6-luna` | 托管 web_search | json_schema（strict）+ 本地校验 |
| 智谱 | `glm-5.3` / `glm-5.3-flash` | 本地工具循环（智谱 Search API + 本机抓取网页） | json_object + 提示词 + 本地校验 |

**在界面里选择**：设置页选默认提供方（Claude / GPT / 智谱）及其核心、辅助模型，并录入各家 API Key（只存系统凭据库，页面仅显示末 4 位）。
设置里的默认提供方用于新建研究；开始研究时可在启动区临时换提供方（或展开指定型号），本次选择记入审计与会话参数快照。
选择需要 Key 的提供方而未配置时，接口在建任务前返回 400（"请先在设置中填写 … 的 API Key"）。重放沿用会话原来的提供方与模型。
启动预检（`python main.py`）只在默认提供方是 Claude 时要求本机 Claude Code，其余检查对应 Key。

---

### 系统要求

- Python 3.10+
- 已安装并登录 [Claude Code](https://github.com/anthropics/claude-code)（复用其 Claude 订阅额度，无需 API Key）
- 正常的网络连接（用于实时网络搜索）
- 内存：512 MB+（推荐 2 GB 以上）

> 实测参考（非承诺值）：2026 年 9 月，引入声明台账前一次完整研究（"开源大模型编程能力"）约 61 分钟、4 轮评审；
> 引入声明台账后一次完整研究（"固态电池量产进展"）约 86 分钟、5 轮评审，其中 2 轮由一个已修复的引用检查缺陷导致。
> 实际耗时随问题复杂度、改进轮数与网络状况波动。

---

## 📖 English Documentation

### Overview

**Cat-Research** is a multi-agent collaborative deep research system. It automatically decomposes a research question into specialized stages, each handled by a dedicated AI agent, ultimately producing a high-quality research report with source credibility verification, cross-referenced fact-checking, and validated conclusions.

> The current version runs on the Claude Agent SDK. The earlier GLM / OpenAI-compatible version is kept at tag [`v1-glm`](https://github.com/mmlong818/Cat-Research/tree/v1-glm).

Unlike simple AI Q&A tools, Cat-Research will:

- 🔍 **Actively search** using Claude Code's built-in WebSearch / WebFetch tools, with automatic recency filtering (prioritizes last 3 months)
- 🔗 **Verify sources** using 4-tier classification + 0–100 domain scoring + 4-level confidence rating
- 📒 **Keep a claim ledger**: every fact is recorded as a numbered claim linked to its sources, deduplicated (including zh/en wording of the same fact) and checked for contradictions; reports cite `[C#]` and get an auto-generated claim-source appendix
- ✅ **Fact-check** by adjudicating every contradiction and independently verifying key numeric claims on the web; the report is checked paragraph by paragraph so it never cites overruled or unresolved claims
- 🔄 **Iteratively improve** with a minimum of 2 and up to 5 quality cycles, with a ratchet mechanism to preserve the best version
- 📊 **Output a confidence report** with weighted quality scoring (sources 25% + facts 35% + conclusions 40%)

---

### Architecture

```
User Query
   │
   ▼
┌─────────────────────────────────────────────────────┐
│                    Orchestrator                     │
└─────────────────────────────────────────────────────┘
   │
   ├─→ [Stage 1]   🗣️  Clarifier          Intent recognition & clarification
   ├─→ [Stage 2]   📋  Planner            Research planning (10–16 queries)
   ├─→ [Stage 3]   🔍  Researcher         Web search + page scraping; notes + structured claims (into the ledger)
   ├─→ [Stage 3.5] 🔎  SourceVerifier     Source authority scoring (Tier 1–4, 0–100)
   ├─→ [Stage 3.8] 📒  Reconciler         Claim reconciliation: dedupe + find contradicting claims
   │               🔬  FactChecker        Adjudicate each contradiction + independently verify key claims
   ├─→ [Stage 4]   🧐  Analyst            Synthesis based on the adjudicated claim ledger
   ├─→ [Stage 5]   ✍️  Writer             First draft (facts cite the ledger as [C#])
   └─→ [Stage 6]   🔄  Quality Loop (≥ 2 rounds, max 5)
           ├─→ 📎 Citation check      Rebuild the claim-source appendix; flag overruled / unresolved / unpaired citations
           ├─→ 🎯 Critic              Multi-dimension review (7 scores / 10)
           ├─→ ✔️ ConclusionValidator  Conclusion validation (5 scores)
           ├─→ 🏁 Stop check          review ≥ 8.0 & conclusion ≥ 7.5 & no citation violations or open contradictions / 1 round without gain / max rounds
           ├─→ 🔍 Researcher          Supplemental research (rounds 1–3, when requested; new claims reconciled and adjudicated right away)
           └─→ ✍️ Writer              Rewrite from the best draft, fixing citation violations and taking that draft's validation notes into account
   │
   ▼
Final Report (09_final.md, best draft without citation violations) + Confidence Report (08_verification/confidence_report.json)
```

---

### 10 Specialized Agents

| Agent | Role |
|-------|------|
| 🗣️ **Clarifier** | Identifies user intent, decides if clarification is needed, adjusts scope |
| 📋 **Planner** | Breaks down the question into 10–16 multilingual queries, layered by recency |
| 🔍 **Researcher** | Executes web searches and page scraping via Claude Code's built-in WebSearch / WebFetch, running query groups of 3 with up to 4 groups in parallel, aggregates raw multi-source data |
| 🔎 **SourceVerifier** | Assigns Tier 1–4 labels and 0–100 domain scores to each source; flags unreliable ones |
| 🧐 **Analyst** | Synthesizes research into key findings; causal, trend, and comparative analysis |
| ✍️ **Writer** | Writes structured research reports; iterates based on review feedback; on rewrites it also gets the conclusion validator's notes on the best draft (instructions, gaps, logic issues), with the critic's review taking priority |
| 🎯 **Critic** | Reviews on 7 dimensions: completeness, accuracy, depth, clarity, usefulness, sources, simplicity; also checks the report against the user's question, confirmed brief and mid-run instructions |
| 📒 **Reconciler** | Compares new and existing claims, merges duplicates (including zh/en wording), finds contradicting claim pairs |
| 🔬 **FactChecker** | Adjudicates each contradiction on the web (one side wins / neither is reliable) and independently verifies up to 8 key numeric claims (confidence 0.0–1.0) |
| ✔️ **ConclusionValidator** | Validates logical rigor, completeness, and practical value of conclusions (5 scores); also judges whether the conclusions answer the user's question, confirmed brief and mid-run instructions (trade-offs made to follow them are not penalised as incomplete; violations go into gaps / logic_issues); its instructions, gaps and logic issues are handed to the writer on rewrites |

---

### Quick Start

#### 1. Clone

```bash
git clone https://github.com/mmlong818/Cat-Research.git
cd Cat-Research
```

#### 2. Install dependencies

```bash
pip install -r requirements.txt
```

#### 3. Install and log in to Claude Code

Every agent calls the local Claude Code installation through [claude-agent-sdk](https://github.com/anthropics/claude-agent-sdk-python), reusing its login session (i.e. your Claude subscription quota) — **no separate API key is required**.

```bash
npm install -g @anthropic-ai/claude-code
claude auth login
```

> Windows note: the npm-installed `claude.CMD` cannot be invoked by the SDK directly. The program
> automatically falls back to the native `claude.exe` bundled with the npm package
> (`node_modules/@anthropic-ai/claude-code/bin/claude.exe`). If it can't be found, set the
> `CLAUDE_CLI_PATH` environment variable to point to it.

(Optional) To override the default models, copy `settings.example.json` to `settings.json` and edit it:

```json
{
  "core_model": "claude-opus-5-5",
  "support_model": "claude-sonnet-5-5"
}
```

You can also configure this via environment variables (takes precedence over settings.json, see `.env.example`):

```bash
export CORE_MODEL=claude-opus-5-5
export SUPPORT_MODEL=claude-sonnet-5-5
```

#### 4. Run

**CLI — direct question:**
```bash
python main.py "What are the major AI breakthroughs in 2025?"
```

**CLI — interactive mode:**
```bash
python main.py
# Enter your question, then go through up to 4 rounds of clarification
# (press Enter with no input to start the research)
# Once confirmed, expect roughly 45-80 minutes depending on question complexity and improvement rounds
```

**Web UI + API server:**
```bash
python run_api.py
# Open http://localhost:8000
```

---

### Output Structure

Each research session creates an isolated folder under `workspace/`:

```
workspace/session_20250322_143022/
├── 00_session.json               # Session metadata (status, models, elapsed time, etc.)
├── 01_question.txt               # Original question
├── 03_plan.json                  # Research plan (query list)
├── 04_clarification/
│   └── clarification.json        # Clarification result
├── 04_research/                  # Raw search data & scraped pages per round (round_N.md)
├── 05_analysis.md                # Synthesized analysis
├── 06_drafts/                    # Draft history (draft_N.md, with a claim-source appendix)
├── 07_reviews/                   # Review records (review_N.json, with 7-dim scores)
├── 08_verification/               # All verification results
│   ├── ledger.json                 # 📒 Claim ledger (sources S* / claims C* / contradictions X* with rulings)
│   ├── source_verification.json    # Source authority scores
│   ├── fact_check.json             # Fact-check results (independent checks + contradiction stats)
│   ├── conclusion_validation.json  # Conclusion validation
│   ├── confidence_report.json      # 📊 Confidence report
│   └── verified_registry.json      # Cache registry of executed queries
├── 09_final.md                   # 📄 Final research report (best draft without citation violations + claim sources)
└── research_log.txt              # Run log
```

---

### API Reference

After running `python run_api.py`:

**Research Tasks**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/research` | Start a new research task |
| `GET` | `/api/research/{id}/stream` | SSE stream for real-time progress |
| `GET` | `/api/research/{id}/status` | Get current task status |
| `GET` | `/api/research/{id}/result` | Get completed task result |
| `GET` | `/api/research/{id}/audit` | Task audit log: user inputs and actions, checkpoints, loop stop reason, final draft selection |
| `POST` | `/api/research/{id}/message` | Inject a message into a running task |
| `POST` | `/api/research/{id}/pause` | Pause a task |
| `POST` | `/api/research/{id}/resume` | Resume a paused task |
| `POST` | `/api/research/{id}/stop` | Stop a task (SSE emits `stopped`, separate from the `error` of a failure) |
| `DELETE` | `/api/research/{id}` | Stop and delete a task (also when its session directory is already gone; audit entries are kept) |

**Sessions**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/sessions` | List all research sessions |
| `GET` | `/api/sessions/{id}/report` | Get session final report |
| `GET` | `/api/sessions/{id}/plan` | Get session research plan |
| `GET` | `/api/sessions/{id}/reviews` | Per-round reviews: 7 dimension scores, average, strengths, critical issues, priority improvements |
| `GET` | `/api/sessions/{id}/phases` | Get all phase outputs for a session |
| `GET` | `/api/sessions/{id}/checkpoints` | List completed-phase checkpoints and the default resume point |
| `POST` | `/api/sessions/{id}/replay` | Replay from a phase (`{"from_phase": "improve"}`; omit to resume); 409 while a stopped run's thread is still exiting |
| `GET` | `/api/sessions/{id}/audit` | Session audit log (including all replay tasks) |
| `DELETE` | `/api/sessions/{id}` | Delete session and workspace |

Task status is stored in `research_tasks.db` and survives a restart; tasks unfinished at restart are marked `interrupted`.
After each phase (clarify → plan → research → sources → ledger → analyze → draft → improve → finish) the workspace is snapshotted into `.checkpoints/`; a replay rolls back later drafts, reviews and the claim ledger, and only one task may run per session at a time.

**Clarification**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/clarify` | Start a clarification session |
| `POST` | `/api/clarify/{id}/message` | Continue clarification dialog |
| `POST` | `/api/clarify/{id}/confirm` | Confirm and start research (optionally with an edited `question` and a `goal`) |

**System**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/config` | Get system configuration |
| `POST` | `/api/config` | Update configuration at runtime |
| `GET` | `/api/settings` | Default profile, per-provider key status (last 4 chars only) and selectable models |
| `POST` | `/api/settings` | Update default profile and API keys (`default_profile`, `api_keys` — empty string = unchanged; `clear_keys` deletes) |
| `DELETE` | `/api/settings/keys/{provider}` | Clear one provider's API key (claude / openai / zhipu) |
| `GET` | `/api/models` | Models from the capability table, grouped by provider |
| `GET` | `/` | Web UI |
| `GET` | `/docs` | Swagger interactive API docs |

---

### Configuration

Environment variables (see `.env.example`; model settings take precedence over `settings.json`):

```env
# Model selection (called through local Claude Code, no API key needed)
CORE_MODEL=claude-opus-5-5      # Core model (planning / research / analysis / writing / clarification)
SUPPORT_MODEL=claude-sonnet-5-5 # Support model (review / source verification / fact-check / conclusion validation)

# Native claude executable path (needed on Windows when npm's claude.CMD can't be used)
# CLAUDE_CLI_PATH=C:\path\to\claude.exe

# API server
API_HOST=127.0.0.1              # loopback only by default; set 0.0.0.0 explicitly for LAN access
CAT_ALLOWED_HOSTS=              # extra allowed host names (comma-separated) for LAN access
CAT_API_AUTH=1                  # /api/* requires the local token; set 0 for dev mode (vite proxy)
API_PORT=8000
CORS_ORIGINS=http://localhost:8000
```

> Security: a local token is generated at startup and injected into the Web UI page, which sends it automatically; other websites cannot read it (same-origin policy).
> Every request's Host header is checked (DNS rebinding protection). API keys entered in the Web UI go to the OS credential store (Windows Credential Manager), never to a plaintext file.

Quality parameters are constants in `config.py` (not read from the environment); edit them there:

```python
MAX_IMPROVEMENT_CYCLES = 5    # Maximum improvement rounds
MIN_IMPROVEMENT_CYCLES = 2    # Minimum rounds (adjusted by clarified complexity; the API can set it per task)
QUALITY_THRESHOLD = 8.0       # Early-stop review-score threshold (out of 10)
CONCLUSION_THRESHOLD = 7.5    # Required average conclusion-validation score
NO_GAIN_PATIENCE = 1          # Stop after this many consecutive rounds with no gain over the best score
```

---

### Models

By default every agent call is routed through `claude-agent-sdk` to the Claude Code installation already logged in on your machine (subscription quota, no API key):

| Role | Default model | Agents |
|------|----------------|--------|
| Core model | `claude-opus-5-5` | Clarifier, Planner, Researcher, Analyst, Writer |
| Support model | `claude-sonnet-5-5` | Critic, SourceVerifier, Reconciler, FactChecker, ConclusionValidator |

Override with the `CORE_MODEL` / `SUPPORT_MODEL` environment variables, or `core_model` / `support_model` in `settings.json`.

Models from other providers work too (the LLM layer routes by model ID; an API key is required, stored via the
settings page in the OS credential store, or set as `OPENAI_API_KEY` / `ZHIPU_API_KEY`):

| Provider | Core / support (default) | Web access | Structured output |
|----------|--------------------------|------------|-------------------|
| OpenAI | `gpt-6.1-sol` / `gpt-6-luna` | hosted web_search | json_schema (strict) + local validation |
| Zhipu | `glm-5.3` / `glm-5.3-flash` | local tool loop (Zhipu Search API + local page fetch) | json_object + prompt + local validation |

**Choosing in the UI**: Settings sets the default provider (Claude / GPT / Zhipu) with its core and support models, and stores each
provider's API key (OS credential store only; the page shows the last 4 characters). When starting a research run you can switch
provider for that run (or expand to pick specific models); the choice is
recorded in the audit log and parameter snapshot. Picking a provider that needs a key you have not entered returns 400 before any task is
created. Replay keeps the session's original provider and models. The startup preflight (`python main.py`) only requires the local Claude
Code when the default provider is Claude; otherwise it checks the matching key.

---

### Requirements

- Python 3.10+
- [Claude Code](https://github.com/anthropics/claude-code) installed and logged in (reuses your Claude subscription quota — no API key needed)
- Internet access (for real-time web search)
- RAM: 512 MB minimum (2 GB recommended)

> Reference data point (not a guarantee): in September 2026, one full research run (a question about
> open-source LLM coding ability) took about 61 minutes and stopped after 4 review rounds due to no
> further gain. Actual time varies with question complexity, improvement rounds, and network conditions.

---

### License

MIT License · Free to use, modify, and distribute.

---

<div align="center">

Made with ❤️ · [Issues](https://github.com/mmlong818/Cat-Research/issues) · [Discussions](https://github.com/mmlong818/Cat-Research/discussions)

</div>
