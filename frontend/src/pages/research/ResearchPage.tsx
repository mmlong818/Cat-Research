import { useState, useEffect, useRef, useCallback } from "react";
import { useLocation } from "wouter";
import { Plus, Trash2, Copy, Check, ChevronDown, ChevronUp, Pause, Play, Download, Zap, Target, RotateCcw, Square } from "lucide-react";
import { setWorkInProgress } from "../../lib/workGuard";
import { decodeNavParam, encodeNavParam } from "../../lib/navData";
import { toast } from "sonner";
import { marked } from "marked";
import { research } from "../../lib/api";
import type { SessionMeta, PipelineStep, LogLine, ConfidenceReport } from "../../lib/types";

// ── Pipeline steps config ──────────────────────────────────────────────────

const STEP_DEFS = [
  { key: "clarify", label: "澄清", emoji: "🔍" },
  { key: "plan", label: "规划", emoji: "📋" },
  { key: "research", label: "研究", emoji: "🌐" },
  { key: "analyze", label: "分析", emoji: "🔬" },
  { key: "write", label: "撰写", emoji: "✍️" },
  { key: "review", label: "评审", emoji: "⭐" },
  { key: "verify", label: "验证", emoji: "✅" },
];

const STATUS_TO_STEP: Record<string, string> = {
  clarifying: "clarify", clarification: "clarify",
  planning: "plan", plan: "plan",
  researching: "research", searching: "research",
  analyzing: "analyze", analysis: "analyze",
  writing: "write", drafting: "write",
  reviewing: "review", improving: "review",
  verifying: "verify", "source_verifying": "verify", fact_checking: "verify",
  completed: "verify",
};

function initSteps(): PipelineStep[] {
  return STEP_DEFS.map((s) => ({ ...s, status: "pending" as const }));
}

function advanceSteps(steps: PipelineStep[], activeKey: string): PipelineStep[] {
  const idx = steps.findIndex((s) => s.key === activeKey);
  if (idx < 0) return steps;
  return steps.map((s, i) => ({
    ...s,
    status: i < idx ? "done" : i === idx ? "active" : "pending",
  }));
}

// ── Sub-components ─────────────────────────────────────────────────────────

function StepPipeline({ steps }: { steps: PipelineStep[] }) {
  return (
    <div style={{ display: "flex", gap: 2, alignItems: "flex-start" }}>
      {steps.map((s, i) => (
        <div key={s.key} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 4, position: "relative", padding: "4px 2px" }}>
          {i < steps.length - 1 && (
            <div style={{
              position: "absolute", right: -2, top: 16, width: 4, height: 2,
              background: s.status === "done" ? "var(--success)" : s.status === "active" ? "var(--accent)" : "var(--border)",
            }} />
          )}
          <div style={{
            width: 30, height: 30, borderRadius: "50%",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 14, border: "2px solid",
            background: s.status === "done" ? "rgba(16,185,129,.1)"
              : s.status === "active" ? "var(--accent)"
              : s.status === "error" ? "rgba(239,68,68,.1)"
              : "var(--surface2)",
            borderColor: s.status === "done" ? "var(--success)"
              : s.status === "active" ? "var(--accent)"
              : s.status === "error" ? "var(--danger)"
              : "var(--border)",
            animation: s.status === "active" ? "pulse 1.6s infinite" : "none",
          }}>
            {s.status === "done" ? "✓" : s.emoji}
          </div>
          <span style={{
            fontSize: 9, fontWeight: 600, color: s.status === "pending" ? "var(--text3)" : "var(--text)",
            whiteSpace: "nowrap",
          }}>{s.label}</span>
          {s.duration && <span style={{ fontSize: 9, color: "var(--text4)", fontFamily: "monospace" }}>{s.duration}s</span>}
        </div>
      ))}
    </div>
  );
}

function LogArea({ lines }: { lines: LogLine[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.scrollTo(0, ref.current.scrollHeight); }, [lines]);
  const colors = { info: "var(--accent)", ok: "var(--success)", warn: "var(--warning)", err: "var(--danger)", dim: "var(--text4)" };
  return (
    <div ref={ref} style={{
      background: "var(--bg)", borderRadius: 8, border: "1px solid var(--border)",
      padding: "8px 12px", height: 120, overflowY: "auto",
      fontSize: 11, fontFamily: "'SF Mono', 'Fira Code', monospace", lineHeight: 1.7, color: "var(--text2)",
    }}>
      {lines.map((l, i) => (
        <div key={i} style={{ color: colors[l.type] }}>{l.text}</div>
      ))}
    </div>
  );
}

