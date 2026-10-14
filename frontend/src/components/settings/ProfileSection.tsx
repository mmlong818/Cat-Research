import { PROVIDERS } from "../../lib/api";
import type { ModelInfo, ProfileChoice, Provider, SettingsInfo } from "../../lib/api";
import { modelLabel, modelName, providerName } from "../../lib/useSettings";
import { useT } from "../../i18n";
import { field, label, note } from "./styles";

function ModelSelect({ title, tip, value, models, onChange }: {
  title: string; tip: string; value: string; models: ModelInfo[]; onChange: (id: string) => void;
}) {
  const { t } = useT();
  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <label style={label} title={tip}>{title}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)} style={field}>
        {!models.some((m) => m.id === value) && <option value={value}>{modelName(value)}</option>}
        {models.map((m) => <option key={m.id} value={m.id}>{modelLabel(t, m)}</option>)}
      </select>
    </div>
  );
}

function ProviderRadio({ provider, checked, enabled, onSelect }: {
  provider: Provider; checked: boolean; enabled: boolean; onSelect: () => void;
}) {
  const { t } = useT();
  const tip = provider === "compat" ? t("common.compatNeedsSetup") : t("common.providerNeedsKey");
  return (
    <button
      type="button" role="radio" aria-checked={checked} disabled={!enabled} onClick={onSelect}
      title={enabled ? undefined : tip}
      style={{
        flex: 1, padding: "9px 6px", borderRadius: 8, fontSize: 13, fontWeight: checked ? 700 : 500,
        border: `1px solid ${checked ? "var(--accent)" : "var(--border)"}`,
        background: checked ? "var(--accent-dim)" : "var(--surface2)",
        color: checked ? "var(--accent)" : "var(--text)",
        opacity: enabled ? 1 : 0.45, cursor: enabled ? "pointer" : "not-allowed",
      }}
    >
      {providerName(provider)}
    </button>
  );
}

interface Props {
  settings: SettingsInfo;
  draft: ProfileChoice;
  /** 各提供方在当前表单下是否可选：已可用，或表单里已补齐所需项 */
  ready: Record<Provider, boolean>;
  /** 表单里现填的兼容端点模型名（可能还没保存） */
  compatModels: { core: string; support: string };
  onChange: (p: ProfileChoice) => void;
}

export function ProfileSection({ settings, draft, ready, compatModels, onChange }: Props) {
  const { t } = useT();
  const isCompat = draft.provider === "compat";
  const models = settings.providers[draft.provider]?.models ?? [];
  const pick = (provider: Provider) => {
    const { core, support } = settings.providers[provider].defaults;
    onChange({ provider, core, support });
  };
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={label}>{t("common.defaultProvider")}</div>
      <div role="radiogroup" style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        {PROVIDERS.map((p) => (
          <ProviderRadio key={p} provider={p} checked={draft.provider === p} enabled={ready[p]} onSelect={() => pick(p)} />
        ))}
      </div>
      {isCompat ? (
        <div style={{ fontSize: 12, color: "var(--text3)", wordBreak: "break-all" }}>
          {t("common.compat.profileLine", { core: compatModels.core || "-", support: compatModels.support || "-" })}
        </div>
      ) : (
        <>
          <div style={{ display: "flex", gap: 8 }}>
            <ModelSelect title={t("common.coreModel")} tip={t("common.coreModelTip")} value={draft.core} models={models}
              onChange={(core) => onChange({ ...draft, core })} />
            <ModelSelect title={t("common.supportModel")} tip={t("common.supportModelTip")} value={draft.support} models={models}
              onChange={(support) => onChange({ ...draft, support })} />
          </div>
          <div style={{ ...note, marginTop: 6, marginBottom: 0 }}>{t("common.priceHint")}</div>
        </>
      )}
    </div>
  );
}
