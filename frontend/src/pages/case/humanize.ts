import type { TFunc, TKey } from "../../i18n";
import type { LogLine } from "../../lib/live/model";

// 事件 → 人话（办案记录时间线里每个阶段下的动态）；原始事件另在"原始日志"里逐行列出

export interface HumanLine {
  at: string;
  text: string;
  kind: "done" | "info" | "warn";
  count: number;
}

const f2 = (v: unknown) => (typeof v === "number" ? v.toFixed(2) : "?");

export const agentNames = (t: TFunc, agents: unknown, sep: string) =>
  (Array.isArray(agents) ? agents : []).map((a) => t(`case.agent.${a}` as TKey)).join(sep);

type Fmt = (t: TFunc, d: Record<string, any>, sep: string) => [string, HumanLine["kind"]] | null;

const FORMATS: Record<string, Fmt> = {
  started: (t) => [t("case.h.started"), "info"],
  agent_thinking: (t, d) => [t("case.h.agent", { a: d.agent ?? "" }), "info"],
  paused: (t, d) => [t("case.h.paused", { g: d.phase ?? "" }), "warn"],
  resumed: (t) => [t("case.h.resumed"), "info"],
  user_message_queued: (t, d) => [t("case.h.queued", { m: d.message ?? "" }), "info"],
  user_message_ack: (t, d) => [t("case.h.ack", { g: d.phase ?? "" }), "done"],
  user_message_applied: (t, d, sep) => [t("case.h.applied", { a: agentNames(t, d.agents, sep) }), "done"],
  loop_decision: (t) => [t("case.h.ask"), "warn"],
  loop_decision_resolved: (t, d) => [t(`case.h.decided.${d.choice}` as TKey), "done"],
  final_selected: (t, d) => (d.draft != null ? [t("case.h.final", { n: d.draft }), "done"] : null),
  confidence_report: (t, d) => [t("case.h.conf", { v: f2(d.overall_confidence) }), "done"],
  stats: (t, d) => [t("case.h.stats", { s: d.total_sources ?? "?", c: d.claims_checked ?? "?" }), "done"],
  completed: (t) => [t("case.h.completed"), "done"],
  stopped: (t) => [t("case.h.stopped"), "warn"],
  error: (t, d) => [t("case.h.error", { m: d.message ?? "" }), "warn"],
};

/** 某个阶段下的人话动态：连续重复的（如研究员按查询组并行开工）合并成"×n" */
export function humanize(t: TFunc, lines: LogLine[], sep: string): HumanLine[] {
  const out: HumanLine[] = [];
  for (const line of lines) {
    const fmt = FORMATS[line.type];
    const res = fmt?.(t, line.data as Record<string, any>, sep);
    if (!res) continue;
    const prev = out[out.length - 1];
    if (prev && prev.text === res[0]) { prev.count += 1; continue; }
    out.push({ at: line.at, text: res[0], kind: res[1], count: 1 });
  }
  return out;
}

/** 原始日志一行：时间 + 事件名 + 数据（截断） */
export function rawLine(line: LogLine): string {
  const json = JSON.stringify(line.data);
  return `${line.at.slice(11, 19)}  ${line.type}  ${json.length > 180 ? `${json.slice(0, 180)}…` : json}`;
}
