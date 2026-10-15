import { useState } from "react";
import { Icon, type IconName } from "../ui/Icon";
import { loadTheme, saveTheme, type ThemePref } from "../../lib/theme";
import { useT, type TKey } from "../../i18n";

const OPTIONS: [ThemePref, IconName][] = [["auto", "monitor"], ["light", "sun"], ["dark", "moon"]];

/** 顶栏紧凑三格：跟随系统 / 浅色 / 深色，选择存 localStorage。 */
export function ThemeSwitch() {
  const { t } = useT();
  const [pref, setPref] = useState<ThemePref>(loadTheme);
  const pick = (p: ThemePref) => { saveTheme(p); setPref(p); };
  return (
    <div className="seg" role="group" aria-label={t("shell.theme")}>
      {OPTIONS.map(([p, icon]) => (
        <button key={p} className={pref === p ? "on" : ""} aria-pressed={pref === p}
                title={t(`shell.theme.${p}` as TKey)} onClick={() => pick(p)}>
          <Icon name={icon} />
        </button>
      ))}
    </div>
  );
}
