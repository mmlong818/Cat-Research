import {
  PHASE_NUM, STAGES, initState, type CaseState, type Decision, type PlanInfo, type RunStatus,
} from "./model";
import { keepLocal, onAck, onApplied, onQueued } from "./messages";
import { localIso } from "../format";

type Data = Record<string, any>;
export interface StreamEvent { type: string; data: Data; timestamp?: string }
type Handler = (s: CaseState, d: Data, at: string, live: boolean) => CaseState;

const LOG_MAX = 400;
const QUIET = new Set(["heartbeat", "ping", "snapshot", "disconnected"]);

const SNAPSHOT_STATUS: Record<string, RunStatus> = {
  pending: "running", running: "running", completed: "completed", failed: "failed",
  stopped: "stopped", interrupted: "interrupted", deleted: "stopped",
};

export const toDecision = (d: Data, receivedAt = Date.now()): Decision => ({
  cycle: Number(d.cycle), maxCycles: Number(d.max_cycles), bestDraft: Number(d.best_draft),
  bestScore: Number(d.best_score), score: d.score ?? null, gain: d.gain ?? null, violations: d.violations ?? 0,
  estSeconds: d.est_seconds ?? null, paused: !!d.paused,
  remaining: Number(d.remaining_s ?? d.timeout_s ?? 0), timeout: Number(d.timeout_s ?? 300), receivedAt,
});

const toPlan = (d: Data): PlanInfo => ({
  objective: String(d.objective ?? ""),
  aspects: Array.isArray(d.key_aspects) ? d.key_aspects.map(String) : [],
  queries: (Array.isArray(d.search_queries) ? d.search_queries : []).map((q: Data) => ({
    query: String(q.query ?? ""), purpose: String(q.purpose ?? ""), language: String(q.language ?? ""),
  })),
  total: Number(d.total_queries ?? d.search_queries?.length ?? 0),
});

function snapshot(prev: CaseState, d: Data, at: string): CaseState {
  const s = initState(prev.taskId);
  return {
    ...s,
    question: d.question ?? prev.question,
    sessionId: d.session_id || prev.sessionId,
    status: SNAPSHOT_STATUS[d.status] ?? "running",
    error: d.error ?? null,
    pauseRequested: !!d.paused,
    elapsed: Number(d.elapsed ?? prev.elapsed ?? 0),
    elapsedAt: Date.now(),
    decision: d.loop_decision ? toDecision(d.loop_decision) : null,
    messages: keepLocal(prev.messages),
    snapshotAt: at,
  };
}

/** 阶段只进不退；重放任务从中途开始时，之前的阶段视为上次已完成 */
function phase(s: CaseState, d: Data, at: string): CaseState {
  const key = PHASE_NUM[String(d.phase)];
  const idx = key ? STAGES.indexOf(key) : -1;
  if (idx < 0 || idx < s.stage) return s;
  return { ...s, stage: idx, stageAt: s.stageAt[key] ? s.stageAt : { ...s.stageAt, [key]: at } };
}

function review(s: CaseState, d: Data, at: string): CaseState {
  const score = Number(d.avg_score);
  const has = s.rounds.some((r) => r.cycle === d.cycle);
  const rounds = has
    ? s.rounds.map((r) => (r.cycle === d.cycle ? { ...r, score } : r))
    : [...s.rounds, { cycle: Number(d.cycle), max: 0, at, score }];
  return { ...s, rounds };
}

/** 回放里的旧提问只记日志：待签批与否以快照为准（快照带 loop_decision 才是还在等） */
function decision(s: CaseState, d: Data, _at: string, live: boolean): CaseState {
  return live ? { ...s, decision: toDecision(d), decided: null } : s;
}

function decisionTimer(s: CaseState, d: Data, _at: string, live: boolean): CaseState {
  if (!live || !s.decision || s.decision.cycle !== d.cycle) return s;
  return { ...s, decision: { ...s.decision, paused: !!d.paused, remaining: Number(d.remaining_s), receivedAt: Date.now() } };
}

