import { Icon } from "../../components/ui/Icon";
import { Stamp } from "../../components/ui/Stamp";
import { Score } from "../../components/ui/Score";
import { AskTag, stageLabel } from "../../components/shell/DeskItems";
import { useT, type TKey } from "../../i18n";
import { N, rich } from "../../i18n/rich";
import { clockTime, crId, f2, minutes, plainQuestion, usd } from "../../lib/format";
import { elapsedNow, isLive } from "../../lib/live/model";
import { live, useNow } from "../../lib/live/store";
import { modelName } from "../../lib/useSettings";
import type { SessionMeta } from "../../lib/types";

export interface RowActions {
  open: (s: SessionMeta) => void;
  resume: (s: SessionMeta) => void;
  redo: (s: SessionMeta) => void;
  remove: (s: SessionMeta) => void;
}

export const caseId = (s: SessionMeta) => (s.session_id ? crId(s.session_id) : s.task_id ?? "");

function Meta({ s }: { s: SessionMeta }) {
  const { t } = useT();
  return (
    <div className="meta">
      {s.depth && <span>{t(`dossier.depth.${s.depth}` as TKey)}</span>}
      {s.core_model && <span className="num">{modelName(s.core_model)}</span>}
      {s.created_at && <span className="num">{clockTime(s.created_at)}</span>}
    </div>
  );
}

function Why({ s }: { s: SessionMeta }) {
  const { t } = useT();
  if (s.status === "stopped" || s.status === "interrupted") return <div className="why">{t(`cabinet.why.${s.status}` as TKey)}</div>;
  if (s.status === "failed") return <div className="why">{s.error ? t("cabinet.why.failed", { e: s.error }) : t("cabinet.why.failedNoMsg")}</div>;
  return null;
}

const Muted = ({ k }: { k: TKey }) => {
  const { t } = useT();
  return <span className="muted">{t(k)}</span>;
};

function Ops({ s, a }: { s: SessionMeta; a: RowActions }) {
  const { t } = useT();
  const prev = s.task_id ? live.get(s.task_id) : undefined;
  const wrapping = !!prev && !prev.ended && !isLive(prev); // 刚停下、后台线程还没退出：等它收尾再续办
  const resumable = s.status === "stopped" || s.status === "interrupted";
  return (
    <td className="ops">
      {s.status === "completed" && <button className="iconbtn" title={t("cabinet.op.open")} onClick={() => a.open(s)}><Icon name="eye" /></button>}
      {resumable && s.session_id && (
        <button className="iconbtn" title={t(wrapping ? "cabinet.op.resumeWait" : "cabinet.op.resume")} disabled={wrapping}
                onClick={() => a.resume(s)}><Icon name="resume" /></button>
      )}
      {s.status === "failed" && <button className="iconbtn" title={t("cabinet.op.redo")} onClick={() => a.redo(s)}><Icon name="resume" /></button>}
      <button className="iconbtn danger" title={t("cabinet.op.delete")} onClick={() => a.remove(s)}><Icon name="trash" /></button>
    </td>
  );
}

/** 一份卷宗：编号、完整问题、状态印章、评分、轮数、用时、费用、可信度、操作 */
export function SessionRow({ s, a }: { s: SessionMeta; a: RowActions }) {
  const { t } = useT();
  const opensDossier = s.status === "completed" && !!s.session_id;
  return (
    <tr>
      <td className="c">{caseId(s)}</td>
      <td className="t">
        {opensDossier ? <h3><button className="qlink" onClick={() => a.open(s)}>{plainQuestion(s.question)}</button></h3> : <h3>{plainQuestion(s.question)}</h3>}
        <Meta s={s} /><Why s={s} />
      </td>
      <td><Stamp status={s.status} /></td>
      <td>{s.final_score != null ? <Score score={s.final_score} /> : <Muted k="cabinet.unscored" />}</td>
      <td className="r">{s.total_cycles != null ? <N>{s.total_cycles}</N> : <Muted k="cabinet.unrecorded" />}</td>
      <td className="r">{s.elapsed_seconds ? rich(t("cabinet.min"), { n: <N>{minutes(s.elapsed_seconds)}</N> }) : <Muted k="cabinet.untimed" />}</td>
      <td className="r">{s.cost_usd != null ? <N>{usd(s.cost_usd)}</N> : <Muted k="cabinet.unrecorded" />}</td>
      <td className="r">{s.confidence != null ? <N>{f2(s.confidence)}</N> : ""}</td>
      <Ops s={s} a={a} />
    </tr>
  );
}

/** 在办的一份：阶段、已办分钟数、当前最优分、轮数；待签批的带倒计时 */
export function LiveRow({ s, onOpen }: { s: SessionMeta; onOpen: () => void }) {
  const { t } = useT();
  const now = useNow();
  const st = s.task_id ? live.get(s.task_id) : undefined;
  const scores = st?.rounds.map((r) => r.score).filter((x): x is number => x != null) ?? [];
  const round = st?.rounds[st.rounds.length - 1];
  const mins = st ? minutes(elapsedNow(st, now)) : 0;
  return (
    <tr className="is-live">
      <td className="c">{caseId(s)}</td>
      <td className="t"><h3><button className="qlink" onClick={onOpen}>{plainQuestion(s.question)}</button></h3><Meta s={s} />
        <div className="why">{stageLabel(t, st, s.phase_key)} · {t("shell.desk.elapsed", { n: mins })}</div></td>
      <td>{st?.decision ? <AskTag s={st} now={now} /> : <Stamp status="running" />}</td>
      <td>{scores.length ? <><Score score={Math.max(...scores)} /><div className="hint">{t("cabinet.best")}</div></> : <Muted k="cabinet.unscored" />}</td>
      <td className="r">{round ? <N>{round.cycle}/{round.max || "?"}</N> : <Muted k="cabinet.unrecorded" />}</td>
      <td className="r">{rich(t("cabinet.min"), { n: <N>{mins}</N> })}</td>
      <td className="r"><Muted k="cabinet.pendingCost" /></td>
      <td className="r"><Muted k="cabinet.afterClose" /></td>
      <td className="ops"><button className="iconbtn" title={t("cabinet.op.case")} onClick={onOpen}><Icon name="eye" /></button></td>
    </tr>
  );
}
