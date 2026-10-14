// ── Research ──────────────────────────────────────────────────────────────

export interface SessionMeta {
  session_id: string;          // 没建成工作空间的失败任务为空串，此时用 task_id 标识
  task_id?: string | null;
  question: string;
  created_at: string;
  status?: string;             // running / completed / failed / stopped / interrupted / unknown
  final_score?: number | null;
  total_cycles?: number | null;
  elapsed_seconds?: number | null;
  final_draft?: number | null;        // 终稿取自第几版
  best_scored_draft?: number | null;  // 评审分最高的一版（有引用违规时可能不是终稿）
  citations?: { cited_claims: number | null; violations: number | null; numeric_coverage: number | null } | null;
  depth?: string | null;
  language?: string | null;
  provider?: string | null;    // 多模型之前的会话为空
  core_model?: string | null;
  support_model?: string | null;
  current_phase?: string | null;
  phase_key?: string | null;
  error?: string | null;
  confidence?: number | null;  // 置信度报告的综合可信度（0–1），没有报告时为空
}

export interface ConfidenceBreakdownItem {
  weight?: string;
  score?: number;
  [k: string]: unknown;
}

export interface ConfidenceReport {
  overall_confidence?: number;
  confidence_level?: "high" | "medium" | "low";
  breakdown?: {
    source_quality?: ConfidenceBreakdownItem;
    fact_accuracy?: ConfidenceBreakdownItem;
    conclusion_validity?: ConfidenceBreakdownItem;
  };
  disputed_claims?: { claim: string; confidence: string }[];
  missing?: string[];
  gaps?: { gap: string; importance: string; suggestion: string }[];
  top_sources?: string[];
}

export interface LedgerClaim {
  id: string;
  text: string;
  status: "unchecked" | "supported" | "disputed" | "unverifiable" | "overruled" | "merged";
  note: string;
  quotes: Record<string, string>;   // 来源编号 -> 原文引语
  sources: { id: string; url: string; title: string; published: string }[];
}

export interface LedgerContradiction {
  id: string;
  topic: string;
  claims: LedgerClaim[];
  resolution: { sides_with: string; reason: string; evidence_url: string } | null;
}

export interface LedgerView {
  counts: { claims: number; citable: number; sources: number; contradictions: number; unresolved: number };
  contradictions: LedgerContradiction[];
  claims: LedgerClaim[];
}

export interface AgentUsage { input: number; output: number }

export interface TokenUsage {
  total_input: number;
  total_cached_input?: number;
  total_output: number;
  by_agent: Record<string, AgentUsage>;
}

export interface ReviewRound {
  cycle: number;
  scores: Record<string, number>;
  average_score: number | null;
  strengths: string[];
  critical_issues: { issue: string; severity?: string; suggestion?: string }[];
  priority_improvements: string[];
}

export interface AuditEntry {
  task_id: string;
  session_id: string | null;
  kind: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ResearchSource {
  title: string;
  url: string;
  authority_tier?: number;
  domain_score?: number;
}
