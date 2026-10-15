import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useLocation } from "wouter";
import { research } from "../../lib/api";
import { live, useLiveVersion } from "../../lib/live/store";
import type { SessionMeta } from "../../lib/types";

export const MAX_ACTIVE = 2; // 后端 MAX_CONCURRENT_TASKS
const RECENT = 8;
const POLL_MS = 20_000;

interface DeskState {
  active: SessionMeta[];
  recent: SessionMeta[];
  loaded: boolean;
  refresh: () => void;
}

const Ctx = createContext<DeskState>({ active: [], recent: [], loaded: false, refresh: () => {} });

/** 待签批的排最前，其余保持新到旧 */
const askFirst = (list: SessionMeta[]) =>
  [...list].sort((a, b) => Number(!!live.get(b.task_id ?? "")?.decision) - Number(!!live.get(a.task_id ?? "")?.decision));

/** 案头数据：/api/sessions 里运行中的（最多 2 份）与最近 8 份；换页时与每 20 秒（页面可见时）刷新。
 *  运行中的任务交给 live 共享状态连 SSE，案头、顶栏与办案记录读同一份阶段、用时与签批状态。 */
export function DeskProvider({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [loaded, setLoaded] = useState(false);
  useLiveVersion();
  const refresh = useCallback(() => {
    research.sessions(0, 50)
      .then((r) => setSessions(r.sessions))
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);
  useEffect(() => { refresh(); }, [refresh, location]);
  useEffect(() => {
    const id = setInterval(() => { if (document.visibilityState === "visible") refresh(); }, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);
  const running = sessions.filter((s) => s.status === "running").slice(0, MAX_ACTIVE);
  const finished = running.filter((s) => s.task_id && live.get(s.task_id)?.ended).length;
  useEffect(() => { running.forEach((s) => { if (s.task_id) live.watch(s.task_id); }); });
  useEffect(() => { if (finished) refresh(); }, [finished, refresh]); // 在办的结束了：不等下一次轮询
  const recent = sessions.filter((s) => s.status !== "running").slice(0, RECENT);
  return <Ctx.Provider value={{ active: askFirst(running), recent, loaded, refresh }}>{children}</Ctx.Provider>;
}

export const useDesk = () => useContext(Ctx);

/** 点案头 / 档案柜条目去哪：已结卷的打开卷宗，在办的看办案记录，其余（停止、中断、失败）去档案柜处理。 */
export const sessionHref = (s: SessionMeta) => {
  if (s.status === "completed" && s.session_id) return `/dossier/${s.session_id}`;
  if (s.status === "running" && s.task_id) return `/case/${s.task_id}`;
  return "/cabinet";
};

/** 顶栏"办案记录"指向哪一份：正在看的那份，否则待签批的，否则第一份在办的 */
export function currentCase(location: string, active: SessionMeta[]): string {
  const m = /^\/case\/([^/?#]+)/.exec(location);
  if (m) return `/case/${m[1]}`;
  const first = active.find((s) => s.task_id);
  return first ? `/case/${first.task_id}` : "/case";
}