function StreamArea({ text, agent, done }: { text: string; agent: string; done: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.scrollTo(0, ref.current.scrollHeight); }, [text]);
  if (!text) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: ".6px", flex: 1 }}>实时输出</span>
        {agent && <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 10, background: "var(--accent-dim)", color: "var(--accent)", border: "1px solid var(--accent-border)" }}>{agent}</span>}
        {done && <span style={{ fontSize: 10, color: "var(--success)", fontWeight: 700 }}>✓ 完成</span>}
      </div>
      <div ref={ref} style={{
        background: "#1a1008", borderRadius: 8, border: "1px solid var(--accent-border)",
        padding: "10px 13px", height: 200, overflowY: "auto",
        fontSize: 12, fontFamily: "'SF Mono', 'Fira Code', monospace",
        lineHeight: 1.75, color: "#c9d1d9", whiteSpace: "pre-wrap", wordBreak: "break-word",
      }}>
        {text}
        {!done && <span style={{ display: "inline-block", width: 7, height: 12, background: "var(--accent)", verticalAlign: "text-bottom", marginLeft: 2, animation: "blink .9s step-end infinite", borderRadius: 1 }} />}
      </div>
    </div>
  );
}

function ConfidenceGauge({ report }: { report: ConfidenceReport }) {
  const pct = report.overall_confidence ?? 0;
  const color = pct >= 75 ? "var(--success)" : pct >= 50 ? "var(--warning)" : "var(--danger)";
  const bars = [
    { label: "来源可靠性", val: report.source_reliability ?? 0 },
    { label: "事实准确性", val: report.fact_accuracy ?? 0 },
    { label: "结论一致性", val: report.conclusion_consistency ?? 0 },
    { label: "证据充分性", val: report.evidence_sufficiency ?? 0 },
  ];
  return (
    <div>
      <div style={{ textAlign: "center", padding: "12px 0 6px" }}>
        <div style={{ fontSize: 36, fontWeight: 800, color }}>{pct}%</div>
        <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 2 }}>综合置信度</div>
      </div>
      <div style={{ marginTop: 12 }}>
        {bars.map((b) => (
          <div key={b.label} style={{ marginBottom: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
              <span style={{ fontSize: 11, color: "var(--text2)" }}>{b.label}</span>
              <span style={{ fontSize: 11, fontWeight: 700, color: "var(--accent)" }}>{b.val}%</span>
            </div>
            <div style={{ height: 5, background: "var(--border)", borderRadius: 3, overflow: "hidden" }}>
              <div style={{ height: "100%", borderRadius: 3, background: `linear-gradient(90deg, var(--accent), var(--accent-hover))`, width: `${b.val}%`, transition: "width 1s" }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function ResearchPage() {
  const [, navigate] = useLocation();
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [question, setQuestion] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    const raw = params.get("q");
    if (raw) { window.history.replaceState({}, "", window.location.pathname); }
    return decodeNavParam("q", raw);
  });
  const [clarification, setClarification] = useState("");
  const [showClarify, setShowClarify] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "running" | "paused" | "completed" | "error">("idle");
  const [steps, setSteps] = useState<PipelineStep[]>(initSteps());
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [streamText, setStreamText] = useState("");
  const [streamAgent, setStreamAgent] = useState("");
  const [streamDone, setStreamDone] = useState(false);
  const [report, setReport] = useState<string | null>(null);
  const [confidence, setConfidence] = useState<ConfidenceReport | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [injectMsg, setInjectMsg] = useState("");
  const [copied, setCopied] = useState(false);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [showReport, setShowReport] = useState(true);

  const esRef = useRef<EventSource | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTsRef = useRef<number>(0);
  const lastStatusRef = useRef<string>("");

  const addLog = useCallback((type: LogLine["type"], text: string) => {
    setLogs((p) => [...p.slice(-200), { type, text }]);
  }, []);

  // Load sessions
  const loadSessions = useCallback(async () => {
    try {
      const s = await research.sessions();
      setSessions(s);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadSessions(); }, [loadSessions]);

  // Sync work-in-progress guard
  useEffect(() => {
    setWorkInProgress(status === "running" || status === "paused");
    return () => setWorkInProgress(false);
  }, [status]);

  // Timer
  useEffect(() => {
    if (status === "running") {
      startTsRef.current = Date.now();
      timerRef.current = setInterval(() => setElapsed(Math.round((Date.now() - startTsRef.current) / 1000)), 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [status]);

  const connectSSE = useCallback((id: string) => {
    if (esRef.current) esRef.current.close();
    const es = research.stream(id);
    esRef.current = es;

    es.onmessage = (e) => {
      try {
        const { type, data } = JSON.parse(e.data);
        switch (type) {
          case "started":
            addLog("info", `▶ 研究任务启动 [${id}]`);
            break;
          case "status": {
            const s = data.status || "";
            if (s !== lastStatusRef.current) {
              lastStatusRef.current = s;
              addLog("info", `◆ ${s}`);
            }
            const stepKey = STATUS_TO_STEP[s.toLowerCase()];
            if (stepKey) setSteps((p) => advanceSteps(p, stepKey));
            break;
          }
          case "stream_start":
            setStreamText("");
            setStreamAgent(data.agent || "");
            setStreamDone(false);
            break;
          case "stream_chunk":
            setStreamText((p) => p + (data.chunk || ""));
            break;
          case "stream_end":
            setStreamDone(true); // Keep text visible, just stop the cursor
            break;
          case "plan":
            addLog("ok", `📋 研究计划生成：${data.total_queries ?? "?"} 个查询`);
            break;
          case "cycle_start":
            addLog("info", `🔄 第 ${data.cycle} 轮优化`);
            break;
          case "review":
            addLog("ok", `⭐ 评审评分：${data.avg_score?.toFixed(1) ?? "?"}/10`);
            break;
          case "confidence_report":
            setConfidence(data as ConfidenceReport);
            break;
          case "heartbeat":
            setElapsed(data.elapsed ?? 0);
            break;
          case "completed":
            setStatus("completed");
            setSteps((p) => p.map((s) => ({ ...s, status: "done" as const })));
            addLog("ok", "✅ 研究完成！");
            if (data.session_id) {
              setActiveSessionId(data.session_id);
              research.report(data.session_id).then((r) => {
                setReport(r.report);
                if (r.confidence_report?.overall_confidence != null) {
                  setConfidence(r.confidence_report as ConfidenceReport);
                }
              }).catch(() => {});
            }
            loadSessions();
            es.close();
            break;
          case "error":
            setStatus("error");
            addLog("err", `✗ 错误：${data.message}`);
            es.close();
            break;
          case "end":
            es.close();
            break;
        }
      } catch { /* ignore parse errors */ }
    };

    es.onerror = () => {
      addLog("warn", "⚠ 连接断开，任务可能仍在运行");
    };
  }, [addLog, loadSessions]);

  const handleStart = async () => {
    if (!question.trim() || status === "running") return;
    setSteps(initSteps());
    setLogs([]);
    setReport(null);
    setConfidence(null);
    setStreamText("");
    setStreamDone(false);
    lastStatusRef.current = "";
    setElapsed(0);
    setStatus("running");
    addLog("info", "▶ 正在启动研究任务...");
    try {
      const { task_id } = await research.start(question.trim(), clarification.trim() || undefined);
      setTaskId(task_id);
      connectSSE(task_id);
    } catch (err: unknown) {
      setStatus("error");
      toast.error(err instanceof Error ? err.message : "启动失败");
    }
  };

  const handleStop = async () => {
    if (!taskId) return;
    try { await research.stop(taskId); } catch { /* ignore */ }
    setStatus("idle");
    setTaskId(null);
    esRef.current?.close();
    addLog("warn", "⊘ 任务已终止");
  };

  const handlePauseResume = async () => {
    if (!taskId) return;
    if (status === "paused") {
      await research.resume(taskId);
      setStatus("running");
      addLog("info", "▶ 已恢复");
    } else {
      await research.pause(taskId);
      setStatus("paused");
      addLog("warn", "⏸ 已暂停");
    }
  };

  const handleInject = async () => {
    if (!taskId || !injectMsg.trim()) return;
    await research.inject(taskId, injectMsg.trim());
    setInjectMsg("");
    addLog("info", `→ 已注入：${injectMsg}`);
  };

  const handleLoadSession = async (s: SessionMeta) => {
    setActiveSessionId(s.session_id);
    setQuestion(s.question);
    setStatus("completed");
    setSteps((p) => p.map((st) => ({ ...st, status: "done" as const })));
    try {
      const r = await research.report(s.session_id);
      setReport(r.report);
      if (r.confidence_report?.overall_confidence != null) {
        setConfidence(r.confidence_report as ConfidenceReport);
      }
    } catch { toast.error("加载报告失败"); }
  };

  const handleDeleteSession = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    try {
      await research.deleteSession(sessionId);
      setSessions((p) => p.filter((s) => s.session_id !== sessionId));
      if (activeSessionId === sessionId) { setReport(null); setActiveSessionId(null); }
      toast.success("已删除");
    } catch { toast.error("删除失败"); }
  };

  const handleCopy = async () => {
    if (!report) return;
    await navigator.clipboard.writeText(report);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const isRunning = status === "running" || status === "paused";
  const hasReport = !!report;

  const handleRestart = (q: string) => {
    setQuestion(q);
    setReport(null);
    setStatus("idle");
    setLogs([]);
    setSteps(initSteps());
    setActiveSessionId(null);
    setStreamText("");
    setStreamDone(false);
    setClarification("");
  };

  const handleStopAll = async () => {
    try { await research.stopAll(); } catch { /* ignore */ }
    if (taskId) { esRef.current?.close(); setTaskId(null); }
    setStatus("idle");
    addLog("warn", "⊘ 所有任务已停止");
  };

  return (
    <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
      {/* Left sidebar */}
      <aside style={{
        width: 240, flexShrink: 0, background: "var(--surface)",
        borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", overflow: "hidden",
      }}>
        <div style={{ padding: "12px 14px 10px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: ".7px" }}>历史会话</span>
          <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
            {isRunning && (
              <button
                onClick={handleStopAll}
                title="停止全部运行中的任务"
                style={{ display: "flex", alignItems: "center", gap: 3, padding: "3px 7px", borderRadius: 5, border: "1px solid rgba(239,68,68,.3)", background: "rgba(239,68,68,.08)", color: "var(--danger)", fontSize: 10, cursor: "pointer", fontWeight: 600 }}
              >
                <Square size={10} />全停
              </button>
            )}
            <button
              onClick={() => { setReport(null); setStatus("idle"); setQuestion(""); setActiveSessionId(null); setLogs([]); setSteps(initSteps()); }}
              style={{ width: 24, height: 24, borderRadius: 6, border: "none", background: "transparent", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text3)" }}
              title="新建"
            >
              <Plus size={14} />
            </button>
          </div>
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: 8 }}>
          {/* Current running task */}
          {isRunning && (
            <div style={{ padding: "9px 10px", borderRadius: 8, marginBottom: 6, border: "1px solid", borderColor: status === "paused" ? "rgba(245,158,11,.4)" : "var(--accent-border)", background: status === "paused" ? "rgba(245,158,11,.06)" : "var(--accent-dim)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 4 }}>
                <div style={{ width: 6, height: 6, borderRadius: "50%", background: status === "paused" ? "var(--warning)" : "var(--success)", flexShrink: 0, animation: status === "paused" ? "none" : "pulse 1.2s infinite" }} />
                <span style={{ fontSize: 10, fontWeight: 700, color: status === "paused" ? "var(--warning)" : "var(--accent)" }}>{status === "paused" ? "已暂停" : `运行中 ${elapsed}s`}</span>
              </div>
              <div style={{ fontSize: 12, color: "var(--text)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", marginBottom: 6 }}>
                {question.slice(0, 38)}{question.length > 38 ? "…" : ""}
              </div>
              <div style={{ display: "flex", gap: 4 }}>
                <button onClick={handlePauseResume} style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 3, padding: "4px 0", borderRadius: 5, border: "1px solid", borderColor: status === "paused" ? "rgba(16,185,129,.3)" : "rgba(245,158,11,.3)", background: status === "paused" ? "rgba(16,185,129,.08)" : "rgba(245,158,11,.08)", color: status === "paused" ? "var(--success)" : "var(--warning)", fontSize: 11, cursor: "pointer" }}>
                  {status === "paused" ? <><Play size={10} />继续</> : <><Pause size={10} />暂停</>}
                </button>
                <button onClick={handleStop} style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 3, padding: "4px 0", borderRadius: 5, border: "1px solid rgba(239,68,68,.3)", background: "rgba(239,68,68,.08)", color: "var(--danger)", fontSize: 11, cursor: "pointer" }}>
                  <Square size={10} />停止
                </button>
              </div>
            </div>
          )}

          {sessions.length === 0 && !isRunning ? (
            <div style={{ padding: "24px 12px", textAlign: "center", color: "var(--text4)", fontSize: 12 }}>
              <div style={{ fontSize: 28, marginBottom: 8, opacity: .5 }}>🔬</div>
              <div>暂无研究记录</div>
            </div>
          ) : sessions.map((s) => (
            <div
              key={s.session_id}
              onClick={() => handleLoadSession(s)}
              style={{
                padding: "9px 10px", borderRadius: 8, cursor: "pointer",
                marginBottom: 3, border: "1px solid",
                borderColor: activeSessionId === s.session_id ? "var(--accent-border)" : "transparent",
                background: activeSessionId === s.session_id ? "var(--accent-dim)" : "transparent",
                transition: "all .15s", position: "relative",
              }}
              onMouseEnter={(e) => {
                if (activeSessionId !== s.session_id) {
                  (e.currentTarget as HTMLDivElement).style.background = "var(--bg2)";
                  (e.currentTarget as HTMLDivElement).style.borderColor = "var(--border)";
                }
                const btns = (e.currentTarget as HTMLDivElement).querySelector(".item-actions") as HTMLElement;
                if (btns) btns.style.opacity = "1";
              }}
              onMouseLeave={(e) => {
                if (activeSessionId !== s.session_id) {
                  (e.currentTarget as HTMLDivElement).style.background = "transparent";
                  (e.currentTarget as HTMLDivElement).style.borderColor = "transparent";
                }
                const btns = (e.currentTarget as HTMLDivElement).querySelector(".item-actions") as HTMLElement;
                if (btns) btns.style.opacity = "0";
              }}
            >
              <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", marginBottom: 3, paddingRight: 4 }}>
                {s.question.slice(0, 38)}{s.question.length > 38 ? "…" : ""}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 10, color: "var(--text3)" }}>
                  {new Date(s.created_at).toLocaleDateString("zh-CN")}
                </span>
                {s.final_score != null && (
                  <span style={{
                    fontSize: 10, fontWeight: 700, padding: "1px 5px", borderRadius: 8,
                    background: s.final_score >= 8 ? "rgba(16,185,129,.12)" : s.final_score >= 6 ? "rgba(245,158,11,.12)" : "rgba(239,68,68,.1)",
                    color: s.final_score >= 8 ? "var(--success)" : s.final_score >= 6 ? "var(--warning)" : "var(--danger)",
                  }}>{s.final_score.toFixed(1)}</span>
                )}
              </div>
              <div
                className="item-actions"
                style={{ position: "absolute", top: 6, right: 6, opacity: 0, display: "flex", gap: 3, transition: "opacity .15s" }}
              >
                <button
                  onClick={(e) => { e.stopPropagation(); handleRestart(s.question); }}
                  title="重来"
                  style={{ width: 22, height: 22, borderRadius: 4, border: "1px solid var(--border)", background: "var(--surface)", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--accent)" }}
                >
                  <RotateCcw size={11} />
                </button>
                <button
                  onClick={(e) => handleDeleteSession(e, s.session_id)}
                  title="删除"
                  style={{ width: 22, height: 22, borderRadius: 4, border: "1px solid var(--border)", background: "var(--surface)", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text4)" }}
                >
                  <Trash2 size={11} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </aside>

      {/* Main */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>

          {/* Input card */}
          <div style={{ background: "var(--surface)", borderRadius: 14, border: "1px solid var(--border)", padding: 20, marginBottom: 16, boxShadow: "0 1px 3px rgba(184,114,26,.06)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
              <span style={{ fontSize: 15, fontWeight: 700, color: "var(--text)" }}>提出研究问题</span>
              {isRunning && (
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--text3)" }}>
                  <div style={{ width: 6, height: 6, borderRadius: "50%", background: status === "paused" ? "var(--warning)" : "var(--success)", animation: status === "paused" ? "none" : "pulse 1.2s infinite" }} />
                  {status === "paused" ? "已暂停" : `运行中 ${elapsed}s`}
                </div>
              )}
            </div>

            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleStart(); }}
              placeholder="输入你想深入研究的问题..."
              disabled={isRunning}
              rows={3}
              style={{
                width: "100%", resize: "vertical", padding: "10px 14px",
                border: "1px solid var(--border)", borderRadius: 10,
                background: "var(--surface2)", color: "var(--text)",
                fontSize: 14, lineHeight: 1.6, outline: "none",
                fontFamily: "inherit", transition: "border-color .15s",
              }}
              onFocus={(e) => { e.target.style.borderColor = "var(--accent)"; e.target.style.boxShadow = "0 0 0 3px var(--accent-dim)"; }}
              onBlur={(e) => { e.target.style.borderColor = "var(--border)"; e.target.style.boxShadow = "none"; }}
            />

            {showClarify && (
              <textarea
                value={clarification}
                onChange={(e) => setClarification(e.target.value)}
                placeholder="补充背景或限制（可选）..."
                rows={2}
                style={{ width: "100%", resize: "vertical", padding: "8px 12px", border: "1px solid var(--border)", borderRadius: 8, background: "var(--bg2)", color: "var(--text)", fontSize: 13, outline: "none", fontFamily: "inherit", marginTop: 8 }}
              />
            )}

            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 12 }}>
              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={() => setShowClarify((v) => !v)} style={{ padding: "6px 12px", borderRadius: 7, border: "1px solid var(--border)", background: "transparent", color: "var(--text3)", fontSize: 12, cursor: "pointer" }}>
                  {showClarify ? "− 收起补充" : "+ 添加补充"}
                </button>
                {isRunning && (
                  <>
                    <button onClick={handlePauseResume} style={{ display: "flex", alignItems: "center", gap: 5, padding: "6px 12px", borderRadius: 7, border: "1px solid", borderColor: status === "paused" ? "rgba(16,185,129,.3)" : "rgba(245,158,11,.3)", background: status === "paused" ? "rgba(16,185,129,.08)" : "rgba(245,158,11,.08)", color: status === "paused" ? "var(--success)" : "var(--warning)", fontSize: 12, cursor: "pointer" }}>
                      {status === "paused" ? <><Play size={12} />恢复</> : <><Pause size={12} />暂停</>}
                    </button>
                    <button onClick={handleStop} style={{ padding: "6px 12px", borderRadius: 7, border: "1px solid rgba(239,68,68,.3)", background: "rgba(239,68,68,.08)", color: "var(--danger)", fontSize: 12, cursor: "pointer" }}>
                      终止
                    </button>
                  </>
                )}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ fontSize: 11, color: "var(--text4)" }}>Ctrl+Enter 启动</span>
                {!isRunning ? (
                  <button
                    onClick={handleStart}
                    disabled={!question.trim()}
                    style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 20px", borderRadius: 8, border: "none", background: "linear-gradient(135deg, var(--accent), var(--accent-hover))", color: "#fff", fontSize: 13, fontWeight: 600, cursor: "pointer", boxShadow: "0 2px 8px var(--accent-border)", opacity: question.trim() ? 1 : .5 }}
                  >
                    🚀 开始研究
                  </button>
                ) : null}
              </div>
            </div>

            {/* Inject input */}
            {isRunning && (
              <div style={{ marginTop: 12, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
                <div style={{ display: "flex", gap: 8 }}>
                  <input
                    value={injectMsg}
                    onChange={(e) => setInjectMsg(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") handleInject(); }}
                    placeholder="向 AI 注入实时指令..."
                    style={{ flex: 1, padding: "7px 10px", borderRadius: 7, border: "1px solid var(--border2)", background: "var(--surface2)", color: "var(--text)", fontSize: 12, outline: "none", fontFamily: "inherit" }}
                  />
                  <button onClick={handleInject} style={{ padding: "7px 14px", borderRadius: 7, border: "none", background: "var(--accent-dim)", color: "var(--accent)", fontSize: 12, cursor: "pointer" }}>发送</button>
                </div>
                <div style={{ fontSize: 10, color: "var(--text4)", marginTop: 4 }}>可以向正在研究的 AI 补充说明或调整方向</div>
              </div>
            )}
          </div>

          {/* Progress card */}
          {(isRunning || status === "completed" || status === "error") && (
            <div style={{ background: "var(--surface)", borderRadius: 14, border: "1px solid var(--border)", overflow: "hidden", marginBottom: 16 }}>
              <div style={{ padding: "14px 18px" }}>
                <div style={{ marginBottom: 14 }}>
                  <StepPipeline steps={steps} />
                </div>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: ".5px", marginBottom: 6 }}>运行日志</div>
                <LogArea lines={logs} />
                <StreamArea text={streamText} agent={streamAgent} done={streamDone} />
              </div>
            </div>
          )}

          {/* Report card */}
          {hasReport && (
            <div style={{ background: "var(--surface)", borderRadius: 14, border: "1px solid var(--border)", overflow: "hidden", marginBottom: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 18px", borderBottom: "1px solid var(--border)", background: "var(--surface2)" }}>
                <span style={{ flex: 1, fontSize: 13, fontWeight: 700, color: "var(--text)" }}>📄 研究报告</span>
                <button onClick={handleCopy} style={{ display: "flex", alignItems: "center", gap: 5, padding: "5px 12px", borderRadius: 7, border: "1px solid var(--border2)", background: "var(--surface)", color: "var(--text2)", fontSize: 12, cursor: "pointer" }}>
                  {copied ? <><Check size={12} />已复制</> : <><Copy size={12} />复制</>}
                </button>
                <button onClick={() => setShowReport((v) => !v)} style={{ width: 28, height: 28, borderRadius: 6, border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text3)", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  {showReport ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </button>
              </div>
              {showReport && (
                <>
                  <div
                    className="report-body"
                    style={{ padding: 20 }}
                    dangerouslySetInnerHTML={{ __html: marked.parse(report) as string }}
                  />
                  <div style={{ borderTop: "1px solid var(--border)", padding: "14px 20px", display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
                    <span style={{ fontSize: 11, color: "var(--text4)", marginRight: 4 }}>继续探索：</span>
                    <button
                      onClick={() => { const blob = new Blob([report], { type: "text/markdown" }); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `research-${Date.now()}.md`; a.click(); }}
                      style={{ display: "flex", alignItems: "center", gap: 5, padding: "6px 12px", borderRadius: 7, border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text2)", fontSize: 12, cursor: "pointer" }}
                    >
                      <Download size={12} />下载 Markdown
                    </button>
                    <button
                      onClick={() => navigate(`/expand?idea=${encodeNavParam("idea", question)}`)}
                      style={{ display: "flex", alignItems: "center", gap: 5, padding: "6px 12px", borderRadius: 7, border: "1px solid rgba(124,58,237,.3)", background: "rgba(124,58,237,.06)", color: "#7C3AED", fontSize: 12, cursor: "pointer" }}
                    >
                      <Zap size={12} />发散更多方向
                    </button>
                    <button
                      onClick={() => navigate(`/intent?init=${encodeNavParam("init", question)}`)}
                      style={{ display: "flex", alignItems: "center", gap: 5, padding: "6px 12px", borderRadius: 7, border: "1px solid rgba(99,102,241,.3)", background: "rgba(99,102,241,.06)", color: "#6366F1", fontSize: 12, cursor: "pointer" }}
                    >
                      <Target size={12} />提炼行动意图
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {/* Right panel */}
        {confidence && (
          <aside className="research-confidence-aside" style={{ width: 240, flexShrink: 0, background: "var(--surface)", borderLeft: "1px solid var(--border)", padding: 14, overflowY: "auto" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: ".6px", marginBottom: 10 }}>置信度分析</div>
            <ConfidenceGauge report={confidence} />
            {confidence.disputed_claims && confidence.disputed_claims.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: ".6px", marginBottom: 8 }}>争议声明</div>
                {confidence.disputed_claims.map((c, i) => (
                  <div key={i} style={{ padding: "8px 10px", borderRadius: 7, borderLeft: "3px solid var(--warning)", background: "rgba(245,158,11,.05)", marginBottom: 6, fontSize: 11, color: "var(--text2)", lineHeight: 1.5 }}>
                    <div style={{ display: "inline-flex", padding: "1px 6px", borderRadius: 8, fontSize: 9, fontWeight: 700, background: "rgba(245,158,11,.15)", color: "var(--warning)", marginBottom: 3 }}>{c.confidence}</div>
                    <div>{c.claim}</div>
                  </div>
                ))}
              </div>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}
