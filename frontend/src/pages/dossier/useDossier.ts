import { useEffect, useState } from "react";
import { research, type DraftFile } from "../../lib/api";
import type {
  AuditEntry, ConfidenceReport, LedgerView, ReviewRound, SessionMeta, TokenUsage,
} from "../../lib/types";

/** /phases 里的会话元数据（00_session.json 的子集） */
export interface PhaseMeta {
  question?: string;
  total_cycles?: number;
  final_score?: number | null;
  score_history?: number[];
  created_at?: string;
  last_updated?: string;
}

export interface Dossier {
  sid: string;
  report: string;
  confidence: ConfidenceReport | null;
  usage: TokenUsage | null;
  ledger: LedgerView | null;
  reviews: ReviewRound[];
  meta: PhaseMeta;
  queries: number | null;
  entry: SessionMeta | null;
  drafts: DraftFile[];
  audit: AuditEntry[];
}

export type DossierState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: Dossier };

/** 会话列表分页，找到这一份的条目（用时、深度、语言、模型都在这里） */
async function findSession(sid: string): Promise<SessionMeta | null> {
  const page = 200;
  for (let offset = 0; ; offset += page) {
    const { sessions, total } = await research.sessions(offset, page);
    const hit = sessions.find((s) => s.session_id === sid);
    if (hit || sessions.length === 0 || offset + page >= total) return hit ?? null;
  }
}

async function load(sid: string): Promise<Dossier> {
  const [report, ledger, reviews, phases, drafts, audit, entry] = await Promise.all([
    research.report(sid),
    research.ledger(sid).catch(() => null),
    research.reviews(sid).catch(() => [] as ReviewRound[]),
    research.phases(sid).catch(() => ({} as Record<string, unknown>)),
    research.drafts(sid).catch(() => [] as DraftFile[]),
    research.audit(sid).then((r) => r.entries).catch(() => [] as AuditEntry[]),
    findSession(sid).catch(() => null),
  ]);
  const plan = phases.plan as { search_queries?: unknown[] } | undefined;
  const confidence = report.confidence_report as ConfidenceReport;
  return {
    sid, report: report.report, usage: report.token_usage, ledger, reviews, drafts, audit, entry,
    confidence: confidence?.overall_confidence != null ? confidence : null,
    meta: (phases.session_meta as PhaseMeta | undefined) ?? {},
    queries: Array.isArray(plan?.search_queries) ? plan.search_queries.length : null,
  };
}

export function useDossier(sid: string): DossierState {
  const [state, setState] = useState<DossierState>({ status: "loading" });
  useEffect(() => {
    let alive = true;
    setState({ status: "loading" });
    load(sid)
      .then((data) => { if (alive) setState({ status: "ready", data }); })
      .catch((e: unknown) => { if (alive) setState({ status: "error", message: e instanceof Error ? e.message : String(e) }); });
    return () => { alive = false; };
  }, [sid]);
  return state;
}
