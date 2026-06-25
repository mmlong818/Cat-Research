"""
FastAPI 应用 - 多智能体研究系统 REST API
支持 SSE 实时流式进度推送
"""
import os
import json
import asyncio
import threading
import uuid
from datetime import datetime
from typing import Optional, AsyncGenerator
from queue import Queue, Empty

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 项目根目录（静态资源用 bundle 内路径；workspace 用户数据目录）
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys as _sys
if getattr(_sys, "frozen", False):
    STATIC_DIR = os.path.join(getattr(_sys, "_MEIPASS", ROOT_DIR), "static")
else:
    STATIC_DIR = os.path.join(ROOT_DIR, "static")
from api.paths import project_root as _project_root
WORKSPACE_DIR = os.path.join(_project_root(), "workspace")
os.makedirs(WORKSPACE_DIR, exist_ok=True)

app = FastAPI(
    title="多智能体研究系统 API",
    description="基于 Claude 的多智能体研究系统，支持来源验证、事实核查和结论验证",
    version="2.0.0"
)

# CORS 配置
# 生产环境请将 CORS_ORIGINS 环境变量设置为实际前端域名，如：
# CORS_ORIGINS=https://yourdomain.com,https://app.yourdomain.com
_cors_origins_env = os.getenv("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()] or ["http://localhost:3000", "http://localhost:8000", "http://127.0.0.1:8000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Accept"],
)

# 挂载静态文件
# Vite 打包后资源在 /assets/、/vite.svg 等路径直接引用，需要在 SPA fallback 之前精确挂载
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    _assets_dir = os.path.join(STATIC_DIR, "assets")
    if os.path.exists(_assets_dir):
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

# 注册路由
from api.routes.config import router as config_router
app.include_router(config_router)


# ── 请求/响应模型 ────────────────────────────────────────────────────────────

class ResearchRequest(BaseModel):
    question: str
    clarification: Optional[str] = None  # 预填写的澄清信息
    research_strategy: Optional[str] = None  # 研究策略（搜索方向、来源类型等）


class ConfigRequest(BaseModel):
    model: Optional[str] = None          # 兼容旧字段（映射到 core_model）
    core_model: Optional[str] = None
    support_model: Optional[str] = None
    min_cycles: Optional[int] = None
    max_cycles: Optional[int] = None
    quality_threshold: Optional[float] = None


class SettingsRequest(BaseModel):
    core_model: Optional[str] = None
    support_model: Optional[str] = None


class ClarifyStartRequest(BaseModel):
    question: str

class ClarifyReplyRequest(BaseModel):
    message: str

class ClarifyConfirmRequest(BaseModel):
    summary: Optional[dict] = None   # 用户可编辑后的摘要
    extra_note: Optional[str] = None # 用户额外补充（可选）


# ── 会话管理 ─────────────────────────────────────────────────────────────────

# 最大并发研究任务数
MAX_CONCURRENT_TASKS = 2

# ── 澄清会话存储 {clarify_id: dict} ─────────────────────────────────────────
_clarify_sessions: dict[str, dict] = {}

# 存储活跃任务的事件队列 {task_id: Queue}
_task_queues: dict[str, Queue] = {}
# 存储任务状态 {task_id: dict}
_task_status: dict[str, dict] = {}
# 存储各任务的 orchestrator 引用（用于注入消息和暂停控制）
_task_orchestrators: dict[str, object] = {}
# 存储各任务的暂停事件 {task_id: threading.Event}
_task_pause_events: dict[str, threading.Event] = {}
# 存储各任务的停止事件 {task_id: threading.Event}
_task_stop_events: dict[str, threading.Event] = {}


def _running_task_count() -> int:
    """返回当前正在运行的任务数量"""
    return sum(1 for s in _task_status.values() if s.get("status") == "running")


def _get_task_status(task_id: str) -> dict:
    return _task_status.get(task_id, {"status": "not_found"})


def _put_event(task_id: str, event_type: str, data: dict):
    """向任务队列推送事件"""
    if task_id in _task_queues:
        _task_queues[task_id].put({
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        })


