// ── Research ──────────────────────────────────────────────────────────────

export interface SessionMeta {
  session_id: string;
  question: string;
  created_at: string;
  status?: string;
  final_score?: number;
}

export type StepStatus = "pending" | "active" | "done" | "error";

export interface PipelineStep {
  key: string;
  label: string;
  emoji: string;
  status: StepStatus;
  duration?: number;
}

export interface LogLine {
  type: "info" | "ok" | "warn" | "err" | "dim";
  text: string;
}

export interface ConfidenceReport {
  overall_confidence?: number;
  source_reliability?: number;
  fact_accuracy?: number;
  conclusion_consistency?: number;
  evidence_sufficiency?: number;
  disputed_claims?: { claim: string; confidence: string }[];
}

export interface ResearchSource {
  title: string;
  url: string;
  authority_tier?: number;
  domain_score?: number;
}
