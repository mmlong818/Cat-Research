<div align="center">

# 🐱 Cat-Research · 多智能体深度研究系统

**让 AI 像专业研究员一样思考、搜索、验证、迭代**

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![OpenAI Compatible](https://img.shields.io/badge/API-OpenAI%20Compatible-412991?style=flat-square&logo=openai&logoColor=white)](https://platform.openai.com)

[中文](#-中文文档) · [English](#-english-documentation)

</div>

---

## 📖 中文文档

### 项目简介

**Cat-Research** 是一个基于多智能体协作的深度研究系统。它将一个研究问题自动分解为多个专业阶段，由职责各异的 AI 智能体协同完成，最终交付一份经过来源权威性验证、事实交叉核查、结论逻辑验证的高质量研究报告。

不同于普通的 AI 问答，Cat-Research 会：

- 🔍 **主动搜索**：通过智谱 Search API 实时获取最新网络信息，自动按时效过滤（优先近 3 个月）
- 🔗 **验证来源**：4 级 Tier 分类 + 0–100 分域名评分 + 4 档置信度等级
- ✅ **核查事实**：对关键声明进行交叉验证，输出置信度分数（0.0–1.0）
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
   ├─→ [阶段 3]   🔍  Researcher         网络搜索 + 网页抓取 + 多源收集
   │
   ├─→ [阶段 3.5] 🔎  SourceVerifier     来源权威性评估（Tier 1–4 + 0–100 分）
   │
   ├─→ [阶段 4]   🧐  Analyst            综合分析（因果 / 趋势 / 对比）
   │
   ├─→ [阶段 5]   ✍️  Writer             初稿撰写（结构化研究报告）
   │
   ├─→ [阶段 5.5] 🔬  FactChecker        事实核查（关键声明交叉验证）
   │
   └─→ [阶段 6]   🔄  质量改进循环（强制 ≥ 2 轮，最多 5 轮）
           ├─→ 🎯 Critic              多维评审（7 项评分，满分 10）
           ├─→ 🔍 Researcher          补充研究（仅前 3 轮）
           ├─→ ✔️ ConclusionValidator  结论验证（5 项评分）
           └─→ ✍️ Writer              迭代改进（棘轮机制保留最优版本）
   │
   ▼
最终研究报告（09_final.md）+ 置信度报告（08_verification/confidence_report.json）
```

---

### 9 大智能体

| 智能体 | 职责 |
|--------|------|
| 🗣️ **Clarifier**（澄清者） | 识别用户意图，判断是否需要澄清，自动调整研究方向与深度 |
| 📋 **Planner**（规划师） | 将问题分解为 10–16 个多语言搜索查询，按时效与领域分层排列 |
| 🔍 **Researcher**（研究员） | 执行网络搜索（智谱 Search API，降级备选 DuckDuckGo），抓取网页正文，聚合多源原始数据 |
| 🔎 **SourceVerifier**（来源验证员） | 对每个来源打 Tier 1–4 标签并给出 0–100 分域名评分，识别不可靠来源 |
| 🧐 **Analyst**（分析师） | 整合原始资料，提炼关键发现，进行因果、趋势、对比分析 |
| ✍️ **Writer**（写作者） | 撰写结构化研究报告，根据评审反馈多轮迭代优化 |
| 🎯 **Critic**（评审员） | 从完整性、准确性、深度、清晰性等 7 个维度对报告打分 |
| 🔬 **FactChecker**（事实核查员） | 对报告内关键声明交叉验证，给出 0.0–1.0 置信度评分 |
| ✔️ **ConclusionValidator**（结论验证员） | 验证结论的逻辑严密性、全面性与实用价值（5 项评分） |

---

### 项目结构

```
cat-research/
├── main.py                  # 命令行入口
├── run_api.py               # Web UI + API 服务入口
├── orchestrator.py          # 研究编排器（主流程控制）
├── config.py                # 全局配置（模型 / 搜索 / 质量参数）
├── requirements.txt         # Python 依赖
├── settings.example.json    # 配置模板
│
├── agents/                  # 所有智能体实现
│   ├── base_agent.py        # 基础智能体（对话 / 上下文压缩）
│   ├── clarifier.py         # 澄清者
│   ├── planner.py           # 规划师
│   ├── researcher.py        # 研究员
│   ├── analyst.py           # 分析师
│   ├── writer.py            # 写作者
│   ├── critic.py            # 评审员
│   ├── source_verifier.py   # 来源验证员
│   ├── fact_checker.py      # 事实核查员
│   └── conclusion_validator.py  # 结论验证员
│
├── api/                     # FastAPI Web 服务
│   ├── app.py               # FastAPI 应用 + 所有路由定义
│   ├── models/              # Pydantic 数据模型
│   └── services/            # 业务逻辑层
│
├── tools/                   # 工具模块
│   ├── web_search.py        # 智谱 Web Search API + 网页抓取（降级 DuckDuckGo）
│   ├── fact_tools.py        # 事实核查工具
│   ├── file_tools.py        # 文件读写工具
│   ├── domain_checker.py    # 域名权威性检测
│   └── verification_registry.py  # 验证结果缓存注册中心
│
├── static/                  # Web UI 前端静态文件
└── workspace/               # 研究输出目录（每次研究独立文件夹）
```

---

### 快速开始

#### 1. 克隆项目

```bash
git clone https://github.com/mmlong818/cat-research.git
cd cat-research
```

#### 2. 安装依赖

```bash
pip install -r requirements.txt
```

#### 3. 配置 API Key

```bash
cp settings.example.json settings.json
# 编辑 settings.json，填入你的 API Key
```

`settings.json` 内容示例：

```json
{
  "api_key": "your_api_key_here",
  "base_url": "https://open.bigmodel.cn/api/paas/v4/",
  "core_model": "glm-5",
  "support_model": "glm-4-flash"
}
```

也可通过环境变量配置（优先级高于 settings.json）：

```bash
# 智谱 GLM
export ZHIPU_API_KEY=your_api_key_here

# 或 OpenAI
export OPENAI_API_KEY=your_api_key_here
export OPENAI_BASE_URL=https://api.openai.com/v1
```

#### 4. 启动研究

**方式一：命令行直接提问**

```bash
python main.py "2025年大模型行业有哪些重要进展？"
```

**方式二：命令行交互模式**

```bash
python main.py
# 按提示输入研究问题
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
├── 01_question.txt              # 原始研究问题
├── 02_clarification.txt         # 意图澄清结果
├── 03_plan.json                 # 研究规划（搜索查询列表）
├── 04_research/                 # 原始搜索数据与网页内容
├── 05_analysis.md               # 综合分析报告
├── 06_drafts/                   # 各轮草稿历史
├── 07_reviews/                  # 评审记录（含 7 维度分数）
├── 08_verification/             # 所有验证结果
│   ├── source_verification.json    # 来源权威性评估
│   ├── fact_check.json             # 事实核查结果
│   ├── conclusion_validation.json  # 结论验证结果
│   └── confidence_report.json      # 📊 综合置信度报告
└── 09_final.md                  # 📄 最终研究报告
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
| `POST` | `/api/research/{id}/message` | 向正在运行的任务注入消息 |
| `POST` | `/api/research/{id}/pause` | 暂停任务 |
| `POST` | `/api/research/{id}/resume` | 恢复任务 |
| `POST` | `/api/research/{id}/stop` | 停止任务 |
| `DELETE` | `/api/research/{id}` | 停止并删除任务 |

**会话管理**

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/sessions` | 获取历史研究会话列表 |
| `GET` | `/api/sessions/{id}/report` | 获取会话最终报告 |
| `GET` | `/api/sessions/{id}/plan` | 获取会话研究计划 |
| `GET` | `/api/sessions/{id}/phases` | 获取会话各阶段内容 |
| `DELETE` | `/api/sessions/{id}` | 删除会话及工作区 |

**澄清对话**

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/clarify` | 开始意图澄清会话 |
| `POST` | `/api/clarify/{id}/message` | 继续澄清对话 |
| `POST` | `/api/clarify/{id}/confirm` | 确认问题并启动研究 |

**系统**

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/config` | 获取当前系统配置 |
| `POST` | `/api/config` | 运行时更新系统配置 |
| `GET` | `/api/settings` | 获取当前 API 设置 |
| `POST` | `/api/settings` | 更新并持久化 API Key / 模型配置 |
| `GET` | `/` | Web UI 界面 |
| `GET` | `/docs` | Swagger 交互式 API 文档 |

---

### 配置说明

所有配置项均可通过环境变量覆盖 `settings.json`：

```env
# ── API 接入 ──────────────────────────────────────────────────────
ZHIPU_API_KEY=your_key          # 智谱 GLM API Key
OPENAI_API_KEY=your_key         # 或 OpenAI API Key
OPENAI_BASE_URL=https://...     # 自定义 Base URL

# ── 模型选择 ─────────────────────────────────────────────────────
CORE_MODEL=glm-5                # 核心模型（规划/研究/分析/写作）
SUPPORT_MODEL=glm-4-flash       # 辅助模型（评审/验证/核查）

# ── 研究质量参数 ──────────────────────────────────────────────────
MAX_IMPROVEMENT_CYCLES=5        # 最多改进轮数（默认 5）
MIN_IMPROVEMENT_CYCLES=2        # 最少强制改进轮数（默认 2）
QUALITY_THRESHOLD=8.0           # 质量提前停止阈值（满分 10）
MAX_SEARCH_RESULTS=8            # 每次搜索最多返回结果数
MAX_FETCH_CHARS=6000            # 每个网页最多提取字符数

# ── 上下文管理 ────────────────────────────────────────────────────
COMPRESS_THRESHOLD_CHARS=100000 # 超过此字符数自动压缩上下文
COMPRESS_KEEP_RECENT=6          # 压缩时保留最近 N 条消息

# ── 子进程隔离（实验性）────────────────────────────────────────────
USE_SUBPROCESS=false            # 是否启用独立子进程隔离
SUBPROCESS_AGENTS=researcher,analyst,writer

# ── API 服务 ──────────────────────────────────────────────────────
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:8000
```

---

### 支持的 API 提供商

Cat-Research 兼容所有 OpenAI 接口标准的 API 服务：

| 提供商 | Base URL | 推荐模型 |
|--------|----------|----------|
| 智谱 AI | `https://open.bigmodel.cn/api/paas/v4/` | glm-5, glm-5-turbo, glm-4-plus, glm-4-flash |
| OpenAI | `https://api.openai.com/v1` | gpt-4.1, gpt-4.1-mini, o3, o4-mini |
| DeepSeek | `https://api.deepseek.com/v1` | deepseek-chat, deepseek-reasoner |
| Moonshot (Kimi) | `https://api.moonshot.cn/v1` | kimi-k2, kimi-k2-thinking, kimi-k1.5 |
| 阿里云百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | qwen3-235b-a22b, qwen3-32b, qwen-plus, qwen-turbo |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | gemini-2.5-pro-preview, gemini-2.5-flash |
| SiliconFlow | `https://api.siliconflow.cn/v1` | Qwen/Qwen3-32B, deepseek-ai/DeepSeek-V3 |
| 本地 Ollama | `http://localhost:11434/v1` | llama4, qwen3:32b, gemma3:27b, deepseek-r1 等 |

---

### 系统要求

- Python 3.9+
- 有效的 API Key（支持上表中任意服务）
- 正常的网络连接（用于实时网络搜索）
- 内存：512 MB+（推荐 2 GB 以上）

---

## 📖 English Documentation

### Overview

**Cat-Research** is a multi-agent collaborative deep research system. It automatically decomposes a research question into specialized stages, each handled by a dedicated AI agent, ultimately producing a high-quality research report with source credibility verification, cross-referenced fact-checking, and validated conclusions.

Unlike simple AI Q&A tools, Cat-Research will:

- 🔍 **Actively search** via Zhipu Search API with automatic recency filtering (prioritizes last 3 months)
- 🔗 **Verify sources** using 4-tier classification + 0–100 domain scoring + 4-level confidence rating
- ✅ **Fact-check** key claims through cross-reference validation (confidence: 0.0–1.0)
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
   ├─→ [Stage 3]   🔍  Researcher         Web search + page scraping
   ├─→ [Stage 3.5] 🔎  SourceVerifier     Source authority scoring (Tier 1–4, 0–100)
   ├─→ [Stage 4]   🧐  Analyst            Synthesis & causal/trend analysis
   ├─→ [Stage 5]   ✍️  Writer             First draft (structured report)
   ├─→ [Stage 5.5] 🔬  FactChecker        Fact verification (0.0–1.0 confidence)
   └─→ [Stage 6]   🔄  Quality Loop (≥ 2 rounds, max 5)
           ├─→ 🎯 Critic              Multi-dimension review (7 scores / 10)
           ├─→ 🔍 Researcher          Supplemental research (rounds 1–3)
           ├─→ ✔️ ConclusionValidator  Conclusion validation (5 scores)
           └─→ ✍️ Writer              Iterative improvement (ratchet to best version)
   │
   ▼
Final Report (09_final.md) + Confidence Report (08_verification/confidence_report.json)
```

---

### 9 Specialized Agents

| Agent | Role |
|-------|------|
| 🗣️ **Clarifier** | Identifies user intent, decides if clarification is needed, adjusts scope |
| 📋 **Planner** | Breaks down the question into 10–16 multilingual queries, layered by recency |
| 🔍 **Researcher** | Executes web searches (Zhipu Search API, falls back to DuckDuckGo), scrapes pages, aggregates raw multi-source data |
| 🔎 **SourceVerifier** | Assigns Tier 1–4 labels and 0–100 domain scores to each source; flags unreliable ones |
| 🧐 **Analyst** | Synthesizes research into key findings; causal, trend, and comparative analysis |
| ✍️ **Writer** | Writes structured research reports; iterates based on review feedback |
| 🎯 **Critic** | Reviews on 7 dimensions: completeness, accuracy, depth, clarity, usefulness, sources, simplicity |
| 🔬 **FactChecker** | Cross-validates key claims and assigns confidence scores (0.0–1.0) |
| ✔️ **ConclusionValidator** | Validates logical rigor, completeness, and practical value of conclusions (5 scores) |

---

### Quick Start

#### 1. Clone

```bash
git clone https://github.com/mmlong818/cat-research.git
cd cat-research
```

#### 2. Install dependencies

```bash
pip install -r requirements.txt
```

#### 3. Configure API Key

```bash
cp settings.example.json settings.json
# Edit settings.json and fill in your API key
```

`settings.json` example:

```json
{
  "api_key": "your_api_key_here",
  "base_url": "https://open.bigmodel.cn/api/paas/v4/",
  "core_model": "glm-5",
  "support_model": "glm-4-flash"
}
```

#### 4. Run

**CLI — direct question:**
```bash
python main.py "What are the major AI breakthroughs in 2025?"
```

**CLI — interactive mode:**
```bash
python main.py
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
├── 01_question.txt              # Original question
├── 02_clarification.txt         # Clarification result
├── 03_plan.json                 # Research plan (query list)
├── 04_research/                 # Raw search data & scraped pages
├── 05_analysis.md               # Synthesized analysis
├── 06_drafts/                   # Draft history
├── 07_reviews/                  # Review records (with 7-dim scores)
├── 08_verification/             # All verification results
│   ├── source_verification.json    # Source authority scores
│   ├── fact_check.json             # Fact-check results
│   ├── conclusion_validation.json  # Conclusion validation
│   └── confidence_report.json      # 📊 Confidence report
└── 09_final.md                  # 📄 Final research report
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
| `POST` | `/api/research/{id}/message` | Inject a message into a running task |
| `POST` | `/api/research/{id}/pause` | Pause a task |
| `POST` | `/api/research/{id}/resume` | Resume a paused task |
| `POST` | `/api/research/{id}/stop` | Stop a task |
| `DELETE` | `/api/research/{id}` | Stop and delete a task |

**Sessions**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/sessions` | List all research sessions |
| `GET` | `/api/sessions/{id}/report` | Get session final report |
| `GET` | `/api/sessions/{id}/plan` | Get session research plan |
| `GET` | `/api/sessions/{id}/phases` | Get all phase outputs for a session |
| `DELETE` | `/api/sessions/{id}` | Delete session and workspace |

**Clarification**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/clarify` | Start a clarification session |
| `POST` | `/api/clarify/{id}/message` | Continue clarification dialog |
| `POST` | `/api/clarify/{id}/confirm` | Confirm and start research |

**System**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/config` | Get system configuration |
| `POST` | `/api/config` | Update configuration at runtime |
| `GET` | `/api/settings` | Get current API settings |
| `POST` | `/api/settings` | Update and persist API key / model settings |
| `GET` | `/` | Web UI |
| `GET` | `/docs` | Swagger interactive API docs |

---

### Configuration

All settings can be overridden via environment variables:

```env
# API access
ZHIPU_API_KEY=your_key
OPENAI_API_KEY=your_key
OPENAI_BASE_URL=https://...

# Model selection
CORE_MODEL=glm-5                # Core model (planning / research / writing)
SUPPORT_MODEL=glm-4-flash       # Support model (review / verification)

# Quality parameters
MAX_IMPROVEMENT_CYCLES=5        # Maximum improvement rounds
MIN_IMPROVEMENT_CYCLES=2        # Minimum forced improvement rounds
QUALITY_THRESHOLD=8.0           # Early-stop quality threshold (out of 10)

# API server
API_HOST=0.0.0.0
API_PORT=8000
```

---

### Supported API Providers

Cat-Research works with any OpenAI-compatible API:

| Provider | Base URL | Recommended Models |
|----------|----------|--------------------|
| Zhipu AI | `https://open.bigmodel.cn/api/paas/v4/` | glm-5, glm-5-turbo, glm-4-plus, glm-4-flash |
| OpenAI | `https://api.openai.com/v1` | gpt-4.1, gpt-4.1-mini, o3, o4-mini |
| DeepSeek | `https://api.deepseek.com/v1` | deepseek-chat, deepseek-reasoner |
| Moonshot (Kimi) | `https://api.moonshot.cn/v1` | kimi-k2, kimi-k2-thinking, kimi-k1.5 |
| Alibaba (Qwen) | `https://dashscope.aliyuncs.com/compatible-mode/v1` | qwen3-235b-a22b, qwen3-32b, qwen-plus, qwen-turbo |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | gemini-2.5-pro-preview, gemini-2.5-flash |
| SiliconFlow | `https://api.siliconflow.cn/v1` | Qwen/Qwen3-32B, deepseek-ai/DeepSeek-V3 |
| Local (Ollama) | `http://localhost:11434/v1` | llama4, qwen3:32b, gemma3:27b, deepseek-r1, etc. |

---

### Requirements

- Python 3.9+
- A valid API Key from any supported provider
- Internet access (for real-time web search)
- RAM: 512 MB minimum (2 GB recommended)

---

### License

MIT License · Free to use, modify, and distribute.

---

<div align="center">

Made with ❤️ · [Issues](https://github.com/mmlong818/cat-research/issues) · [Discussions](https://github.com/mmlong818/cat-research/discussions)

</div>
