import { useEffect, useState } from "react";
import { useSearch } from "wouter";
import { Icon } from "../../components/ui/Icon";
import type { LedgerClaim } from "../../lib/types";
import { useT, type TKey } from "../../i18n";
import { N, rich } from "../../i18n/rich";
import type { Dossier } from "./useDossier";
import type { Derived } from "./useDerived";
import { ClaimEvidence, StatusBadge } from "./ClaimParts";
import { STATUS_ORDER, type ClaimStatus } from "./model";

type Filter = "all" | ClaimStatus;

const clip = (s: string, n = 90) => (s.length > n ? `${s.slice(0, n)}……` : s);

const matches = (c: LedgerClaim, q: string) =>
  !q || [c.id, c.text, ...c.sources.map((s) => s.id), ...Object.values(c.quotes)].join(" ").toLowerCase().includes(q);

function ClaimRow({ c, zh, open, onToggle }: { c: LedgerClaim; zh?: string; open: boolean; onToggle: () => void }) {
  const { t } = useT();
  return (
    <>
      <tr id={`ev-${c.id}`} className={open ? "open" : ""} onClick={onToggle}>
        <td className="c"><button type="button" className="num" aria-expanded={open}>{c.id}</button></td>
        <td>
          <div className="en" lang="en">{c.text}</div>
          {zh && <div className="zh">{t("dossier.ev.inReport", { s: clip(zh) })}</div>}
        </td>
        <td><StatusBadge status={c.status} /></td>
        <td className="sc">
          <span className="num">{c.sources[0]?.id}</span>
          {c.sources.length > 1 && rich(t("dossier.ev.andMore"), { n: <N>{c.sources.length}</N> })}
        </td>
      </tr>
      {open && <tr className="det"><td /><td colSpan={3}><ClaimEvidence claim={c} /></td></tr>}
    </>
  );
}

function Explainer({ total, unchecked }: { total: number; unchecked: number }) {
  const { t } = useT();
  const pct = total ? Math.round((unchecked / total) * 100) : 0;
  return (
    <div className="ledger-x">
      <p>{rich(t("dossier.ev.whatClaim"), { b: <b>{t("dossier.ev.claimWord")}</b> })}</p>
      <p>{rich(t("dossier.ev.whatUnchecked"), {
        b: <b>{t("dossier.status.unchecked")}</b>, n: <N>{unchecked}</N>, p: <N>{`${pct}%`}</N>, not: <b>{t("dossier.ev.notSuspect")}</b>,
      })}</p>
    </div>
  );
}

function ClaimTable({ list, x, openId, setOpenId }: {
  list: LedgerClaim[]; x: Derived; openId: string | null; setOpenId: (id: string | null) => void;
}) {
  const { t } = useT();
  return (
    <table className="il ctab">
      <thead><tr><th className="w-id">{t("dossier.ev.colId")}</th><th>{t("dossier.ev.colClaim")}</th>
        <th className="w-st">{t("dossier.ev.colStatus")}</th><th className="w-src">{t("dossier.ev.colSources")}</th></tr></thead>
      <tbody>
        {list.map((c) => (
          <ClaimRow key={c.id} c={c} zh={x.sentences.get(c.id)} open={openId === c.id}
                    onToggle={() => setOpenId(openId === c.id ? null : c.id)} />
        ))}
        {list.length === 0 && <tr><td colSpan={4}><p className="hint ev-empty">{t("dossier.ev.empty")}</p></td></tr>}
      </tbody>
    </table>
  );
}

/** 证据台账：按状态筛选（计数取全台账），点一行展开来源、引语与核查备注；?c=C# 直达某条 */
export function EvidenceTab({ d, x }: { d: Dossier; x: Derived }) {
  const { t } = useT();
  const focus = new URLSearchParams(useSearch()).get("c");
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<string | null>(focus);
  useEffect(() => {
    if (!focus) return;
    setFilter("all");
    setOpenId(focus);
    requestAnimationFrame(() => document.getElementById(`ev-${focus}`)?.scrollIntoView({ block: "center" }));
  }, [focus]);
  const total = d.ledger?.counts.claims ?? 0;
  const list = (d.ledger?.claims ?? []).filter((c) => (filter === "all" || c.status === filter) && matches(c, q.trim().toLowerCase()));
  const tabs: Filter[] = ["all", ...STATUS_ORDER];
  return (
    <>
      <div className="sec-h"><h3>{t("dossier.ev.title")}</h3>
        <span className="meta">{rich(t("dossier.ev.meta"), { c: <N>{total}</N>, s: <N>{d.ledger?.counts.sources ?? 0}</N> })}</span></div>
      <Explainer total={total} unchecked={x.counts.unchecked} />
      <div className="tabs">
        {tabs.map((k) => (
          <button key={k} className={filter === k ? "on" : ""} onClick={() => { setFilter(k); setOpenId(null); }}>
            {k === "all" ? t("dossier.ev.all") : t(`dossier.status.${k}` as TKey)}
            <span className="num">{k === "all" ? total : x.counts[k]}</span>
          </button>
        ))}
      </div>
      <p className="hint ev-hint">{filter === "all" ? t("dossier.ev.hintAll") : <><StatusBadge status={filter} />　{t(`dossier.statusDesc.${filter}` as TKey)}</>}</p>
      {filter === "merged" ? (
        <div className="notice ev-merged"><Icon name="info" /><span>{t("dossier.ev.mergedNote", { n: x.counts.merged })}</span></div>
      ) : (
        <>
          <div className="filters">
            <label className="input ev-search"><Icon name="search" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("dossier.ev.searchPh")} /></label>
            <span className="sp" />
            <span className="hint">{t("dossier.ev.shown", { n: list.length })}</span>
          </div>
          <ClaimTable list={list} x={x} openId={openId} setOpenId={setOpenId} />
        </>
      )}
    </>
  );
}
