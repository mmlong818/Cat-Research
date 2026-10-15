import { Link } from "wouter";
import { Icon, type IconName } from "../../components/ui/Icon";
import { host, webUrl } from "../../lib/format";
import type { LedgerClaim } from "../../lib/types";
import { useT, type TKey } from "../../i18n";
import { CITE, splitIds, type ClaimStatus } from "./model";
import { STATUS_ICON } from "./markdown";

const BADGE_ICON: Record<ClaimStatus, IconName> = {
  unchecked: "dash", merged: "merge", unverifiable: "question", disputed: "warning", supported: "check", overruled: "prohibit",
};

/** 声明状态（台账口径）：颜色 + 图标 + 文字 */
export function StatusBadge({ status }: { status: ClaimStatus }) {
  const { t } = useT();
  return <span className={`st ${status}`}><Icon name={BADGE_ICON[status]} />{t(`dossier.status.${status}` as TKey)}</span>;
}

/** 来源标题与链接、站点、发布日期、原文引语；limit 只显示前几个 */
export function SourceList({ claim, limit }: { claim: LedgerClaim; limit?: number }) {
  const { t } = useT();
  const shown = limit ? claim.sources.slice(0, limit) : claim.sources;
  return (
    <>
      {shown.map((s) => (
        <div className="ev-src" key={s.id}>
          <span className="num sid">{s.id}</span>
          <a href={webUrl(s.url)} target="_blank" rel="noopener noreferrer">{s.title || host(s.url)}{"\u00a0"}<Icon name="out" small /></a>
          <div className="meta">
            {host(s.url)} · {s.published ? t("dossier.ev.published", { d: s.published }) : t("dossier.ev.noDate")}
          </div>
          {claim.quotes[s.id] && <blockquote className="ev-q" lang="en">{claim.quotes[s.id]}</blockquote>}
        </div>
      ))}
    </>
  );
}

/** 一条声明的全部证据：来源与引语、核查备注、状态说明 */
export function ClaimEvidence({ claim, limit, sid }: { claim: LedgerClaim; limit?: number; sid?: string }) {
  const { t } = useT();
  const more = limit ? claim.sources.length - limit : 0;
  return (
    <>
      <div className="ev-k">{t("dossier.ev.sources", { n: claim.sources.length })}</div>
      <SourceList claim={claim} limit={limit} />
      {more > 0 && sid && (
        <Link className="more ev-more" href={`/dossier/${sid}/evidence?c=${claim.id}`}>
          {t("dossier.ev.moreSources", { n: more })} <Icon name="arrow-right" small />
        </Link>
      )}
      {claim.note && (<><div className="ev-k">{t("dossier.ev.note")}</div><p className="ev-note">{claim.note}</p></>)}
      <p className="ev-why">{t(`dossier.statusDesc.${claim.status}` as TKey)}</p>
    </>
  );
}

/** 封面摘要里的行内 Markdown：只认 **加粗** 与 [C#]；编号点开到证据页那一条 */
export function InlineText({ text, sid, claims }: { text: string; sid: string; claims: Map<string, LedgerClaim> }) {
  const parts = text.split(/(\*\*.+?\*\*|\[C\d+(?:\s*[,，、]\s*C\d+)*\])/g).filter(Boolean);
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
        if (!new RegExp(`^${CITE.source}$`).test(p)) return p;
        return splitIds(p.slice(1, -1)).map((id) => {
          const c = claims.get(id);
          const icon = c && STATUS_ICON[c.status];
          return (
            <Link key={`${i}-${id}`} className={`cc ${c ? c.status : "ext"}`} href={`/dossier/${sid}/evidence?c=${id}`}>
              {id}{icon && <Icon name={icon} />}
            </Link>
          );
        });
      })}
    </>
  );
}
