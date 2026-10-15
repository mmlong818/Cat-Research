[中文](api.md) · English · [Back to README](../README.en.md)

# API

Full Swagger docs are at `http://localhost:8000/docs` once the server is running. Apart from `/api/health`, every `/api/*` call needs the local token; see [Configuration](configuration.en.md#security).

## Research tasks

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/research` | Start research (429 when 2 tasks are already running) |
| `GET` | `/api/research/{id}/stream` | Live progress over SSE |
| `GET` | `/api/research/{id}/status` | Task status |
| `GET` | `/api/research/{id}/result` | Task result (425 until finished) |
| `GET` | `/api/research/{id}/audit` | Audit log: user input and actions, checkpoints, stop reason, final draft choice |
| `POST` | `/api/research/{id}/message` | Add a requirement mid-run |
| `POST` | `/api/research/{id}/loop-decision` | Answer the revision loop's "revise once more?" |
| `POST` | `/api/research/{id}/pause` · `/resume` · `/stop` | Pause / resume / stop (stop sends a `stopped` event, separate from a failure's `error`) |
| `POST` | `/api/research/stop-all` | Stop every task |
| `DELETE` | `/api/research/{id}` | Stop and delete a task (the audit log is kept) |

## Sessions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/sessions` | Past sessions (paginated) |
| `GET` | `/api/sessions/{id}/report` | Final report |
| `GET` | `/api/sessions/{id}/drafts` | List of drafts |
| `GET` | `/api/sessions/{id}/drafts/{draft_id}/download` | Download a draft (`draft_id` is a version number or `final`) |
| `GET` | `/api/sessions/{id}/ledger` | Claim ledger and rulings |
| `GET` | `/api/sessions/{id}/reviews` | Review per round: 7 scores, strengths, key issues, what to change |
| `GET` | `/api/sessions/{id}/plan` · `/phases` · `/phase-log` | Search plan / phase content / phase status and timing |
| `GET` | `/api/sessions/{id}/checkpoints` | Checkpoints of finished phases and the default resume point |
| `POST` | `/api/sessions/{id}/replay` | Replay from a phase (`{"from_phase": "improve"}`; omit to resume from the checkpoint) |
| `GET` | `/api/sessions/{id}/audit` | Session audit log (including all replays) |
| `DELETE` | `/api/sessions/{id}` | Delete the session and its workspace |

Phases in order: clarify → plan → research → sources → ledger → analyze → draft → improve → finish. A replay rolls back the drafts, reviews and ledger after that phase; a session runs one task at a time.

## Clarification

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/clarify` | Start a clarification conversation |
| `POST` | `/api/clarify/{id}/message` | Continue it |
| `POST` | `/api/clarify/{id}/confirm` | Confirm the request and start research (optionally with an edited `question` and a research `goal`) |

## System and settings

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check (no token needed) |
| `GET` · `POST` | `/api/config` | Read / update system config at runtime |
| `GET` · `POST` | `/api/settings` | Default profile, key status per provider and search service (last 4 characters only) and available models / update settings |
| `POST` | `/api/settings/compat/test` | Test the OpenAI-compatible endpoint: does it connect, does the model support tool calling |
| `DELETE` | `/api/settings/keys/{name}` | Clear an API key (`claude` / `openai` / `zhipu` / `compat` / `bocha` / `tavily`) |
| `GET` | `/api/models` | Models in the capability table, grouped by provider |
