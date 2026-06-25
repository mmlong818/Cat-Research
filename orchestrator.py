"""
ResearchOrchestrator - 研究协调器
统一协调所有智能体的工作，管理完整的研究流程
实现多智能体协作、文件通信和5+轮质量改进循环
包含来源验证、事实核查、结论验证等质量保障流程
"""
import os
import sys
import json
import time
import threading
import subprocess
import tempfile
from datetime import datetime
from typing import Optional, Callable

# Windows GBK 控制台 emoji 兼容：仅非 frozen / 未被 launcher 重定向时包装
import io as _io
if not getattr(sys, 'frozen', False) and not getattr(sys, '_cat_logging_configured', False):
    try:
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
        if hasattr(sys.stderr, 'buffer'):
            sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except Exception:
        pass

import config as _config
from config import (
    ORCHESTRATOR_MODEL,
    MAX_IMPROVEMENT_CYCLES, MIN_IMPROVEMENT_CYCLES,
    QUALITY_THRESHOLD, WORKSPACE_DIR, SEPARATOR,
    USE_SUBPROCESS, SUBPROCESS_AGENTS
)
from tools.file_tools import read_file, write_file, write_json, read_json, append_to_log
from tools.verification_registry import load_registry, save_registry, add_executed_query
from agents.planner import PlannerAgent
from agents.researcher import ResearcherAgent
from agents.analyst import AnalystAgent
from agents.writer import WriterAgent
from agents.critic import CriticAgent
from agents.source_verifier import SourceVerifierAgent
from agents.fact_checker import FactCheckerAgent
from agents.conclusion_validator import ConclusionValidatorAgent


