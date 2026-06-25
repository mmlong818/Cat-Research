import { useState, useEffect, useCallback } from "react";
import { X, Eye, EyeOff, Trash2, RefreshCw, ExternalLink, Check } from "lucide-react";
import { toast } from "sonner";
import {
  config as configApi,
  type ProviderInfo,
  type ConfigInfo,
  type FetchModelsResult,
} from "../lib/api";

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function SettingsModal({ open, onClose }: Props) {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [cfg, setCfg] = useState<ConfigInfo | null>(null);
  const [activeProvider, setActiveProvider] = useState<string>("anthropic");
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [model, setModel] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [modelsSource, setModelsSource] = useState<"live" | "fallback" | "none">("none");
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const currentProvider = providers.find((p) => p.id === activeProvider);
  const isConfigured = !!cfg?.configured_providers.find((p) => p.id === activeProvider);
  const preview = cfg?.configured_providers.find((p) => p.id === activeProvider)?.preview || "";

  const reload = useCallback(async () => {
    const [provList, currentCfg] = await Promise.all([
      configApi.listProviders(),
      configApi.get(),
    ]);
    setProviders(provList);
    setCfg(currentCfg);
    setActiveProvider(currentCfg.active_provider || "anthropic");
    setModel(currentCfg.active_model || "");
  }, []);

  useEffect(() => {
    if (!open) return;
    reload();
    setApiKey("");
    setModels([]);
    setModelsSource("none");
    setModelsError(null);
  }, [open, reload]);

  // 切换 provider 时重置临时输入并尝试用已存的 key 拉取模型
  useEffect(() => {
    if (!open || !activeProvider) return;
    setApiKey("");
    setModels([]);
    setModelsSource("none");
    setModelsError(null);
    if (isConfigured) {
      handleFetchModels("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProvider, open]);

  // key 输入防抖触发模型拉取
  useEffect(() => {
    if (!apiKey || apiKey.length < 8) return;
    const t = setTimeout(() => handleFetchModels(apiKey), 700);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey]);

  async function handleFetchModels(keyOverride?: string) {
    if (!activeProvider) return;
    setFetching(true);
    setModelsError(null);
    try {
      const result: FetchModelsResult = await configApi.fetchModels(
        activeProvider,
        keyOverride
      );
      setModels(result.models);
      setModelsSource(result.source);
      setModelsError(result.error);
      if (result.models.length > 0 && !result.models.includes(model)) {
        setModel(result.models[0]);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "模型拉取失败";
      setModelsError(msg);
      toast.error(msg);
    } finally {
      setFetching(false);
    }
  }

  async function handleSave() {
    if (!activeProvider) return;
    setSaving(true);
    try {
      const body: Parameters<typeof configApi.update>[0] = {
        active_provider: activeProvider,
        active_model: model,
      };
      if (apiKey) {
        body.keys = { [activeProvider]: apiKey };
      }
      await configApi.update(body);
      await reload();
      setApiKey("");
      setSaved(true);
      toast.success("设置已保存");
      setTimeout(() => setSaved(false), 1500);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function handleClearKey() {
    await configApi.clearProviderKey(activeProvider);
    await reload();
    setApiKey("");
    setModels([]);
    setModelsSource("none");
    toast.success("已清除当前提供商的 Key");
  }

  if (!open) return null;

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,.5)",
        zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center",
        padding: 16,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--surface)", borderRadius: 16, padding: 28,
          width: 520, maxHeight: "90vh", overflowY: "auto",
          boxShadow: "var(--shadow-lg)",
          border: "1px solid var(--border)",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: "var(--text)" }}>模型设置</span>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text3)", padding: 4 }}>
            <X size={18} />
          </button>
        </div>

        {/* Provider grid */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 12, color: "var(--text3)", marginBottom: 8 }}>
            选择服务提供商
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8 }}>
            {providers.map((p) => {
              const configured = !!cfg?.configured_providers.find((c) => c.id === p.id);
              const active = activeProvider === p.id;
              return (
                <button
                  key={p.id}
                  onClick={() => setActiveProvider(p.id)}
                  style={{
                    padding: "10px 12px",
                    borderRadius: 10,
                    border: active
                      ? "1.5px solid var(--p1)"
                      : "1px solid var(--border)",
                    background: active ? "rgba(184,114,26,.08)" : "var(--surface2)",
                    cursor: "pointer",
                    textAlign: "left",
                    display: "flex",
                    flexDirection: "column",
                    gap: 4,
                    position: "relative",
                  }}
                >
                  <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>
                    {p.name}
                  </span>
                  <span style={{ fontSize: 11, color: "var(--text3)" }}>
                    {p.default_model}
                  </span>
                  {configured && (
                    <div
                      style={{
                        position: "absolute",
                        top: 8,
                        right: 8,
                        width: 14,
                        height: 14,
                        borderRadius: 7,
                        background: "#10B981",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "#fff",
                      }}
                    >
                      <Check size={9} strokeWidth={3} />
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* API Key */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
            <label style={{ fontSize: 12, color: "var(--text3)" }}>
              API Key
              {isConfigured && (
                <span style={{ marginLeft: 8, color: "#10B981", fontSize: 11 }}>
                  已保存 ({preview})
                </span>
              )}
            </label>
            {currentProvider?.docs_url && (
              <a
                href={currentProvider.docs_url}
                target="_blank"
                rel="noreferrer"
                style={{ fontSize: 11, color: "var(--p1)", display: "inline-flex", alignItems: "center", gap: 4 }}
              >
                获取 Key <ExternalLink size={10} />
              </a>
            )}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <div style={{ flex: 1, display: "flex", alignItems: "center", border: "1px solid var(--border)", borderRadius: 8,
              background: "var(--surface2)", padding: "0 10px" }}>
              <input
                type={showKey ? "text" : "password"}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={isConfigured ? "粘贴新 Key 以替换" : currentProvider?.key_placeholder || ""}
                style={{ flex: 1, background: "none", border: "none", outline: "none",
                  fontSize: 13, color: "var(--text)", padding: "9px 0", fontFamily: "monospace" }}
              />
              <button onClick={() => setShowKey(!showKey)}
                style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text3)", padding: 2 }}>
                {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
            {isConfigured && (
              <button onClick={handleClearKey}
                title="清除已保存的 Key"
                style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid var(--border)",
                  background: "none", cursor: "pointer", color: "var(--text3)" }}>
                <Trash2 size={14} />
              </button>
            )}
          </div>
        </div>

        {/* Model select */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
            <label style={{ fontSize: 12, color: "var(--text3)" }}>
              模型
              {modelsSource === "live" && (
                <span style={{ marginLeft: 8, color: "#10B981", fontSize: 11 }}>
                  实时拉取 ({models.length})
                </span>
              )}
              {modelsSource === "fallback" && (
                <span style={{ marginLeft: 8, color: "#F59E0B", fontSize: 11 }}>
                  内置列表
                </span>
              )}
            </label>
            <button
              onClick={() => handleFetchModels(apiKey)}
              disabled={fetching || (!apiKey && !isConfigured)}
              style={{
                background: "none", border: "none",
                cursor: fetching || (!apiKey && !isConfigured) ? "default" : "pointer",
                color: "var(--p1)", fontSize: 11,
                display: "inline-flex", alignItems: "center", gap: 4,
                opacity: fetching || (!apiKey && !isConfigured) ? 0.4 : 1,
              }}
            >
              <RefreshCw size={11} style={{ animation: fetching ? "spin 1s linear infinite" : "none" }} />
              刷新
            </button>
          </div>

          {models.length > 0 ? (
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              style={{ width: "100%", padding: "9px 10px", borderRadius: 8, border: "1px solid var(--border)",
                background: "var(--surface2)", color: "var(--text)", fontSize: 13, outline: "none" }}
            >
              {models.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
              {model && !models.includes(model) && (
                <option value={model}>{model} (自定义)</option>
              )}
            </select>
          ) : (
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={currentProvider?.default_model || "输入模型名称"}
              style={{ width: "100%", padding: "9px 10px", borderRadius: 8, border: "1px solid var(--border)",
                background: "var(--surface2)", color: "var(--text)", fontSize: 13, outline: "none" }}
            />
          )}

          {modelsError && (
            <div style={{ fontSize: 11, color: "#F59E0B", marginTop: 6 }}>
              拉取失败：{modelsError}
            </div>
          )}
        </div>

        {/* Save */}
        <button
          onClick={handleSave}
          disabled={saving || !activeProvider || !model}
          style={{
            width: "100%", padding: "10px", borderRadius: 10, border: "none",
            background: saved ? "#10B981" : "linear-gradient(135deg, var(--p1), var(--p2))",
            color: "#fff", fontSize: 14, fontWeight: 600,
            cursor: saving || !activeProvider || !model ? "default" : "pointer",
            transition: "background .3s",
            opacity: saving || !activeProvider || !model ? 0.6 : 1,
          }}
        >
          {saved ? "已保存 ✓" : saving ? "保存中..." : "保存设置"}
        </button>

        <style>{`
          @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
          }
        `}</style>
      </div>
    </div>
  );
}
