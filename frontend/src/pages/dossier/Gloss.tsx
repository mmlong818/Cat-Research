import { memo, useCallback, useEffect, useLayoutEffect, type RefObject } from "react";
import type { LedgerClaim } from "../../lib/types";
import { useT } from "../../i18n";
import { Icon } from "../../components/ui/Icon";
import { ClaimEvidence, StatusBadge } from "./ClaimParts";

interface NoteProps {
  id: string;
  claim?: LedgerClaim;
  rep: boolean;    // 前文已注：同一声明再次出现时折叠，只留一行
  open: boolean;
  on: boolean;
  sid: string;
}

function NoteHead({ id, claim, label }: { id: string; claim?: LedgerClaim; label: string }) {
  return (
    <>
      <span className="cid num">{id}</span>
      {claim && <StatusBadge status={claim.status} />}
      <span className="gl-n">{label}</span>
    </>
  );
}

/** 展开的旁注：宽屏时浮在旁注栏上方（不占位，不推挤正文和其他旁注），窄屏时排在段落下方 */
function NotePop({ id, claim, sid }: { id: string; claim?: LedgerClaim; sid: string }) {
  const { t } = useT();
  return (
    <div className="gl-pop" role="dialog" aria-label={t("dossier.chipUnknown", { id })}>
      <div className="gl-h">
        <NoteHead id={id} claim={claim} label={claim ? t("dossier.gloss.sources", { n: claim.sources.length }) : ""} />
        <button type="button" className="iconbtn gl-x" title={t("common.close")}><Icon name="x" /></button>
      </div>
      <p className="gl-full" lang={claim ? "en" : undefined}>{claim ? claim.text : t("dossier.gloss.missing")}</p>
      {claim && <ClaimEvidence claim={claim} limit={3} sid={sid} />}
    </div>
  );
}

/** 正文旁注：折叠时一行编号状态 + 两行英文原文；点编号或旁注展开来源、引语、核查备注 */
export const GlossNote = memo(function GlossNote({ id, claim, rep, open, on, sid }: NoteProps) {
  const { t } = useT();
  const cls = ["gl", rep && "rep", open && "open", on && "on"].filter(Boolean).join(" ");
  const label = rep ? t("dossier.gloss.seen") : claim ? t("dossier.gloss.sources", { n: claim.sources.length }) : "";
  return (
    <div className={cls} data-c={id}>
      <button type="button" className="gl-h" aria-expanded={open}><NoteHead id={id} claim={claim} label={label} /></button>
      {!rep && <p className="gl-en" lang={claim ? "en" : undefined}>{claim ? claim.text : t("dossier.gloss.missing")}</p>}
      {open && <NotePop id={id} claim={claim} sid={sid} />}
    </div>
  );
});

export const isWide = (art: HTMLElement) => {
  const blk = art.querySelector<HTMLElement>(".blk");
  return !!blk && getComputedStyle(blk).gridTemplateColumns.trim().split(/\s+/).length > 1;
};

/** 每条旁注推到它所注的编号的同一高度，碰撞时顺延；只按折叠时的高度算（展开层是绝对定位，不计入 offsetHeight）。
 *  先清空、再统一读、最后统一写，只触发一次排版。 */
function alignNotes(art: HTMLElement) {
  const notes = Array.from(art.querySelectorAll<HTMLElement>(".gls .gl"));
  notes.forEach((g) => { g.style.marginTop = ""; });
  if (!isWide(art)) return;
  const plan: [HTMLElement, number][] = [];
  art.querySelectorAll<HTMLElement>(".blk").forEach((blk) => {
    const top = blk.getBoundingClientRect().top;
    let floor = 0;
    blk.querySelectorAll<HTMLElement>(".gls .gl").forEach((g) => {
      const cite = blk.querySelector<HTMLElement>(`.tx .cc[data-c="${g.dataset.c}"]`);
      const want = cite ? Math.max(0, cite.getBoundingClientRect().top - top - 4) : floor;
      const at = Math.max(want, floor);
      plan.push([g, at - floor]);
      floor = at + g.offsetHeight;
    });
  });
  plan.forEach(([g, m]) => { g.style.marginTop = m ? `${m}px` : ""; });
}

/** version 变化（正文内容）后重排；正文宽度变化（窗口、案头收起）与网络字体到位后也重排。展开、收起不重排 */
export function useGlossAlign(artRef: RefObject<HTMLElement | null>, version: unknown) {
  const align = useCallback(() => { if (artRef.current) alignNotes(artRef.current); }, [artRef]);
  useLayoutEffect(() => { align(); }, [align, version]);
  useEffect(() => {
    const art = artRef.current;
    if (!art) return;
    let frame = 0;
    let width = -1;
    const later = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(align); };
    const ro = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width !== width) { width = entry.contentRect.width; later(); }
    });
    ro.observe(art);
    document.fonts.ready.then(later);
    document.fonts.addEventListener("loadingdone", later);
    return () => {
      ro.disconnect();
      cancelAnimationFrame(frame);
      document.fonts.removeEventListener("loadingdone", later);
    };
  }, [artRef, align]);
}
