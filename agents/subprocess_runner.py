"""
subprocess_runner.py - 独立子进程运行器
以子进程方式运行任意智能体方法，通过文件系统与父进程通信。

通信机制：
  --task-file   : JSON 文件，包含运行所需的全部参数
  --events-file : JSONL 文件，每行一个事件（父进程实时监控）
  --result-file : JSON 文件，包含运行结果
"""
import argparse
import json
import os
import sys
import time

# 确保项目根目录在 sys.path 中（文件位于 agents/ 子目录下）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Windows GBK 控制台 emoji 兼容
import io as _io
if not getattr(sys, 'frozen', False) and not getattr(sys, '_cat_logging_configured', False):
    try:
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
        if hasattr(sys.stderr, 'buffer'):
            sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 工厂：根据 agent_type 创建智能体实例
# ---------------------------------------------------------------------------
_AGENT_FACTORIES = {
    "planner": lambda: __import__("agents.planner", fromlist=["PlannerAgent"]).PlannerAgent(),
    "researcher": lambda: __import__("agents.researcher", fromlist=["ResearcherAgent"]).ResearcherAgent(),
    "analyst": lambda: __import__("agents.analyst", fromlist=["AnalystAgent"]).AnalystAgent(),
    "writer": lambda: __import__("agents.writer", fromlist=["WriterAgent"]).WriterAgent(),
    "critic": lambda: __import__("agents.critic", fromlist=["CriticAgent"]).CriticAgent(),
    "source_verifier": lambda: __import__("agents.source_verifier", fromlist=["SourceVerifierAgent"]).SourceVerifierAgent(),
    "fact_checker": lambda: __import__("agents.fact_checker", fromlist=["FactCheckerAgent"]).FactCheckerAgent(),
    "conclusion_validator": lambda: __import__("agents.conclusion_validator", fromlist=["ConclusionValidatorAgent"]).ConclusionValidatorAgent(),
}

# 各 agent_type 对应的方法名
_AGENT_METHODS = {
    "planner": "create_plan",
    "researcher": "research",
    "analyst": "analyze",
    "writer": "write_draft",
    "critic": "review",
    "source_verifier": "verify_sources",
    "fact_checker": "check_facts",
    "conclusion_validator": "validate_conclusions",
}


def _make_file_stream_callback(events_file: str):
    """
    创建将事件追加写入 events-file 的 stream_callback。
    每行为独立 JSON，父进程可实时读取。
    """
    def file_stream_callback(event_type: str, data):
        line = json.dumps(
            {"type": event_type, "data": data, "ts": time.time()},
            ensure_ascii=False
        )
        try:
            with open(events_file, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
                f.flush()
        except Exception:
            pass
    return file_stream_callback


def _write_result(result_file: str, status: str, **kwargs):
    """写入 result-file"""
    payload = {"status": status}
    payload.update(kwargs)
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="子进程智能体运行器")
    parser.add_argument("--task-file", required=True, help="任务描述 JSON 文件路径")
    parser.add_argument("--events-file", required=True, help="事件输出 JSONL 文件路径")
    parser.add_argument("--result-file", required=True, help="结果输出 JSON 文件路径")
    args = parser.parse_args()

    task_file = os.path.abspath(args.task_file)
    events_file = os.path.abspath(args.events_file)
    result_file = os.path.abspath(args.result_file)

    # ── 读取任务描述 ──
    try:
        with open(task_file, 'r', encoding='utf-8') as f:
            task = json.load(f)
    except Exception as e:
        _write_result(result_file, "error", error=f"读取 task-file 失败: {str(e)}")
        sys.exit(1)

    agent_type = task.get("agent_type", "")
    method_name = task.get("method", _AGENT_METHODS.get(agent_type, ""))
    workspace = task.get("workspace", "")
    method_kwargs = task.get("method_kwargs", {})
    use_stream = task.get("stream", True)

    # ── 验证参数 ──
    if agent_type not in _AGENT_FACTORIES:
        _write_result(result_file, "error",
                      error=f"不支持的 agent_type: {agent_type}，"
                            f"可选值: {list(_AGENT_FACTORIES.keys())}")
        sys.exit(1)

    # ── 创建智能体实例 ──
    try:
        agent = _AGENT_FACTORIES[agent_type]()
    except Exception as e:
        _write_result(result_file, "error", error=f"创建智能体 {agent_type} 失败: {str(e)}")
        sys.exit(1)

    # ── 注入 stream_callback ──
    if use_stream:
        agent.stream_callback = _make_file_stream_callback(events_file)

    # ── 获取目标方法 ──
    method = getattr(agent, method_name, None)
    if method is None:
        _write_result(result_file, "error",
                      error=f"智能体 {agent_type} 没有方法 {method_name}")
        sys.exit(1)

    # ── 构造调用参数 ──
    # workspace 作为第一个位置参数（如果方法签名需要且 method_kwargs 未包含）
    # 根据各方法签名，workspace 始终是第一个参数
    call_kwargs = {}
    if workspace:
        call_kwargs["workspace"] = workspace
    call_kwargs.update(method_kwargs)

    # ── 执行方法 ──
    try:
        result = method(**call_kwargs)
        # 结果可能是字符串、dict、tuple 等，统一序列化
        if isinstance(result, (dict, list, str, int, float, bool, type(None))):
            serializable_result = result
        else:
            serializable_result = str(result)
        _write_result(result_file, "ok", result=serializable_result)
    except Exception as e:
        import traceback
        _write_result(result_file, "error",
                      error=f"{type(e).__name__}: {str(e)}",
                      traceback=traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