class ResearchOrchestrator:
    """
    多智能体研究系统主协调器

    工作流程：
    1. 用户确认问题 → 创建工作空间
    2. 规划智能体创建研究计划
    3. 研究智能体执行网络搜索和内容收集
    3.5 来源验证（SourceVerifier）
    4. 分析智能体综合分析研究结果
    5. 写作智能体创建初始报告
    5.5 事实核查（FactChecker，仅一次）
    6. 改进循环（最少5次）：
       6.0 评审
       6.1 补充研究
       6.2 结论验证（ConclusionValidator）
       6.3 改进写作
    7. 生成置信度报告
    8. 输出最终报告
    """

    def __init__(self, progress_callback: Optional[Callable] = None):
        self.workspace = None
        self.session_id = None
        self.log_file = None
        self.progress_callback = progress_callback  # API 模式下的进度回调
        self._user_messages = []          # 用户中途注入的消息列表
        self._pause_event = None          # threading.Event，None=不暂停，clear=暂停中
        self._stop_event = None           # threading.Event，set=立即停止
        self._token_usage = {}            # 各 Agent token 累计 {agent_name: {input, output}}

        # 初始化所有智能体
        print("\n🔧 正在初始化智能体...", flush=True)
        self.planner = PlannerAgent()
        self.researcher = ResearcherAgent()
        self.analyst = AnalystAgent()
        self.writer = WriterAgent()
        self.critic = CriticAgent()
        self.source_verifier = SourceVerifierAgent()
        self.fact_checker = FactCheckerAgent()
        self.conclusion_validator = ConclusionValidatorAgent()
        print("✅ 所有智能体已就绪（含验证智能体）", flush=True)

        # 注入流式回调（API 模式下实时推送 LLM 输出）
        if self.progress_callback:
            for agent in [self.planner, self.researcher, self.analyst, self.writer,
                          self.critic, self.source_verifier, self.fact_checker,
                          self.conclusion_validator]:
                agent.stream_callback = self._emit

    def _emit(self, event_type: str, data: dict):
        """发送进度事件（API模式）"""
        if event_type == "token_usage":
            agent = data.get("agent", "unknown")
            if agent not in self._token_usage:
                self._token_usage[agent] = {"input": 0, "output": 0}
            self._token_usage[agent]["input"] += data.get("total_input", 0)
            self._token_usage[agent]["output"] += data.get("total_output", 0)
        if self.progress_callback:
            self.progress_callback(event_type, data)

    def _run_in_subprocess(self, agent_type: str, method: str, workspace: str,
                           method_kwargs: dict, phase_name: str,
                           timeout: int = 900) -> dict:
        """
        在独立子进程中运行智能体方法。
        通过文件系统与子进程通信：task-file / events-file / result-file。
        返回 result-file 中的结果字典，失败时返回 {"status": "error", "error": "..."}。
        """
        # 所有临时文件以 _subprocess_ 前缀命名，存放在 workspace 目录
        prefix = os.path.join(workspace, f"_subprocess_{agent_type}_{int(time.time())}_")
        task_file = prefix + "task.json"
        events_file = prefix + "events.jsonl"
        result_file = prefix + "result.json"

        # 子进程运行器路径
        subprocess_runner_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "agents", "subprocess_runner.py"
        )

        try:
            # ── 写入 task-file ──
            task_data = {
                "agent_type": agent_type,
                "method": method,
                "workspace": workspace,
                "method_kwargs": method_kwargs,
                "stream": True
            }
            with open(task_file, 'w', encoding='utf-8') as f:
                json.dump(task_data, f, ensure_ascii=False, indent=2)

            # 预创建 events-file（避免监控线程读取时文件不存在）
            open(events_file, 'w', encoding='utf-8').close()

            # ── 启动子进程 ──
            proc = subprocess.Popen(
                [sys.executable, subprocess_runner_path,
                 "--task-file", task_file,
                 "--events-file", events_file,
                 "--result-file", result_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding='utf-8',
                errors='replace'
            )

            print(f"  [子进程] {phase_name} 已启动（PID={proc.pid}）", flush=True)

            # ── 事件监控线程（daemon）──
            # 使用行计数器避免重复读取已处理的行
            _monitor_stop = threading.Event()

            def _monitor_events():
                line_offset = 0
                while not _monitor_stop.is_set():
                    try:
                        with open(events_file, 'r', encoding='utf-8', errors='replace') as ef:
                            lines = ef.readlines()
                        new_lines = lines[line_offset:]
                        for raw in new_lines:
                            raw = raw.strip()
                            if not raw:
                                continue
                            try:
                                evt = json.loads(raw)
                                evt_type = evt.get("type", "")
                                evt_data = evt.get("data", {})
                                # 跳过 token_usage（子进程独立计数）
                                if evt_type != "token_usage":
                                    self._emit(evt_type, evt_data)
                            except Exception:
                                pass
                        line_offset += len(new_lines)
                    except Exception:
                        pass
                    time.sleep(0.3)

                # 子进程结束后，再读一次剩余事件（最多等待 2 秒）
                deadline = time.time() + 2.0
                last_offset = line_offset
                while time.time() < deadline:
                    try:
                        with open(events_file, 'r', encoding='utf-8', errors='replace') as ef:
                            lines = ef.readlines()
                        new_lines = lines[last_offset:]
                        for raw in new_lines:
                            raw = raw.strip()
                            if not raw:
                                continue
                            try:
                                evt = json.loads(raw)
                                evt_type = evt.get("type", "")
                                evt_data = evt.get("data", {})
                                if evt_type != "token_usage":
                                    self._emit(evt_type, evt_data)
                            except Exception:
                                pass
                        last_offset += len(new_lines)
                        if not new_lines:
                            break
                    except Exception:
                        break
                    time.sleep(0.2)

            monitor_thread = threading.Thread(target=_monitor_events, daemon=True)
            monitor_thread.start()

            # ── 等待子进程完成（带超时）──
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                print(f"  [子进程] {phase_name} 超时（{timeout}s），发送终止信号", flush=True)
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                _monitor_stop.set()
                return {"status": "error", "error": f"子进程超时（{timeout}s）"}

            # ── 停止监控线程 ──
            _monitor_stop.set()
            monitor_thread.join(timeout=5)

            # 打印子进程 stderr（调试信息）
            stderr_out = proc.stderr.read() if proc.stderr else ""
            if stderr_out and stderr_out.strip():
                print(f"  [子进程 stderr] {stderr_out[:500]}", flush=True)

            # ── 读取 result-file ──
            if not os.path.exists(result_file):
                return {"status": "error", "error": "result-file 不存在"}

            with open(result_file, 'r', encoding='utf-8') as f:
                result = json.load(f)

            if result.get("status") != "ok":
                print(f"  [子进程] {phase_name} 执行出错: {result.get('error', '未知错误')[:200]}", flush=True)

            return result

        finally:
            # 清理临时文件
            for tmp in (task_file, events_file, result_file):
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except Exception:
                    pass

    def _checkpoint(self, phase_name: str) -> Optional[str]:
        """
        阶段间检查点：
        1. 若已暂停，发送暂停事件并阻塞等待恢复（最多等30分钟）
        2. 若有待处理的用户消息，发送确认事件并返回合并后的附加指令
        """
        import threading

        # ── 停止检查（最高优先级）──
        if self._stop_event and self._stop_event.is_set():
            print(f"\n🛑 收到停止信号（阶段：{phase_name}），立即终止", flush=True)
            return None

        # ── 暂停处理 ──
        if self._pause_event is not None and not self._pause_event.is_set():
            self._emit("paused", {"phase": phase_name})
            print(f"\n⏸️  任务已暂停（阶段：{phase_name}），等待恢复...", flush=True)
            self._pause_event.wait(timeout=1800)  # 最多等30分钟
            if not self._pause_event.is_set():
                # 超时仍未恢复，当作停止
                return None
            self._emit("resumed", {"phase": phase_name})
            print(f"\n▶️  任务已恢复（阶段：{phase_name}）", flush=True)

        # ── 用户消息处理 ──
        if not self._user_messages:
            return ""
        msgs = self._user_messages[:]
        self._user_messages.clear()
        combined = "\n\n".join(f"【用户补充指令 {i+1}】{m}" for i, m in enumerate(msgs))
        self._emit("user_message_ack", {"messages": msgs, "phase": phase_name})
        print(f"\n💬 接收到用户指令（阶段 {phase_name}）：{combined[:100]}", flush=True)
        self._log(f"用户指令注入 at {phase_name}: {combined[:200]}")
        return combined

    def _create_workspace(self, question: str) -> str:
        """创建本次研究的工作空间"""
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        workspace = os.path.join(WORKSPACE_DIR, f"session_{self.session_id}")

        # 创建目录结构
        for subdir in ["02_plan", "04_research", "04_clarification", "05_analysis",
                       "06_drafts", "07_reviews", "08_verification", "08_messages"]:
            os.makedirs(os.path.join(workspace, subdir), exist_ok=True)

        # 保存会话元数据
        session_meta = {
            "session_id": self.session_id,
            "created_at": datetime.now().isoformat(),
            "question": question,
            "status": "initialized",
            "model": ORCHESTRATOR_MODEL
        }
        write_json(os.path.join(workspace, "00_session.json"), session_meta)
        write_file(os.path.join(workspace, "01_question.txt"), question)

        self.log_file = os.path.join(workspace, "research_log.txt")
        append_to_log(self.log_file, f"研究会话启动: {question}")

        print(f"\n📁 工作空间: {workspace}", flush=True)
        return workspace

    def _log(self, message: str):
        """记录日志"""
        if self.log_file:
            append_to_log(self.log_file, message)

    def _update_status(self, status: str, extra: dict = None):
        """更新会话状态"""
        if not self.workspace:
            return
        meta_file = os.path.join(self.workspace, "00_session.json")
        meta = read_json(meta_file) if os.path.exists(meta_file) else {}
        meta["status"] = status
        meta["last_updated"] = datetime.now().isoformat()
        if extra:
            meta.update(extra)
        write_json(meta_file, meta)
        self._emit("status", {"status": status, **(extra or {})})

    def _ask_clarification(self, question: str) -> str:
        """澄清研究问题（API 模式下已由 ClarifierAgent 完成，直接返回）"""
        clarification_data = {
            "original_question": question,
            "analysis": "",
            "final_question": question
        }
        write_json(
            os.path.join(self.workspace, "04_clarification", "clarification.json"),
            clarification_data
        )
        return question

    def _display_review_summary(self, review: dict, cycle: int):
        """显示评审结果摘要"""
        scores = review.get("scores", {})
        avg = review.get("average_score", 0)

        print(f"\n📊 第 {cycle} 轮评审结果：", flush=True)
        print(f"   平均分：{avg:.1f}/10", flush=True)

        if scores:
            dim_names = {
                "completeness": "完整性",
                "accuracy": "准确性",
                "depth": "分析深度",
                "clarity": "逻辑清晰度",
                "usefulness": "实用价值",
                "sources": "信息来源",
                "simplicity": "简洁性"
            }
            for dim, name in dim_names.items():
                score = scores.get(dim, 0)
                bar = "█" * int(score) + "░" * (10 - int(score))
                print(f"   {name:8s}: {bar} {score:.0f}/10", flush=True)

        issues = review.get("critical_issues", [])
        if issues:
            high_issues = [i for i in issues if i.get("severity") == "high"]
            print(f"   关键问题：{len(issues)} 个（高优先级：{len(high_issues)} 个）", flush=True)

        assessment = review.get("overall_assessment", "")
        if assessment:
            print(f"   总体评价：{assessment[:100]}", flush=True)

        self._emit("review", {"cycle": cycle, "avg_score": avg, "scores": scores})

    def _generate_confidence_report(self, workspace: str,
                                     source_verification: dict,
                                     fact_check: dict,
                                     conclusion_validation: dict) -> str:
        """生成综合置信度报告"""
        verification_dir = os.path.join(workspace, "08_verification")
        report_file = os.path.join(verification_dir, "confidence_report.json")

        # 提取各模块评分
        source_avg = source_verification.get('summary', {}).get('average_score', 50) if source_verification else 50
        source_quality = source_verification.get('summary', {}).get('overall_quality', 'fair') if source_verification else 'fair'
        high_conf_sources = source_verification.get('summary', {}).get('high_confidence_count', 0) if source_verification else 0

        fact_confidence = fact_check.get('overall_confidence', 0.6) if fact_check else 0.6
        claims_checked = fact_check.get('total_claims_checked', 0) if fact_check else 0
        disputed = fact_check.get('disputed_claims', []) if fact_check else []

        conclusion_avg = conclusion_validation.get('average_score', 6.0) if conclusion_validation else 6.0
        conclusion_conf = conclusion_validation.get('conclusion_confidence', 0.6) if conclusion_validation else 0.6
        verdict = conclusion_validation.get('overall_verdict', 'needs_improvement') if conclusion_validation else 'needs_improvement'

        # 加权综合置信度 (来源25% + 事实35% + 结论40%)
        final_confidence = (
            (source_avg / 100) * 0.25 +
            fact_confidence * 0.35 +
            (conclusion_avg / 10) * 0.40
        )

        confidence_report = {
            "generated_at": datetime.now().isoformat(),
            "overall_confidence": round(final_confidence, 3),
            "confidence_level": (
                "high" if final_confidence >= 0.75 else
                "medium" if final_confidence >= 0.55 else
                "low"
            ),
            "breakdown": {
                "source_quality": {
                    "weight": "25%",
                    "score": round(source_avg / 100, 3),
                    "average_domain_score": source_avg,
                    "quality_rating": source_quality,
                    "high_confidence_sources": high_conf_sources
                },
                "fact_accuracy": {
                    "weight": "35%",
                    "score": round(fact_confidence, 3),
                    "claims_checked": claims_checked,
                    "disputed_claims_count": len(disputed)
                },
                "conclusion_validity": {
                    "weight": "40%",
                    "score": round(conclusion_avg / 10, 3),
                    "average_validation_score": conclusion_avg,
                    "overall_verdict": verdict
                }
            },
            "top_sources": source_verification.get('top_sources', []) if source_verification else [],
            "disputed_claims": disputed[:5],
            "gaps": conclusion_validation.get('gaps', []) if conclusion_validation else [],
            "recommended_improvements": conclusion_validation.get('improvement_instructions', '') if conclusion_validation else ''
        }

        write_json(report_file, confidence_report)
        self._emit("confidence_report", confidence_report)
        return report_file

    def run(self, question: str, research_strategy: Optional[str] = None,
            intent_meta: Optional[dict] = None,
            pause_event=None, stop_event=None):
        """执行完整的研究流程"""
        import threading
        self._pause_event = pause_event  # 由外部注入（app.py 传入 threading.Event）
        self._stop_event = stop_event    # 由外部注入，set() 时立即停止

        # 把 stop_event 注入所有 agent，让它们在每轮 LLM 调用前检查
        for agent in [self.planner, self.researcher, self.analyst, self.writer,
                      self.critic, self.source_verifier, self.fact_checker,
                      self.conclusion_validator]:
            agent.stop_event = stop_event

        print(f"\n{'='*70}", flush=True)
        print("🚀 多智能体研究系统启动（含质量验证流程）", flush=True)
        print(f"{'='*70}", flush=True)

        # === 解析意图元数据，动态调整研究参数 ===
        _intent_type = "info_seeking"
        _dimensions = {"urgency": 0.5, "specificity": 0.5, "complexity": 0.5}
        if intent_meta:
            _intent_type = intent_meta.get("intent_type", _intent_type)
            _dimensions = intent_meta.get("dimensions", _dimensions)

        # 根据复杂度动态调整最小改进轮数
        _complexity = float(_dimensions.get("complexity", 0.5))
        if _complexity >= 0.75:
            _min_cycles = min(MAX_IMPROVEMENT_CYCLES, MIN_IMPROVEMENT_CYCLES + 2)
        elif _complexity <= 0.35:
            _min_cycles = max(2, MIN_IMPROVEMENT_CYCLES - 2)
        else:
            _min_cycles = MIN_IMPROVEMENT_CYCLES

        if intent_meta:
            print(f"[info] Research base date: {_config.CURRENT_DATE_STR}", flush=True)

        # 意图类型 → 规划策略提示
        _INTENT_STRATEGY_HINT = {
            "info_seeking":    "综合信息汇总，注重广度和来源多样性，覆盖主流观点与最新动态",
            "problem_solving": "聚焦问题根因与解决路径，注重深度分析，优先找到可执行的答案",
            "exploration":     "开放式探索，鼓励发现新方向与潜在机会，不限于已知框架",
            "optimization":    "多方案横向对比评估，注重客观数据与实测结果，找出最优选择",
            "task_completion": "产出结构化、可直接使用的成果，注重实用性和完整性",
        }
        _intent_hint = _INTENT_STRATEGY_HINT.get(_intent_type, "")
        if _intent_hint and research_strategy:
            research_strategy = f"{research_strategy}\n研究策略偏向：{_intent_hint}"
        elif _intent_hint:
            research_strategy = f"研究策略偏向：{_intent_hint}"

        if intent_meta:
            print(f"🎯 意图类型: {_intent_type} | 复杂度: {_complexity:.1f} | 最小改进轮数: {_min_cycles}", flush=True)

        # === 阶段 0：初始化 ===
        self.workspace = self._create_workspace(question)

        # === 阶段 1：意图澄清 ===
        print(f"\n{'='*70}", flush=True)
        print("📝 阶段 1/8：意图识别与澄清", flush=True)
        print(f"{'='*70}", flush=True)
        self._update_status("clarifying")
        self._emit("phase", {"phase": 1, "name": "问题澄清"})
        clarified_question = self._ask_clarification(question)
        print(f"\n✅ 研究方向确认", flush=True)
        self._log(f"研究方向确认: {clarified_question[:200]}")

        extra = self._checkpoint("阶段1→2")
        if extra is None: return "任务已中断"
        if extra: clarified_question += f"\n\n{extra}"

        # === 阶段 2：研究规划 ===
        print(f"\n{'='*70}", flush=True)
        print("📋 阶段 2/8：研究规划", flush=True)
        print(f"{'='*70}", flush=True)
        self._update_status("planning")
        self._emit("phase", {"phase": 2, "name": "研究规划"})

        if USE_SUBPROCESS and "planner" in SUBPROCESS_AGENTS:
            self._run_in_subprocess(
                "planner", "create_plan", self.workspace,
                {"clarified_question": clarified_question,
                 "research_strategy": research_strategy},
                phase_name="研究规划"
            )
            # 子进程已将 plan 写入文件，从文件读取
            plan_file = os.path.join(self.workspace, "03_plan.json")
            if os.path.exists(plan_file):
                with open(plan_file, 'r', encoding='utf-8') as _pf:
                    plan = json.load(_pf)
            else:
                plan = {}
        else:
            plan = self.planner.create_plan(self.workspace, clarified_question, research_strategy=research_strategy)
        queries_count = len(plan.get("search_queries", []))
        aspects_count = len(plan.get("key_aspects", []))
        print(f"\n✅ 研究计划完成：{aspects_count} 个研究维度，{queries_count} 个搜索查询", flush=True)
        self._log(f"研究计划创建完成，{queries_count} 个搜索查询")
        # 推送计划事件（供前端展示）
        self._emit("plan", {
            "objective": plan.get("objective", ""),
            "domain": plan.get("domain", ""),
            "key_aspects": plan.get("key_aspects", []),
            "search_queries": plan.get("search_queries", []),
            "expected_output": plan.get("expected_output", ""),
            "depth_requirement": plan.get("depth_requirement", ""),
            "total_queries": queries_count
        })

        extra = self._checkpoint("阶段2→3")
        if extra is None: return "任务已中断"
        if extra and isinstance(plan, dict):
            plan.setdefault("user_directives", []).append(extra)

        # === 阶段 3：网络研究 ===
        print(f"\n{'='*70}", flush=True)
        print("🔍 阶段 3/8：网络研究", flush=True)
        print(f"{'='*70}", flush=True)
        self._update_status("researching")
        self._emit("phase", {"phase": 3, "name": "网络研究"})

        if USE_SUBPROCESS and "researcher" in SUBPROCESS_AGENTS:
            self._run_in_subprocess(
                "researcher", "research", self.workspace,
                {"plan": plan, "round_num": 1},
                phase_name="网络研究（第1轮）"
            )
            research_file = os.path.join(self.workspace, "04_research", "research_round_1.json")
        else:
            research_file = self.researcher.research(self.workspace, plan, round_num=1)
        print(f"\n✅ 第1轮研究完成", flush=True)
        self._log("第1轮研究完成")

        # === 快速失败门：检查研究内容质量 ===
        research_dir = os.path.join(self.workspace, "04_research")
        total_content_size = sum(
            os.path.getsize(os.path.join(research_dir, f))
            for f in os.listdir(research_dir)
            if os.path.isfile(os.path.join(research_dir, f))
        ) if os.path.isdir(research_dir) else 0

        if total_content_size < 1000:
            print(f"\n⚠️  快速失败检测：研究内容不足（{total_content_size} 字节），触发重试...", flush=True)
            self._log(f"研究内容不足（{total_content_size} 字节），触发重试")
            for retry in range(2):
                self.researcher.research(self.workspace, plan, round_num=2 + retry,
                                         additional_queries=[clarified_question])
                total_content_size = sum(
                    os.path.getsize(os.path.join(research_dir, f))
                    for f in os.listdir(research_dir)
                    if os.path.isfile(os.path.join(research_dir, f))
                ) if os.path.isdir(research_dir) else 0
                print(f"   重试 {retry + 1}/2：当前内容 {total_content_size} 字节", flush=True)
                if total_content_size >= 1000:
                    break
            if total_content_size < 1000:
                print(f"  [警告] 重试后内容仍不足，继续后续流程", flush=True)
            else:
                print(f"✅ 快速失败修复成功，内容已充足", flush=True)

        # === 阶段 3.5：来源验证 ===
        print(f"\n{'='*70}", flush=True)
        print("🔎 阶段 3.5/8：来源可信度验证", flush=True)
        print(f"{'='*70}", flush=True)
        self._update_status("verifying_sources")
        self._emit("phase", {"phase": 3.5, "name": "来源验证"})

        source_verification, sv_file = self.source_verifier.verify_sources(self.workspace)
        sv_summary = source_verification.get('summary', {})
        print(f"\n✅ 来源验证完成：{source_verification.get('total_sources', 0)} 个来源", flush=True)
        print(f"   高可信: {sv_summary.get('high_confidence_count', 0)}  "
              f"中等: {sv_summary.get('medium_confidence_count', 0)}  "
              f"低可信: {sv_summary.get('low_confidence_count', 0)}", flush=True)
        print(f"   整体质量: {sv_summary.get('overall_quality', 'N/A')}  "
              f"平均分: {sv_summary.get('average_score', 0):.1f}/100", flush=True)
        self._log(f"来源验证完成，整体质量: {sv_summary.get('overall_quality')}")

        # 如果来源质量差，触发补充研究
        if sv_summary.get('overall_quality') in ('poor', 'fair'):
            print(f"\n⚠️  来源质量不佳，触发补充研究...", flush=True)
            unreliable = source_verification.get('unreliable_sources', [])
            self.researcher.research(
                self.workspace, plan, round_num=2,
                additional_queries=[f"权威来源 {clarified_question[:40]}"]
            )
            self._log("来源质量不佳，已触发补充研究")

        extra = self._checkpoint("阶段3→4")
        if extra is None: return "任务已中断"

        # === 阶段 4：分析综合 ===
        print(f"\n{'='*70}", flush=True)
        print("🧐 阶段 4/8：分析综合", flush=True)
        print(f"{'='*70}", flush=True)
        self._update_status("analyzing")
        self._emit("phase", {"phase": 4, "name": "分析综合"})

        if USE_SUBPROCESS and "analyst" in SUBPROCESS_AGENTS:
            self._run_in_subprocess(
                "analyst", "analyze", self.workspace,
                {"question": clarified_question},
                phase_name="分析综合"
            )
            analysis_file = os.path.join(self.workspace, "05_analysis.md")
        else:
            analysis_file = self.analyst.analyze(self.workspace, clarified_question)
        print(f"\n✅ 分析完成", flush=True)
        self._log("分析综合完成")

        extra = self._checkpoint("阶段4→5")
        if extra is None: return "任务已中断"

        # === 阶段 5：初稿写作 ===
        print(f"\n{'='*70}", flush=True)
        print("✍️  阶段 5/8：初稿写作", flush=True)
        print(f"{'='*70}", flush=True)
        self._update_status("writing")
        self._emit("phase", {"phase": 5, "name": "初稿写作"})

        if USE_SUBPROCESS and "writer" in SUBPROCESS_AGENTS:
            self._run_in_subprocess(
                "writer", "write_draft", self.workspace,
                {"question": clarified_question, "draft_num": 0},
                phase_name="初稿写作"
            )
            draft_file = os.path.join(self.workspace, "06_drafts", "draft_0.md")
        else:
            draft_file = self.writer.write_draft(self.workspace, clarified_question, draft_num=0)
        print(f"\n✅ 初稿完成", flush=True)
        self._log("初稿写作完成")

        # === 阶段 6：质量改进循环（最少5次）===
        print(f"\n{'='*70}", flush=True)
        print(f"🔄 阶段 6/8：质量评审与改进循环（最少 {_min_cycles} 次）", flush=True)
        print(f"{'='*70}", flush=True)
        self._update_status("improving")
        self._emit("phase", {"phase": 6, "name": "评审优化"})

        current_draft = 0
        best_draft_num = 0
        best_score = 0.0
        all_scores = []
        completed_cycles = 0
        latest_fact_check = None
        latest_conclusion_validation = None

        # === 事实核查（仅执行一次，分析文件在循环中不会改变）===
        print(f"\n{'='*70}", flush=True)
        print("🔬 事实核查（一次性，分析文件不变则结果复用）", flush=True)
        print(f"{'='*70}", flush=True)
        registry = load_registry(self.workspace)  # 加载注册表
        try:
            latest_fact_check, fc_file = self.fact_checker.check_facts(
                self.workspace, analysis_file, registry=registry, cycle=0
            )
            save_registry(self.workspace, registry)  # 保存已核查的声明
            fc_conf = latest_fact_check.get('overall_confidence', 0.6)
            fc_claimed = latest_fact_check.get('total_claims_checked', 0)
            print(f"✅ 事实核查完成：核查 {fc_claimed} 个声明，置信度: {fc_conf:.0%}", flush=True)
            self._log(f"事实核查完成（一次性），置信度: {fc_conf:.0%}")
        except Exception as e:
            print(f"  [警告] 事实核查出错: {str(e)[:80]}", flush=True)
            latest_fact_check = None
            registry = load_registry(self.workspace)

        for cycle in range(1, MAX_IMPROVEMENT_CYCLES + 1):
            print(f"\n{'─'*70}", flush=True)
            print(f"🔄 第 {cycle}/{MAX_IMPROVEMENT_CYCLES} 轮 改进循环", flush=True)
            print(f"{'─'*70}", flush=True)
            self._log(f"开始第 {cycle} 轮改进")
            self._emit("cycle_start", {"cycle": cycle, "max": MAX_IMPROVEMENT_CYCLES})

            extra = self._checkpoint(f"改进循环第{cycle}轮")
            if extra is None: return "任务已中断"

            # 步骤 6.0：评审当前草稿
            print(f"\n📋 步骤 {cycle}.0：评审草稿（第 {current_draft} 版）", flush=True)
            draft_to_review = os.path.join(self.workspace, "06_drafts", f"draft_{current_draft}.md")
            if not os.path.exists(draft_to_review):
                print(f"  [警告] 草稿文件不存在，跳过本轮", flush=True)
                continue

            review, review_file = self.critic.review(self.workspace, current_draft, cycle)
            avg_score = review.get("average_score", 0)
            all_scores.append(avg_score)
            completed_cycles += 1
            self._display_review_summary(review, cycle)
            self._log(f"第 {cycle} 轮评审完成，平均分: {avg_score:.1f}")

            # 棘轮机制：记录最优草稿，分数回退时从最优基础改进
            if avg_score >= best_score:
                best_score = avg_score
                best_draft_num = current_draft
                print(f"   ⭐ 新最优草稿: 第 {best_draft_num} 版（分数 {best_score:.1f}）", flush=True)
            else:
                print(f"   ↩️  分数回退（{avg_score:.1f} < 最优 {best_score:.1f}），回溯到第 {best_draft_num} 版继续改进", flush=True)
                self._log(f"分数回退，回溯到最优版本 #{best_draft_num}")
                current_draft = best_draft_num

            # 步骤 6.1：补充研究（仅前3轮，且有需要时）
            additional_research = review.get("additional_research_needed", [])
            if additional_research and cycle <= 3:
                print(f"\n🔍 步骤 {cycle}.1：补充研究（{len(additional_research)} 个话题）", flush=True)
                self._log(f"补充研究: {additional_research}")
                self.researcher.research(
                    self.workspace, plan,
                    round_num=cycle + 2,
                    additional_queries=additional_research
                )
                # 将本次额外查询写入注册表
                for q in additional_research:
                    add_executed_query(registry, q if isinstance(q, str) else q.get('query', ''))
                save_registry(self.workspace, registry)
                print(f"✅ 补充研究完成", flush=True)
            else:
                print(f"\n✅ 步骤 {cycle}.1：无需补充研究", flush=True)

            # 步骤 6.2：结论验证
            print(f"\n🔬 步骤 {cycle}.2：结论验证", flush=True)
            try:
                latest_conclusion_validation, cv_file = self.conclusion_validator.validate_conclusions(
                    self.workspace,
                    draft_file=draft_to_review,
                    source_verification=source_verification,
                    fact_check=latest_fact_check,
                    registry=registry,
                    cycle=cycle
                )
                save_registry(self.workspace, registry)
                cv_verdict = latest_conclusion_validation.get('overall_verdict', 'needs_improvement')
                cv_conf = latest_conclusion_validation.get('conclusion_confidence', 0.6)
                print(f"   验证结果: {cv_verdict}  综合置信度: {cv_conf:.0%}", flush=True)
                self._log(f"结论验证完成: {cv_verdict}，置信度: {cv_conf:.0%}")
            except Exception as e:
                print(f"  [警告] 结论验证出错: {str(e)[:80]}", flush=True)
                latest_conclusion_validation = None

            # 步骤 6.3：改进写作
            new_draft_num = current_draft + 1
            print(f"\n✍️  步骤 {cycle}.3：改进报告（生成第 {new_draft_num} 版）", flush=True)
            if USE_SUBPROCESS and "writer" in SUBPROCESS_AGENTS:
                self._run_in_subprocess(
                    "writer", "write_draft", self.workspace,
                    {"question": clarified_question,
                     "draft_num": new_draft_num,
                     "review_file": review_file},
                    phase_name=f"改进写作（第{new_draft_num}版）"
                )
                new_draft_file = os.path.join(self.workspace, "06_drafts", f"draft_{new_draft_num}.md")
            else:
                new_draft_file = self.writer.write_draft(
                    self.workspace,
                    clarified_question,
                    draft_num=new_draft_num,
                    review_file=review_file
                )

            if os.path.exists(new_draft_file) and os.path.getsize(new_draft_file) > 100:
                current_draft = new_draft_num
                print(f"✅ 第 {current_draft} 版草稿完成（{os.path.getsize(new_draft_file):,} 字节）", flush=True)
                self._log(f"第 {current_draft} 版草稿完成")
            else:
                print(f"  [警告] 第 {new_draft_num} 版草稿生成失败，保持当前版本", flush=True)

            # 判断是否可以提前结束
            if completed_cycles >= _min_cycles:
                # 综合评估：质量分数 + 结论验证通过
                conclusion_ok = (latest_conclusion_validation is None or
                                 latest_conclusion_validation.get('overall_verdict') == 'pass')
                if avg_score >= QUALITY_THRESHOLD and conclusion_ok:
                    print(f"\n🎉 质量达标！评审 {avg_score:.1f} >= {QUALITY_THRESHOLD}，结论验证通过，提前结束", flush=True)
                    self._log("质量达标，提前结束改进循环")
                    break
                else:
                    print(f"\n📈 继续改进（评审: {avg_score:.1f}/{QUALITY_THRESHOLD}，"
                          f"结论: {latest_conclusion_validation.get('overall_verdict', 'N/A') if latest_conclusion_validation else 'N/A'}）", flush=True)

        # === 阶段 7：生成置信度报告 ===
        print(f"\n{'='*70}", flush=True)
        print("📊 阶段 7/8：生成置信度报告", flush=True)
        print(f"{'='*70}", flush=True)
        self._update_status("confidence_report")
        self._emit("phase", {"phase": 7, "name": "置信度报告"})

        confidence_report_file = self._generate_confidence_report(
            self.workspace,
            source_verification,
            latest_fact_check,
            latest_conclusion_validation
        )
        print(f"✅ 置信度报告生成完成", flush=True)
        self._log("置信度报告生成完成")

        # === 阶段 8：完成 ===
        total_done = len(all_scores)
        final_score = all_scores[-1] if all_scores else 0

        # 推送研究统计（供前端"研究统计"面板显示）
        self._emit("stats", {
            "cycles": total_done,
            "claims_checked": latest_fact_check.get("total_claims_checked", 0) if latest_fact_check else 0,
            "total_sources": source_verification.get("total_sources", 0) if source_verification else 0,
            "final_score": round(final_score, 1),
        })
        final_file = os.path.join(self.workspace, "09_final.md")

        # 将最后一版草稿复制为最终报告
        last_draft = os.path.join(self.workspace, "06_drafts", f"draft_{current_draft}.md")
        if os.path.exists(last_draft):
            content = read_file(last_draft)
            # 附加置信度信息
            conf_data = read_json(confidence_report_file) if os.path.exists(confidence_report_file) else {}
            conf_appendix = f"""

---
## 研究质量报告

| 维度 | 评分 |
|------|------|
| 综合置信度 | {conf_data.get('overall_confidence', 'N/A'):.0%} |
| 来源质量 | {conf_data.get('breakdown', {}).get('source_quality', {}).get('quality_rating', 'N/A')} |
| 事实准确度 | {conf_data.get('breakdown', {}).get('fact_accuracy', {}).get('score', 0):.0%} |
| 结论有效性 | {conf_data.get('breakdown', {}).get('conclusion_validity', {}).get('score', 0):.0%} |
| 改进轮数 | {total_done} 轮 |
| 最终评审分 | {final_score:.1f}/10 |

*本报告由多智能体研究系统自动生成，包含来源验证、事实核查和结论验证流程*
"""
            # 枚举型任务：从事件台账确定性生成完整附录（事件全表 + 投资方汇总），保证报告不丢条目
            try:
                from agents.researcher import build_ledger_appendix
                ledger_appendix = build_ledger_appendix(self.workspace)
            except Exception as _e:
                print(f"  [警告] 生成台账附录失败: {str(_e)[:80]}", flush=True)
                ledger_appendix = ""
            write_file(final_file, content + conf_appendix + ledger_appendix)

        total_input = sum(v["input"] for v in self._token_usage.values())
        total_output = sum(v["output"] for v in self._token_usage.values())
        self._update_status("completed", {
            "total_cycles": total_done,
            "final_score": final_score,
            "score_history": all_scores,
            "final_report": final_file,
            "token_usage": {
                "total_input": total_input,
                "total_output": total_output,
                "total": total_input + total_output,
                "by_agent": self._token_usage,
            }
        })
        self._log(f"研究完成，共 {total_done} 轮改进，最终分: {final_score:.1f}")

        # === 跨会话历史记录 ===
        history_entry = {
            "session_id": self.session_id,
            "timestamp": datetime.now().isoformat(),
            "question": question,
            "research_strategy": research_strategy,
            "final_score": final_score,
            "total_cycles": total_done,
            "score_history": all_scores,
            "best_score": best_score,
            "workspace": self.workspace
        }
        history_file = os.path.join(WORKSPACE_DIR, "research_history.jsonl")
        try:
            with open(history_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(history_entry, ensure_ascii=False) + '\n')
        except Exception as e:
            print(f"  [警告] 历史记录写入失败: {str(e)}", flush=True)

        print(f"\n{'='*70}", flush=True)
        print("🎊 研究完成！", flush=True)
        print(f"{'='*70}", flush=True)
        print(f"📊 质量分数历程: {' → '.join(f'{s:.1f}' for s in all_scores)}", flush=True)
        print(f"📁 工作空间: {self.workspace}", flush=True)
        print(f"📄 最终报告: {final_file}", flush=True)
        print(f"📋 置信度报告: {confidence_report_file}", flush=True)

        if os.path.exists(final_file):
            return read_file(final_file)
        else:
            return f"研究完成，请查看工作空间: {self.workspace}"
