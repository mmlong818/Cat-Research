# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for 猫叔的深思熟虑
Usage: pyinstaller cat_research.spec
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# ── 源码目录（相对于本 spec 文件所在目录的上级）─────────────────────────────────
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))  # noqa: F821
SRC_DIR  = os.path.normpath(os.path.join(SPEC_DIR, '..', 'cat-research'))

# ── 收集各依赖包的全部文件和隐式导入 ──────────────────────────────────────────
uvicorn_d,    uvicorn_b,    uvicorn_h    = collect_all('uvicorn')
fastapi_d,    fastapi_b,    fastapi_h    = collect_all('fastapi')
starlette_d,  starlette_b,  starlette_h  = collect_all('starlette')
pydantic_d,   pydantic_b,   pydantic_h   = collect_all('pydantic')
pydantic_c_d, pydantic_c_b, pydantic_c_h = collect_all('pydantic_core')
anyio_d,      anyio_b,      anyio_h      = collect_all('anyio')
httpx_d,      httpx_b,      httpx_h      = collect_all('httpx')

# ── 静态资源 ──────────────────────────────────────────────────────────────────
app_datas = [
    # Web UI 静态文件 → bundle 内 static/
    (os.path.join(SRC_DIR, 'static'), 'static'),
    # 配置示例
    (os.path.join(SRC_DIR, 'settings.example.json'), '.'),
]

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [os.path.join(SPEC_DIR, 'launcher.py')],
    pathex=[SRC_DIR],        # 告知 PyInstaller 在此目录寻找项目模块
    binaries=(
        uvicorn_b + fastapi_b + starlette_b +
        pydantic_b + pydantic_c_b + anyio_b + httpx_b
    ),
    datas=(
        app_datas +
        uvicorn_d + fastapi_d + starlette_d +
        pydantic_d + pydantic_c_d + anyio_d + httpx_d
    ),
    hiddenimports=[
        # uvicorn 动态加载的模块
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.protocols.websockets.wsproto_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        # fastapi / starlette
        'fastapi.routing',
        'fastapi.middleware',
        'fastapi.middleware.cors',
        'fastapi.staticfiles',
        'fastapi.responses',
        'starlette.routing',
        'starlette.middleware',
        'starlette.middleware.cors',
        'starlette.staticfiles',
        'starlette.responses',
        'starlette.background',
        # anyio backends
        'anyio._backends._asyncio',
        'anyio._backends._trio',
        # pydantic
        'pydantic.deprecated.class_validators',
        'pydantic.deprecated.config',
        'pydantic.deprecated.tools',
        # 其他依赖
        'h11',
        'h11._connection',
        'h11._events',
        'sniffio',
        'aiofiles',
        'aiofiles.os',
        'aiofiles.threadpool',
        'multipart',
        'requests',
        'dotenv',
        'anthropic',
        'claude_agent_sdk',
        'keyring',
        'keyring.backends.Windows',
        # 项目模块
        'config',
        'orchestrator',
        'llm',
        'llm.client',
        'research',
        'research.loop_policy',
        'research.confidence',
        'research.ledger',
        'research.checkpoints',
        'agents',
        'agents.llm_agent',
        'agents.planner',
        'agents.researcher',
        'agents.analyst',
        'agents.writer',
        'agents.critic',
        'agents.source_verifier',
        'agents.fact_checker',
        'agents.reconciler',
        'agents.conclusion_validator',
        'agents.clarifier',
        'tools',
        'tools.file_tools',
        'tools.fact_tools',
        'tools.domain_checker',
        'tools.verification_registry',
        'api',
        'api.app',
        'api.security',
        'api.db.task_store',
    ] + uvicorn_h + fastapi_h + starlette_h + pydantic_h + pydantic_c_h + anyio_h + httpx_h,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'pandas', 'scipy', 'PIL',
        'tkinter', 'PyQt5', 'PyQt6', 'wx',
        'IPython', 'notebook', 'jupyter',
        'pytest', 'unittest.mock',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='cat-research',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,        # 保留控制台以显示服务器日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='cat-research',
)
