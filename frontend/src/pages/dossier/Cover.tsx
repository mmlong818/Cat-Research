import type { ReactNode } from "react";
import { Link } from "wouter";
import { Icon } from "../../components/ui/Icon";
import { Stamp } from "../../components/ui/Stamp";
import { f2, minutes, plainQuestion } from "../../lib/format";
import { useT, type TKey } from "../../i18n";
import { N, rich } from "../../i18n/rich";
import type { Dossier } from "./useDossier";
import type { Derived } from "./useDerived";
import { InlineText } from "./ClaimParts";
import { ConfidenceSide } from "./ConfidenceSide";
import { tabHref, type Tab } from "./DossierChrome";

/** 导语：用真实数字拼成一句话；缺哪项数据就略过哪一段 */
function Lede({ d, x }: { d: Dossier; x: Derived }) {
  const { t } = useT();
  const elapsed = d.entry?.elapsed_seconds;
  const L = d.ledger?.counts;
  const parts: ReactNode[] = [];
  if (elapsed != null) parts.push(rich(t("dossier.lede.effort"), { min: <N>{minutes(elapsed)}</N> }));
  if (L) {
    const work = { s: <N>{L.sources}</N>, c: <N>{L.claims}</N>, x: <N>{L.contradictions}</N>, q: <N>{d.queries}</N> };
    parts.push(rich(t(d.queries != null ? "dossier.lede.work" : "dossier.lede.workNoQueries"), work));
  }
  if (x.cycles) {
    const loop = { n: <N>{x.cycles}</N>, v: <N>{x.finalDraft}</N> };
    parts.push(rich(t(x.finalDraft != null ? "dossier.lede.loop" : "dossier.lede.loopNoFinal"), loop));
  }
  const cited = x.citations?.cited_claims ?? x.cited;
  const violations = x.citations?.violations;
  const coverage = x.citations?.numeric_coverage;
  if (cited) {
    parts.push(<>
      {rich(t("dossier.lede.cite"), { n: <N>{cited}</N> })}
      {violations != null && rich(t("dossier.lede.violations"), { v: <N>{violations}</N> })}
      {coverage != null && rich(t("dossier.lede.coverage"), { p: <N>{`${(coverage * 100).toFixed(1)}%`}</N> })}
    </>);
  }
  if (!parts.length) return null;
  return (
    <p className="dateline">
      {parts.map((p, i) => <span key={i}>{i > 0 && t("dossier.lede.sep")}{p}</span>)}{t("dossier.lede.end")}
    </p>
  );
}

/** 标题在「与 / 和 / 及」处分成两段，各段内不断行（宽屏），避免把一个词劈在两行 */
function Title({ text }: { text: string }) {
  const k = text.search(/[与和及]/);
  if (k <= 4 || k >= text.length - 4) return <>{text}</>;
  return <><span className="nw">{text.slice(0, k)}</span><span className="nw">{text.slice(k)}</span></>;
}

function Lead({ d, x }: { d: Dossier; x: Derived }) {
  const { t } = useT();
  const s = x.summary;
  const facts = [d.entry?.depth && t(`dossier.depth.${d.entry.depth}` as TKey), d.entry?.language && t(`common.lang.${d.entry.language}` as TKey)];
  return (
    <article className="lead">
      <div className="kicker">
        {t("dossier.cover.kicker")}
        <span>{facts.filter(Boolean).join(" / ")}</span>
        <Stamp status={d.entry?.status ?? "completed"} />
        {x.finalDraft != null && x.finalScore != null && (
          <span className="stamp gold">{rich(t("dossier.cover.final"), { v: <N>{x.finalDraft}</N>, s: <N>{f2(x.finalScore)}</N> })}</span>
        )}
      </div>
      <h2><Title text={plainQuestion(d.meta.question || d.entry?.question || "")} /></h2>
      {s?.dek && <p className="dek"><InlineText text={s.dek} sid={d.sid} claims={x.claims} /></p>}
      {s && s.conclusions.length > 0 && (
        <ol className="conc">
          {s.conclusions.map((c, i) => (
            <li key={i}><div><b><InlineText text={c.head} sid={d.sid} claims={x.claims} /></b>
              {c.text && <p><InlineText text={c.text} sid={d.sid} claims={x.claims} /></p>}</div></li>
          ))}
        </ol>
      )}
      <div className="acts">
        <Link className="btn btn--primary btn--lg" href={tabHref(d.sid, "text")}><Icon name="book" />{t("dossier.cover.open")}</Link>
        <Link className="btn" href={tabHref(d.sid, "evidence")}>{t("dossier.cover.check")} <N>{d.ledger?.counts.claims ?? 0}</N></Link>
        <Link className="btn" href={tabHref(d.sid, "verdict")}>{t("dossier.cover.verdicts")} <N>{d.ledger?.counts.contradictions ?? 0}</N></Link>
        <span className="hint">{t("dossier.cover.hint")}</span>
      </div>
    </article>
  );
}

function SectionStrip({ d, x }: { d: Dossier; x: Derived }) {
  const { t } = useT();
  const cols: [Tab, string][] = [
    ["text", t("dossier.idx.chapters", { n: x.sections.length })],
    ["evidence", t("dossier.strip.claims", { n: d.ledger?.counts.claims ?? 0 })],
    ["verdict", t("dossier.strip.contradictions", { n: d.ledger?.counts.contradictions ?? 0 })],
    ["process", t("dossier.idx.rounds", { n: x.cycles })],
    ["files", t("dossier.idx.versions", { n: d.drafts.filter((f) => f.kind === "draft").length })],
  ];
  return (
    <div className="sections">
      {cols.map(([k, count]) => (
        <section className="col" key={k}>
          <div className="col-h"><h3>{t(`dossier.tab.${k}` as TKey)}</h3><span>{count}</span></div>
          <div className="item">
            <p>{t(`dossier.strip.${k}` as TKey)}</p>
            <Link className="rest" href={tabHref(d.sid, k)}>{t("dossier.strip.open")} <Icon name="arrow-right" /></Link>
          </div>
        </section>
      ))}
    </div>
  );
}

/** 封面：导语、结论与可信度，下接五个页签的入口 */
export function Cover({ d, x }: { d: Dossier; x: Derived }) {
  return (
    <>
      <Lede d={d} x={x} />
      <div className="front">
        <Lead d={d} x={x} />
        {d.confidence && <ConfidenceSide c={d.confidence} disputed={x.counts.disputed} />}
      </div>
      <SectionStrip d={d} x={x} />
    </>
  );
}
