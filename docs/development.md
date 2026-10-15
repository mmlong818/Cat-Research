中文 · [English](development.en.md) · [返回 README](../README.md)

# 开发

```bash
pip install -r requirements-dev.txt

# 前端开发模式：vite 把 /api 代理到 8002
API_PORT=8002 CAT_API_AUTH=0 python run_api.py
cd frontend && npm run dev

# 检查与测试（与 CI 一致）
ruff check .
mypy
python -m unittest discover -s tests -t .
```

CI 在 Python 3.11 / 3.14 上跑 ruff、mypy 与单元测试，在 Node 22 上构建前端。

## 回归评测

改动研究流程（提示词、核查规则、循环策略、模型）后，可以用 `tools/eval` 跑固定问题并与基线报告盲评，见 [tools/eval/README.md](../tools/eval/README.md)。

## 项目结构

```
Cat-Research/
├── main.py / run_api.py      # 命令行入口 / Web 服务入口
├── orchestrator.py           # 研究编排器
├── config.py                 # 模型与研究参数（DEPTH_PRESETS 等）
├── orchestration/            # 编排器分阶段实现：base（检查点、进度事件）、phases（阶段 1–7）、improve（改进循环）、finish（终稿与报告）
├── agents/                   # 10 个智能体
├── research/                 # 纯逻辑，不调用 LLM：台账与引用检查、原文片段比对、循环策略、中途要求、置信度、检查点
├── llm/                      # 统一调用层：模型能力表、配置档、重试、schema 校验、用量
│   ├── providers/            # claude / anthropic / openai / zhipu / compat（后两者共用 chat_completions）
│   └── search/               # 智谱与兼容端点用的搜索服务：zhipu / bocha / tavily
├── api/                      # FastAPI：路由、任务库、SSE 事件、本地令牌与 Host 校验
├── tools/                    # 声明核实、域名评分、查询缓存；eval/ 回归评测
├── frontend/                 # React Web UI 源码（构建到 static/）
├── docs/                     # 文档与截图
├── build-dist/               # Windows 打包脚本（PyInstaller）
└── tests/
```