def _heartbeat_thread(task_id: str, stop_ev):
    """每 8 秒推送一次心跳，告知前端任务仍在运行"""
    import time as _time
    while not stop_ev.is_set():
        stop_ev.wait(timeout=8)
        if stop_ev.is_set():
            break
        st = _task_status.get(task_id, {})
        if st.get("status") not in ("running",):
            break
        _put_event(task_id, "heartbeat", {
            "current_status": st.get("current_status", ""),
            "current_cycle": st.get("current_cycle", 0),
            "elapsed": round(_time.time() - st.get("_start_ts", _time.time()))
        })


def _run_research_task(task_id: str, question: str, clarification: Optional[str],
                       research_strategy: Optional[str] = None,
                       intent_meta: Optional[dict] = None):
    """在后台线程中运行研究任务"""
    import sys, time as _time
    sys.path.insert(0, ROOT_DIR)
    # orchestrator.py 在模块加载时已全局替换 stdout/stderr 为 UTF-8，
    # 线程内不再重复替换，否则会产生 "I/O operation on closed file" 错误

    try:
        _task_status[task_id]["status"] = "running"
        _task_status[task_id]["_start_ts"] = _time.time()
        _put_event(task_id, "started", {"task_id": task_id, "question": question})

        # 启动心跳线程
        hb_stop = _task_stop_events.get(task_id) or threading.Event()
        hb_thread = threading.Thread(target=_heartbeat_thread, args=(task_id, hb_stop), daemon=True)
        hb_thread.start()

        # 如果有预填写的澄清信息，合并到问题中
        full_question = question
        if clarification:
            full_question = f"{question}\n\n补充说明：{clarification}"

        from orchestrator import ResearchOrchestrator

        def progress_callback(event_type: str, data: dict):
            try:
                _put_event(task_id, event_type, data)
                # 同步更新状态
                if event_type == "status":
                    _task_status[task_id]["current_status"] = data.get("status", "")
                elif event_type == "plan":
                    _task_status[task_id]["plan"] = data
                elif event_type == "cycle_start":
                    _task_status[task_id]["current_cycle"] = data.get("cycle", 0)
                elif event_type == "review":
                    scores = _task_status[task_id].get("scores", [])
                    scores.append(data.get("avg_score", 0))
                    _task_status[task_id]["scores"] = scores
                elif event_type == "confidence_report":
                    _task_status[task_id]["confidence_report"] = data
            except Exception:
                pass  # 回调失败不中断主流程

        pause_event = _task_pause_events.get(task_id)
        stop_event = _task_stop_events.get(task_id)
        orchestrator = ResearchOrchestrator(progress_callback=progress_callback)
        _task_orchestrators[task_id] = orchestrator

        # 注入澄清信息跳过交互式输入
        if clarification:
            import unittest.mock as mock
            with mock.patch('builtins.input', return_value=clarification):
                result = orchestrator.run(full_question, research_strategy=research_strategy,
                                         intent_meta=intent_meta,
                                         pause_event=pause_event, stop_event=stop_event)
        else:
            result = orchestrator.run(full_question, research_strategy=research_strategy,
                                      intent_meta=intent_meta,
                                      pause_event=pause_event, stop_event=stop_event)

        _task_status[task_id]["status"] = "completed"
        _task_status[task_id]["result"] = result
        _task_status[task_id]["workspace"] = str(orchestrator.workspace)
        _task_status[task_id]["session_id"] = orchestrator.session_id
        _put_event(task_id, "completed", {
            "result": result[:500] + "..." if len(result) > 500 else result,
            "workspace": str(orchestrator.workspace),
            "session_id": orchestrator.session_id
        })

    except Exception as e:
        error_msg = str(e)
        _task_status[task_id]["status"] = "failed"
        _task_status[task_id]["error"] = error_msg
        _put_event(task_id, "error", {"message": error_msg})

    finally:
        # 发送结束标记
        _put_event(task_id, "end", {})


# ── API 路由 ─────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    """提供 Web UI"""
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return JSONResponse({"message": "多智能体研究系统 API v2.0", "docs": "/docs"})


