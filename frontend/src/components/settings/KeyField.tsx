import { useState } from "react";
import { Eye, EyeOff, Trash2 } from "lucide-react";
import type { KeyName, KeyView } from "../../lib/api";
import { useT, type TKey } from "../../i18n";
import { field, label, note } from "./styles";

interface Props {
  name: KeyName;
  info: KeyView;
  value: string;
  onChange: (v: string) => void;
  onClear: () => void;
  hint?: string;
}

/** 一个 API Key 的状态（已配置 …末 4 位）、替换输入框与清除按钮 */
export function KeyField({ name, info, value, onChange, onClear, hint }: Props) {
  const { t } = useT();
  const [show, setShow] = useState(false);
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={label}>{t(`common.keyLabel.${name}` as TKey)}</label>
      {hint && <div style={note}>{hint}</div>}
      <div style={{ fontSize: 12, marginBottom: 6, color: info.has_key ? "var(--success)" : "var(--text4)" }}>
        {info.has_key ? t("common.keyConfigured", { last4: info.key_preview.slice(-4) }) : t("common.keyMissing")}
        {info.key_source === "env" && ` ${t("common.keyFromEnv")}`}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <div style={{ ...field, flex: 1, display: "flex", alignItems: "center", padding: "0 10px" }}>
          <input
            type={show ? "text" : "password"} value={value} onChange={(e) => onChange(e.target.value)}
            placeholder={t("common.keyPlaceholder")} autoComplete="off"
            style={{ flex: 1, background: "none", border: "none", outline: "none", fontSize: 13, color: "var(--text)", padding: "8px 0" }}
          />
          <button type="button" onClick={() => setShow(!show)}
            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text3)", padding: 2 }}>
            {show ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        </div>
        {info.key_source === "keyring" && (
          <button type="button" onClick={onClear} title={t("common.keyClearTip")} aria-label={t("common.keyClear")}
            style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "none", cursor: "pointer", color: "var(--text3)" }}>
            <Trash2 size={14} />
          </button>
        )}
      </div>
    </div>
  );
}
