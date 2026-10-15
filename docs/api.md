中文 · [English](api.en.md) · [返回 README](../README.md)

# API

启动后在 `http://localhost:8000/docs` 有完整的 Swagger 文档。除 `/api/health` 外，`/api/*` 都需要本地令牌，见 [配置](configuration.md#安全)。

## 研究任务

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/research` | 启动研究（超过 2 个并发任务返回 429） |
| `GET` | `/api/research/{id}/stream` | SSE 实时进度 |
| `GET` | `/api/research/{id}/status` | 任务状态 |
| `GET` | `/api/research/{id}/result` | 任务结果（未完成返回 425） |
| `GET` | `/api/research/{id}/audit` | 审计日志：用户输入与操作、检查点、停止原因、终稿选择 |
| `POST` | `/api/research/{id}/message` | 中途补充要求 |
| `POST` | `/api/research/{id}/loop-decision` | 回答改进循环的「是否再改一轮」 |
| `POST` | `/api/research/{id}/pause` · `/resume` · `/stop` | 暂停 / 恢复 / 停止（停止发 `stopped` 事件，与失败的 `error` 分开） |
| `POST` | `/api/research/stop-all` | 停止全部任务 |
| `DELETE` | `/api/research/{id}` | 停止并删除任务（审计记录保留） |

## 会话

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/sessions` | 历史会话列表（分页） |
| `GET` | `/api/sessions/{id}/report` | 终稿 |
| `GET` | `/api/sessions/{id}/drafts` | 各版草稿列表 |
| `GET` | `/api/sessions/{id}/drafts/{draft_id}/download` | 下载草稿（`draft_id` 为版本号或 `final`） |
| `GET` | `/api/sessions/{id}/ledger` | 声明台账与矛盾裁决 |
| `GET` | `/api/sessions/{id}/reviews` | 每轮评审：7 项分数、优点、关键问题、改进点 |
| `GET` | `/api/sessions/{id}/plan` · `/phases` · `/phase-log` | 检索计划 / 各阶段内容 / 阶段状态与起止时间 |
| `GET` | `/api/sessions/{id}/checkpoints` | 已完成阶段的检查点与默认续跑起点 |
| `POST` | `/api/sessions/{id}/replay` | 从指定阶段重放（`{"from_phase": "improve"}`，省略则从断点续跑） |
| `GET` | `/api/sessions/{id}/audit` | 会话审计日志（含所有重放任务） |
| `DELETE` | `/api/sessions/{id}` | 删除会话及工作区 |

阶段依次为 clarify → plan → research → sources → ledger → analyze → draft → improve → finish。重放时该阶段之后的草稿、评审与台账一并回滚；同一会话同时只能有一个任务。

## 澄清

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/clarify` | 开始澄清对话 |
| `POST` | `/api/clarify/{id}/message` | 继续对话 |
| `POST` | `/api/clarify/{id}/confirm` | 确认委托并启动研究（可带改过的 `question` 与研究目标 `goal`） |

## 系统与设置

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查（无需令牌） |
| `GET` · `POST` | `/api/config` | 查看 / 运行时更新系统配置 |
| `GET` · `POST` | `/api/settings` | 默认配置档、各提供方与搜索服务的 Key 状态（仅末 4 位）与可选模型 / 更新设置 |
| `POST` | `/api/settings/compat/test` | 测试 OpenAI 兼容端点：能否连通、模型是否支持工具调用 |
| `DELETE` | `/api/settings/keys/{name}` | 清除某个 API Key（`claude` / `openai` / `zhipu` / `compat` / `bocha` / `tavily`） |
| `GET` | `/api/models` | 能力表里的模型，按提供方分组 |
