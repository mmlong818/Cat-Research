import { X } from "lucide-react";
import { useT } from "../i18n";
import { SettingsBody } from "./settings/SettingsBody";
import { useSettingsForm } from "./settings/useSettingsForm";

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function SettingsModal({ open, onClose }: Props) {
  const f = useSettingsForm(open);
  const { t } = useT();

  if (!open) return null;

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,.45)",
        zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--surface)", borderRadius: 16, padding: 28,
          width: 560, maxWidth: "94vw", maxHeight: "90vh", overflowY: "auto",
          boxShadow: "0 12px 40px rgba(0,0,0,.25)", border: "1px solid var(--border)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: "var(--text)" }}>{t("common.settings")}</span>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text3)", padding: 4 }}>
            <X size={18} />
          </button>
        </div>

        {f.settings && f.draft && <SettingsBody f={f} settings={f.settings} draft={f.draft} />}
        {f.error && <div role="alert" style={{ fontSize: 12, color: "var(--danger)", marginBottom: 10, wordBreak: "break-word" }}>{f.error}</div>}

        <button
          onClick={f.save}
          disabled={f.saving || !f.draft}
          style={{
            width: "100%", padding: "10px", borderRadius: 10, border: "none", marginTop: 6,
            background: f.saved ? "#10B981" : "linear-gradient(135deg, var(--accent), var(--accent-hover))",
            color: "#fff", fontSize: 14, fontWeight: 600, cursor: f.saving ? "default" : "pointer",
            transition: "background .3s", opacity: f.draft ? 1 : 0.5,
          }}
        >
          {f.saved ? t("common.saved") : f.saving ? t("common.saving") : t("common.save")}
        </button>
      </div>
    </div>
  );
}
