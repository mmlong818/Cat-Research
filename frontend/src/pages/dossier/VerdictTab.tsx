import { Icon } from "../../components/ui/Icon";
import { host, webUrl } from "../../lib/format";
import type { LedgerContradiction } from "../../lib/types";
import { useT } from "../../i18n";
import { N, rich } from "../../i18n/rich";
import type { Dossier } from "./useDossier";
import { StatusBadge } from "./ClaimParts";

function Ruling({ x }: { x: LedgerContradiction }) {
  const { t } = useT();
  const r = x.resolution;
  if (!r) return <span className="tag warn"><Icon name="warning" small />{t("dossier.vd.pending")}</span>;
  if (r.sides_with === "neither") return <span className="tag warn"><Icon name="warning" small />{t("dossier.vd.neither")}</span>;
  return <span className="tag gold"><Icon name="check" small />{t("dossier.vd.won", { id: r.sides_with })}</span>;
}

function Side({ x, i }: { x: LedgerContradiction; i: number }) {
  const { t } = useT();
  const c = x.claims[i];
  const src = c.sources[0];
  return (
    <div>
      <div className="side-k"><span className="muted">{t(i === 0 ? "dossier.vd.sideA" : "dossier.vd.sideB")}</span>
        <span className="num">{c.id}</span><StatusBadge status={c.status} /></div>
      <p className="en" lang="en">{c.text}</p>
      {src && <a className="src" href={webUrl(src.url)} target="_blank" rel="noopener noreferrer">{src.title || host(src.url)}{"\u00a0"}<Icon name="out" small /></a>}
    </div>
  );
}

function Verdict({ x }: { x: LedgerContradiction }) {
  const { t } = useT();
  const r = x.resolution;
  return (
    <div className="vd">
      <div className="no"><b>{x.id}</b><Ruling x={x} /></div>
      <div>
        <h4>{x.topic}</h4>
        <div className="ab">{x.claims.map((c, i) => <Side key={c.id} x={x} i={i} />)}</div>
        {r?.reason && <p className="why">{r.reason}</p>}
        {r?.evidence_url && (
          <a className="more" href={webUrl(r.evidence_url)} target="_blank" rel="noopener noreferrer">
            {t("dossier.vd.basis", { h: host(r.evidence_url) })} <Icon name="out" small />
          </a>
        )}
      </div>
    </div>
  );
}

/** 裁决：每处矛盾的双方说法、谁胜出或两方存疑、理由、依据链接 */
export function VerdictTab({ d }: { d: Dossier }) {
  const { t } = useT();
  const xs = d.ledger?.contradictions ?? [];
  const pending = d.ledger?.counts.unresolved ?? 0;
  return (
    <>
      <div className="sec-h"><h3>{t("dossier.vd.title")}</h3>
        <span className="meta">{rich(t("dossier.vd.meta"), { n: <N>{xs.length}</N>, u: <N>{pending}</N> })}</span></div>
      <p className="dateline vd-intro">{t("dossier.vd.intro")}</p>
      {xs.length ? xs.map((x) => <Verdict key={x.id} x={x} />) : <p className="hint vd-empty">{t("dossier.vd.empty")}</p>}
    </>
  );
}
