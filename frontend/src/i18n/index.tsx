import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import common from "./common";
import shell from "./shell";
import dossier from "./dossier";
import commission from "./commission";
import caseLog from "./case";
import cabinet from "./cabinet";

// 每个模块：{ zh: {键: 中文}, en: {同样的键: 英文} }，键加模块前缀避免冲突
const zh = { ...common.zh, ...shell.zh, ...dossier.zh, ...commission.zh, ...caseLog.zh, ...cabinet.zh };
const en: Record<keyof typeof zh, string> = {
  ...common.en, ...shell.en, ...dossier.en, ...commission.en, ...caseLog.en, ...cabinet.en,
};

export type Lang = "zh" | "en";
export type TKey = keyof typeof zh;
export type TFunc = (key: TKey, vars?: Record<string, string | number>) => string;

const DICTS: Record<Lang, Record<TKey, string>> = { zh, en };
const STORAGE_KEY = "cr.lang";

function initialLang(): Lang {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === "zh" || saved === "en") return saved;
  return navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
}

let current: Lang = initialLang();

/** 组件外（如 window.confirm）用的翻译；组件内用 useT()，语言切换时才会重新渲染。 */
export const translate: TFunc = (key, vars) => {
  let s = DICTS[current][key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{{${k}}}`).join(String(v));
  return s;
};

const Ctx = createContext<{ lang: Lang; setLang: (l: Lang) => void; t: TFunc }>({
  lang: current, setLang: () => {}, t: translate,
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(current);
  useEffect(() => { document.documentElement.lang = lang === "zh" ? "zh-CN" : "en"; }, [lang]);
  const setLang = useCallback((l: Lang) => {
    current = l;
    localStorage.setItem(STORAGE_KEY, l);
    setLangState(l);
  }, []);
  // t 随 lang 换新引用，依赖它的 useCallback/useEffect 会更新
  const t = useCallback<TFunc>((key, vars) => translate(key, vars), [lang]); // eslint-disable-line react-hooks/exhaustive-deps
  return <Ctx.Provider value={{ lang, setLang, t }}>{children}</Ctx.Provider>;
}

export const useT = () => useContext(Ctx);

/** 日期时间按当前语言格式化 */
export const locale = (lang: Lang) => (lang === "zh" ? "zh-CN" : "en-US");
