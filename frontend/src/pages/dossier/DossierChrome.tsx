import { Link } from "wouter";
import { toast } from "sonner";
import { Masthead } from "../../components/ui/Masthead";
import { Icon } from "../../components/ui/Icon";
import { saveText } from "../../lib/api";
import { clockTime, crId, dateShort } from "../../lib/format";
import { useT, type TKey } from "../../i18n";
import type { Dossier } from "./useDossier";
import type { Derived } from "./useDerived";
import { draftFileName } from "./model";

export const TABS = ["cover", "text", "evidence", "verdict", "process", "files"] as const;
export type Tab = (typeof TABS)[number];

export const tabHref = (sid: string, tab: Tab) => (tab === "cover" ? `/dossier/${sid}` : `/dossier/${sid}/${tab}`);

function MastTools({ d }: { d: Dossier }) {
  const { t, lang } = useT();
  const final = d.drafts.find((f) => f.kind === "final");
  const download = () => {
    if (final) saveText(final.download_url, draftFileName(d.sid, lang, null, null, false)).catch((e) => toast.error(String(e)));
  };
  const copy = () => navigator.clipboard.writeText(d.report).then(() => toast.success(t("dossier.mast.copied")));
  return (
    <>
      {final && <button className="linkbtn" onClick={download}><Icon name="download" />Markdown</button>}
      <button className="linkbtn" onClick={copy}><Icon name="copy" />{t("dossier.mast.copy")}</button>
      <button className="linkbtn" onClick={() => window.print()}><Icon name="printer" />{t("dossier.mast.print")}</button>
    </>
  );
}

/** 报头：卷宗 + 编号 + 结卷时间、深度、语言 */
export function DossierMast({ d }: { d: Dossier }) {
  const { t, lang } = useT();
  const closed = d.meta.last_updated;
  const facts = [
    closed && t("dossier.mast.closed", { d: `${dateShort(closed, lang)} ${clockTime(closed)}` }),
    d.entry?.depth && t(`dossier.depth.${d.entry.depth}` as TKey),
    d.entry?.language && t(`common.lang.${d.entry.language}` as TKey),
  ].filter(Boolean);
  return (
    <Masthead title={t("dossier.title")} tools={<MastTools d={d} />}>
      <span className="wk">{crId(d.sid)}</span>
      <span className="issue">{facts.join(" · ")}</span>
    </Masthead>
  );
}

function TocList({ sections, sec }: { sections: string[]; sec: number }) {
  const jump = (i: number) => document.getElementById(`sec-${i}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  return (
    <ul className="toc">
      {sections.map((s, i) => (
        <li key={i}><button className={i === sec ? "cur" : ""} onClick={() => jump(i)}>{s}</button></li>
      ))}
    </ul>
  );
}

/** 左侧编号页签索引；在正文页签下展开 13 章目录 */
export function DossierIndex({ d, x, tab, sec }: { d: Dossier; x: Derived; tab: Tab; sec: number }) {
  const { t } = useT();
  const counts: Record<Tab, string> = {
    cover: "",
    text: t("dossier.idx.chapters", { n: x.sections.length }),
    evidence: String(d.ledger?.counts.claims ?? 0),
    verdict: String(d.ledger?.counts.contradictions ?? 0),
    process: t("dossier.idx.rounds", { n: x.cycles }),
    files: t("dossier.idx.versions", { n: d.drafts.filter((f) => f.kind === "draft").length }),
  };
  return (
    <ul className="idx">
      {TABS.map((k, i) => (
        <li key={k}>
          <Link href={tabHref(d.sid, k)} className={tab === k ? "on" : ""}>
            <span className="no num">{String(i).padStart(2, "0")}</span>
            {t(`dossier.tab.${k}` as TKey)}
            <span className="c">{counts[k]}</span>
          </Link>
          {k === "text" && tab === "text" && <TocList sections={x.sections} sec={sec} />}
        </li>
      ))}
    </ul>
  );
}
