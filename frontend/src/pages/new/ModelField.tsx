import { useState } from "react";
import { PROVIDERS, type Provider, type SettingsInfo } from "../../lib/api";
import { modelLabel, modelName, providerName, useSettings } from "../../lib/useSettings";
import { useT } from "../../i18n";
import { setDraft, type ModelChoice } from "./draft";

/** 实际生效的提供方与主笔 / 协办型号：没换过就是设置里的默认配置档，换了提供方取该家默认 */
function effective(settings: SettingsInfo, c: ModelChoice) {
  const provider = c.provider === "default" ? settings.default_profile.provider : c.provider;
  const info = settings.providers[provider];
  const base = c.provider === "default" ? settings.default_profile : info.defaults;
  return { provider, info, core: c.core ?? base.core, support: c.support ?? base.support };
}

function ModelSelect({ label, value, models, onChange }: {
  label: string; value: string; models: SettingsInfo["providers"][Provider]["models"]; onChange: (id: string) => void;
}) {
  const { t } = useT();
  return (
    <label className="model-pick-row"><span className="hint">{label}</span>
      <select className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        {!models.some((m) => m.id === value) && <option value={value}>{modelName(value)}</option>}
        {models.map((m) => <option key={m.id} value={m.id}>{modelLabel(t, m)}</option>)}
      </select>
    </label>
  );
}

function Picker({ settings, value }: { settings: SettingsInfo; value: ModelChoice }) {
  const { t } = useT();
  const eff = effective(settings, value);
  const set = (c: ModelChoice) => setDraft((d) => ({ ...d, model: c }));
  return (
    <div className="model-pick">
      <label className="model-pick-row"><span className="hint">{t("new.f.provider")}</span>
        <select className="select" value={value.provider} onChange={(e) => set({ provider: e.target.value as ModelChoice["provider"] })}>
          <option value="default">{t("new.f.modelDefault", { name: providerName(settings.default_profile.provider) })}</option>
          {PROVIDERS.map((p) => (
            <option key={p} value={p} disabled={!settings.providers[p].available}>
              {settings.providers[p].available ? providerName(p) : t(p === "compat" ? "new.f.modelNotSet" : "new.f.modelNoKey", { name: providerName(p) })}
            </option>
          ))}
        </select>
      </label>
      <ModelSelect label={t("new.f.core")} value={eff.core} models={eff.info.models} onChange={(id) => set({ ...value, core: id })} />
      <ModelSelect label={t("new.f.support")} value={eff.support} models={eff.info.models} onChange={(id) => set({ ...value, support: id })} />
    </div>
  );
}

/** 承办模型：默认用设置里的默认配置档；"更换"后可临时换提供方或指定主笔 / 协办型号（只对这一份委托生效） */
export function ModelField({ value }: { value: ModelChoice }) {
  const { t } = useT();
  const settings = useSettings();
  const [open, setOpen] = useState(false);
  const eff = settings ? effective(settings, value) : null;
  return (
    <div className="cf">
      <div className="flabel">{t("new.f.model")}
        {settings && <span className="r"><button className="btn btn--link" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {t(open ? "new.f.modelDone" : "new.f.modelChange")}</button></span>}
      </div>
      {eff ? (
        <p className="model-line">{providerName(eff.provider)} · {t("new.f.core")} <span className="num">{modelName(eff.core)}</span>
          <span className="sep" />{t("new.f.support")} <span className="num">{modelName(eff.support)}</span></p>
      ) : <p className="hint">{t("new.f.modelLoading")}</p>}
      {settings && open && <Picker settings={settings} value={value} />}
      <p className="hint mt-s">{t("new.f.modelHint")}</p>
    </div>
  );
}
