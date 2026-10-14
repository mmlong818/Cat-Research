import { useCallback, useEffect, useState } from "react";
import { config, PROVIDERS, type ModelInfo, type SettingsInfo } from "./api";
import { translate, type TFunc, type TKey } from "../i18n";

const CHANGED = "cat-settings-changed";

/** 设置保存后调用，让所有用到 useSettings 的组件重新取数。 */
export const notifySettingsChanged = () => window.dispatchEvent(new Event(CHANGED));

/** 当前设置（默认配置档、各提供方可用性与模型表）；取数失败时为 null。 */
export function useSettings(): SettingsInfo | null {
  const [settings, setSettings] = useState<SettingsInfo | null>(null);
  const load = useCallback(() => { config.get().then(setSettings).catch(() => setSettings(null)); }, []);
  useEffect(() => {
    load();
    window.addEventListener(CHANGED, load);
    return () => window.removeEventListener(CHANGED, load);
  }, [load]);
  return settings;
}

/** 提供方的显示名；未知提供方（旧数据）原样返回。 */
export const providerName = (p: string | null | undefined): string =>
  (PROVIDERS as readonly string[]).includes(p ?? "") ? translate(`common.provider.${p}` as TKey) : (p ?? "");

/** compat 模型 ID 形如 "compat:名字"，界面只显示名字。 */
export const modelName = (id: string): string => id.replace(/^compat:/, "");

/** 下拉里的模型文案：型号 · 价格（美元/百万 token，输入/输出）；withTier 时再加价格档。兼容端点不计 token 价格，只显示名字。 */
export const modelLabel = (t: TFunc, m: ModelInfo, withTier = true): string =>
  m.id.startsWith("compat:") ? modelName(m.id)
    : `${m.id} · $${m.input_price}/$${m.output_price}${withTier ? ` · ${t(`common.tier.${m.tier}` as TKey)}` : ""}`;
