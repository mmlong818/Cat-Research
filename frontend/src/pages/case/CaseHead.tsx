import { useState } from "react";
import { Link, useLocation } from "wouter";
import { toast } from "sonner";
import { Masthead } from "../../components/ui/Masthead";
import { Icon } from "../../components/ui/Icon";
import { stageLabel } from "../../components/shell/DeskItems";
import { useT, type TKey } from "../../i18n";
import { N, rich } from "../../i18n/rich";
import { clockTime, crId, dateShort, minutes, plainQuestion } from "../../lib/format";
import { elapsedNow, runMode, type CaseState } from "../../lib/live/model";
import { useNow } from "../../lib/live/store";
import { ApiError, research } from "../../lib/api";
import { prefillDraft } from "../new/draft";
import type { TaskInfo } from "./useCaseMeta";

export function CaseMast({ s, info }: { s: CaseState; info: TaskInfo | null }) {
  const { t, lang } = useT();
  const facts = [
    info?.depth && t(`dossier.depth.${info.depth}` as TKey),
    info?.language && t(`common.lang.${info.language}` as TKey),
    info?.created_at && t("case.issue.signed", { d: `${dateShort(info.created_at, lang)} ${clockTime(info.created_at)}` }),
  ].filter(Boolean);
  return (
    <Masthead title={t("case.title")}
              tools={<Link className="linkbtn" href="/cabinet"><Icon name="archive" />{t("case.toCabinet")}</Link>}>
      <span className="wk num">{s.sessionId ? crId(s.sessionId) : s.taskId}</span>
      {facts.length > 0 && <span className="issue">{facts.join(" · ")}</span>}
    </Masthead>
  );
}

/** 报头下的一句话：现在在做什么、已办几分钟、要不要你动手 */
export function Lede({ s }: { s: CaseState }) {
  const { t } = useT();
  const sec = elapsedNow(s, useNow(10_000));
  const m = <N>{minutes(sec)}</N>;
  const mode = runMode(s);
  if (s.status === "connecting") return <p className="dateline">{t("case.lede.connecting")}</p>;
  if (s.status === "completed") return <p className="dateline">{t("case.lede.done")}</p>;
  if (mode === "done") return sec > 0 ? <p className="dateline">{rich(t("case.lede.ended"), { m })}</p> : null; // 停掉、中断的旧任务不知道用时
  if (s.decision) return <p className="dateline">{rich(t("case.lede.ask"), { n: <N>{s.decision.cycle}</N>, b: <strong>{t("case.lede.askB")}</strong>, m })}</p>;
  if (mode === "paused") return <p className="dateline">{rich(t("case.lede.paused"), { b: <strong>{t("case.lede.pausedB")}</strong>, gate: s.pauseGate ?? "", m })}</p>;
  if (mode === "pausing") return <p className="dateline">{rich(t("case.lede.pausing"), { b: <strong>{t("case.lede.pausingB")}</strong>, m })}</p>;
  return <p className="dateline">{rich(t("case.lede.running"), { stage: <strong>{stageLabel(t, s)}</strong>, m })}</p>;
}

/** 续办：用检查点找默认起点，POST /replay；要等后台线程退出（end）后才可以，免得两个线程写同一个工作空间。
 *  刷新后连上的页面会先收到 end（任务已停），线程却可能还没退出：后端此时回 409，提示稍后再试 */
function ResumeButton({ s }: { s: CaseState }) {
  const { t } = useT();
  const [, navigate] = useLocation();
  const [busy, setBusy] = useState(false);
  const sid = s.sessionId;
  if (!sid) return null;
  const resume = () => {
    setBusy(true);
    research.replay(sid, null)
      .then(({ task_id }) => { toast.success(t("case.toast.resumed")); navigate(`/case/${task_id}`); })
      .catch((e: Error) => (e instanceof ApiError && e.status === 409
        ? toast.warning(t("case.toast.wrapping"))
        : toast.error(t("case.toast.failed", { m: e.message }))))
      .finally(() => setBusy(false));
  };
  return (
    <button className={`btn btn--sm${busy ? " is-loading" : ""}`} disabled={!s.ended || busy} onClick={resume}
            title={s.ended ? undefined : t("case.resumeWait")}>{!busy && <Icon name="resume" />}{t("case.resume")}</button>
  );
}

/** 办理结束但没结卷：停止、中断、失败各一条横幅 */
export function EndBanner({ s }: { s: CaseState }) {
  const { t } = useT();
  const [, navigate] = useLocation();
  if (s.stopping && s.status === "running") {
    return <div className="banner warn mt-m"><Icon name="pause" /><span>{t("case.banner.stopping")}</span></div>;
  }
  if (s.status === "stopped" || s.status === "interrupted") {
    return (
      <div className="banner warn mt-m"><Icon name="pause" />
        <span><strong>{t(`case.banner.${s.status}` as TKey)}</strong></span><ResumeButton s={s} />
      </div>
    );
  }
  if (s.status !== "failed") return null;
  const redo = () => { prefillDraft(plainQuestion(s.question)); navigate("/new"); };
  return (
    <div className="banner mt-m" role="alert"><Icon name="warning" />
      <span>{t("case.banner.failed", { msg: s.error ?? "" })}</span>
      <button className="btn btn--sm" onClick={redo}><Icon name="resume" />{t("case.redo")}</button>
    </div>
  );
}