@app.post("/api/research")
async def start_research(request: ResearchRequest):
    """
    启动一个新的研究任务（最多同时运行 MAX_CONCURRENT_TASKS 个）
    返回 task_id，通过 /api/research/{task_id}/stream 获取实时进度
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="研究问题不能为空")

    running = _running_task_count()
    if running >= MAX_CONCURRENT_TASKS:
        raise HTTPException(
            status_code=429,
            detail=f"当前已有 {running} 个任务在运行，最多支持 {MAX_CONCURRENT_TASKS} 个并发研究，请等待现有任务完成后再提交。"
        )

    task_id = str(uuid.uuid4())[:8]
    _task_queues[task_id] = Queue()
    pause_ev = threading.Event()
    pause_ev.set()  # 初始为"未暂停"状态
    _task_pause_events[task_id] = pause_ev
    stop_ev = threading.Event()  # 初始未设置（未停止）
    _task_stop_events[task_id] = stop_ev
    _task_status[task_id] = {
        "task_id": task_id,
        "question": request.question,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "scores": [],
        "current_cycle": 0
    }

    # 在后台线程中运行
    thread = threading.Thread(
        target=_run_research_task,
        args=(task_id, request.question, request.clarification, request.research_strategy),
        daemon=True
    )
    thread.start()

    return {
        "task_id": task_id,
        "status": "started",
        "stream_url": f"/api/research/{task_id}/stream",
        "status_url": f"/api/research/{task_id}/status"
    }


@app.get("/api/research/{task_id}/stream")
async def stream_progress(task_id: str):
    """
    SSE 流式获取研究进度
    每个事件格式：data: {json}\n\n
    """
    if task_id not in _task_queues:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    async def event_generator() -> AsyncGenerator[str, None]:
        # 心跳，保持连接
        yield f"data: {json.dumps({'type': 'ping', 'task_id': task_id})}\n\n"

        queue = _task_queues[task_id]
        end_received = False

        while not end_received:
            # 非阻塞读取队列（100ms 超时）
            try:
                await asyncio.sleep(0.1)
                while True:
                    try:
                        event = queue.get_nowait()
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                        if event.get("type") == "end":
                            end_received = True
                            break
                    except Empty:
                        break
            except asyncio.CancelledError:
                break

        # 清理队列（但保留状态）
        if task_id in _task_queues:
            del _task_queues[task_id]

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )


@app.get("/api/research/{task_id}/status")
async def get_task_status(task_id: str):
    """获取任务状态快照"""
    status = _get_task_status(task_id)
    if status.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return status


@app.get("/api/research/{task_id}/result")
async def get_task_result(task_id: str):
    """获取已完成任务的完整结果"""
    status = _get_task_status(task_id)
    if status.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    if status.get("status") != "completed":
        raise HTTPException(status_code=425, detail=f"任务尚未完成，当前状态: {status.get('status')}")
    return {
        "task_id": task_id,
        "result": status.get("result", ""),
        "workspace": status.get("workspace", ""),
        "session_id": status.get("session_id", ""),
        "confidence_report": status.get("confidence_report", {}),
        "plan": status.get("plan", {})
    }


@app.get("/api/sessions")
async def list_sessions():
    """列出所有研究会话"""
    sessions = []
    if not os.path.exists(WORKSPACE_DIR):
        return {"sessions": []}

    for name in sorted(os.listdir(WORKSPACE_DIR), reverse=True):
        session_path = os.path.join(WORKSPACE_DIR, name)
        if not os.path.isdir(session_path):
            continue
        meta_file = os.path.join(session_path, "00_session.json")
        if os.path.exists(meta_file):
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                sessions.append({
                    "session_id": meta.get("session_id", name),
                    "question": meta.get("question", "")[:100],
                    "status": meta.get("status", "unknown"),
                    "created_at": meta.get("created_at", ""),
                    "final_score": meta.get("final_score", None),
                    "total_cycles": meta.get("total_cycles", None)
                })
            except Exception:
                sessions.append({"session_id": name, "status": "unknown"})

    return {"sessions": sessions[:20]}


@app.post("/api/research/{task_id}/message")
async def send_message(task_id: str, body: dict):
    """向正在运行的任务注入用户消息（在下一个阶段检查点生效）"""
    msg = (body.get("message") or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="消息不能为空")
    orchestrator = _task_orchestrators.get(task_id)
    if not orchestrator:
        raise HTTPException(status_code=404, detail="任务不存在或已完成")
    orchestrator._user_messages.append(msg)
    _put_event(task_id, "user_message_queued", {"message": msg})
    return {"status": "queued", "message": msg}


@app.post("/api/research/{task_id}/stop")
async def stop_task(task_id: str):
    """立即停止正在运行的任务"""
    stop_ev = _task_stop_events.get(task_id)
    if stop_ev:
        stop_ev.set()
    # 同时解除暂停（若已暂停则让线程继续运行到停止检查点）
    pause_ev = _task_pause_events.get(task_id)
    if pause_ev:
        pause_ev.set()
    if task_id in _task_status:
        _task_status[task_id]["status"] = "stopped"
    _put_event(task_id, "error", {"message": "任务已被用户停止"})
    return {"status": "stopping"}


@app.post("/api/research/stop-all")
async def stop_all_tasks():
    """停止所有正在运行的任务"""
    stopped = 0
    for tid, st in list(_task_status.items()):
        if st.get("status") in ("running", "paused"):
            stop_ev = _task_stop_events.get(tid)
            if stop_ev:
                stop_ev.set()
            pause_ev = _task_pause_events.get(tid)
            if pause_ev:
                pause_ev.set()
            st["status"] = "stopped"
            _put_event(tid, "error", {"message": "任务已被用户停止"})
            stopped += 1
    return {"stopped": stopped}


@app.delete("/api/research/{task_id}")
async def delete_task(task_id: str):
    """停止并删除任务（含工作区目录）"""
    import shutil, time as _t
    # 先停止
    stop_ev = _task_stop_events.get(task_id)
    if stop_ev:
        stop_ev.set()
    pause_ev = _task_pause_events.get(task_id)
    if pause_ev:
        pause_ev.set()
    if task_id in _task_status:
        _task_status[task_id]["status"] = "deleted"
    _put_event(task_id, "error", {"message": "任务已删除"})
    # 短暂等待线程响应停止信号
    await asyncio.sleep(0.5)
    # 删除工作区
    workspace = _task_status.get(task_id, {}).get("workspace")
    if workspace and os.path.isdir(workspace):
        shutil.rmtree(workspace, ignore_errors=True)
    else:
        # 尝试从会话 ID 查找
        session_id = _task_status.get(task_id, {}).get("session_id")
        if session_id:
            ws = _find_workspace(session_id)
            if os.path.isdir(ws):
                shutil.rmtree(ws, ignore_errors=True)
    # 清理内存状态
    for d in [_task_status, _task_queues, _task_pause_events, _task_stop_events, _task_orchestrators]:
        d.pop(task_id, None)
    return {"status": "deleted", "task_id": task_id}


@app.post("/api/research/{task_id}/pause")
async def pause_task(task_id: str):
    """暂停正在运行的任务"""
    ev = _task_pause_events.get(task_id)
    if not ev:
        raise HTTPException(status_code=404, detail="任务不存在")
    ev.clear()  # 清除事件 → orchestrator 在检查点阻塞
    _task_status[task_id]["paused"] = True
    return {"status": "pausing"}


@app.post("/api/research/{task_id}/resume")
async def resume_task(task_id: str):
    """恢复已暂停的任务"""
    ev = _task_pause_events.get(task_id)
    if not ev:
        raise HTTPException(status_code=404, detail="任务不存在")
    ev.set()  # 设置事件 → orchestrator 继续运行
    _task_status[task_id]["paused"] = False
    return {"status": "resumed"}


def _find_workspace_or_none(session_id: str):
    """按 session_id 查找工作空间路径，不存在返回 None"""
    if os.path.exists(WORKSPACE_DIR):
        for name in os.listdir(WORKSPACE_DIR):
            if session_id in name:
                return os.path.join(WORKSPACE_DIR, name)
    return None


@app.get("/api/sessions/{session_id}/report")
async def get_session_report(session_id: str):
    """获取指定会话的最终报告"""
    workspace = _find_workspace_or_none(session_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    final_file = os.path.join(workspace, "09_final.md")
    if not os.path.exists(final_file):
        raise HTTPException(status_code=404, detail="最终报告尚未生成")

    with open(final_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 尝试读取置信度报告
    conf_file = os.path.join(workspace, "08_verification", "confidence_report.json")
    confidence_report = {}
    if os.path.exists(conf_file):
        with open(conf_file, 'r', encoding='utf-8') as f:
            try:
                confidence_report = json.load(f)
            except Exception:
                pass

    return {
        "session_id": session_id,
        "report": content,
        "confidence_report": confidence_report
    }


@app.get("/api/sessions/{session_id}/plan")
async def get_session_plan(session_id: str):
    """获取指定会话的研究计划"""
    workspace = _find_workspace(session_id)
    plan_file = os.path.join(workspace, "03_plan.json")
    if not os.path.exists(plan_file):
        raise HTTPException(status_code=404, detail="研究计划尚未生成")
    with open(plan_file, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except Exception:
            raise HTTPException(status_code=500, detail="计划文件解析失败")


@app.get("/api/sessions/{session_id}/phases")
async def get_session_phases(session_id: str):
    """获取指定会话各阶段的存储内容摘要"""
    workspace = _find_workspace(session_id)
    result = {}

    # 会话元数据（含原始问题、轮次、评分、时间戳）
    sess_file = os.path.join(workspace, "00_session.json")
    if os.path.exists(sess_file):
        try:
            with open(sess_file, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            result["session_meta"] = {
                "question": meta.get("question", ""),
                "total_cycles": meta.get("total_cycles", 0),
                "final_score": meta.get("final_score"),
                "score_history": meta.get("score_history", []),
                "created_at": meta.get("created_at"),
                "last_updated": meta.get("last_updated"),
                "status": meta.get("status"),
            }
            result["question"] = meta.get("question", "")
        except Exception:
            pass

    # 原始问题（备用：单独文件）
    q_file = os.path.join(workspace, "01_question.txt")
    if os.path.exists(q_file) and not result.get("question"):
        with open(q_file, 'r', encoding='utf-8') as f:
            result["question"] = f.read().strip()

    # 研究计划
    plan_file = os.path.join(workspace, "03_plan.json")
    if os.path.exists(plan_file):
        with open(plan_file, 'r', encoding='utf-8') as f:
            try:
                result["plan"] = json.load(f)
            except Exception:
                pass

    # 澄清分析
    clarif_file = os.path.join(workspace, "04_clarification", "clarification.json")
    if os.path.exists(clarif_file):
        with open(clarif_file, 'r', encoding='utf-8') as f:
            try:
                result["clarification"] = json.load(f)
            except Exception:
                pass

    # 分析综合
    analysis_file = os.path.join(workspace, "05_analysis.md")
    if os.path.exists(analysis_file):
        with open(analysis_file, 'r', encoding='utf-8') as f:
            result["analysis"] = f.read()

    # 草稿列表
    drafts_dir = os.path.join(workspace, "06_drafts")
    if os.path.isdir(drafts_dir):
        drafts = []
        for fn in sorted(os.listdir(drafts_dir)):
            if fn.endswith(".md"):
                fp = os.path.join(drafts_dir, fn)
                drafts.append({
                    "name": fn,
                    "size": os.path.getsize(fp),
                    "modified": datetime.fromtimestamp(os.path.getmtime(fp)).isoformat()
                })
        result["drafts"] = drafts

    # 置信度报告
    conf_file = os.path.join(workspace, "08_verification", "confidence_report.json")
    if os.path.exists(conf_file):
        with open(conf_file, 'r', encoding='utf-8') as f:
            try:
                result["confidence_report"] = json.load(f)
            except Exception:
                pass

    # 来源验证（提取 total_sources）
    sv_file = os.path.join(workspace, "08_verification", "source_verification.json")
    if os.path.exists(sv_file):
        try:
            with open(sv_file, 'r', encoding='utf-8') as f:
                sv = json.load(f)
            result["source_total"] = sv.get("total_sources", 0)
        except Exception:
            pass

    return result


def _find_workspace(session_id: str) -> str:
    """按 session_id 查找工作空间路径，不存在则抛出 404"""
    ws = _find_workspace_or_none(session_id)
    if not ws:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    return ws


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话及其工作空间目录"""
    import shutil
    workspace = _find_workspace(session_id)
    if not os.path.isdir(workspace):
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    shutil.rmtree(workspace)
    return {"status": "deleted", "session_id": session_id}


