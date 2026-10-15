import { useEffect, useState } from "react";
import { useLocation } from "wouter";
import SettingsModal from "../SettingsModal";
import LangSwitch from "../../i18n/LangSwitch";
import { useT, type TKey } from "../../i18n";
import { clock, decisionLeft, type CaseState } from "../../lib/live/model";
import { live, useNow } from "../../lib/live/store";
import { Icon } from "../ui/Icon";
import { ThemeSwitch } from "./ThemeSwitch";
import { currentCase, useDesk } from "./useDesk";

type NavKey = "desk" | "run" | "cabinet";

const activeNav = (location: string): NavKey | "" =>
  location.startsWith("/new") ? "desk"
    : location.startsWith("/case") ? "run"
      : location.startsWith("/cabinet") || location.startsWith("/dossier") ? "cabinet" : "";

function BrandMark() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect className="m-doc" x="3" y="2.5" width="15.5" height="19" rx="1.5" />
      <path className="m-line" d="M6.5 7.5h8.5M6.5 11h8.5M6.5 14.5h5" />
      <circle className="m-dot" cx="17.6" cy="17.6" r="4" />
    </svg>
  );
}

/** 在办的里正在等签批的（案头已按待签批优先排序） */
function useAsks(): CaseState[] {
  const { active } = useDesk();
  return active.map((s) => (s.task_id ? live.get(s.task_id) : undefined)).filter((s): s is CaseState => !!s?.decision);
}

/** 有待签批时，标签页标题加提示，离开页面也看得到 */
function useAskTitle(asking: boolean) {
  const { t } = useT();
  useEffect(() => {
    const base = document.title.replace(t("shell.title.ask"), "");
    document.title = asking ? `${t("shell.title.ask")}${base}` : base;
  }, [asking, t]);
}

function DeskPill({ onToggle }: { onToggle: () => void }) {
  const { t } = useT();
  const { active } = useDesk();
  const asks = useAsks();
  const now = useNow();
  const first = asks[0]?.decision;
  return (
    <button className="deskbtn" onClick={onToggle} title={t("shell.desk.label")}>
      <Icon name="sidebar" />{t("shell.desk.pill")} <span className="num">{active.length}</span>
      {first && (
        <span className="askc"><i className="wdot" />{t("shell.desk.askPill")} <span className="num">{asks.length}</span>
          <span className="num cd">{clock(decisionLeft(first, now))}</span></span>
      )}
    </button>
  );
}

export function Topbar({ online, onToggleDesk }: { online: boolean; onToggleDesk: () => void }) {
  const [location, navigate] = useLocation();
  const [showSettings, setShowSettings] = useState(false);
  const { active } = useDesk();
  const asking = useAsks().length > 0;
  const { t } = useT();
  useAskTitle(asking);
  const cur = activeNav(location);
  const nav: { key: NavKey; to: string }[] = [
    { key: "desk", to: "/new" }, { key: "run", to: currentCase(location, active) }, { key: "cabinet", to: "/cabinet" },
  ];
  return (
    <>
    <header className="bar">
      <a className="brand" href="/new" onClick={(e) => { e.preventDefault(); navigate("/new"); }}>
        <BrandMark /><span className="wordmark">Cat-Research</span>
      </a>
      <nav className="nav">
        {nav.map(({ key, to }) => (
          <a key={key} href={to} className={cur === key ? "on" : ""}
             onClick={(e) => { e.preventDefault(); navigate(to); }}>
            {t(`shell.nav.${key}` as TKey)}
            <small>{t(`shell.nav.${key}Sub` as TKey)}</small>
            {key === "run" && (asking
              ? <span className="navbadge">{t("shell.nav.askBadge")}</span>
              : active.length > 0 && <span className="live" title={t("shell.nav.live")} />)}
          </a>
        ))}
      </nav>
      <div className="bar-right">
        <DeskPill onToggle={onToggleDesk} />
        <span className={`online${online ? " on" : ""}`}><i />{t(online ? "common.online" : "common.offline")}</span>
        <LangSwitch />
        <button className="iconbtn" onClick={() => setShowSettings(true)} title={t("common.settings")}>
          <Icon name="gear" />
        </button>
        <ThemeSwitch />
      </div>
    </header>
    <SettingsModal open={showSettings} onClose={() => setShowSettings(false)} />
    </>
  );
}
