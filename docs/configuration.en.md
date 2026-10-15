[中文](configuration.md) · English · [Back to README](../README.en.md)

# Configuration

## Environment variables

See `.env.example`. Model settings take precedence over `settings.json`; API keys can also be entered in Settings in the UI.

| Variable | Default | Meaning |
|----------|---------|---------|
| `CORE_MODEL` / `SUPPORT_MODEL` | `claude-opus-5-5` / `claude-sonnet-5-5` | Core / support model |
| `CLAUDE_CLI_PATH` | found automatically | Path to the native claude executable |
| `OPENAI_API_KEY` / `ZHIPU_API_KEY` | — | Needed for that provider |
| `COMPAT_BASE_URL` / `COMPAT_API_KEY` | — | OpenAI-compatible endpoint |
| `SEARCH_BACKEND` | `zhipu` | Search service for Zhipu and the compatible endpoint: `zhipu` / `bocha` / `tavily` |
| `BOCHA_API_KEY` / `TAVILY_API_KEY` | — | Needed when Bocha / Tavily is selected |
| `API_HOST` | `127.0.0.1` | Set to `0.0.0.0` for LAN access |
| `API_PORT` | `8000` | Server port |
| `CAT_ALLOWED_HOSTS` | — | Extra allowed host names (comma-separated) for LAN access |
| `CAT_API_AUTH` | `1` | `/api/*` requires the local token; set `0` for frontend dev mode |
| `CAT_API_TOKEN` | random at startup | Fixed local token |
| `CORS_ORIGINS` | `localhost:3000`, `localhost:8000`, `127.0.0.1:8000` | Allowed cross-origin sources |

Instead of environment variables you can copy `settings.example.json` to `settings.json` and fill in `core_model` / `support_model`.

## LAN access

The server listens on localhost only by default. To reach it from other devices on your network, set `API_HOST=0.0.0.0` and put this machine's host name or IP in `CAT_ALLOWED_HOSTS`.

## Security

- At startup the server creates a local token and injects it into the web UI page; the frontend sends it automatically, and other sites cannot read it because of the same-origin policy.
- Every request has its Host header checked (against DNS rebinding).
- API keys entered in the UI go to the system credential store (Windows Credential Manager), never to a plain-text file; the page shows only the last 4 characters.

## Research parameters

Research parameters are constants in `config.py` (not read from the environment): depth presets live in `DEPTH_PRESETS`, plus

```python
QUALITY_THRESHOLD = 8.0       # Review score bar (out of 10)
CONCLUSION_THRESHOLD = 7.5    # Conclusion validation average bar
NO_GAIN_PATIENCE = 1          # Stop after this many rounds without beating the best review score
```
