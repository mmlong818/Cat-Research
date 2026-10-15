import { useCallback, useState } from "react";
import { Link, useLocation } from "wouter";
import { toast } from "sonner";
import { Masthead } from "../../components/ui/Masthead";
import { Icon } from "../../components/ui/Icon";
import { Stamp } from "../../components/ui/Stamp";
import { Dialog } from "../../components/ui/Dialog";
import { MAX_ACTIVE, useDesk } from "../../components/shell/useDesk";
import { useT, locale, type TKey } from "../../i18n";
import { N, rich } from "../../i18n/rich";
import { ApiError, research } from "../../lib/api";
import type { SessionMeta } from "../../lib/types";
import { plainQuestion } from "../../lib/format";
import { prefillDraft } from "../new/draft";
import { FILTERS, keyOf, useCabinet, type Group } from "./useCabinet";
import { LiveRow, SessionRow, caseId, type RowActions } from "./CabinetRow";
import "./cabinet.css";

function Head() {
  const { t } = useT();
  const cols: [TKey, string][] = [["cabinet.col.id", "w-id"], ["cabinet.col.q", ""], ["cabinet.col.status", "w-st"], ["cabinet.col.score", "w-sc"],
    ["cabinet.col.rounds", "w-n r"], ["cabinet.col.time", "w-time r"], ["cabinet.col.conf", "w-conf r"], ["cabinet.col.ops", "w-ops"]];
  return <thead><tr>{cols.map(([k, cls]) => <th key={k} className={cls}>{k === "cabinet.col.ops" ? <span className="sr">{t(k)}</span> : t(k)}</th>)}</tr></thead>;
}

function DayRow({ g }: { g: Group }) {
  const { t, lang } = useT();
  const d = new Date(`${g.day}T00:00:00`);
  const date = d.toLocaleDateString(locale(lang), { month: lang === "zh" ? "long" : "short", day: "numeric" });
  const week = d.toLocaleDateString(locale(lang), { weekday: "long" });
  return <tr className="grp"><td colSpan={8}>{date}<span>{week} · {t("cabinet.group", { n: g.items.length })}</span></td></tr>;
}

function Legend() {
  const { t } = useT();
  const items: [string, TKey][] = [["running", "cabinet.stamps.running"], ["completed", "cabinet.stamps.completed"],
    ["stopped", "cabinet.stamps.stopped"], ["failed", "cabinet.stamps.failed"]];
  return (
    <>
      <div className="sec-h"><h3>{t("cabinet.stamps.title")}</h3></div>
      <div className="legend">{items.map(([st, k]) => <span key={st} className="hint"><Stamp status={st} />{t(k)}</span>)}</div>
    </>
  );
}

function EmptyCabinet() {
  const { t } = useT();
  return (
    <div className="wrap cabinet">
      <Masthead title={t("cabinet.title")}><span className="issue">{t("cabinet.empty.issue")}</span></Masthead>
      <div className="empty"><Icon name="archive" /><h3>{t("cabinet.empty.title")}</h3><p>{t("cabinet.empty.body")}</p>
        <div className="btns"><Link className="btn btn--primary" href="/new"><Icon name="pen" />{t("cabinet.empty.go")}</Link></div></div>
      <Legend />
    </div>
  );
}

