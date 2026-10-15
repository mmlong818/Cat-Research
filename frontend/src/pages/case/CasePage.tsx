import { useEffect } from "react";
import { Link, Redirect, useLocation } from "wouter";
import { Masthead } from "../../components/ui/Masthead";
import { Icon } from "../../components/ui/Icon";
import { Stamp } from "../../components/ui/Stamp";
import { useDesk } from "../../components/shell/useDesk";
import { useT, type TKey } from "../../i18n";
import { runMode, type CaseState } from "../../lib/live/model";
import { plainQuestion } from "../../lib/format";
import { useLive } from "../../lib/live/store";
import { useLedgerCounts, useReviews, useTaskInfo } from "./useCaseMeta";
import { CaseMast, EndBanner, Lede } from "./CaseHead";
import { SignOff, SignReceipt } from "./SignOff";
import { Timeline } from "./Timeline";
import { Controls } from "./Controls";
import { Directives } from "./Directives";
import { Leave, RawLog, Tally } from "./Side";
import "./case.css";

function StateMark({ s }: { s: CaseState }) {
  const { t } = useT();
  const mode = runMode(s);
  if (mode === "done") return <Stamp status={s.status === "missing" ? "unknown" : s.status} />;
  const cls = mode === "paused" || mode === "pausing" ? "state paused" : "state";
  return <span className={cls}>{t(`case.state.${mode}` as TKey)}</span>;
}

function CaseView({ s }: { s: CaseState }) {
  const { t } = useT();
  const info = useTaskInfo(s.taskId);
  const counts = useLedgerCounts(s);
  const reviews = useReviews(s);
  return (
    <div className="wrap case">
      <CaseMast s={s} info={info} />
      {s.question && <h2 className="runq">{plainQuestion(s.question)}</h2>}
      <Lede s={s} />
      {s.offline != null && <div className="banner info mt-m"><Icon name="info" /><span>{t("case.offline", { n: s.offline })}</span></div>}
      <EndBanner s={s} />
      <div className="run-grid">
        <div className="run-left">
          {s.decision && <SignOff s={s} reviews={reviews} />}
          <SignReceipt s={s} />
          <div className="sec-h stages-h"><h3>{t("case.stages.title")}</h3><StateMark s={s} /><span className="meta">{t("case.stages.meta")}</span></div>
          <Timeline s={s} counts={counts} />
        </div>
        <div className="run-right">
          <div className="form-h"><h3>{t("case.ctl.title")}</h3><p>{t("case.ctl.sub")}</p></div>
          <Controls s={s} />
          <Directives s={s} />
          <Leave />
          <Tally s={s} counts={counts} />
          <RawLog s={s} />
        </div>
      </div>
    </div>
  );
}

function Missing({ taskId }: { taskId: string }) {
  const { t } = useT();
  return (
    <div className="wrap case">
      <Masthead title={t("case.title")}><span className="wk num">{taskId}</span></Masthead>
      <div className="empty"><Icon name="archive" /><h3>{t("case.missing.title")}</h3><p>{t("case.missing.body", { id: taskId })}</p>
        <div className="btns"><Link className="btn btn--primary" href="/cabinet">{t("shell.nav.cabinet")}</Link></div></div>
    </div>
  );
}

/** 办案记录 /case/:taskId：结卷后跳到卷宗；断线自动重连，刷新页面从快照与回放恢复 */
export default function CasePage({ taskId }: { taskId: string }) {
  const s = useLive(taskId);
  const [, navigate] = useLocation();
  const done = s?.status === "completed" && s.sessionId ? s.sessionId : null;
  useEffect(() => { if (done) navigate(`/dossier/${done}`, { replace: true }); }, [done, navigate]);
  if (!s) return null;
  if (s.status === "missing") return <Missing taskId={taskId} />;
  return <CaseView s={s} />;
}

/** /case 不带编号：去待签批或第一份在办的；没有在办的就说明并给出去处 */
export function CaseIndex() {
  const { t } = useT();
  const { active, loaded } = useDesk();
  const first = active.find((x) => x.task_id);
  if (first) return <Redirect to={`/case/${first.task_id}`} replace />;
  if (!loaded) return null;
  return (
    <div className="wrap case">
      <Masthead title={t("case.title")} />
      <div className="empty"><Icon name="archive" /><h3>{t("case.none.title")}</h3><p>{t("case.none.body")}</p>
        <div className="btns">
          <Link className="btn btn--primary" href="/new"><Icon name="pen" />{t("case.none.new")}</Link>
          <Link className="btn btn--text" href="/cabinet">{t("shell.nav.cabinet")}</Link>
        </div></div>
    </div>
  );
}
