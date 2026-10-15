import { useSyncExternalStore } from "react";
import type { ClarifySummary, Depth, Provider, ResearchStartOptions } from "../../lib/api";

// 委托台的草稿：跨页面保留（去别处看一眼再回来，对话、委托单和停在第几步都还在），刷新页面从 sessionStorage 恢复；
// 深度档、报告语言、改进轮询问沿用上次的选择（localStorage）。

export type DepthChoice = Depth | "custom";
export type Lang = "zh" | "en";

/** 本次研究的模型：provider 为 default 表示用设置里的默认；core/support 只在指定型号后才有 */
export interface ModelChoice {
  provider: Provider | "default";
  core?: string;
  support?: string;
}

export const FIELD_KEYS = ["objective", "scope", "timeframe", "aspects", "exclude"] as const;
export type FieldKey = (typeof FIELD_KEYS)[number] | "extra" | "question";

export interface Fields {
  objective: string;
  scope: string;
  timeframe: string;
  aspects: string[];
  exclude: string;
  extra: string;
}

export interface Turn {
  who: "me" | "ai";
  text: string;
  wrote?: string[];   // 这一轮研究助理写进委托单的栏
}

/** 两步：1 说清问题（和研究助理对话），2 核对委托单（改完签发） */
export type Step = 1 | 2;

export interface Draft {
  step: Step;
  question: string;
  asked: string;              // 交给研究助理时的原问题（改了研究问题要另行说明）
  clarifyId: string | null;
  turns: Turn[];
  summary: ClarifySummary | null;
  fields: Fields;
  edited: FieldKey[];
  ready: boolean;
  depth: DepthChoice;
  minCycles: number;
  maxCycles: number;
  lang: Lang | null;          // null = 跟随界面语言
  askLoop: boolean;
  model: ModelChoice;
}

const DRAFT_KEY = "cr.commission";
export const EMPTY_FIELDS: Fields = { objective: "", scope: "", timeframe: "", aspects: [], exclude: "", extra: "" };

const read = (store: Storage | undefined, key: string): string | null => {
  try { return store?.getItem(key) ?? null; } catch { return null; }
};
const write = (store: Storage | undefined, key: string, value: string | null) => {
  try { if (value == null) store?.removeItem(key); else store?.setItem(key, value); } catch { /* 隐私模式等：只是不记住 */ }
};
const local = typeof localStorage === "undefined" ? undefined : localStorage;
const session = typeof sessionStorage === "undefined" ? undefined : sessionStorage;

const rounds = (key: string, fallback: number) => {
  const n = Number(read(local, key));
  return Number.isFinite(n) && n >= 1 && n <= 20 ? n : fallback;
};

function initial(): Draft {
  const depth = read(local, "cr.depth");
  const lang = read(local, "cr.reportLang");
  const base: Draft = {
    step: 1, question: "", asked: "", clarifyId: null, turns: [], summary: null, fields: EMPTY_FIELDS, edited: [], ready: false,
    depth: depth === "quick" || depth === "deep" || depth === "custom" ? depth : "standard",
    minCycles: rounds("cr.minCycles", 2), maxCycles: rounds("cr.maxCycles", 5),
    lang: lang === "zh" || lang === "en" ? lang : null,
    askLoop: read(local, "cr.askLoop") !== "0",
    model: { provider: "default" },
  };
  try {
    const saved = JSON.parse(read(session, DRAFT_KEY) ?? "null");
    return saved && typeof saved === "object" ? { ...base, ...saved } : base;
  } catch {
    return base;
  }
}

let state: Draft = initial();
const listeners = new Set<() => void>();

function persist(d: Draft) {
  write(session, DRAFT_KEY, JSON.stringify(d));
  write(local, "cr.depth", d.depth);
  write(local, "cr.minCycles", String(d.minCycles));
  write(local, "cr.maxCycles", String(d.maxCycles));
  write(local, "cr.reportLang", d.lang);
  write(local, "cr.askLoop", d.askLoop ? "1" : "0");
}

export function setDraft(fn: (d: Draft) => Draft) {
  state = fn(state);
  persist(state);
  listeners.forEach((l) => l());
}

export const getDraft = () => state;

export const useDraft = () => useSyncExternalStore(
  (fn) => { listeners.add(fn); return () => { listeners.delete(fn); }; },
  () => state,
);

/** 清空对话与委托单、回到第 1 步，保留深度档、语言、询问、模型这些偏好 */
export const resetDraft = (question = "") => setDraft((d) => ({
  ...d, step: 1, question, asked: "", clarifyId: null, turns: [], summary: null, fields: EMPTY_FIELDS, edited: [], ready: false,
}));

export const setStep = (step: Step) => setDraft((d) => ({ ...d, step }));

/** 档案柜「重办」：按原问题与原深度、语言回填 */
export function prefillDraft(question: string, depth?: string | null, lang?: string | null) {
  resetDraft(question);
  setDraft((d) => ({
    ...d,
    depth: depth === "quick" || depth === "standard" || depth === "deep" ? depth : d.depth,
    lang: lang === "zh" || lang === "en" ? lang : d.lang,
  }));
}

/** 只把用户改过的部分带给后端，其余由后端按设置里的默认配置档补全 */
export const modelRequest = (c: ModelChoice): Pick<ResearchStartOptions, "provider" | "core_model" | "support_model"> => ({
  ...(c.provider !== "default" ? { provider: c.provider } : {}),
  ...(c.core ? { core_model: c.core } : {}),
  ...(c.support ? { support_model: c.support } : {}),
});

/** 深度档：自定义只带改进轮数（检索条数按标准档），其余带档位 */
export function depthRequest(d: Draft): Pick<ResearchStartOptions, "depth" | "min_cycles" | "max_cycles"> {
  if (d.depth !== "custom") return { depth: d.depth };
  const min = Math.min(Math.max(1, d.minCycles), 20);
  return { min_cycles: min, max_cycles: Math.min(Math.max(min, d.maxCycles), 20) };
}