@app.get("/api/config")
async def get_config():
    """获取当前系统配置"""
    from config import (
        CORE_MODEL, SUPPORT_MODEL,
        MIN_IMPROVEMENT_CYCLES, MAX_IMPROVEMENT_CYCLES, QUALITY_THRESHOLD
    )
    return {
        "model": CORE_MODEL,          # 兼容旧字段
        "core_model": CORE_MODEL,
        "support_model": SUPPORT_MODEL,
        "min_improvement_cycles": MIN_IMPROVEMENT_CYCLES,
        "max_improvement_cycles": MAX_IMPROVEMENT_CYCLES,
        "quality_threshold": QUALITY_THRESHOLD,
        "max_concurrent_tasks": MAX_CONCURRENT_TASKS,
    }


@app.post("/api/config")
async def update_config(request: ConfigRequest):
    """
    更新系统配置（运行时生效）
    注意：重启后恢复默认值，如需持久化请修改 .env 文件
    """
    import config

    changes = {}

    # 核心模型
    core = request.core_model or request.model
    if core is not None:
        config.CORE_MODEL = core
        config.ORCHESTRATOR_MODEL = core
        config.PLANNER_MODEL = core
        config.RESEARCHER_MODEL = core
        config.ANALYST_MODEL = core
        config.WRITER_MODEL = core
        changes["core_model"] = core

    # 辅助模型
    if request.support_model is not None:
        config.SUPPORT_MODEL = request.support_model
        config.CRITIC_MODEL = request.support_model
        config.SOURCE_VERIFIER_MODEL = request.support_model
        config.FACT_CHECKER_MODEL = request.support_model
        config.CONCLUSION_VALIDATOR_MODEL = request.support_model
        changes["support_model"] = request.support_model

    if request.min_cycles is not None:
        if 1 <= request.min_cycles <= 10:
            config.MIN_IMPROVEMENT_CYCLES = request.min_cycles
            changes["min_cycles"] = request.min_cycles
        else:
            raise HTTPException(status_code=400, detail="min_cycles 必须在 1-10 之间")

    if request.max_cycles is not None:
        if 1 <= request.max_cycles <= 20:
            config.MAX_IMPROVEMENT_CYCLES = request.max_cycles
            changes["max_cycles"] = request.max_cycles
        else:
            raise HTTPException(status_code=400, detail="max_cycles 必须在 1-20 之间")

    if request.quality_threshold is not None:
        if 0.0 <= request.quality_threshold <= 10.0:
            config.QUALITY_THRESHOLD = request.quality_threshold
            changes["quality_threshold"] = request.quality_threshold
        else:
            raise HTTPException(status_code=400, detail="quality_threshold 必须在 0-10 之间")

    return {"updated": changes, "message": "配置已更新（重启后恢复默认值）"}


