import { Icon } from "../../components/ui/Icon";
import { useT, type TKey } from "../../i18n";
import { setDraft, type DepthChoice, type Draft, type Lang } from "./draft";

const DEPTHS: DepthChoice[] = ["quick", "standard", "deep", "custom"];
const LANGS: Lang[] = ["zh", "en"];

function Stepper({ value, min, max, onChange }: { value: number; min: number; max: number; onChange: (n: number) => void }) {
  const { t } = useT();
  return (
    <span className="stepper">
      <button onClick={() => onChange(value - 1)} disabled={value <= min} aria-label={t("new.depth.less")}><Icon name="minus" small /></button>
      <span>{value}</span>
      <button onClick={() => onChange(value + 1)} disabled={value >= max} aria-label={t("new.depth.more")}><Icon name="plus" small /></button>
    </span>
  );
}

function DepthField({ d }: { d: Draft }) {
  const { t } = useT();
  const setMin = (n: number) => setDraft((x) => ({ ...x, minCycles: n, maxCycles: Math.max(n, x.maxCycles) }));
  const setMax = (n: number) => setDraft((x) => ({ ...x, maxCycles: n, minCycles: Math.min(n, x.minCycles) }));
  return (
    <div className="cf">
      <div className="flabel">{t("new.f.depth")}</div>
      <div className="seg lg" role="group" aria-label={t("new.f.depth")}>
        {DEPTHS.map((k) => (
          <button key={k} className={d.depth === k ? "on" : ""} aria-pressed={d.depth === k}
                  onClick={() => setDraft((x) => ({ ...x, depth: k }))}>{t(`new.depth.${k}` as TKey)}</button>
        ))}
      </div>
      <p className="hint mt-s">{t(`new.depth.spec.${d.depth}` as TKey)}</p>
      {d.depth === "custom" && (
        <div className="row mt-m">
          <span className="hint">{t("new.depth.min")}</span><Stepper value={d.minCycles} min={1} max={20} onChange={setMin} />
          <span className="hint">{t("new.depth.max")}</span><Stepper value={d.maxCycles} min={1} max={20} onChange={setMax} />
        </div>
      )}
    </div>
  );
}

function LangField({ d, uiLang }: { d: Draft; uiLang: Lang }) {
  const { t } = useT();
  const cur = d.lang ?? uiLang;
  return (
    <div className="cf">
      <div className="row">
        <span className="flabel">{t("new.f.lang")}</span><span className="sp" />
        <div className="seg" role="group" aria-label={t("new.f.lang")}>
          {LANGS.map((l) => (
            <button key={l} className={cur === l ? "on" : ""} aria-pressed={cur === l}
                    onClick={() => setDraft((x) => ({ ...x, lang: l }))}>{t(`common.lang.${l}` as TKey)}</button>
          ))}
        </div>
      </div>
      <p className="hint mt-s">{t("new.f.langHint")}</p>
    </div>
  );
}

function AskLoopField({ d }: { d: Draft }) {
  const { t } = useT();
  return (
    <div className="cf">
      <button className={`switch${d.askLoop ? " on" : ""}`} role="switch" aria-checked={d.askLoop}
              onClick={() => setDraft((x) => ({ ...x, askLoop: !x.askLoop }))}>
        <i className="trk" />{t("new.f.askLoop")}
      </button>
      <p className="hint mt-s">{t("new.f.askLoopHint")}</p>
    </div>
  );
}

/** 委托单上的办案设置：深度档、报告语言、改进轮中询问我 */
export function SettingsFields({ d, uiLang }: { d: Draft; uiLang: Lang }) {
  return (
    <>
      <DepthField d={d} />
      <LangField d={d} uiLang={uiLang} />
      <AskLoopField d={d} />
    </>
  );
}
