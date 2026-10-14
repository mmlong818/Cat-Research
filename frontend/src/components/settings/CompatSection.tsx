import { useState } from "react";
import { config as configApi } from "../../lib/api";
import type { CompatTestResult, KeyView } from "../../lib/api";
import { useT } from "../../i18n";
import { KeyField } from "./KeyField";
import { field, label, note, sectionTitle } from "./styles";
import type { CompatForm } from "./useSettingsForm";

function TextField({ title, value, placeholder, onChange }: {
  title: string; value: string; placeholder: string; onChange: (v: string) => void;
}) {
  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <label style={label}>{title}</label>
      <input type="text" value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)}
        autoComplete="off" spellCheck={false} style={field} />
    </div>
  );
}

function TestResult({ r }: { r: CompatTestResult | { error: string } }) {
  const { t } = useT();
  const ok = "ok" in r && r.ok;
  const text = "error" in r ? t("common.compat.testError", { msg: r.error })
    : t(r.ok ? (r.tool_calls ? "common.compat.testOk" : "common.compat.testNoTools") : "common.compat.testFail", { ms: r.latency_ms });
  return (
    <div role="status" style={{ fontSize: 12, color: ok ? "var(--success)" : "var(--danger)", wordBreak: "break-word" }}>
      <div>{text}</div>
      {!ok && "detail" in r && r.detail && <div style={{ color: "var(--text3)", marginTop: 2 }}>{r.detail}</div>}
    </div>
  );
}

interface Props {
  info: KeyView;
  form: CompatForm;
  keyInput: string;
  onForm: (f: CompatForm) => void;
  onKeyInput: (v: string) => void;
  onClearKey: () => void;
}

/** 测试连接用表单里现填的值（没填的项服务端用已保存的），不保存 */
export function CompatSection({ info, form, keyInput, onForm, onKeyInput, onClearKey }: Props) {
  const { t } = useT();
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<CompatTestResult | { error: string } | null>(null);
  const set = (k: keyof CompatForm) => (v: string) => onForm({ ...form, [k]: v });

  async function runTest() {
    setTesting(true);
    setResult(null);
    const body = { base_url: form.base_url.trim(), api_key: keyInput.trim(), model: form.core.trim() };
    try {
      setResult(await configApi.testCompat(Object.fromEntries(Object.entries(body).filter(([, v]) => v))));
    } catch (e) {
      setResult({ error: e instanceof Error ? e.message : String(e) });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={sectionTitle}>{t("common.compat.title")}</div>
      <div style={{ marginBottom: 14 }}>
        <TextField title={t("common.compat.baseUrl")} value={form.base_url} onChange={set("base_url")}
          placeholder={t("common.compat.baseUrlPlaceholder")} />
      </div>
      <KeyField name="compat" info={info} value={keyInput} onChange={onKeyInput} onClear={onClearKey} />
      <div style={{ display: "flex", gap: 8, marginBottom: 6 }}>
        <TextField title={t("common.compat.core")} value={form.core} onChange={set("core")} placeholder={t("common.compat.modelPlaceholder")} />
        <TextField title={t("common.compat.support")} value={form.support} onChange={set("support")} placeholder={t("common.compat.modelPlaceholder")} />
      </div>
      <div style={note}>{t("common.compat.note")}</div>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginTop: 10 }}>
        <button type="button" onClick={runTest} disabled={testing}
          style={{ padding: "7px 14px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface2)",
            color: "var(--text)", fontSize: 13, cursor: testing ? "default" : "pointer", opacity: testing ? 0.6 : 1, flexShrink: 0 }}>
          {testing ? t("common.compat.testing") : t("common.compat.test")}
        </button>
        {result && <TestResult r={result} />}
      </div>
    </div>
  );
}
