中文 · [English](configuration.en.md) · [返回 README](../README.md)

# 配置

## 环境变量

示例见 `.env.example`。模型项的优先级高于 `settings.json`；API Key 也可以在界面的设置里录入。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CORE_MODEL` / `SUPPORT_MODEL` | `claude-opus-5-5` / `claude-sonnet-5-5` | 核心 / 辅助模型 |
| `CLAUDE_CLI_PATH` | 自动查找 | 原生 claude 可执行文件路径 |
| `OPENAI_API_KEY` / `ZHIPU_API_KEY` | — | 使用对应提供方时需要 |
| `COMPAT_BASE_URL` / `COMPAT_API_KEY` | — | OpenAI 兼容端点 |
| `SEARCH_BACKEND` | `zhipu` | 智谱与兼容端点用的搜索服务：`zhipu` / `bocha` / `tavily` |
| `BOCHA_API_KEY` / `TAVILY_API_KEY` | — | 选用博查 / Tavily 时需要 |
| `API_HOST` | `127.0.0.1` | 局域网访问改为 `0.0.0.0` |
| `API_PORT` | `8000` | 服务端口 |
| `CAT_ALLOWED_HOSTS` | — | 额外允许的主机名（逗号分隔），局域网访问时填写 |
| `CAT_API_AUTH` | `1` | `/api/*` 需要本地令牌；前端开发模式可设 `0` |
| `CAT_API_TOKEN` | 启动时随机生成 | 固定本地令牌 |
| `CORS_ORIGINS` | `localhost:3000`、`localhost:8000`、`127.0.0.1:8000` | 允许的跨域来源 |

不用环境变量时，也可以复制 `settings.example.json` 为 `settings.json`，填 `core_model` / `support_model`。

## 局域网访问

默认只监听本机。要让局域网里的其他设备访问，设 `API_HOST=0.0.0.0`，并把本机的主机名或 IP 填进 `CAT_ALLOWED_HOSTS`。

## 安全

- 服务启动时生成本地令牌并注入 Web UI 页面，前端自动携带；其他网站受同源策略限制读不到它。
- 所有请求校验 Host 头（防 DNS rebinding）。
- 界面里填的 API Key 存入系统凭据库（Windows 凭据管理器），不写明文文件，页面只显示末 4 位。

## 研究参数

研究参数是 `config.py` 里的常量（不读环境变量）：深度档在 `DEPTH_PRESETS`，另有

```python
QUALITY_THRESHOLD = 8.0       # 评审分达标线（满分 10）
CONCLUSION_THRESHOLD = 7.5    # 结论验证平均分达标线
NO_GAIN_PATIENCE = 1          # 连续多少轮评审分未超过最优分即停止
```
