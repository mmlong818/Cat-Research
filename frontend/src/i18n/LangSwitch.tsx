import { useT } from "./index";

/** 中/EN 切换按钮（顶栏）。 */
export default function LangSwitch() {
  const { lang, setLang, t } = useT();
  return (
    <button className="iconbtn lang" onClick={() => setLang(lang === "zh" ? "en" : "zh")} title={t("common.language")}>
      {lang === "zh" ? "EN" : "中"}
    </button>
  );
}