/** 档案柜的动作：打开卷宗、续办（检查点 + replay）、重办（回填委托台）、删除（二次确认） */
function useActions(onRemoved: (key: string) => void) {
  const { t } = useT();
  const [, navigate] = useLocation();
  const { refresh } = useDesk();
  const [doomed, setDoomed] = useState<SessionMeta | null>(null);
  const [busy, setBusy] = useState(false);
  const cancel = useCallback(() => setDoomed(null), []);
  const resume = async (s: SessionMeta) => {
    try {
      const { resume_from } = await research.checkpoints(s.session_id);
      if (!resume_from) { toast.error(t("cabinet.toast.noCheckpoint")); return; }
      const { task_id, from_phase } = await research.replay(s.session_id, null);
      toast.success(t("cabinet.toast.resumed", { id: caseId(s), p: t(`shell.stage.${from_phase}` as TKey) }));
      navigate(`/case/${task_id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) toast.warning(t("cabinet.toast.wrapping")); // 停止后旧线程还没退出
      else toast.error(t("cabinet.toast.resumeFailed", { msg: (e as Error).message }));
    }
  };
  const confirmDelete = async () => {
    if (!doomed) return;
    setBusy(true);
    try {
      if (doomed.session_id) await research.deleteSession(doomed.session_id);
      else if (doomed.task_id) await research.deleteTask(doomed.task_id);
      toast.success(t("cabinet.toast.deleted", { id: caseId(doomed) }));
      onRemoved(keyOf(doomed));
      refresh();
      setDoomed(null);
    } catch (e) { toast.error(t("cabinet.toast.deleteFailed", { msg: (e as Error).message })); }
    finally { setBusy(false); }
  };
  const actions: RowActions = {
    open: (s) => navigate(`/dossier/${s.session_id}`),
    resume: (s) => { void resume(s); },
    redo: (s) => { prefillDraft(plainQuestion(s.question), s.depth, s.language); navigate("/new"); },
    remove: setDoomed,
  };
  return { actions, doomed, busy, confirmDelete, cancel };
}

/** 档案柜 /cabinet：在办的排最前，其余按日期分组；搜索、按状态筛选、删除、续办、重办 */
export default function CabinetPage() {
  const { t } = useT();
  const [, navigate] = useLocation();
  const c = useCabinet();
  const { actions, doomed, busy, confirmDelete, cancel } = useActions(c.remove);
  if (!c.loaded) return <div className="wrap cabinet"><Masthead title={t("cabinet.title")} /><p className="hint mt-m">{c.error ? t("cabinet.loadFailed", { msg: c.error }) : t("cabinet.loading")}</p></div>;
  if (c.total === 0) return <EmptyCabinet />;
  return (
    <div className="wrap cabinet">
      <Masthead title={t("cabinet.title")}><span className="issue">{rich(t("cabinet.issue"), { n: <b>{c.total}</b> })}</span></Masthead>
      <p className="dateline">{t("cabinet.lede")}</p>
      {c.live.length > 0 && (
        <div className="pin">
          <div className="sec-h"><h3>{t("cabinet.live.title")}</h3><span className="state">{rich(t("cabinet.live.count"), { n: <N>{c.live.length}</N> })}</span>
            <span className="meta">{t("cabinet.live.meta", { n: MAX_ACTIVE })}</span></div>
          <table className="il cab top"><Head /><tbody>
            {c.live.map((s) => <LiveRow key={keyOf(s)} s={s} onOpen={() => navigate(`/case/${s.task_id}`)} />)}
          </tbody></table>
        </div>
      )}
      <div className="filters">
        <label className="input search"><Icon name="search" />
          <input value={c.query} placeholder={t("cabinet.search.ph")} aria-label={t("cabinet.search.label")} onChange={(e) => c.setQuery(e.target.value)} /></label>
        <div className="seg lg" role="group" aria-label={t("cabinet.filter.label")}>
          {FILTERS.map((f) => <button key={f} className={c.filter === f ? "on" : ""} aria-pressed={c.filter === f} onClick={() => c.setFilter(f)}>{t(`cabinet.filter.${f}` as TKey)}</button>)}
        </div>
      </div>
      <table className="il cab"><Head /><tbody>
        {c.groups.length === 0 && <tr><td colSpan={8}><p className="hint none">{t("cabinet.none")}</p></td></tr>}
        {c.groups.map((g) => [<DayRow key={g.day} g={g} />, ...g.items.map((s) => <SessionRow key={keyOf(s)} s={s} a={actions} />)])}
      </tbody></table>
      {doomed && (
        <Dialog title={t("cabinet.del.title")} confirm={t("cabinet.del.ok")} danger busy={busy} onConfirm={() => void confirmDelete()} onClose={cancel}>
          {t("cabinet.del.body", { id: caseId(doomed), q: plainQuestion(doomed.question) })}
        </Dialog>
      )}
    </div>
  );
}
