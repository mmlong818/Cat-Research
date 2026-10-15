import type { ConfidenceBreakdownItem, ConfidenceReport } from "../../lib/types";
import { f2, host, webUrl } from "../../lib/format";
import { useT, type TKey } from "../../i18n";
import { Mixed, N, rich } from "../../i18n/rich";

const num = (item?: ConfidenceBreakdownItem, key = "score") => (typeof item?.[key] === "number" ? (item[key] as number) : null);
const str = (item?: ConfidenceBreakdownItem, key = "") => (typeof item?.[key] === "string" ? (item[key] as string) : "");

/** 白话解释的第一句：按等级与三项高低给出拿去用的态度 */
function headlineKey(c: ConfidenceReport): TKey {
  const b = c.breakdown ?? {};
  const level = c.confidence_level ?? "medium";
  if (level !== "medium") return `dossier.conf.head.${level}` as TKey;
  const cv = num(b.conclusion_validity) ?? 0;
  return cv >= Math.max(num(b.source_quality) ?? 0, num(b.fact_accuracy) ?? 0)
    ? "dossier.conf.head.mediumConclusion" : "dossier.conf.head.medium";
}

function ConfidenceNote({ c, disputed }: { c: ConfidenceReport; disputed: number }) {
  const { t } = useT();
  const b = c.breakdown ?? {};
  const word = (prefix: string, v: string) => (v ? t(`${prefix}.${v}` as TKey) : "");
  return (
    <p className="conf-note">
      <strong>{t(headlineKey(c))}</strong>
      {rich(t("dossier.conf.explain"), {
        cv: <N>{f2(num(b.conclusion_validity) ?? 0)}</N>, verdict: word("dossier.conf.verdict", str(b.conclusion_validity, "overall_verdict")),
        sq: <N>{f2(num(b.source_quality) ?? 0)}</N>, rating: word("dossier.conf.rating", str(b.source_quality, "quality_rating")),
        n: <N>{num(b.fact_accuracy, "claims_checked") ?? 0}</N>, fa: <N>{f2(num(b.fact_accuracy) ?? 0)}</N>,
      })}
      {disputed > 0 ? rich(t("dossier.conf.adviceDisputed"), { d: <N>{disputed}</N> }) : t("dossier.conf.advice")}
    </p>
  );
}

const ROWS = [["conclusion_validity", "dossier.conf.conclusion"], ["fact_accuracy", "dossier.conf.fact"], ["source_quality", "dossier.conf.source"]] as const;

function Breakdown({ c }: { c: ConfidenceReport }) {
  const { t } = useT();
  const b = c.breakdown ?? {};
  const terms = ROWS.map(([k]) => `${(num(b[k]) ?? 0).toFixed(3)} × ${b[k]?.weight ?? ""}`).join(" + ");
  return (
    <>
      <div className="jbars">
        {ROWS.map(([k, label]) => (
          <span className="jrow" key={k}>
            <span>{t(label)} <span className="muted">{b[k]?.weight}</span></span>
            <span className="bar-t"><i style={{ width: `${(num(b[k]) ?? 0) * 100}%` }} /></span>
            <span className="num">{f2(num(b[k]) ?? 0)}</span>
          </span>
        ))}
      </div>
      {(c.missing ?? []).length === 0
        ? <p className="hint formula"><Mixed text={`${terms} = ${(c.overall_confidence ?? 0).toFixed(3)}`} /></p>
        : <p className="hint formula">{t("dossier.conf.missing", { m: (c.missing ?? []).join(", ") })}</p>}
    </>
  );
}

function Gaps({ c }: { c: ConfidenceReport }) {
  const { t } = useT();
  const gaps = c.gaps ?? [];
  const tone: Record<string, string> = { high: "down", medium: "warn" };
  if (!gaps.length) return null;
  return (
    <div className="side-block">
      <div className="side-h">{t("dossier.gaps.title")}<span>{t("dossier.gaps.count", { n: gaps.length })}</span></div>
      {gaps.map((g, i) => (
        <div className="gap" key={i}>
          <div className="hd"><span className={`tag ${tone[g.importance] ?? ""}`}>{t(`dossier.gaps.${g.importance}` as TKey)}</span><span>{g.gap}</span></div>
          {g.suggestion && <div className="sg">{t("dossier.gaps.suggest", { s: g.suggestion })}</div>}
        </div>
      ))}
    </div>
  );
}

function TopSources({ urls }: { urls: string[] }) {
  const { t } = useT();
  if (!urls.length) return null;
  const tail = (u: string) => u.split("/").filter(Boolean).pop()?.split("?")[0].slice(0, 32) ?? "";
  return (
    <div className="side-block">
      <div className="side-h">{t("dossier.top.title", { n: urls.length })}</div>
      <ol className="srcs">
        {urls.map((u) => (
          <li key={u}><span><a href={webUrl(u)} target="_blank" rel="noopener noreferrer">{host(u)}</a><span className="muted"> · {tail(u)}</span></span></li>
        ))}
      </ol>
    </div>
  );
}

/** 封面右栏：可信度、「有争议」口径、还缺什么、最可靠来源 */
export function ConfidenceSide({ c, disputed }: { c: ConfidenceReport; disputed: number }) {
  const { t } = useT();
  const overall = c.overall_confidence ?? 0;
  const factChecked = num(c.breakdown?.fact_accuracy, "claims_checked") ?? 0;
  const factDisputed = num(c.breakdown?.fact_accuracy, "disputed_claims_count") ?? 0;
  return (
    <aside className="side">
      <div className="side-h">{t("dossier.conf.title")}<span>{t("dossier.conf.report")}</span></div>
      <div className="score-big">
        <span className="n num">{f2(overall)}</span><span className="of">/ 1.00</span>
        <span className="tag gold">{t(`dossier.conf.level.${c.confidence_level ?? "medium"}` as TKey)}</span>
      </div>
      <div className="mark" style={{ width: `${overall * 100}%` }} />
      <ConfidenceNote c={c} disputed={disputed} />
      <Breakdown c={c} />
      <div className="side-block">
        <div className="side-h">{t("dossier.disputed.title")}</div>
        <p className="conf-note">
          {rich(t(factDisputed ? "dossier.disputed.noteN" : "dossier.disputed.note0"), {
            count: <strong>{t("dossier.disputed.count", { n: disputed })}</strong>,
            m: <N>{factChecked}</N>, k: <N>{factDisputed}</N>,
          })}
        </p>
      </div>
      <Gaps c={c} />
      <TopSources urls={c.top_sources ?? []} />
    </aside>
  );
}
