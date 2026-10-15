import { Fragment, useState } from "react";
import { toast } from "sonner";
import { Icon } from "../../components/ui/Icon";
import { useT, type TKey } from "../../i18n";
import { N, rich } from "../../i18n/rich";
import { clock, decisionLeft, type CaseState, type Decision } from "../../lib/live/model";
import { live, useNow } from "../../lib/live/store";
import { clockTime, f2 } from "../../lib/format";
import type { ReviewRound } from "../../lib/types";

const THRESHOLD = 8.0; // config.QUALITY_THRESHOLD

function Countdown({ d }: { d: Decision }) {
  const { t } = useT();
  const left = decisionLeft(d, useNow(500));
  if (d.paused) return <span className="cd">{rich(t("case.so.cdPaused"), { t: <N>{clock(left)}</N> })}</span>;
  if (left <= 0) return <span className="cd">{t("case.so.cdOver")}</span>;
  return <span className="cd">{rich(t("case.so.cd"), { t: <N>{clock(left)}</N> })}</span>;
}

function Stats({ d, prev }: { d: Decision; prev: number | null }) {
  const { t } = useT();
  const min = d.estSeconds == null ? null : Math.max(1, Math.round(d.estSeconds / 60));
  const gain = d.gain == null ? "—" : `${d.gain >= 0 ? "+" : ""}${f2(d.gain)}`;
  return (
    <div className="so-stats">
      <div><span className="l">{t("case.so.best")}</span>
        <span className="v">{f2(d.bestScore)}<small>{t("case.so.bestDraft", { n: d.bestDraft })}</small></span>
        <div className="mark" style={{ width: `${Math.min(100, d.bestScore * 10)}%` }} /></div>
      <div><span className="l">{t("case.so.gain")}</span>
        <span className="v">{gain}{prev != null && d.score != null && <small>{t("case.so.gainFrom", { a: f2(prev), b: f2(d.score) })}</small>}</span></div>
      <div><span className="l">{t("case.so.violations")}</span>
        <span className="v">{d.violations}<small>{t("case.so.violUnit")}</small></span></div>
      <div><span className="l">{t("case.so.eta")}</span>
        {min == null ? <span className="v small">{t("case.so.etaNone")}</span>
          : <span className="v">{min}<small>{t("case.so.etaUnit")}</small></span>}</div>
    </div>
  );
}

function Trail({ scores }: { scores: number[] }) {
  const { t } = useT();
  return (
    <div className="so-trail">{t("case.so.trail")}
      {scores.map((s, i) => <Fragment key={i}>{i > 0 && <Icon name="arrow-right" />}<b>{f2(s)}</b></Fragment>)}
      <Icon name="arrow-right" /><span className="q">{t("case.so.again")}</span>
    </div>
  );
}

/** 复审签批单：loop_decision 到达时置顶；倒计时随暂停冻结；两个按钮各发一次 loop-decision */
export function SignOff({ s, reviews }: { s: CaseState; reviews: ReviewRound[] }) {
  const { t } = useT();
  const [busy, setBusy] = useState(false);
  const d = s.decision!;
  const scores = s.rounds.filter((r) => r.score != null).map((r) => r.score as number);
  const prev = scores.length >= 2 ? scores[scores.length - 2] : null;
  const todo = reviews.find((r) => r.cycle === d.bestDraft + 1)?.priority_improvements.slice(0, 2) ?? [];
  const choose = (choice: "continue" | "stop") => {
    setBusy(true);
    live.decide(s.taskId, choice).catch((e: Error) => toast.error(t("case.toast.failed", { m: e.message }))).finally(() => setBusy(false));
  };
  return (
    <section className="signoff" role="alertdialog" aria-label={t("case.so.title")}>
      <div className="double" />
      <div className="so-h"><h3>{t("case.so.title")}</h3>
        <span className="tag warn"><Icon name="pen" small />{t("case.so.tag")}</span><span className="sp" /><Countdown d={d} /></div>
      <p className="so-sub">{rich(t("case.so.sub"), { n: <N>{d.cycle}</N>, max: <N>{d.maxCycles}</N>, th: <N>{f2(THRESHOLD)}</N> })}</p>
      <Stats d={d} prev={prev} />
      {scores.length > 0 && <Trail scores={scores} />}
      {todo.length > 0 && (
        <div className="so-why">{t("case.so.why", { n: d.bestDraft })}<ol>{todo.map((x, i) => <li key={i}>{x}</li>)}</ol></div>
      )}
      <div className="so-acts">
        <button className="btn btn--primary" disabled={busy} onClick={() => choose("continue")}><Icon name="resume" />{t("case.so.continue")}</button>
        <button className="btn" disabled={busy} onClick={() => choose("stop")}><Icon name="check" />{t("case.so.stop", { n: d.bestDraft })}</button>
        <span className="hint">{t("case.so.foot", { m: Math.round(d.timeout / 60) })}</span>
      </div>
    </section>
  );
}

/** 签批之后的回执（直到下一轮开始） */
export function SignReceipt({ s }: { s: CaseState }) {
  const { t } = useT();
  if (!s.decided || s.decision) return null;
  const later = s.rounds.some((r) => r.cycle > s.decided!.cycle);
  if (later) return null;
  return (
    <div className="receipt so-receipt"><Icon name="check" />
      <p>{t(`case.so.done.${s.decided.choice}` as TKey)}</p>
      <span className="hint">{rich(t("case.so.doneAt"), { t: <N>{clockTime(s.decided.at)}</N> })}</span>
    </div>
  );
}
