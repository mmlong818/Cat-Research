import { useCallback, useEffect, useMemo, useState } from "react";
import { research } from "../../lib/api";
import type { SessionMeta } from "../../lib/types";

export type Filter = "all" | "completed" | "resumable" | "failed";
export const FILTERS: Filter[] = ["all", "completed", "resumable", "failed"];

export const keyOf = (s: SessionMeta) => s.session_id || s.task_id || s.created_at;

const matches = (f: Filter, status?: string) =>
  f === "all" || (f === "resumable" ? status === "stopped" || status === "interrupted" : status === f);

/** 全部会话（分页取完，新到旧） */
async function loadAll(): Promise<SessionMeta[]> {
  const page = 200;
  const out: SessionMeta[] = [];
  for (let offset = 0; ; offset += page) {
    const { sessions, total } = await research.sessions(offset, page);
    out.push(...sessions);
    if (sessions.length === 0 || offset + page >= total) return out;
  }
}

export interface Group { day: string; items: SessionMeta[] }

/** 按创建日期分组（本地日期），保持新到旧 */
function groupByDay(list: SessionMeta[]): Group[] {
  const groups: Group[] = [];
  for (const s of list) {
    const day = (s.created_at || "").slice(0, 10);
    const last = groups[groups.length - 1];
    if (last && last.day === day) last.items.push(s);
    else groups.push({ day, items: [s] });
  }
  return groups;
}

/** 档案柜数据：在办的单列置顶；其余按搜索词（问题或编号）与状态筛选后按日期分组 */
export function useCabinet() {
  const [all, setAll] = useState<SessionMeta[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const reload = useCallback(() => {
    loadAll().then((list) => { setAll(list); setError(null); }).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(() => { reload(); }, [reload]);
  const remove = useCallback((key: string) => setAll((list) => list?.filter((s) => keyOf(s) !== key) ?? null), []);
  const view = useMemo(() => {
    const list = all ?? [];
    const q = query.trim().toLowerCase();
    const hit = (s: SessionMeta) => !q || s.question.toLowerCase().includes(q)
      || (s.session_id || "").includes(q.replace(/^cr-/, "").replace("-", "_")) || (s.task_id ?? "").includes(q);
    const rest = list.filter((s) => s.status !== "running" && hit(s) && matches(filter, s.status));
    return { live: list.filter((s) => s.status === "running"), groups: groupByDay(rest), total: list.length };
  }, [all, query, filter]);
  return { loaded: all != null, error, query, setQuery, filter, setFilter, reload, remove, ...view };
}
