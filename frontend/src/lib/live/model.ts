// 运行中任务的界面状态：由 SSE 事件逐条推出（事件契约见 api/app.py、orchestration/*.py）

/** 9 个阶段，与后端 api/sessions.py 的 PHASE_KEYS、research/checkpoints.py 的 PHASES 同序 */
export const STAGES = ["clarify", "plan", "research", "sources", "ledger", "analyze", "draft", "improve", "finish"] as const;
export type StageKey = (typeof STAGES)[number];

/** phase 事件的阶段号 → 阶段键 */
export const PHASE_NUM: Record<string, StageKey> = {
  "1": "clarify", "2": "plan", "3": "research", "3.5": "sources", "3.8": "ledger",
  "4": "analyze", "5": "draft", "6": "improve", "7": "finish",
};

export type RunStatus = "connecting" | "running" | "completed" | "stopped" | "failed" | "interrupted" | "missing";

export interface PlanInfo {
  objective: string;
  aspects: string[];
  queries: { query: string; purpose: string; language: string }[];
  total: number;
}

export interface RoundInfo {
  cycle: number;
  max: number;
  at: string;
  score: number | null;
}

/** 复审签批单：后端 loop_decision；receivedAt 是前端收到的时刻，倒计时据此推算，不依赖两端时钟一致 */
export interface Decision {
  cycle: number;
  maxCycles: number;
  bestDraft: number;
  bestScore: number;
  score: number | null;
  gain: number | null;
  violations: number;
  estSeconds: number | null;
  paused: boolean;
  remaining: number;
  timeout: number;
  receivedAt: number;
}

export type MsgState = "sending" | "queued" | "ack" | "applied" | "failed";

/** 补充指令：已收到（queued）→ 已读取（ack，带检查点名）→ 已用上（applied，逐条累加智能体） */
export interface DirectiveMsg {
  id: number;
  text: string;
  state: MsgState;
  seen: boolean;          // 服务端的 queued 事件已对上这一条
  gate: string | null;
  agents: string[];
  sentAt: string;
  error?: string;
}

export interface LogLine {
  at: string;
  type: string;
  data: Record<string, unknown>;
  stage: number;
}

export interface CaseState {
  taskId: string;
  question: string;
  sessionId: string | null;
  status: RunStatus;
  ended: boolean;
  offline: number | null;        // 断线后多少秒重连；连上为 null
  error: string | null;
  stage: number;                 // 已到达的最大阶段下标（只进不退），-1 = 还没开始
  stageAt: Partial<Record<StageKey, string>>;
  plan: PlanInfo | null;
  rounds: RoundInfo[];
  loopStop: { cycle: number; reason: string } | null;
  decision: Decision | null;
  decided: { choice: string; cycle: number; at: string } | null;
  pauseRequested: boolean;
  lastPause: "paused" | "resumed" | null;
  pauseGate: string | null;
  resuming: boolean;
  stopping: boolean;
  messages: DirectiveMsg[];
  elapsed: number;
  elapsedAt: number;
  agent: string | null;
  finalDraft: number | null;
  confidence: number | null;
  stats: Record<string, number | null> | null;
  log: LogLine[];
  snapshotAt: string;
}

export const initState = (taskId: string): CaseState => ({
  taskId, question: "", sessionId: null, status: "connecting", ended: false, offline: null, error: null,
  stage: -1, stageAt: {}, plan: null, rounds: [], loopStop: null, decision: null, decided: null,
  pauseRequested: false, lastPause: null, pauseGate: null, resuming: false, stopping: false,
  messages: [], elapsed: 0, elapsedAt: Date.now(), agent: null, finalDraft: null,
  confidence: null, stats: null, log: [], snapshotAt: "",
});

export type RunMode = "running" | "pausing" | "paused" | "resuming" | "done";

/** 暂停只在检查点生效：请求后到 paused 事件之前是"正在暂停"，收到 paused 才是"已暂停" */
export function runMode(s: CaseState): RunMode {
  if (s.status !== "running" && s.status !== "connecting") return "done";
  if (s.resuming) return "resuming";
  if (!s.pauseRequested) return "running";
  return s.lastPause === "paused" ? "paused" : "pausing";
}

export const isLive = (s: CaseState) => s.status === "running" || s.status === "connecting";

/** 已运行秒数：最近一次快照或心跳的值 + 之后流逝的时间（结束后停表） */
export const elapsedNow = (s: CaseState, now: number) =>
  isLive(s) ? s.elapsed + Math.max(0, (now - s.elapsedAt) / 1000) : s.elapsed;

/** 签批倒计时剩余秒数；暂停时冻结 */
export const decisionLeft = (d: Decision, now: number) =>
  d.paused ? d.remaining : Math.max(0, d.remaining - (now - d.receivedAt) / 1000);

export const clock = (sec: number) => `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;
