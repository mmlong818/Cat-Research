import { useState } from "react";
import { Icon } from "../../components/ui/Icon";
import { Score, Tick } from "../../components/ui/Score";
import { f2 } from "../../lib/format";
import type { ReviewRound, TokenUsage } from "../../lib/types";
import { useT, type TKey } from "../../i18n";
import { N, rich } from "../../i18n/rich";
import type { Dossier } from "./useDossier";
import type { Derived } from "./useDerived";
import { ScoreChart } from "./ScoreChart";
import { DIMS, QUALITY_THRESHOLD } from "./model";

function DimsTable({ reviews }: { reviews: ReviewRound[] }) {
  const { t } = useT();
  return (
    <div className="tbl">
      <table className="il dims">
        <thead><tr><th>{t("dossier.proc.dim")}</th>{reviews.map((r) => <th key={r.cycle} className="r">{t("dossier.proc.round", { n: r.cycle })}</th>)}</tr></thead>
        <tbody>
          {DIMS.map((k) => (
            <tr key={k}><td>{t(`dossier.dim.${k}` as TKey)}</td>
              {reviews.map((r) => (
                <td key={r.cycle} className="num r">{r.scores[k] != null ? <>{r.scores[k].toFixed(1)}<Tick score={r.scores[k]} /></> : ""}</td>
              ))}</tr>
          ))}
          <tr><td><strong>{t("dossier.proc.avg")}</strong></td>
            {reviews.map((r) => <td key={r.cycle} className="num r"><strong>{r.average_score != null ? f2(r.average_score) : ""}</strong></td>)}</tr>
        </tbody>
      </table>
    </div>
  );
}

const SEVERITY: Record<string, string> = { high: "down", medium: "warn", low: "" };

function RoundBody({ r }: { r: ReviewRound }) {
  const { t } = useT();
  const list = (items: string[]) => <ol className="plain-ol">{items.map((s, i) => <li key={i}>{s}</li>)}</ol>;
  return (
    <div className="bd">
      {r.critical_issues.length > 0 && (
        <div><h5>{t("dossier.proc.issues")}</h5>
          {r.critical_issues.map((i, k) => (
            <div className="issue-row" key={k}>
              <span><span className={`tag ${SEVERITY[i.severity ?? ""] ?? ""}`}>{t(`dossier.proc.sev.${i.severity ?? "low"}` as TKey)}</span></span>
              <span>{i.issue}{i.suggestion && <span className="muted">{t("dossier.proc.suggest", { s: i.suggestion })}</span>}</span>
            </div>
          ))}</div>
      )}
      {r.priority_improvements.length > 0 && <div><h5>{t("dossier.proc.todo")}</h5>{list(r.priority_improvements)}</div>}
      {r.strengths.length > 0 && <div><h5>{t("dossier.proc.strengths")}</h5>{list(r.strengths)}</div>}
    </div>
  );
}

function Rounds({ reviews }: { reviews: ReviewRound[] }) {
  const { t } = useT();
  const [open, setOpen] = useState<number | null>(reviews[reviews.length - 1]?.cycle ?? null);
  return (
    <>
      {[...reviews].reverse().map((r) => (
        <div className="round" key={r.cycle}>
          <button aria-expanded={open === r.cycle} onClick={() => setOpen(open === r.cycle ? null : r.cycle)}>
            <span className="muted">{t("dossier.proc.round", { n: r.cycle })}</span>
            <b>{t("dossier.proc.reviewOf", { n: r.cycle - 1 })}</b>
            <span className="sc">{r.average_score != null && <Score score={r.average_score} />}</span>
            <Icon name={open === r.cycle ? "caret-down" : "caret-right"} />
          </button>
          {open === r.cycle && <RoundBody r={r} />}
        </div>
      ))}
    </>
  );
}

