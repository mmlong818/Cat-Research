"""
FastAPI 应用 - 多智能体研究系统 REST API
支持 SSE 实时流式进度推送
"""
import asyncio
import json
import os
import threading
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from queue import Empty
from typing import TYPE_CHECKING, Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api import security
from api import sessions as _sessions
from api.db.task_store import ACTIVE, TaskStore
from api.events import BroadcastRegistry
from api.profile_resolver import ensure_key, resolve_profile, session_profile
from api.routes.config import models_by_provider
from api.routes.config import router as config_router
from llm.profiles import Profile, default_profile
from research.checkpoints import PHASES, Checkpoints
from research.ledger import Ledger
from research.params import resolve_params
from tools.file_tools import mark_workspace_deleted

if TYPE_CHECKING:
    from orchestrator import ResearchOrchestrator

# 项目根目录
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(ROOT_DIR, "static")
WORKSPACE_DIR = os.path.join(ROOT_DIR, "workspace")

# 研究任务状态持久化（重启后仍可查询），见 api/db/task_store.py
_store = TaskStore(os.path.join(ROOT_DIR, "research_tasks.db"))


@asynccontextmanager
async def _lifespan(_app):
    _store.mark_interrupted()  # 上次进程里未结束的任务线程已不存在
    yield


app = FastAPI(
    title="多智能体研究系统 API",
    description="基于 Claude 的多智能体研究系统，支持来源验证、事实核查和结论验证",
    version="2.0.0",
    lifespan=_lifespan,
)

# CORS 配置
# 生产环境请将 CORS_ORIGINS 环境变量设置为实际前端域名，如：
# CORS_ORIGINS=https://yourdomain.com,https://app.yourdomain.com
_cors_origins_env = os.getenv("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()] or [
    "http://localhost:3000", "http://localhost:8000", "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Accept", security.TOKEN_HEADER],
)
app.middleware("http")(security.guard)  # Host 校验 + /api/* 令牌校验，见 api/security.py

# 挂载静态文件
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 注册配置路由
app.include_router(config_router)


# ── 请求/响应模型 ────────────────────────────────────────────────────────────

Depth = Literal["quick", "standard", "deep"]
Language = Literal["zh", "en"]    # 最终报告的撰写语言


class ModelChoice(BaseModel):
    """本次任务临时指定的提供方/模型；都不传则用设置里的默认配置档"""
    provider: str | None = None
    core_model: str | None = None
    support_model: str | None = None


class ResearchRequest(ModelChoice):
    question: str
    clarification: str | None = None  # 预填写的澄清信息
    research_strategy: str | None = None  # 研究策略（搜索方向、来源类型等）
    min_cycles: int | None = None  # 本次任务最小改进轮数（覆盖档位默认）
    max_cycles: int | None = None  # 本次任务最大改进轮数（覆盖档位默认）
    depth: Depth = "standard"         # 研究深度档，见 config.DEPTH_PRESETS
    language: Language = "zh"         # 报告语言
    max_queries: int | None = Field(default=None, ge=1, le=30)  # 覆盖档位的规划查询数
    ask_loop: bool = False            # 改进循环中即时询问用户是否继续（界面默认开启；API 直接调用默认关，不会卡住等人）


class ConfigRequest(BaseModel):
    model: str | None = None          # 兼容旧字段（映射到 core_model）
    core_model: str | None = None
    support_model: str | None = None
    quality_threshold: float | None = None


class ClarifyStartRequest(ModelChoice):
    question: str

class ClarifyReplyRequest(BaseModel):
    message: str

class ClarifyConfirmRequest(ModelChoice):
    summary: dict | None = None   # 用户可编辑后的摘要
    extra_note: str | None = None # 用户额外补充（可选）
    question: str | None = None   # 委托台改过的研究问题（覆盖澄清时的原问题；空白视为没改）
    goal: str | None = None       # 研究目标（写进补充说明第一行）
    min_cycles: int | None = None # 本次任务最小改进轮数
    max_cycles: int | None = None # 本次任务最大改进轮数
    depth: Depth = "standard"        # 研究深度档
    language: Language = "zh"        # 报告语言
    ask_loop: bool = False           # 改进循环中即时询问用户是否继续


class LoopDecisionRequest(BaseModel):
    choice: Literal["continue", "stop"]


# ── 会话管理 ─────────────────────────────────────────────────────────────────

# 最大并发研究任务数
MAX_CONCURRENT_TASKS = 2

# ── 澄清会话存储 {clarify_id: dict} ─────────────────────────────────────────
_clarify_sessions: dict[str, dict] = {}

