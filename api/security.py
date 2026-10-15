"""
本地 API 安全基线

威胁模型：服务只给本机浏览器用。需要防的是
  1. 局域网其他机器 → 默认只监听 127.0.0.1（API_HOST 可显式放开）
  2. 浏览器里任意网页向本机 API 发请求（CSRF）→ /api/* 须带启动时生成的令牌；
     令牌只写在同源页面里，其他网站受同源策略限制读不到
  3. DNS rebinding（恶意域名解析到 127.0.0.1 后读取页面）→ 所有路径校验 Host 头
开发模式（vite 代理、页面不经后端）可设 CAT_API_AUTH=0 关闭令牌校验（Host 校验保留）。
"""
import hmac
import os
import secrets

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

TOKEN_HEADER = "X-Cat-Token"
TOKEN_META = "cat-api-token"
TOKEN = os.getenv("CAT_API_TOKEN") or secrets.token_urlsafe(32)
EXEMPT_PATHS = {"/api/health"}
DEFAULT_HOSTS = {"127.0.0.1", "localhost", "::1"}


def bind_host() -> str:
    return os.getenv("API_HOST", "127.0.0.1")


def _allowed_hosts() -> set:
    extra = {h.strip().lower() for h in os.getenv("CAT_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return DEFAULT_HOSTS | extra


def _hostname(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1]:8000
        return host[1:host.find("]")]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _auth_enabled() -> bool:
    return os.getenv("CAT_API_AUTH", "1") != "0"


def _supplied_token(request: Request) -> str:
    token = request.headers.get(TOKEN_HEADER, "")
    if not token and request.method == "GET":  # EventSource 与下载链接无法加请求头
        token = request.query_params.get("token", "")
    return token


async def guard(request: Request, call_next):
    if _hostname(request.headers.get("host", "")) not in _allowed_hosts():
        return JSONResponse({"detail": "forbidden host"}, status_code=403)
    path = request.url.path
    if (_auth_enabled() and path.startswith("/api/") and path not in EXEMPT_PATHS
            and not hmac.compare_digest(_supplied_token(request), TOKEN)):
        return JSONResponse({"detail": "missing or invalid API token"}, status_code=401)
    return await call_next(request)


def index_response(index_file: str) -> HTMLResponse:
    """返回注入了令牌 <meta> 的前端入口页。"""
    with open(index_file, encoding="utf-8") as f:
        html = f.read()
    meta = f'<meta name="{TOKEN_META}" content="{TOKEN}">'
    html = html.replace("</head>", f"{meta}</head>", 1) if "</head>" in html else meta + html
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
