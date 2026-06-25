"""
启动多智能体研究系统 Web API 服务器
访问 http://localhost:8000 使用 Web UI
访问 http://localhost:8000/docs 查看 API 文档
"""
import os
import sys

# Windows GBK 控制台 emoji 兼容
import io
try:
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
except Exception:
    pass

# 添加项目根目录到路径
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

from dotenv import load_dotenv
load_dotenv()

# 检查依赖
try:
    import fastapi
    import uvicorn
except ImportError:
    print("❌ 缺少依赖，请运行：")
    print("   pip install fastapi uvicorn[standard] sse-starlette aiofiles")
    sys.exit(1)

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
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