# 各任务的事件广播器（多订阅者 + 回放缓冲），任务结束后保留一段时间，见 api/events.py
_events = BroadcastRegistry()
# 存储各任务的 orchestrator 引用（用于注入消息和暂停控制）
_task_orchestrators: dict[str, "ResearchOrchestrator"] = {}
# 存储各任务的暂停事件 {task_id: threading.Event}
_task_pause_events: dict[str, threading.Event] = {}
# 存储各任务的停止事件 {task_id: threading.Event}
_task_stop_events: dict[str, threading.Event] = {}
# 各任务的后台线程 {task_id: Thread}，删除接口据此等待线程退出（线程结束时自行移除）
_task_threads: dict[str, threading.Thread] = {}
# 删除运行中的任务/会话时，最多等后台线程退出多久（秒）；线程可能卡在长耗时的模型调用里，超时就不再等
DELETE_JOIN_TIMEOUT = 5.0


# 进度事件中需要进审计日志的（其余只推送给前端）
AUDITED_EVENTS = ("user_message_ack", "user_message_applied", "checkpoint", "loop_stop", "final_selected")


def _get_task_status(task_id: str) -> dict:
    return _store.get(task_id) or {"status": "not_found"}


def _put_event(task_id: str, event_type: str, data: dict):
    """向任务的所有订阅者广播事件"""
    bc = _events.get(task_id)
    if bc:
        bc.publish({
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
        st = _store.get(task_id) or {}
        if st.get("status") not in ("running",):
            break
        _put_event(task_id, "heartbeat", {
            "current_status": st.get("current_status", ""),
            "current_cycle": st.get("current_cycle", 0),
            "elapsed": round(_time.time() - st.get("_start_ts", _time.time()))
        })


def _run_research_task(task_id: str, question: str, clarification: str | None,
                       research_strategy: str | None = None,
                       intent_meta: dict | None = None,
                       min_cycles: int | None = None,
                       max_cycles: int | None = None,
                       depth: str | None = None,
                       language: str = "zh",
                       max_queries: int | None = None,
                       ask_loop: bool = False,
                       replay: dict | None = None,
                       profile: Profile | None = None):
    """在后台线程中运行研究任务；replay={"workspace", "from_phase"} 时在已有会话上重放"""
    import sys
    import time as _time
    sys.path.insert(0, ROOT_DIR)
    # orchestrator.py 在模块加载时已全局替换 stdout/stderr 为 UTF-8，
    # 线程内不再重复替换，否则会产生 "I/O operation on closed file" 错误

    try:
        _store.merge(task_id, status="running", _start_ts=_time.time())
        _put_event(task_id, "started", {"task_id": task_id, "question": question})

        # 启动心跳线程
        hb_stop = _task_stop_events.get(task_id) or threading.Event()
        hb_thread = threading.Thread(target=_heartbeat_thread, args=(task_id, hb_stop), daemon=True)
        hb_thread.start()

        from orchestrator import ResearchOrchestrator

        def progress_callback(event_type: str, data: dict):
            try:
                _put_event(task_id, event_type, data)
                # 同步更新状态
                if event_type == "status":
                    _store.merge(task_id, current_status=data.get("status", ""))
                elif event_type == "session":
                    _store.attach_session(task_id, data["session_id"], data["workspace"])
                elif event_type in AUDITED_EVENTS:
                    _store.audit(task_id, event_type, data)
                elif event_type == "loop_decision_resolved":  # 提问本身只推送给前端，结果（含超时/停止）记审计
                    _store.audit(task_id, "loop_decision", data)
                elif event_type == "phase":
                    _store.start_phase(task_id, data.get("phase", 0), data.get("name", ""))
                elif event_type == "plan":
                    _store.merge(task_id, plan=data)
                elif event_type == "cycle_start":
                    _store.merge(task_id, current_cycle=data.get("cycle", 0))
                elif event_type == "review":
                    scores = _get_task_status(task_id).get("scores", [])
                    _store.merge(task_id, scores=[*scores, data.get("avg_score", 0)])
                elif event_type == "confidence_report":
                    _store.merge(task_id, confidence_report=data)
            except Exception as e:
                print(f"[app] 进度回调失败（不中断主流程）: {e!r}", flush=True)

        pause_event = _task_pause_events.get(task_id)
        stop_event = _task_stop_events.get(task_id)
        orchestrator = ResearchOrchestrator(progress_callback=progress_callback, profile=profile)
        _task_orchestrators[task_id] = orchestrator

        if replay:
            result = orchestrator.replay(replay["workspace"], replay["from_phase"],
                                         pause_event=pause_event, stop_event=stop_event)
        else:
            result = orchestrator.run(
                question,
                clarification=clarification,  # 预填写的澄清信息与问题分开存，进入提示词时由编排器接在问题后面
                research_strategy=research_strategy,
                intent_meta=intent_meta,
                pause_event=pause_event,
                stop_event=stop_event,
                min_cycles=min_cycles,
                max_cycles=max_cycles,
                depth=depth,
                language=language,
                max_queries=max_queries,
                ask_loop=ask_loop,
            )

        if orchestrator.interrupted:  # 停止或暂停超时：返回的是提示文本，不能记成完成（检查点仍可续跑）
            _store.merge(task_id, status="stopped")
            _store.finish_phase(task_id, "stopped")
            _store.audit(task_id, "task_finished", {"status": "stopped"})
            return
        _store.merge(task_id, status="completed", result=result,
                     workspace=str(orchestrator.workspace), session_id=orchestrator.session_id)
        _store.finish_phase(task_id, "completed")
        _store.audit(task_id, "task_finished", {"status": "completed", "result_chars": len(result)})
        _put_event(task_id, "completed", {
            "result": result[:500] + "..." if len(result) > 500 else result,
            "workspace": str(orchestrator.workspace),
            "session_id": orchestrator.session_id
        })

    except Exception as e:
        error_msg = str(e)
        _store.merge(task_id, status="failed", error=error_msg)
        _store.finish_phase(task_id, "failed", error_msg)
        _store.audit(task_id, "task_finished", {"status": "failed", "error": error_msg})
        _put_event(task_id, "error", {"message": error_msg})

    finally:
        # 发送结束标记
        _put_event(task_id, "end", {})
        _task_threads.pop(task_id, None)


def _signal_stop(task_id: str):
    """发出停止信号，并解除暂停（暂停中的线程才能走到停止检查点）。"""
    stop_ev = _task_stop_events.get(task_id)
    if stop_ev:
        stop_ev.set()
    pause_ev = _task_pause_events.get(task_id)
    if pause_ev:
        pause_ev.set()


def _wait_for_threads(task_ids: list):
    """给仍在运行的后台线程一个退出的机会，总共最多等 DELETE_JOIN_TIMEOUT 秒。"""
    deadline = time.monotonic() + DELETE_JOIN_TIMEOUT
    for tid in task_ids:
        thread = _task_threads.get(tid)
        if thread and thread is not threading.current_thread():
            thread.join(max(0.0, deadline - time.monotonic()))


def _wrapping_up(session_id: str) -> bool:
    """会话上有任务已经停下（状态不再是运行中），后台线程却还没退出（例如还在等进行中的模型调用返回）。"""
    for task_id, thread in list(_task_threads.items()):
        task = _store.get(task_id) or {}
        if thread.is_alive() and task.get("session_id") == session_id and task.get("status") not in ACTIVE:
            return True
    return False


def _remove_workspace(workspace: str, ignore_errors: bool):
    """删除工作区目录。先登记为已删除：还没退出的后台线程之后落盘会被拒绝，不会把目录重新建出来。"""
    import shutil
    mark_workspace_deleted(workspace)
    shutil.rmtree(workspace, ignore_errors=ignore_errors)


# ── API 路由 ─────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    """提供 Web UI"""
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return security.index_response(index_file)
    return JSONResponse({"message": "多智能体研究系统 API v2.0", "docs": "/docs"})


@app.post("/api/research")
async def start_research(request: ResearchRequest):
    """
    启动一个新的研究任务（最多同时运行 MAX_CONCURRENT_TASKS 个）
    返回 task_id，通过 /api/research/{task_id}/stream 获取实时进度
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="研究问题不能为空")
    profile = resolve_profile(request.provider, request.core_model, request.support_model)  # 缺 key 等在建任务前就 400

    task_id = str(uuid.uuid4())[:8]
    if _store.reserve(task_id, request.question, MAX_CONCURRENT_TASKS, scores=[], current_cycle=0,
                      depth=request.depth, language=request.language, **_profile_fields(profile)):
        raise HTTPException(
            status_code=429,
            detail=(f"当前已有 {_store.active_count()} 个任务在运行，最多支持 {MAX_CONCURRENT_TASKS} 个并发研究，"
                    "请等待现有任务完成后再提交。")
        )
    _store.audit(task_id, "task_created", {
        "source": "direct", "question": request.question, "clarification": request.clarification,
        "research_strategy": request.research_strategy,
        "min_cycles": request.min_cycles, "max_cycles": request.max_cycles, "depth": request.depth,
        "language": request.language, "max_queries": request.max_queries, "ask_loop": request.ask_loop,
        **_profile_fields(profile),
        "resolved_params": resolve_params(request.depth, request.language, request.min_cycles,
                                          request.max_cycles, request.max_queries, profile, request.ask_loop),
    })
    _events.create(task_id)
    pause_ev = threading.Event()
    pause_ev.set()  # 初始为"未暂停"状态
    _task_pause_events[task_id] = pause_ev
    stop_ev = threading.Event()  # 初始未设置（未停止）
    _task_stop_events[task_id] = stop_ev

    # 在后台线程中运行
    thread = threading.Thread(
        target=_run_research_task,
        args=(task_id, request.question, request.clarification, request.research_strategy),
        kwargs={"min_cycles": request.min_cycles, "max_cycles": request.max_cycles, "depth": request.depth,
                "language": request.language, "max_queries": request.max_queries, "ask_loop": request.ask_loop,
                "profile": profile},
        daemon=True
    )
    _task_threads[task_id] = thread  # 删除接口据此等待线程退出
    thread.start()

    return {
        "task_id": task_id,
        "status": "started",
        "stream_url": f"/api/research/{task_id}/stream",
        "status_url": f"/api/research/{task_id}/status"
    }


def _profile_fields(profile: Profile) -> dict:
    """任务记录与审计里的模型配置档字段"""
    return {"provider": profile.provider, "core_model": profile.core, "support_model": profile.support}


SNAPSHOT_FIELDS = ("status", "question", "current_status", "current_cycle", "scores", "paused", "error", "session_id")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _task_snapshot(task_id: str) -> dict:
    """当前状态快照（不含报告正文，正文走 /result）；订阅者收到后据此重置界面"""
    import time as _time
    st = _store.get(task_id) or {}
    data = {k: st[k] for k in SNAPSHOT_FIELDS if k in st}
    data["task_id"] = task_id
    if st.get("status") in ACTIVE and "_start_ts" in st:
        data["elapsed"] = round(_time.time() - st["_start_ts"])
    orchestrator = _task_orchestrators.get(task_id)
    pending = orchestrator.loop_ask.pending if orchestrator else None  # 正在等用户决定：快照带上，重连后恢复提示卡
    if pending:
        data["loop_decision"] = pending
    return {"type": "snapshot", "data": data, "timestamp": datetime.now().isoformat()}


async def _event_stream(task_id: str) -> AsyncGenerator[str, None]:
    """先发 ping 与快照，再回放缓冲，最后接实时事件；任务已结束或没有广播器（如服务重启后）时发完即关"""
    yield _sse({"type": "ping", "task_id": task_id})
    yield _sse(_task_snapshot(task_id))

    bc = _events.get(task_id)
    replay, queue = bc.subscribe() if bc else ([], None)
    try:
        for event in replay:
            yield _sse(event)
            if event.get("type") == "end":
                return
        status = (_store.get(task_id) or {}).get("status")
        if queue is None or status not in ACTIVE:  # 已停止/失败/中断：线程可能还没退出，不必等它的 end
            yield _sse({"type": "end", "data": {}, "timestamp": datetime.now().isoformat()})
            return
        while True:
            await asyncio.sleep(0.1)
            while True:
                try:
                    event = queue.get_nowait()
                except Empty:
                    break
                yield _sse(event)
                if event.get("type") == "end":
                    return
    finally:  # 客户端断开时 Starlette 会取消/关闭生成器，订阅者随之移除
        if bc and queue is not None:
            bc.unsubscribe(queue)


@app.get("/api/research/{task_id}/stream")
async def stream_progress(task_id: str):
    """
    SSE 流式获取研究进度，支持多订阅者与断线重连（回放缓冲 + 状态快照，见 api/events.py）
    每个事件格式：data: {json}\n\n
    """
    if _store.get(task_id) is None and _events.get(task_id) is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    return StreamingResponse(
        _event_stream(task_id),
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
def list_sessions(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    """研究会话列表（新到旧）：workspace 里的会话合并任务记录（状态、深度、语言、阶段、错误）；
    没建成工作空间的失败任务也会列出（session_id 为空，用 task_id 标识）"""
    return _sessions.list_sessions(_store, WORKSPACE_DIR, limit, offset)


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
    _store.audit(task_id, "user_message", {"message": msg})
    _put_event(task_id, "user_message_queued", {"message": msg})
    return {"status": "queued", "message": msg}


@app.post("/api/research/{task_id}/loop-decision")
async def answer_loop_decision(task_id: str, body: LoopDecisionRequest):
    """回答改进循环里的「是否继续」提问；任务当前没有在等决定时返回 409"""
    orchestrator = _task_orchestrators.get(task_id)
    if not orchestrator:
        raise HTTPException(status_code=404, detail="任务不存在或已完成")
    if not orchestrator.loop_ask.answer(body.choice):
        raise HTTPException(status_code=409, detail="任务当前没有在等待决定")
    return {"status": "accepted", "choice": body.choice}


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
    _store.merge(task_id, status="stopped")
    _store.audit(task_id, "stop_requested")
    _put_event(task_id, "stopped", {"reason": "user"})  # 用户停止不是失败：不用 error 事件
    return {"status": "stopping"}


@app.post("/api/research/stop-all")
async def stop_all_tasks():
    """停止所有正在运行的任务"""
    stopped = 0
    for tid in _store.active_ids():
        stop_ev = _task_stop_events.get(tid)
        if stop_ev:
            stop_ev.set()
        pause_ev = _task_pause_events.get(tid)
        if pause_ev:
            pause_ev.set()
        _store.merge(tid, status="stopped")
        _store.audit(tid, "stop_requested", {"scope": "all"})
        _put_event(tid, "stopped", {"reason": "user"})
        stopped += 1
    return {"stopped": stopped}


@app.delete("/api/research/{task_id}")
async def delete_task(task_id: str):
    """停止并删除任务（含工作区目录）"""
    # 先停止
    _signal_stop(task_id)
    _store.merge(task_id, status="deleted")
    _store.audit(task_id, "delete_requested")
    _put_event(task_id, "stopped", {"reason": "deleted"})
    # 等后台线程退出再删目录；超时（线程还卡在模型调用里）也照删，之后它落盘会被 _remove_workspace 的登记拒绝
    await asyncio.to_thread(_wait_for_threads, [task_id])
    # 删除工作区
    task = _store.get(task_id) or {}
    workspace = task.get("workspace")
    if workspace and await asyncio.to_thread(os.path.isdir, workspace):
        _remove_workspace(workspace, ignore_errors=True)
    else:
        # 尝试从会话 ID 查找
        session_id = task.get("session_id")
        if session_id:
            ws = _find_workspace_or_none(session_id)  # 会话目录已不在时照样删任务记录
            if ws and await asyncio.to_thread(os.path.isdir, ws):
                _remove_workspace(ws, ignore_errors=True)
    # 清理持久化记录与内存状态
    _store.delete(task_id)
    bc = _events.drop(task_id)
    if bc:
        bc.close()  # 让仍连着的订阅者收到结束标记，而不是一直挂着
    _task_pause_events.pop(task_id, None)
    _task_stop_events.pop(task_id, None)
    _task_orchestrators.pop(task_id, None)
    return {"status": "deleted", "task_id": task_id}


@app.post("/api/research/{task_id}/pause")
async def pause_task(task_id: str):
    """暂停正在运行的任务"""
    ev = _task_pause_events.get(task_id)
    if not ev:
        raise HTTPException(status_code=404, detail="任务不存在")
    ev.clear()  # 清除事件 → orchestrator 在检查点阻塞
    _store.merge(task_id, paused=True)
    _store.audit(task_id, "pause_requested")
    return {"status": "pausing"}


@app.post("/api/research/{task_id}/resume")
async def resume_task(task_id: str):
    """恢复已暂停的任务"""
    ev = _task_pause_events.get(task_id)
    if not ev:
        raise HTTPException(status_code=404, detail="任务不存在")
    ev.set()  # 设置事件 → orchestrator 继续运行
    _store.merge(task_id, paused=False)
    _store.audit(task_id, "resume_requested")
    return {"status": "resumed"}


def _find_workspace_or_none(session_id: str):
    """按 session_id 查找工作空间路径，不存在返回 None"""
    if os.path.exists(WORKSPACE_DIR):
        for name in os.listdir(WORKSPACE_DIR):
            if session_id in name:
                return os.path.join(WORKSPACE_DIR, name)
    return None


@app.get("/api/sessions/{session_id}/report")
def get_session_report(session_id: str):
    """获取指定会话的最终报告"""
    workspace = _find_workspace_or_none(session_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    final_file = os.path.join(workspace, "09_final.md")
    if not os.path.exists(final_file):
        raise HTTPException(status_code=404, detail="最终报告尚未生成")

    with open(final_file, encoding='utf-8') as f:
        content = f.read()

    # 尝试读取置信度报告
    conf_file = os.path.join(workspace, "08_verification", "confidence_report.json")
    confidence_report = {}
    if os.path.exists(conf_file):
        with open(conf_file, encoding='utf-8') as f, suppress(OSError, ValueError):  # 损坏/不可读时按"无报告"处理
            confidence_report = json.load(f)

    token_usage = None
    sess_file = os.path.join(workspace, "00_session.json")
    if os.path.exists(sess_file):
        with open(sess_file, encoding='utf-8') as f, suppress(OSError, ValueError, AttributeError):
            token_usage = json.load(f).get("token_usage")

    return {
        "session_id": session_id,
        "report": content,
        "confidence_report": confidence_report,
        "token_usage": token_usage
    }


@app.get("/api/sessions/{session_id}/drafts")
def list_session_drafts(session_id: str):
    """列出指定会话所有版本草稿（含最终报告）"""
    workspace = _find_workspace_or_none(session_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    drafts: list[dict] = []
    drafts_dir = os.path.join(workspace, "06_drafts")
    if os.path.isdir(drafts_dir):
        items: list[dict[str, Any]] = []
        for name in os.listdir(drafts_dir):
            if not name.startswith("draft_") or not name.endswith(".md"):
                continue
            try:
                num = int(name[len("draft_"):-len(".md")])
            except ValueError:
                continue
            path = os.path.join(drafts_dir, name)
            try:
                size = os.path.getsize(path)
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            items.append({
                "kind": "draft",
                "draft_num": num,
                "name": name,
                "size": size,
                "modified_at": datetime.fromtimestamp(mtime).isoformat(),
                "download_url": f"/api/sessions/{session_id}/drafts/{num}/download",
            })
        items.sort(key=lambda x: x["draft_num"])
        drafts.extend(items)

    final_file = os.path.join(workspace, "09_final.md")
    if os.path.exists(final_file):
        drafts.append({
            "kind": "final",
            "draft_num": None,
            "name": "09_final.md",
            "size": os.path.getsize(final_file),
            "modified_at": datetime.fromtimestamp(os.path.getmtime(final_file)).isoformat(),
            "download_url": f"/api/sessions/{session_id}/drafts/final/download",
        })

    return {"session_id": session_id, "drafts": drafts}


@app.get("/api/sessions/{session_id}/drafts/{draft_id}/download")
def download_session_draft(session_id: str, draft_id: str):
    """下载某一版本草稿（draft_id 为整数版本号或 'final'）"""
    workspace = _find_workspace_or_none(session_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    if draft_id == "final":
        path = os.path.join(workspace, "09_final.md")
        filename = f"{session_id}-final.md"
    else:
        try:
            num = int(draft_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="draft_id 必须是整数或 'final'") from None
        path = os.path.join(workspace, "06_drafts", f"draft_{num}.md")
        filename = f"{session_id}-draft-{num}.md"

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="草稿文件不存在")

    return FileResponse(path, media_type="text/markdown", filename=filename)


@app.get("/api/sessions/{session_id}/plan")
def get_session_plan(session_id: str):
    """获取指定会话的研究计划"""
    workspace = _find_workspace(session_id)
    plan_file = os.path.join(workspace, "03_plan.json")
    if not os.path.exists(plan_file):
        raise HTTPException(status_code=404, detail="研究计划尚未生成")
    with open(plan_file, encoding='utf-8') as f:
        try:
            return json.load(f)
        except (OSError, ValueError) as e:
            raise HTTPException(status_code=500, detail="计划文件解析失败") from e


@app.get("/api/sessions/{session_id}/phases")
def get_session_phases(session_id: str):
    """获取指定会话各阶段的存储内容摘要"""
    workspace = _find_workspace(session_id)
    result: dict[str, Any] = {}

    # 会话元数据（含原始问题、轮次、评分、时间戳）
    sess_file = os.path.join(workspace, "00_session.json")
    if os.path.exists(sess_file):
        try:
            with open(sess_file, encoding='utf-8') as f:
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
        except (OSError, ValueError, AttributeError):  # 元数据缺失/损坏/非对象时跳过该字段
            pass

    # 原始问题（备用：单独文件）
    q_file = os.path.join(workspace, "01_question.txt")
    if os.path.exists(q_file) and not result.get("question"):
        with open(q_file, encoding='utf-8') as f:
            result["question"] = f.read().strip()

    # 研究计划
    plan_file = os.path.join(workspace, "03_plan.json")
    if os.path.exists(plan_file):
        with open(plan_file, encoding='utf-8') as f, suppress(OSError, ValueError):
            result["plan"] = json.load(f)

    # 澄清分析
    clarif_file = os.path.join(workspace, "04_clarification", "clarification.json")
    if os.path.exists(clarif_file):
        with open(clarif_file, encoding='utf-8') as f, suppress(OSError, ValueError):
            result["clarification"] = json.load(f)

    # 分析综合
    analysis_file = os.path.join(workspace, "05_analysis.md")
    if os.path.exists(analysis_file):
        with open(analysis_file, encoding='utf-8') as f:
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
        with open(conf_file, encoding='utf-8') as f, suppress(OSError, ValueError):
            result["confidence_report"] = json.load(f)

    # 来源验证（提取 total_sources）
    sv_file = os.path.join(workspace, "08_verification", "source_verification.json")
    if os.path.exists(sv_file):
        try:
            with open(sv_file, encoding='utf-8') as f:
                sv = json.load(f)
            result["source_total"] = sv.get("total_sources", 0)
        except (OSError, ValueError, AttributeError):  # 来源验证文件缺失/损坏/非对象时跳过该字段
            pass

    return result


class ReplayRequest(BaseModel):
    from_phase: str | None = None  # None = 从断点续跑


@app.get("/api/sessions/{session_id}/checkpoints")
async def list_checkpoints(session_id: str):
    """会话已完成阶段的检查点，以及默认的续跑起点"""
    ck = Checkpoints(_find_workspace(session_id))
    try:
        resume_from = PHASES[ck.resolve(None)]
    except ValueError:
        resume_from = None
    return {"session_id": session_id, "phases": list(PHASES), "checkpoints": ck.list(), "resume_from": resume_from}


@app.post("/api/sessions/{session_id}/replay")
async def replay_session(session_id: str, request: ReplayRequest):
    """从指定阶段重放会话（之后阶段的产物与台账回滚到该阶段之前）；同一会话同时只能有一个任务"""
    workspace = _find_workspace(session_id)
    session_id = os.path.basename(workspace).removeprefix("session_")  # 路由按子串匹配，互斥检查要用完整 ID
    if _wrapping_up(session_id):  # 停止后旧线程还会落盘，此时回滚工作空间会和它互相覆盖
        raise HTTPException(status_code=409, detail="上一个线程还在收尾，请稍后再试")
    try:
        from_phase = PHASES[Checkpoints(workspace).resolve(request.from_phase)]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    profile = ensure_key(session_profile(workspace))  # 沿用会话原来的提供方与模型

    task_id = str(uuid.uuid4())[:8]
    question = _read_session_question(workspace)
    refusal = _store.reserve(task_id, question, MAX_CONCURRENT_TASKS, session_id=session_id,
                             scores=[], current_cycle=0, replay_from=from_phase, **_profile_fields(profile))
    if refusal == "busy":
        raise HTTPException(status_code=409, detail=f"会话 {session_id} 已有任务在运行，请等待其结束后再重放")
    if refusal:
        raise HTTPException(
            status_code=429, detail=f"当前已有 {_store.active_count()} 个任务在运行，请等待完成后再提交。")
    _store.audit(task_id, "task_created", {"source": "replay", "question": question, "from_phase": from_phase,
                                           **_profile_fields(profile)})
    _events.create(task_id)
    pause_ev = threading.Event()
    pause_ev.set()
    _task_pause_events[task_id] = pause_ev
    _task_stop_events[task_id] = threading.Event()

    thread = threading.Thread(
        target=_run_research_task,
        args=(task_id, question, None),
        kwargs={"replay": {"workspace": workspace, "from_phase": from_phase}, "profile": profile},
        daemon=True
    )
    _task_threads[task_id] = thread  # 删除接口据此等待线程退出
    thread.start()
    return {
        "task_id": task_id,
        "status": "started",
        "from_phase": from_phase,
        "stream_url": f"/api/research/{task_id}/stream",
        "status_url": f"/api/research/{task_id}/status",
    }


@app.get("/api/research/{task_id}/audit")
async def get_task_audit(task_id: str):
    """任务的审计日志：用户输入与操作、检查点、改进循环停止原因、最终稿选择"""
    return {"task_id": task_id, "entries": _store.audit_log(task_id=task_id)}


@app.get("/api/sessions/{session_id}/audit")
async def get_session_audit(session_id: str):
    """会话的审计日志（含该会话上所有重放任务；会话被删除后仍可按完整 ID 查询）"""
    workspace = _find_workspace_or_none(session_id)
    if workspace:
        session_id = os.path.basename(workspace).removeprefix("session_")
    # 没有工作空间的任务（如启动即失败）没有会话 ID，按任务 ID 查
    entries = _store.audit_log(session_id=session_id) or _store.audit_log(task_id=session_id)
    return {"session_id": session_id, "entries": entries}


@app.get("/api/sessions/{session_id}/phase-log")
async def get_session_phase_log(session_id: str):
    """阶段记录（状态、起止时间、失败原因），按任务分组：一个会话可有原任务与多个重放任务；也可传任务 ID"""
    workspace = _find_workspace_or_none(session_id)
    full_id = os.path.basename(workspace).removeprefix("session_") if workspace else session_id
    tasks = _store.session_tasks(session_id=full_id) or _store.session_tasks(task_id=session_id)
    if not tasks and not workspace:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    return {"session_id": full_id, "tasks": _sessions.with_phase_keys(tasks)}


@app.get("/api/sessions/{session_id}/ledger")
async def get_session_ledger(session_id: str):
    """会话的声明台账视图：计数与矛盾裁决（双方声明、来源、理由与证据）"""
    return {"session_id": session_id, **Ledger.load(_find_workspace(session_id)).view()}


@app.get("/api/sessions/{session_id}/reviews")
def get_session_reviews(session_id: str):
    """每轮评审（卷宗「过程」页）：7 维评分、平均分、优点、关键问题、下一版要改的点"""
    return {"session_id": session_id, "reviews": _sessions.read_reviews(_find_workspace(session_id))}


def _read_session_question(workspace: str) -> str:
    try:
        with open(os.path.join(workspace, "00_session.json"), encoding="utf-8") as f:
            return json.load(f).get("question", "")
    except (OSError, ValueError):
        return ""


def _find_workspace(session_id: str) -> str:
    """按 session_id 查找工作空间路径，不存在则抛出 404"""
    ws = _find_workspace_or_none(session_id)
    if not ws:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    return ws


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    """删除指定会话及其工作空间目录；会话上仍在运行的任务先停止"""
    workspace = _find_workspace(session_id)
    if not os.path.isdir(workspace):
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    full_id = os.path.basename(workspace).removeprefix("session_")
    running = [t["task_id"] for t in _store.session_tasks(session_id=full_id) if t["task_id"] in _task_threads]
    for tid in running:
        _signal_stop(tid)
    _wait_for_threads(running)
    _remove_workspace(workspace, ignore_errors=False)
    return {"status": "deleted", "session_id": session_id}


@app.get("/api/config")
async def get_config():
    """获取当前系统配置"""
    from config import DEFAULT_DEPTH, DEPTH_PRESETS, QUALITY_THRESHOLD
    profile = default_profile()
    return {
        "model": profile.core,        # 兼容旧字段
        "provider": profile.provider,
        "core_model": profile.core,
        "support_model": profile.support,
        "default_depth": DEFAULT_DEPTH,
        "depth_presets": DEPTH_PRESETS,
        "quality_threshold": QUALITY_THRESHOLD,
        "max_concurrent_tasks": MAX_CONCURRENT_TASKS,
    }


@app.post("/api/config")
async def update_config(request: ConfigRequest):
    """
    更新系统配置（运行时生效）
    注意：重启后恢复默认值，如需持久化请修改 .env 文件；设置页保存了默认配置档（/api/settings）时以后者为准
    """
    import config

    changes: dict[str, str | float] = {}

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
    profile = resolve_profile(request.provider, request.core_model, request.support_model)
    try:
        from agents.clarifier import ClarifierAgent
        agent = ClarifierAgent(profile)
        # 模型调用是同步的（内部 asyncio.run），放到线程里跑：不能在事件循环里直接调，也别卡住其他请求与 SSE
        result = await asyncio.to_thread(agent.start, request.question.strip())
        clarify_id = str(uuid.uuid4())[:8]
        _clarify_sessions[clarify_id] = {
            "clarify_id": clarify_id,
            "profile": profile,
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
        raise HTTPException(status_code=500, detail=f"澄清智能体启动失败：{str(e)}") from e


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
        agent = ClarifierAgent(session.get("profile"))
        result = await asyncio.to_thread(agent.reply, session["history"], request.message.strip())
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
        raise HTTPException(status_code=500, detail=f"澄清对话失败：{str(e)}") from e


@app.post("/api/clarify/{clarify_id}/confirm")
async def confirm_clarify(clarify_id: str, request: ClarifyConfirmRequest):
    """用户确认研究需求，启动正式研究任务"""
    session = _clarify_sessions.get(clarify_id)
    if not session:
        raise HTTPException(status_code=404, detail="澄清会话不存在")

    # 用用户编辑后的摘要（若有）覆盖
    summary = request.summary or session["summary"]

    # 将摘要拼装成补充说明与意图元数据，传给 orchestrator
    from agents.clarifier import summary_to_brief
    clarification_text, intent_meta = summary_to_brief(summary, request.extra_note, (request.goal or "").strip())
    question = (request.question or "").strip() or session["question"]  # 委托台改过的研究问题优先

    profile = resolve_profile(request.provider, request.core_model, request.support_model)

    task_id = str(uuid.uuid4())[:8]
    if _store.reserve(task_id, question, MAX_CONCURRENT_TASKS, scores=[], current_cycle=0,
                          clarify_id=clarify_id, summary=summary, intent_meta=intent_meta,
                          depth=request.depth, language=request.language, **_profile_fields(profile)):
        raise HTTPException(
            status_code=429,
            detail=f"当前已有 {_store.active_count()} 个任务在运行，请等待完成后再提交。"
        )
    _store.audit(task_id, "task_created", {
        "source": "clarify", "question": question, "clarify_history": session["history"],
        "summary": summary, "summary_edited": request.summary is not None, "extra_note": request.extra_note,
        "goal": request.goal,
        "min_cycles": request.min_cycles, "max_cycles": request.max_cycles, "depth": request.depth,
        "language": request.language, "ask_loop": request.ask_loop, **_profile_fields(profile),
        "resolved_params": resolve_params(request.depth, request.language, request.min_cycles, request.max_cycles,
                                          profile=profile, ask_loop=request.ask_loop),
    })
    _events.create(task_id)
    pause_ev = threading.Event()
    pause_ev.set()
    _task_pause_events[task_id] = pause_ev
    stop_ev = threading.Event()
    _task_stop_events[task_id] = stop_ev

    thread = threading.Thread(
        target=_run_research_task,
        args=(task_id, question, clarification_text, None, intent_meta),
        kwargs={"min_cycles": request.min_cycles, "max_cycles": request.max_cycles, "depth": request.depth,
                "language": request.language, "ask_loop": request.ask_loop, "profile": profile},
        daemon=True
    )
    _task_threads[task_id] = thread  # 删除接口据此等待线程退出
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
        "active_tasks": _events.active_count(),
        "current_date": config.CURRENT_DATE_STR,
    }


@app.get("/api/models")
async def list_models():
    """能力表（llm/models.py）里的模型，按提供方分组"""
    return {"models": models_by_provider()}


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    """SPA catch-all：static/ 下存在的文件（构建产物 /assets/*、/logo.png 等）原样返回，其余返回 index.html"""
    root = os.path.realpath(STATIC_DIR)
    candidate = os.path.realpath(os.path.join(root, full_path))
    if candidate.startswith(root + os.sep) and os.path.isfile(candidate) \
            and os.path.basename(candidate) != "index.html":
        return FileResponse(candidate)
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return security.index_response(index_file)
    return JSONResponse({"error": "前端尚未构建"}, status_code=404)