@app.post("/api/clarify")
async def start_clarify(request: ClarifyStartRequest):
    """启动研究前置澄清会话，返回 AI 第一条澄清消息"""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="研究问题不能为空")
    try:
        from agents.clarifier import ClarifierAgent
        agent = ClarifierAgent()
        result = agent.start(request.question.strip())
        clarify_id = str(uuid.uuid4())[:8]
        _clarify_sessions[clarify_id] = {
            "clarify_id": clarify_id,
            "question": request.question.strip(),
            "history": result.get("history", []),
            "summary": result.get("summary", {}),
            "turns": 1,
        }
        return {
            "clarify_id": clarify_id,
            "message": result.get("message", ""),
            "summary": result.get("summary", {}),
            "ready": result.get("ready", False),
            "confidence": result.get("confidence", 0.0),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"澄清智能体启动失败：{str(e)}")


@app.post("/api/clarify/{clarify_id}/message")
async def clarify_message(clarify_id: str, request: ClarifyReplyRequest):
    """继续澄清对话"""
    session = _clarify_sessions.get(clarify_id)
    if not session:
        raise HTTPException(status_code=404, detail="澄清会话不存在")
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")
    try:
        from agents.clarifier import ClarifierAgent
        agent = ClarifierAgent()
        result = agent.reply(session["history"], request.message.strip())
        session["history"] = result.get("history", session["history"])
        session["summary"] = result.get("summary", session["summary"])
        session["turns"] += 1
        return {
            "message": result.get("message", ""),
            "summary": result.get("summary", {}),
            "ready": result.get("ready", False),
            "confidence": result.get("confidence", 0.0),
            "turns": session["turns"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"澄清对话失败：{str(e)}")


@app.post("/api/clarify/{clarify_id}/confirm")
async def confirm_clarify(clarify_id: str, request: ClarifyConfirmRequest):
    """用户确认研究需求，启动正式研究任务"""
    session = _clarify_sessions.get(clarify_id)
    if not session:
        raise HTTPException(status_code=404, detail="澄清会话不存在")

    running = _running_task_count()
    if running >= MAX_CONCURRENT_TASKS:
        raise HTTPException(
            status_code=429,
            detail=f"当前已有 {running} 个任务在运行，请等待完成后再提交。"
        )

    # 用用户编辑后的摘要（若有）覆盖
    summary = request.summary or session["summary"]

    # 将摘要拼装成富文本补充说明，传给 orchestrator
    s = summary
    parts = []
    if s.get("scope"):       parts.append(f"研究范围：{s['scope']}")
    if s.get("key_aspects"): parts.append(f"重点方面：{'、'.join(s['key_aspects'])}")
    if s.get("timeframe"):   parts.append(f"时间范围：{s['timeframe']}")
    if s.get("depth"):       parts.append(f"研究深度：{s['depth']}")
    if s.get("angle"):       parts.append(f"研究角度：{s['angle']}")
    if s.get("exclude"):     parts.append(f"排除内容：{s['exclude']}")
    if s.get("search_hints"):parts.append(f"关键搜索词：{', '.join(s['search_hints'])}")
    if request.extra_note:   parts.append(f"用户补充：{request.extra_note}")

    clarification_text = "\n".join(parts)

    # 提取意图元数据，传给 orchestrator 调整研究策略
    intent_meta = {
        "intent_type": s.get("intent_type", "info_seeking"),
        "dimensions": s.get("dimensions", {"urgency": 0.5, "specificity": 0.5, "complexity": 0.5}),
    }

    task_id = str(uuid.uuid4())[:8]
    _task_queues[task_id] = Queue()
    pause_ev = threading.Event(); pause_ev.set()
    _task_pause_events[task_id] = pause_ev
    stop_ev = threading.Event()
    _task_stop_events[task_id] = stop_ev
    _task_status[task_id] = {
        "task_id": task_id,
        "question": session["question"],
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "scores": [],
        "current_cycle": 0,
        "clarify_id": clarify_id,
        "summary": summary,
        "intent_meta": intent_meta,
    }

    thread = threading.Thread(
        target=_run_research_task,
        args=(task_id, session["question"], clarification_text, None, intent_meta),
        daemon=True
    )
    thread.start()

    # 清理澄清会话（已不需要）
    _clarify_sessions.pop(clarify_id, None)

    return {
        "task_id": task_id,
        "status": "started",
        "stream_url": f"/api/research/{task_id}/stream",
        "status_url": f"/api/research/{task_id}/status",
    }


@app.get("/api/health")
async def health_check():
    """健康检查"""
    import config
    return {
        "status": "ok",
        "model": config.ORCHESTRATOR_MODEL,
        "active_tasks": len(_task_queues),
        "current_date": config.CURRENT_DATE_STR,
    }


@app.get("/api/settings")
async def get_settings():
    """获取当前模型设置"""
    import config
    return {
        "core_model": config.CORE_MODEL,
        "support_model": config.SUPPORT_MODEL,
    }


@app.post("/api/settings")
async def update_settings(request: SettingsRequest):
    """更新模型设置并持久化到 settings.json"""
    import config
    from config import save_settings

    try:
        changes = {}

        if request.core_model is not None:
            m = request.core_model.strip()
            if m:
                config.CORE_MODEL = m
                config.ORCHESTRATOR_MODEL = m
                config.PLANNER_MODEL = m
                config.RESEARCHER_MODEL = m
                config.ANALYST_MODEL = m
                config.WRITER_MODEL = m
                changes["core_model"] = m

        if request.support_model is not None:
            m = request.support_model.strip()
            if m:
                config.SUPPORT_MODEL = m
                config.CRITIC_MODEL = m
                config.SOURCE_VERIFIER_MODEL = m
                config.FACT_CHECKER_MODEL = m
                config.CONCLUSION_VALIDATOR_MODEL = m
                changes["support_model"] = m

        save_settings(changes)
        return {"updated": list(changes.keys()), "message": "设置已保存"}

    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"保存失败：{str(e)}\n{traceback.format_exc()}")


@app.get("/api/models")
async def list_models():
    """返回可用 Claude 模型列表"""
    return {"models": ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"]}


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """SPA catch-all：先尝试 STATIC_DIR 下的真实文件，否则返回 index.html"""
    # 1) STATIC_DIR 下存在的真实文件（如 favicon.ico、vite.svg 等）
    if full_path and ".." not in full_path:
        candidate = os.path.join(STATIC_DIR, full_path)
        if os.path.isfile(candidate):
            return FileResponse(candidate)
    # 2) 兜底返回 index.html（让 React Router 处理）
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return JSONResponse({"error": "前端尚未构建"}, status_code=404)
