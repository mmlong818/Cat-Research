import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Folio } from "../../components/ui/Folio";
import { Icon } from "../../components/ui/Icon";
import { Score } from "../../components/ui/Score";
import { fetchText, saveText, type DraftFile } from "../../lib/api";
import { clockTime, f2 } from "../../lib/format";
import type { LedgerClaim } from "../../lib/types";
import { useT } from "../../i18n";
import { Mixed, N, rich } from "../../i18n/rich";
import type { Dossier } from "./useDossier";
import type { Derived } from "./useDerived";
import { bodyOf, draftFileName } from "./model";
import { useBlocks } from "./useBlocks";

interface Row { file: DraftFile; name: string; score: number | null; isFinal: boolean }

function useRows(d: Dossier, x: Derived): Row[] {
  const { lang } = useT();
  const drafts = d.drafts.filter((f) => f.kind === "draft").sort((a, b) => (b.draft_num ?? 0) - (a.draft_num ?? 0));
  const rows = drafts.map((file) => {
    const n = file.draft_num ?? 0;
    const score = x.history[n] ?? null;
    const isFinal = n === x.finalDraft;
    return { file, score, isFinal, name: draftFileName(d.sid, lang, n, score, isFinal) };
  });
  const final = d.drafts.find((f) => f.kind === "final");
  return final ? [...rows, { file: final, score: null, isFinal: false, name: draftFileName(d.sid, lang, null, null, false) }] : rows;
}

function RowNote({ row, x }: { row: Row; x: Derived }) {
  const { t } = useT();
  const n = row.file.draft_num;
  if (n == null) return <>{rich(t("dossier.files.reportNote"), { v: <N>{x.finalDraft ?? "?"}</N> })}</>;
  const review = row.score != null
    ? rich(t(n === 0 ? "dossier.files.firstNote" : "dossier.files.reviewNote"), { c: <N>{n + 1}</N>, s: <N>{f2(row.score)}</N> })
    : t("dossier.files.notReviewed");
  return <>{review}{row.isFinal && t("dossier.files.picked")}</>;
}

function DraftView({ row, claims, onClose }: { row: Row; claims: Map<string, LedgerClaim>; onClose: () => void }) {
  const { t } = useT();
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => { fetchText(row.file.download_url).then(setText).catch(() => setFailed(true)); }, [row.file.download_url]);
  const blocks = useBlocks(text == null ? null : bodyOf(text), claims, false);
  const n = row.file.draft_num;
  const title = n == null ? t("dossier.files.report") : t(row.isFinal ? "dossier.files.titleFinal" : "dossier.files.title", { n });
  return (
    <Folio crumb={t("dossier.files.crumb", { name: title })} onClose={onClose}>
      <div className="kicker">{t("dossier.tab.files")}<span className="fn"><Mixed text={row.name} /></span></div>
      <h2>{title}</h2>
      <div className="byline">
        {row.score != null && <span>{t("dossier.files.score")} <span className="num">{f2(row.score)}</span></span>}
        <span>{t("dossier.files.done")} <span className="num">{clockTime(row.file.modified_at)}</span></span>
        <span><span className="num">{(row.file.size / 1024).toFixed(1)}</span> KB</span>
      </div>
      <div className="acts"><DownloadButton row={row} /></div>
      {failed && <div className="notice draft-msg"><Icon name="info" />{t("dossier.files.loadFailed")}</div>}
      {!failed && text == null && <p className="hint draft-msg">{t("dossier.loading")}</p>}
      <div className="tx draftview" dangerouslySetInnerHTML={{ __html: blocks.map((b) => b.html).join("") }} />
    </Folio>
  );
}

function DownloadButton({ row, quiet = false }: { row: Row; quiet?: boolean }) {
  const { t } = useT();
  const save = () => saveText(row.file.download_url, row.name).catch((e) => toast.error(String(e)));
  return <button className={`btn btn--sm${quiet ? " btn--text" : ""}`} onClick={save}><Icon name="download" />{t("dossier.files.download")}</button>;
}

/** 附件：各版草稿与最终报告，对开页里在线看；下载走现有 drafts download 接口，文件名可读 */
export function FilesTab({ d, x }: { d: Dossier; x: Derived }) {
  const { t } = useT();
  const rows = useRows(d, x);
  const [viewing, setViewing] = useState<Row | null>(null);
  const close = useCallback(() => setViewing(null), []);
  return (
    <>
      <div className="sec-h"><h3>{t("dossier.tab.files")}</h3><span className="meta">{t("dossier.files.meta")}</span></div>
      <div className="tbl">
        <table className="il files">
          <thead><tr><th>{t("dossier.files.colFile")}</th><th className="w-score">{t("dossier.files.score")}</th>
            <th className="w-time">{t("dossier.files.done")}</th><th>{t("dossier.files.colNote")}</th><th className="r w-ops" /></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.file.name}>
                <td><span className="fn"><Mixed text={row.name} /></span>{row.isFinal && <span className="tag gold">{t("dossier.files.final")}</span>}</td>
                <td>{row.score != null && <Score score={row.score} />}</td>
                <td className="num">{clockTime(row.file.modified_at)}</td>
                <td><RowNote row={row} x={x} /></td>
                <td className="r ops">
                  <button className="btn btn--sm" onClick={() => setViewing(row)}><Icon name="eye" />{t("dossier.files.view")}</button>
                  <DownloadButton row={row} quiet />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {viewing && <DraftView row={viewing} claims={x.claims} onClose={close} />}
    </>
  );
}