const HANDLERS: Record<string, Handler> = {
  started: (s, d) => ({ ...s, question: d.question || s.question, status: s.status === "connecting" ? "running" : s.status }),
  session: (s, d) => ({ ...s, sessionId: d.session_id ?? s.sessionId }),
  status: (s, d) => (d.status === "stopped" ? { ...s, status: "stopped", stopping: false } : s),
  phase,
  plan: (s, d) => ({ ...s, plan: toPlan(d) }),
  cycle_start: (s, d, at) => ({
    ...s, rounds: [...s.rounds.filter((r) => r.cycle !== d.cycle), { cycle: Number(d.cycle), max: Number(d.max), at, score: null }],
  }),
  review,
  loop_decision: decision,
  loop_decision_timer: decisionTimer,
  loop_decision_resolved: (s, d, at) => ({
    ...s, decision: s.decision?.cycle === d.cycle ? null : s.decision, decided: { choice: d.choice, cycle: d.cycle, at },
  }),
  loop_stop: (s, d) => ({ ...s, loopStop: { cycle: Number(d.cycle), reason: String(d.reason ?? "") } }),
  paused: (s, d, _at, live) => ({ ...s, lastPause: "paused", pauseGate: d.phase ?? null, pauseRequested: live ? true : s.pauseRequested }),
  resumed: (s, _d, _at, live) => ({ ...s, lastPause: "resumed", resuming: false, pauseRequested: live ? false : s.pauseRequested }),
  user_message_queued: (s, d, at) => ({ ...s, messages: onQueued(s.messages, String(d.message ?? ""), at) }),
  user_message_ack: (s, d, at) => ({ ...s, messages: onAck(s.messages, d.messages ?? [], String(d.phase ?? ""), at) }),
  user_message_applied: (s, d, at) => ({
    ...s, messages: onApplied(s.messages, d.messages ?? [], String(d.phase ?? ""), d.agents ?? [], at),
  }),
  agent_thinking: (s, d) => ({ ...s, agent: d.agent ?? s.agent }),
  final_selected: (s, d) => ({ ...s, finalDraft: d.draft ?? s.finalDraft }),
  confidence_report: (s, d) => ({ ...s, confidence: typeof d.overall_confidence === "number" ? d.overall_confidence : null }),
  stats: (s, d) => ({ ...s, stats: d, elapsed: Number(d.elapsed_seconds ?? s.elapsed) }),
  heartbeat: (s, d) => ({ ...s, elapsed: Number(d.elapsed ?? s.elapsed), elapsedAt: Date.now() }),
  completed: (s, d) => ({ ...s, status: "completed", sessionId: d.session_id || s.sessionId }),
  stopped: (s) => ({ ...s, status: "stopped", stopping: false }), // 用户停止（或删除），不是失败
  error: (s, d) => ({ ...s, status: "failed", error: String(d.message ?? "") }),
  end: (s) => ({ ...s, ended: true, status: s.status === "running" || s.status === "connecting" ? "interrupted" : s.status }),
  disconnected: (s, d) => ({ ...s, offline: Number(d.retry_in) || 1 }),
};

function withLog(s: CaseState, ev: StreamEvent, at: string): CaseState {
  if (QUIET.has(ev.type)) return s;
  const log = [...s.log, { at, type: ev.type, data: ev.data ?? {}, stage: s.stage }];
  return { ...s, log: log.length > LOG_MAX ? log.slice(-LOG_MAX) : log };
}

/** 一条事件 → 新状态。snapshot 清空重建（随后的回放把事件补回来）；时间戳早于快照的是回放 */
export function reduce(prev: CaseState, ev: StreamEvent): CaseState {
  const at = ev.timestamp ?? localIso();
  if (ev.type === "snapshot") return snapshot(prev, ev.data ?? {}, at);
  const live = !prev.snapshotAt || at > prev.snapshotAt;
  const base = ev.type === "disconnected" ? prev : { ...prev, offline: null };
  const handler = HANDLERS[ev.type];
  const next = handler ? handler(base, ev.data ?? {}, at, live) : base;
  return withLog(next, ev, at);
}
