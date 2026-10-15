"""
启动多智能体研究系统 Web API 服务器
访问 http://localhost:8000 使用 Web UI
访问 http://localhost:8000/docs 查看 API 文档
"""
# Windows GBK 控制台 emoji 兼容
import io
import os
import sys

try:
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
except Exception as e:
    print(f"[run_api] 重设 stdout/stderr 编码失败，沿用默认编码: {e!r}", file=sys.stderr, flush=True)

# 添加项目根目录到路径
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

from dotenv import load_dotenv

load_dotenv()

# 检查依赖
try:
    import fastapi  # noqa: F401  仅用于检测依赖是否已安装
    import uvicorn
except ImportError:
    print("❌ 缺少依赖，请运行：")
    print("   pip install fastapi uvicorn[standard] sse-starlette aiofiles")
    sys.exit(1)

if __name__ == "__main__":
    import uvicorn

    from api.security import bind_host
    host = bind_host()  # 默认只监听本机；局域网访问需显式设置 API_HOST 与 CAT_ALLOWED_HOSTS
    port = int(os.getenv("API_PORT", "8000"))

    print(f"""
╔══════════════════════════════════════════╗
║     多智能体研究系统 v2.0 启动中          ║
╠══════════════════════════════════════════╣
║  Web UI:  http://localhost:{port}          ║
║  API 文档: http://localhost:{port}/docs    ║
║  健康检查: http://localhost:{port}/api/health ║
╚══════════════════════════════════════════╝
    """)

    uvicorn.run(
        "api.app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
        access_log=True
    )
