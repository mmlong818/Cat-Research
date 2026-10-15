export type ThemePref = "auto" | "light" | "dark";

const KEY = "cr.theme";

export function loadTheme(): ThemePref {
  const saved = localStorage.getItem(KEY);
  return saved === "light" || saved === "dark" ? saved : "auto";
}

/** 跟随系统 = 不设 data-theme，由 tokens.css 的 prefers-color-scheme 接管。 */
export function applyTheme(pref: ThemePref) {
  const root = document.documentElement;
  if (pref === "auto") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", pref);
}

export function saveTheme(pref: ThemePref) {
  localStorage.setItem(KEY, pref);
  applyTheme(pref);
}
