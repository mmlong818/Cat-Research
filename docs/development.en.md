[中文](development.md) · English · [Back to README](../README.en.md)

# Development

```bash
pip install -r requirements-dev.txt

# Frontend dev mode: vite proxies /api to 8002
API_PORT=8002 CAT_API_AUTH=0 python run_api.py
cd frontend && npm run dev

# Lint and test (same as CI)
ruff check .
mypy
python -m unittest discover -s tests -t .
```

CI runs ruff, mypy and the unit tests on Python 3.11 / 3.14, and builds the frontend on Node 22.

## Regression evaluation

After changing the research flow (prompts, checking rules, loop policy, models), `tools/eval` runs fixed questions and blind-compares the result with baseline reports; see [tools/eval/README.md](../tools/eval/README.md).

## Project layout

```
Cat-Research/
├── main.py / run_api.py      # CLI entry / web server entry
├── orchestrator.py           # Research orchestrator
├── config.py                 # Models and research parameters (DEPTH_PRESETS etc.)
├── orchestration/            # Orchestrator by phase: base (checkpoints, progress events), phases (phases 1–7), improve (revision loop), finish (final report)
├── agents/                   # The 10 agents
├── research/                 # Pure logic, no LLM calls: ledger and citation checks, quote checks, loop policy, mid-run requirements, confidence, checkpoints
├── llm/                      # Unified call layer: model capability table, profiles, retries, schema validation, usage
│   ├── providers/            # claude / anthropic / openai / zhipu / compat (the last two share chat_completions)
│   └── search/               # Search services for Zhipu and the compatible endpoint: zhipu / bocha / tavily
├── api/                      # FastAPI: routes, task store, SSE events, local token and Host checks
├── tools/                    # Claim verification, domain scoring, query cache; eval/ regression evaluation
├── frontend/                 # React web UI source (builds to static/)
├── docs/                     # Documentation and screenshots
├── build-dist/               # Windows packaging scripts (PyInstaller)
└── tests/
```
