import { useState } from "react";
import { Settings } from "lucide-react";
import SettingsModal from "./SettingsModal";

export default function Topbar({ online }: { online?: boolean }) {
  const [showSettings, setShowSettings] = useState(false);

  return (
    <>
      <header
        style={{
          height: "var(--topbar-h)",
          background: "var(--surface)",
          borderBottom: "1px solid var(--border)",
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          padding: "0 20px",
          gap: 16,
          zIndex: 100,
          boxShadow: "0 1px 3px rgba(184,114,26,.08)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, flex: 1 }}>
          <img src="/logo.png" alt="logo" style={{ width: 40, height: 40, borderRadius: 10, objectFit: "cover" }} />
          <div style={{ fontSize: 15, fontWeight: 700, background: "linear-gradient(135deg, #B8721A, #7A3F00)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
            猫叔的深思熟虑
          </div>
          <span style={{ fontSize: 11, color: "var(--text3)", marginLeft: 4 }}>
            多智能体深度研究
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            onClick={() => setShowSettings(true)}
            title="设置"
            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text3)", padding: 6, display: "flex", alignItems: "center" }}
          >
            <Settings size={16} />
          </button>
          <div
            style={{
              width: 7, height: 7, borderRadius: "50%",
              background: online ? "var(--success)" : "var(--border2)",
              boxShadow: online ? "0 0 0 3px rgba(16,185,129,.2)" : "none",
              transition: "all .3s",
            }}
          />
          <span style={{ fontSize: 11, color: "var(--text3)" }}>{online ? "在线" : "离线"}</span>
        </div>
      </header>
      <SettingsModal open={showSettings} onClose={() => setShowSettings(false)} />
    </>
  );
}
