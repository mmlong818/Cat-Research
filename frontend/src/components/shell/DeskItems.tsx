import type { SessionMeta } from "../../lib/types";
import { dateShort, minutes, plainQuestion } from "../../lib/format";
import { useT, type TFunc, type TKey } from "../../i18n";
import { STAGES, clock, decisionLeft, elapsedNow, runMode, type CaseState } from "../../lib/live/model";
import { live, useNow } from "../../lib/live/store";
import { Icon } from "../ui/Icon";
import { Stamp } from "../ui/Stamp";
import { Score } from "../ui/Score";

/** 9 段迷你进度：已完成墨色，当前油墨蓝 */
function Segs({ at }: { at: number }) {
  const { t } = useT();
  return (
    <span className="segs" role="img" aria-label={t("shell.desk.stage", { n: Math.max(0, at) + 1, total: STAGES.length })}>
      {STAGES.map((p, i) => <i key={p} className={i < at ? "d" : i === at ? "a" : ""} />)}
    </span>
  );
}

/** 当前阶段的叫法：改进阶段写第几轮，暂停时加前缀 */
export function stageLabel(t: TFunc, s: CaseState | undefined, fallbackKey?: string | null): string {
  const key = s && s.stage >= 0 ? STAGES[s.stage] : fallbackKey;
  if (!key) return t("shell.desk.starting");
  const round = s?.rounds[s.rounds.length - 1];
  const name = key === "improve" && round ? t("shell.desk.round", { n: round.cycle }) : t(`shell.stage.${key}` as TKey);
  return s && runMode(s) === "paused" ? `${t("shell.desk.paused")} · ${name}` : name;
}

/** 待签批的倒计时标签（案头、顶栏共用） */
export function AskTag({ s, now }: { s: CaseState; now: number }) {
  const { t } = useT();
  if (!s.decision) return null;
  return (
    <span className="tag warn"><Icon name="pen" small />{t("shell.desk.askTag")}
      <span className="num">{clock(decisionLeft(s.decision, now))}</span></span>
  );
}

const sinceMinutes = (iso: string) => minutes(Math.max(0, (Date.now() - new Date(iso.slice(0, 19)).getTime()) / 1000));

export function ActiveItem({ s, onOpen }: { s: SessionMeta; onOpen: () => void }) {
  const { t } = useT();
  const now = useNow();
  const st = s.task_id ? live.get(s.task_id) : undefined;
  const mins = st && st.status !== "connecting" ? minutes(elapsedNow(st, now)) : sinceMinutes(s.created_at);
  const at = st && st.stage >= 0 ? st.stage : Math.max(0, STAGES.indexOf((s.phase_key ?? "") as (typeof STAGES)[number]));
  return (
    <button className={`task${st?.decision ? " ask" : ""}`} onClick={onOpen}>
      {st && <AskTag s={st} now={now} />}
      <b className="tq">{plainQuestion(s.question)}</b>
      <span className="tm">{stageLabel(t, st, s.phase_key)} · {t("shell.desk.elapsed", { n: mins })}</span>
      <Segs at={at} />
    </button>
  );
}

export function RecentItem({ s, onOpen }: { s: SessionMeta; onOpen: () => void }) {
  const { lang } = useT();
  return (
    <button className="recent" onClick={onOpen}>
      <span className="rq">{plainQuestion(s.question)}</span>
      <span className="rm">
        <Stamp status={s.status} small />
        {s.final_score != null && <Score score={s.final_score} />}
        <span className="sp" />
        {s.created_at && <span>{dateShort(s.created_at, lang)}</span>}
      </span>
    </button>
  );
}
