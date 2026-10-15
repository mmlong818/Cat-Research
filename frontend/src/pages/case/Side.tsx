import { useState } from "react";
import { Icon } from "../../components/ui/Icon";
import { useT } from "../../i18n";
import { N, rich } from "../../i18n/rich";
import { f2 } from "../../lib/format";
import type { CaseState } from "../../lib/live/model";
import type { LedgerView } from "../../lib/types";
import { rawLine } from "./humanize";

export function Leave() {
  const { t } = useT();
  return <div className="fieldset"><div className="leave"><Icon name="bell" /><p>{t("case.leave")}</p></div></div>;
}

/** 台账：声明、来源、矛盾（来自台账接口）+ 当前最优评分 */
export function Tally({ s, counts }: { s: CaseState; counts: LedgerView["counts"] | null }) {
  const { t } = useT();
  const scores = s.rounds.map((r) => r.score).filter((x): x is number => x != null);
  const cells: [string, string][] = [];
  if (counts && counts.claims + counts.sources > 0) { // 研究阶段落盘之前台账是空的，先不摆一排 0
    cells.push([String(counts.claims), t("case.tally.claims")], [String(counts.sources), t("case.tally.sources")]);
    cells.push([String(counts.contradictions), t("case.tally.contra", { r: counts.contradictions - counts.unresolved })]);
  } else if (s.plan) {
    cells.push([String(s.plan.total), t("case.tally.queries")]);
  }
  if (scores.length) cells.push([f2(Math.max(...scores)), t("case.tally.best")]);
  if (!cells.length) return null;
  return (
    <div className="fieldset">
      <div className="flabel">{t("case.tally.title")}<span className="muted">{t("case.tally.meta")}</span></div>
      <div className="tally">
        {cells.map(([n, l], i) => <div key={i}><span className="n">{n}</span><span className="l">{l}</span></div>)}
      </div>
    </div>
  );
}

export function RawLog({ s }: { s: CaseState }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  return (
    <div className="fieldset last">
      <button className="btn btn--text log-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <Icon name={open ? "caret-down" : "caret-right"} />{rich(t("case.log.title"), { n: <N>{s.log.length}</N> })}
      </button>
      {open && <div className="code log">{s.log.length ? s.log.map(rawLine).join("\n") : t("case.log.empty")}</div>}
    </div>
  );
}
