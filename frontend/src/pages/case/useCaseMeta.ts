import { useEffect, useState } from "react";
import { research } from "../../lib/api";
import type { CaseState } from "../../lib/live/model";
import type { LedgerView, ReviewRound } from "../../lib/types";

export interface TaskInfo {
  depth?: string;
  language?: string;
  created_at?: string;
  min_cycles?: number;
}

/** 任务记录里的深度、语言、签发时间（报头用）；任务不存在时为空 */
export function useTaskInfo(taskId: string): TaskInfo | null {
  const [info, setInfo] = useState<TaskInfo | null>(null);
  useEffect(() => {
    let alive = true;
    research.status(taskId).then((r) => { if (alive) setInfo(r as TaskInfo); }).catch(() => {});
    return () => { alive = false; };
  }, [taskId]);
  return info;
}

/** 台账计数：每存一个检查点（研究、来源、对账、改进各轮之后）重取一次 */
export function useLedgerCounts(s: CaseState | undefined): LedgerView["counts"] | null {
  const [counts, setCounts] = useState<LedgerView["counts"] | null>(null);
  const sid = s?.sessionId;
  const marks = s?.log.filter((l) => l.type === "checkpoint" || l.type === "completed").length ?? 0;
  useEffect(() => {
    if (!sid) return;
    let alive = true;
    research.ledger(sid).then((v) => { if (alive) setCounts(v.counts); }).catch(() => {});
    return () => { alive = false; };
  }, [sid, marks]);
  return counts;
}

/** 签批单要引用评审员对当前最优稿的意见：出现待签批时取一次各轮评审 */
export function useReviews(s: CaseState | undefined): ReviewRound[] {
  const [reviews, setReviews] = useState<ReviewRound[]>([]);
  const sid = s?.sessionId;
  const cycle = s?.decision?.cycle;
  useEffect(() => {
    if (!sid || cycle == null) return;
    let alive = true;
    research.reviews(sid).then((r) => { if (alive) setReviews(r); }).catch(() => {});
    return () => { alive = false; };
  }, [sid, cycle]);
  return reviews;
}
