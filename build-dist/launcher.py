"""
猫叔的深思熟虑 - 打包启动器
自动启动 Web 服务器并打开浏览器
"""
import sys
import os
import io
import threading
import time
import webbrowser

# ── UTF-8 控制台输出 ──────────────────────────────────────────────────────────
try:
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
except Exception:
    pass

# ── PyInstaller 路径修复 ───────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    # 运行在 PyInstaller bundle 中
    BUNDLE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    if BUNDLE_DIR not in sys.path:
        sys.path.insert(0, BUNDLE_DIR)

# ── 等待服务器就绪后打开浏览器 ─────────────────────────────────────────────────
def _wait_and_open(url: str, timeout: int = 30):
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            webbrowser.open(url)
            return
        except Exception:
            time.sleep(0.4)
    # 超时仍尝试打开
    webbrowser.open(url)


if __name__ == "__main__":
    PORT = int(os.environ.get("API_PORT", "8000"))
    HOST = os.environ.get("API_HOST", "0.0.0.0")
    URL  = f"http://localhost:{PORT}"

    print(f"""
╔══════════════════════════════════════════╗
║     猫叔的深思熟虑 v2.0 启动中           ║
╠══════════════════════════════════════════╣
║  Web UI : {URL:<30} ║
║  API 文档: {URL + '/docs':<30} ║
╚══════════════════════════════════════════╝
    """)

    # 后台线程等待服务就绪后自动打开浏览器
    threading.Thread(target=_wait_and_open, args=(URL,), daemon=True).start()

    import uvicorn
    from api.app import app  # 直接导入避免 uvicorn 字符串解析问题

    uvicorn.run(app, host=HOST, port=PORT, reload=False, log_level="info", access_log=True)
