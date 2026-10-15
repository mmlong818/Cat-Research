import { useState, type ReactNode } from "react";
import { Icon, type IconName } from "../../components/ui/Icon";
import { useT, type TKey } from "../../i18n";
import { N, rich } from "../../i18n/rich";
import { STAGES, isLive, runMode, type CaseState, type StageKey } from "../../lib/live/model";
import { useNow } from "../../lib/live/store";
import { f2 } from "../../lib/format";
import type { LedgerView } from "../../lib/types";
import { humanize } from "./humanize";
import { Improve } from "./Improve";

type Counts = LedgerView["counts"] | null;
type Row = "done" | "active" | "pending" | "halted";

const hms = (iso?: string) => (iso ? iso.slice(11, 19) : "");
const secs = (a?: string, b?: string) => (a && b ? (new Date(b).getTime() - new Date(a).getTime()) / 1000 : null);

function rowState(s: CaseState, i: number): Row {
  if (s.status === "completed" || i < s.stage) return "done";
  if (i > s.stage) return "pending";
  return isLive(s) ? "active" : "halted";
}

function Duration({ s, i, row }: { s: CaseState; i: number; row: Row }) {
  const { t } = useT();
  const now = useNow(15_000);
  const key = STAGES[i];
  const next = STAGES.slice(i + 1).map((k) => s.stageAt[k]).find(Boolean);
  if (row === "pending") return <span className="dur" />;
  if (row === "done" && !s.stageAt[key]) return <span className="dur">{t("case.dur.inherited")}</span>;
  const end = next ?? s.log[s.log.length - 1]?.at;
  const sec = row === "active" ? (now - new Date(s.stageAt[key] ?? now).getTime()) / 1000 : secs(s.stageAt[key], end);
  const mins = sec == null ? "" : sec < 60 ? t("case.dur.lt1") : t("case.dur.min", { n: Math.round(sec / 60) });
  if (row === "active") return <span className="dur">{runMode(s) === "paused" ? t("case.dur.paused") : t("case.dur.now")} · {mins}</span>;
  return <span className="dur">{mins}</span>;
}

function PlanAttachment({ s }: { s: CaseState }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  if (!s.plan) return null;
  const lang = (l: string) => (["zh", "en", "ja", "ko"].includes(l) ? t(`case.lang.${l}` as TKey) : l);
  return (
    <>
      <div className="att">
        <button onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          <Icon name={open ? "caret-down" : "clip"} small />{rich(t("case.att.plan"), { n: <N>{s.plan.total}</N> })}</button>
      </div>
      {open && s.plan.aspects.length > 0 && <p className="hint">{t("case.att.aspects", { v: s.plan.aspects.join(" · ") })}</p>}
      {open && (
        <ul className="qlist">
          {s.plan.queries.map((q, i) => (
            <li key={i}><span className="num">{i + 1}</span>
              <div><div className="q">{q.query}</div>{q.purpose && <div className="p">{q.purpose}</div>}</div>
              {q.language && <span className="tag">{lang(q.language)}</span>}</li>
          ))}
        </ul>
      )}
    </>
  );
}

/** 各阶段归档的产物：从事件与台账计数里拿得到的都列上 */
function Attachments({ s, k, counts }: { s: CaseState; k: StageKey; counts: Counts }) {
  const { t } = useT();
  const items: [IconName, ReactNode][] = [];
  if (k === "sources" && counts) items.push(["clip", rich(t("case.att.sources"), { n: <N>{counts.sources}</N> })]);
  if (k === "ledger" && counts) {
    items.push(["clip", rich(t("case.att.claims"), { n: <N>{counts.claims}</N> })]);
    items.push(["clip", rich(t("case.att.contra"), { n: <N>{counts.contradictions}</N>, r: <N>{counts.contradictions - counts.unresolved}</N> })]);
  }
  if (k === "draft" && s.stage > STAGES.indexOf("draft")) items.push(["clip", t("case.att.draft0")]);
  if (k === "finish" && s.finalDraft != null) items.push(["clip", rich(t("case.att.final"), { n: <N>{s.finalDraft}</N> })]);
  if (k === "finish" && s.confidence != null) items.push(["clip", rich(t("case.att.conf"), { v: <N>{f2(s.confidence)}</N> })]);
  if (s.log.some((l) => l.type === "checkpoint" && l.data.phase === k)) items.push(["check", t("case.att.checkpoint")]);
  if (items.length === 0) return null;
  return <div className="att">{items.map(([icon, label], i) => <span key={i}><Icon name={icon} small />{label}</span>)}</div>;
}

function Feed({ s, i }: { s: CaseState; i: number }) {
  const { t, lang } = useT();
  const lines = humanize(t, s.log.filter((l) => l.stage === i || (i === 0 && l.stage < 0)), lang === "zh" ? "、" : ", ");
  if (lines.length === 0) return null;
  const icon = { done: "check", info: "dot", warn: "warning" } as const;
  return (
    <ul className="sub">
      {lines.slice(-8).map((l, k) => (
        <li key={k} className={l.kind === "warn" ? "warn" : ""}><span className="t">{hms(l.at)}</span><Icon name={icon[l.kind]} />
          <span>{l.text}{l.count > 1 && <span className="num"> ×{l.count}</span>}</span></li>
      ))}
    </ul>
  );
}

/** 9 阶段纵向时间线：phase 事件驱动、只进不退；完成的阶段把产物归档进去 */
export function Timeline({ s, counts }: { s: CaseState; counts: Counts }) {
  const { t } = useT();
  return (
    <ol className="tl">
      {STAGES.map((k, i) => {
        const row = rowState(s, i);
        return (
          <li key={k} className={row}>
            <span className="t">{hms(s.stageAt[k])}</span>
            <span className="rail"><i /></span>
            <div className="l">
              <b>{t(`shell.stage.${k}` as TKey)}</b>
              <span>{t(`case.sum.${k}` as TKey)}</span>
              {k === "plan" && <PlanAttachment s={s} />}
              {row !== "pending" && <Attachments s={s} k={k} counts={counts} />}
              {k === "improve" && row !== "pending" && <Improve s={s} />}
              <Feed s={s} i={i} />
            </div>
            <Duration s={s} i={i} row={row} />
          </li>
        );
      })}
    </ol>
  );
}
