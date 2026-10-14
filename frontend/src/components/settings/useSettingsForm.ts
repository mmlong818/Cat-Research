import { useEffect, useState } from "react";
import { config as configApi, PROVIDERS, SEARCH_BACKENDS } from "../../lib/api";
import type { CompatUpdate, KeyName, ProfileChoice, Provider, SearchBackend, SettingsInfo, SettingsUpdate } from "../../lib/api";
import { modelName, notifySettingsChanged } from "../../lib/useSettings";
import { useT } from "../../i18n";

export type KeyInputs = Record<KeyName, string>;
export interface CompatForm { base_url: string; core: string; support: string }

const KEY_NAMES: KeyName[] = [...new Set<KeyName>([...PROVIDERS, ...SEARCH_BACKENDS])];
const EMPTY_INPUTS = Object.fromEntries(KEY_NAMES.map((n) => [n, ""])) as KeyInputs;
const NOT_READY: Record<Provider, boolean> = { claude: false, openai: false, zhipu: false, compat: false };
const COMPAT_FIELDS = ["base_url", "core", "support"] as const;

const compatFrom = (s: SettingsInfo): CompatForm => ({
  base_url: s.providers.compat.base_url ?? "",
  core: modelName(s.providers.compat.defaults.core),
  support: modelName(s.providers.compat.defaults.support),
});

/** 各提供方现在能不能选：已可用，或表单里已补齐所需项（未保存也算） */
function readiness(s: SettingsInfo, inputs: KeyInputs, compat: CompatForm): Record<Provider, boolean> {
  const typed = (n: KeyName) => inputs[n].trim() !== "";
  const compatOk = (s.providers.compat.has_key || typed("compat"))
    && [compat.base_url, compat.core, compat.support].every((v) => v.trim() !== "");
  return {
    claude: s.providers.claude.available || typed("claude"),
    openai: s.providers.openai.available || typed("openai"),
    zhipu: s.providers.zhipu.available || typed("zhipu"),
    compat: compatOk,
  };
}

/** 只提交改过的字段；兼容端点作默认提供方时不带模型名，由服务端取同一请求里的 compat 设置 */
function buildUpdate(s: SettingsInfo, draft: ProfileChoice, inputs: KeyInputs, compat: CompatForm, backend: SearchBackend): SettingsUpdate {
  const api_keys = Object.fromEntries(KEY_NAMES.filter((n) => inputs[n].trim()).map((n) => [n, inputs[n].trim()]));
  const body: SettingsUpdate = { default_profile: draft.provider === "compat" ? { provider: "compat" } : draft, api_keys };
  const before = compatFrom(s);
  const changed = COMPAT_FIELDS.filter((f) => compat[f].trim() !== before[f]);
  if (changed.length) body.compat = Object.fromEntries(changed.map((f) => [f, compat[f].trim()])) as CompatUpdate;
  if (backend !== s.search.backend) body.search_backend = backend;
  return body;
}

/** 保存成功后短暂显示"已保存" */
function useFlash(ms = 2000): [boolean, () => void] {
  const [on, setOn] = useState(false);
  return [on, () => { setOn(true); setTimeout(() => setOn(false), ms); }];
}

export function useSettingsForm(open: boolean) {
  const { t } = useT();
  const [settings, setSettings] = useState<SettingsInfo | null>(null);
  const [draft, setDraft] = useState<ProfileChoice | null>(null);
  const [inputs, setInputs] = useState<KeyInputs>(EMPTY_INPUTS);
  const [compat, setCompat] = useState<CompatForm>({ base_url: "", core: "", support: "" });
  const [backend, setBackend] = useState<SearchBackend>("zhipu");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, flashSaved] = useFlash();
  const fail = (e: unknown) => setError(t("common.saveFailed", { msg: e instanceof Error ? e.message : String(e) }));

  const apply = (s: SettingsInfo) => {
    setSettings(s); setDraft(s.default_profile); setInputs(EMPTY_INPUTS); setCompat(compatFrom(s)); setBackend(s.search.backend);
  };

  useEffect(() => {
    if (!open) return;
    setError("");
    configApi.get().then(apply).catch(() => setError(t("common.settingsLoadFailed")));
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  async function save() {
    if (!settings || !draft) return;
    setSaving(true); setError("");
    try {
      apply(await configApi.update(buildUpdate(settings, draft, inputs, compat, backend)));
      notifySettingsChanged();
      flashSaved();
    } catch (e) {
      fail(e);
    } finally {
      setSaving(false);
    }
  }

  async function clear(name: KeyName) {
    try {
      setSettings(await configApi.clearKey(name));
      setInputs((i) => ({ ...i, [name]: "" }));
      notifySettingsChanged();
    } catch (e) {
      fail(e);
    }
  }

  const ready = settings ? readiness(settings, inputs, compat) : NOT_READY;
  const setInput = (name: KeyName, v: string) => setInputs((i) => ({ ...i, [name]: v }));
  return { settings, draft, setDraft, inputs, setInput, compat, setCompat, backend, setBackend, ready, error, saving, saved, save, clear };
}
