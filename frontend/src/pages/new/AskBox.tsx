import { Icon } from "../../components/ui/Icon";
import { MAX_ACTIVE } from "../../components/shell/useDesk";
import { useT } from "../../i18n";
import { setDraft, type Draft } from "./draft";
import type { Busy, Failure } from "./useCommission";

const EXAMPLES = [1, 2, 3] as const;

function Examples() {
  const { t } = useT();
  return (
    <div className="block">
      <div className="sec-h"><h3>{t("new.examples.title")}</h3><span className="meta">{t("new.examples.meta")}</span></div>
      {EXAMPLES.map((i) => (
        <button className="brief" key={i} onClick={() => setDraft((d) => ({ ...d, question: t(`new.examples.q${i}`) }))}>
          <span className="rk">{i}</span>
          <h4>{t(`new.examples.q${i}`)}</h4>
          <span className="meta">{t(`new.examples.w${i}`)}</span>
        </button>
      ))}
    </div>
  );
}

function Tips() {
  const { t } = useT();
  return (
    <div className="block">
      <div className="sec-h"><h3>{t("new.tips.title")}</h3></div>
      <ol className="mech">
        {EXAMPLES.map((i) => <li key={i}><b>{t(`new.tips.h${i}`)}</b>：{t(`new.tips.b${i}`)}</li>)}
      </ol>
    </div>
  );
}

/** 第 1 步 · 空状态：唯一的输入是一句话问题框；交给研究助理，或跳过提问直接去填委托单；下面是示例与好问题的三个要素 */
export function AskBox({ d, active, busy, failure, onAsk, onSkip }: {
  d: Draft; active: number; busy: Busy; failure: Failure | null; onAsk: () => void; onSkip: () => void;
}) {
  const { t } = useT();
  const q = d.question.trim();
  const full = active >= MAX_ACTIVE;
  const room = full ? t("new.ask.full", { n: active }) : active > 0 ? t("new.ask.active", { n: active, m: MAX_ACTIVE - active }) : "";
  return (
    <>
      <h2 className="ask-big">{t("new.ask.title")}</h2>
      <div className="qbox">
        <textarea value={d.question} aria-label={t("new.ask.label")} placeholder={t("new.ask.ph", { q: t("new.examples.q1") })}
                  onChange={(e) => setDraft((x) => ({ ...x, question: e.target.value }))}
                  onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) onAsk(); }} />
        <div className="row">
          <span className="hint">{t("new.ask.hint")}{room && <><br />{room}</>}</span>
          <span className="sp" />
          <button className="btn btn--primary" onClick={onAsk} disabled={!q || busy !== null}><Icon name="send" />{t("new.ask.submit")}</button>
        </div>
      </div>
      {failure?.kind === "clarify" && (
        <div className="banner mt-m" role="alert"><Icon name="warning" /><span>{t("new.err.clarify", { msg: failure.message })}</span></div>
      )}
      <p className="skip-line hint">{t("new.skip.lead")}
        <button className="btn btn--link" onClick={onSkip} disabled={busy !== null}>{t("new.ask.skip")}<Icon name="arrow-right" /></button></p>
      <Examples />
      <Tips />
    </>
  );
}
