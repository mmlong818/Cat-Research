import { useLocation } from "wouter";
import { useT } from "../../i18n";
import { Icon } from "../ui/Icon";
import LangSwitch from "../../i18n/LangSwitch";
import { ThemeSwitch } from "./ThemeSwitch";
import { ActiveItem, RecentItem } from "./DeskItems";
import { MAX_ACTIVE, sessionHref, useDesk } from "./useDesk";
import { live } from "../../lib/live/store";
import type { SessionMeta } from "../../lib/types";

interface Props {
  narrow: boolean;
  collapsed: boolean;
  drawerOpen: boolean;
  onToggle: () => void;
  onClose: () => void;
}

const keyOf = (s: SessionMeta) => s.session_id || s.task_id || s.created_at;

function MiniRail({ go, onToggle }: { go: (to: string) => void; onToggle: () => void }) {
  const { t } = useT();
  const { active } = useDesk();
  const asks = active.filter((s) => s.task_id && live.get(s.task_id)?.decision).length;
  const title = asks ? t("shell.desk.askCount", { n: active.length, a: asks }) : t("shell.desk.activeCount", { n: active.length });
  return (
    <>
      <button className="iconbtn" onClick={onToggle} title={t("shell.desk.expand")}><Icon name="sidebar" /></button>
      <button className="rail-count" onClick={onToggle} title={title}>
        <span className="num">{active.length}</span>{asks > 0 && <i className="wdot" />}<small>{t("shell.desk.mini")}</small>
      </button>
      <button className="iconbtn" onClick={() => go("/new")} title={t("shell.desk.new")}><Icon name="plus" /></button>
      <button className="iconbtn" onClick={() => go("/cabinet")} title={t("shell.nav.cabinet")}><Icon name="archive" /></button>
    </>
  );
}

function DeskBody({ narrow, go, onToggle, onClose }: { narrow: boolean; go: (to: string) => void; onToggle: () => void; onClose: () => void }) {
  const { t } = useT();
  const { active, recent, loaded } = useDesk();
  return (
    <>
      <div className="rail-h">
        <h2>{t("shell.desk.title")}</h2>
        <span className="sp" />
        {narrow
          ? <button className="iconbtn" onClick={onClose} title={t("common.close")}><Icon name="x" /></button>
          : <button className="iconbtn" onClick={onToggle} title={t("shell.desk.collapse")}><Icon name="sidebar" /></button>}
      </div>
      <button className="btn rail-new" onClick={() => go("/new")}><Icon name="plus" />{t("shell.desk.new")}</button>
      <div className="rail-sec">
        <span>{t("shell.desk.active")}</span>
        <span className="num">{active.length}/{MAX_ACTIVE}</span>
        <span className="hint">{t("shell.desk.max", { n: MAX_ACTIVE })}</span>
      </div>
      {active.length > 0
        ? active.map((s) => <ActiveItem key={keyOf(s)} s={s} onOpen={() => go(sessionHref(s))} />)
        : loaded && <p className="hint rail-empty">{t("shell.desk.activeEmpty")}</p>}
      <div className="rail-sec"><span>{t("shell.desk.recent")}</span></div>
      {recent.length > 0
        ? recent.map((s) => <RecentItem key={keyOf(s)} s={s} onOpen={() => go(sessionHref(s))} />)
        : loaded && <p className="hint rail-empty">{t("shell.desk.recentEmpty")}</p>}
      <div className="rail-foot">
        <button className="btn btn--link" onClick={() => go("/cabinet")}>
          {t("shell.desk.all")} <Icon name="arrow-right" />
        </button>
      </div>
      {narrow && <div className="rail-prefs"><LangSwitch /><ThemeSwitch /></div>}
    </>
  );
}

/** 案头：每页常驻的左栏。桌面可收成 56px 窄条（偏好存 localStorage），≤760px 时改为抽屉。 */
export function Desk({ narrow, collapsed, drawerOpen, onToggle, onClose }: Props) {
  const { t } = useT();
  const [, navigate] = useLocation();
  const go = (to: string) => { onClose(); navigate(to); };
  const cls = narrow ? `dock drawer${drawerOpen ? " open" : ""}` : `dock${collapsed ? " mini" : ""}`;
  return (
    <>
      {narrow && drawerOpen && <div className="scrim" onClick={onClose} />}
      <aside className={cls} aria-label={t("shell.desk.label")} aria-hidden={narrow && !drawerOpen}>
        {collapsed
          ? <MiniRail go={go} onToggle={onToggle} />
          : <DeskBody narrow={narrow} go={go} onToggle={onToggle} onClose={onClose} />}
      </aside>
    </>
  );
}