function FinalChoice({ x }: { x: Derived }) {
  const { t } = useT();
  const v = x.finalDraft;
  const best = x.bestDraft;
  const violations = x.citations?.violations;
  const picked = { v: <N>{v}</N>, s: <N>{x.finalScore != null ? f2(x.finalScore) : ""}</N>, n: <N>{violations}</N> };
  return (
    <p className="dateline proc-why">
      {x.stopReason && rich(t("dossier.proc.stopped"), { n: <N>{x.cycles}</N>, r: x.stopReason })}
      {t("dossier.proc.rule")}
      {v != null && x.finalScore != null && (
        <>
          {rich(t(violations != null ? "dossier.proc.pickedClean" : "dossier.proc.picked"), picked)}
          {best === v && t("dossier.proc.alsoBest")}
          {best != null && best !== v && x.history[best] != null
            && rich(t("dossier.proc.bestHadIssues"), { b: <N>{best}</N>, s: <N>{f2(x.history[best])}</N> })}
          {(best == null || (best !== v && x.history[best] == null)) && t("dossier.lede.end")}
        </>
      )}
    </p>
  );
}

function Usage({ usage }: { usage: TokenUsage }) {
  const { t } = useT();
  const M = (v: number) => `${(v / 1e6).toFixed(2)}M`;
  const total = (u: { input: number; output: number }) => u.input + u.output;
  const agents = Object.entries(usage.by_agent ?? {}).sort((a, b) => total(b[1]) - total(a[1]));
  const max = agents[0] ? total(agents[0][1]) || 1 : 1;
  return (
    <>
      <div className="sec-h"><h3>{t("dossier.proc.usage")}</h3></div>
      <div className="jbars usage">
        {agents.map(([name, u]) => (
          <span className="jrow" key={name}><span>{name}</span>
            <span className="bar-t"><i style={{ width: `${(total(u) / max) * 100}%` }} /></span>
            <span className="num">{M(total(u))}</span></span>
        ))}
      </div>
      <p className="hint">{rich(t("dossier.proc.tokens"), {
        i: <N>{M(usage.total_input)}</N>, c: <N>{M(usage.total_cached_input ?? 0)}</N>, o: <N>{M(usage.total_output)}</N>,
      })}</p>
    </>
  );
}

/** 过程：评分轨迹、7 维 × N 轮、每轮评审要点、终稿选择理由、用量 */
export function ProcessTab({ d, x }: { d: Dossier; x: Derived }) {
  const { t } = useT();
  return (
    <>
      <div className="sec-h"><h3>{t("dossier.proc.trend")}</h3>
        <span className="meta">{rich(t("dossier.proc.trendMeta"), { n: <N>{x.cycles}</N>, th: <N>{f2(QUALITY_THRESHOLD)}</N> })}
          {x.finalDraft != null && rich(t("dossier.proc.trendFinal"), { v: <N>{x.finalDraft}</N> })}</span></div>
      <ScoreChart history={x.history} finalDraft={x.finalDraft} />
      <p className="hint">{t("dossier.proc.chartHint")}</p>
      {d.reviews.length > 0 && (
        <>
          <div className="block"><div className="sec-h"><h3>{t("dossier.proc.dims")}</h3><span className="meta">{t("dossier.proc.dimsMeta")}</span></div>
            <DimsTable reviews={d.reviews} /></div>
          <div className="block"><div className="sec-h"><h3>{t("dossier.proc.rounds")}</h3><span className="meta">{t("dossier.proc.roundsMeta")}</span></div>
            <Rounds reviews={d.reviews} /></div>
        </>
      )}
      <div className="block"><div className="sec-h"><h3>{x.finalDraft != null ? rich(t("dossier.proc.why"), { v: <N>{x.finalDraft}</N> }) : t("dossier.proc.whyUnknown")}</h3></div>
        <FinalChoice x={x} /></div>
      {d.usage && <div className="block"><Usage usage={d.usage} /></div>}
    </>
  );
}
