import type { SessionMeta } from "./types";

const BASE = "/api";

async function req<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? res.statusText);
  }
  return res.json();
}

// ── Research ──────────────────────────────────────────────────────────────

export const research = {
  start: (question: string, clarification?: string) =>
    req<{ task_id: string }>(`${BASE}/research`, {
      method: "POST",
      body: JSON.stringify({ question, clarification }),
    }),

  stream: (taskId: string) => new EventSource(`${BASE}/research/${taskId}/stream`),

  status: (taskId: string) => req<Record<string, unknown>>(`${BASE}/research/${taskId}/status`),

  stop: (taskId: string) =>
    req(`${BASE}/research/${taskId}`, { method: "DELETE" }),

  pause: (taskId: string) =>
    req(`${BASE}/research/${taskId}/pause`, { method: "POST" }),

  resume: (taskId: string) =>
    req(`${BASE}/research/${taskId}/resume`, { method: "POST" }),

  inject: (taskId: string, message: string) =>
    req(`${BASE}/research/${taskId}/message`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),

  sessions: () =>
    req<{ sessions: SessionMeta[] } | SessionMeta[]>(`${BASE}/sessions`)
      .then((r) => (Array.isArray(r) ? r : (r as { sessions: SessionMeta[] }).sessions ?? [])),

  stopAll: () => req(`${BASE}/research/stop-all`, { method: "POST" }),

  report: (sessionId: string) =>
    req<{ report: string; confidence_report: Record<string, unknown> }>(
      `${BASE}/sessions/${sessionId}/report`
    ),

  phases: (sessionId: string) =>
    req<Record<string, unknown>>(`${BASE}/sessions/${sessionId}/phases`),

  deleteSession: (sessionId: string) =>
    req(`${BASE}/sessions/${sessionId}`, { method: "DELETE" }),

  health: () => req<{ status: string }>(`${BASE}/health`),
};

// ── Config ────────────────────────────────────────────────────────────────

export interface ProviderInfo {
  id: string;
  name: string;
  key_placeholder: string;
  default_model: string;
  docs_url: string;
  openai_compatible: boolean;
}

export interface ConfiguredProvider {
  id: string;
  preview: string;
}

export interface ConfigInfo {
  active_provider: string;
  active_model: string;
  configured_providers: ConfiguredProvider[];
  has_api_key: boolean;
  api_key_preview: string;
  core_model: string;
  mode: "api" | "cli";
}

export interface FetchModelsResult {
  models: string[];
  source: "live" | "fallback";
  error: string | null;
}

export interface ConfigUpdate {
  anthropic_api_key?: string;
  core_model?: string;
  active_provider?: string;
  active_model?: string;
  keys?: Record<string, string>;
}

export const config = {
  get: () => req<ConfigInfo>(`${BASE}/settings`),

  update: (body: ConfigUpdate) =>
    req<ConfigInfo>(`${BASE}/settings`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  clearKey: () => req<ConfigInfo>(`${BASE}/settings/api-key`, { method: "DELETE" }),

  clearProviderKey: (pid: string) =>
    req<ConfigInfo>(`${BASE}/settings/keys/${pid}`, { method: "DELETE" }),

  listProviders: () =>
    req<{ providers: ProviderInfo[] }>(`${BASE}/settings/providers`).then(
      (r) => r.providers
    ),

  fetchModels: (pid: string, apiKey?: string) =>
    req<FetchModelsResult>(`${BASE}/settings/providers/${pid}/models`, {
      method: "POST",
      body: JSON.stringify({ api_key: apiKey ?? "" }),
    }),
};
