import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState, type MouseEvent, type RefObject } from "react";
import type { LedgerClaim } from "../../lib/types";
import { useT } from "../../i18n";
import type { Block } from "./markdown";
import { GlossNote, isWide, useGlossAlign } from "./Gloss";
import { StatusBadge } from "./ClaimParts";
import type { ClaimStatus } from "./model";

interface Slot { id: string; rep: boolean }

/** 每块要注的声明；同一声明在前文注过的标成「前文已注」 */
function slotsOf(blocks: Block[]): Slot[][] {
  const seen = new Set<string>();
  return blocks.map((b) => b.ids.map((id) => {
    const rep = seen.has(id);
    seen.add(id);
    return { id, rep };
  }));
}

interface BlockProps {
  block: Block;
  slots: Slot[];
  index: number;
  openKey: string;     // 本块里展开的编号（逗号连接），用于 memo 比较
  active: string | null;
  claims: Map<string, LedgerClaim>;
  sid: string;
}

const BlockView = memo(function BlockView({ block, slots, index, openKey, active, claims, sid }: BlockProps) {
  const open = new Set(openKey.split(","));
  return (
    <div className={`blk ${block.kind}${block.cont ? " cont" : ""}`} data-i={index}>
      <div className="tx" dangerouslySetInnerHTML={{ __html: block.html }} />
      <aside className="gls">
        {slots.map((s) => (
          <GlossNote key={s.id} id={s.id} claim={claims.get(s.id)} rep={s.rep} sid={sid}
                     open={open.has(s.id)} on={active === s.id} />
        ))}
      </aside>
    </div>
  );
});

const LEGEND: ClaimStatus[] = ["supported", "disputed", "overruled", "unverifiable", "unchecked"];

/** 当前章：标题已经越过主区上方四分之一处的最后一章 */
function useSectionSpy(artRef: RefObject<HTMLDivElement | null>, blocks: Block[], onSection: (i: number) => void) {
  useEffect(() => {
    const art = artRef.current;
    const root = art?.closest<HTMLElement>(".shell-main");
    if (!art || !root) return;
    const heads = Array.from(art.querySelectorAll<HTMLElement>("h2[id^='sec-']"));
    let frame = 0;
    const update = () => {
      const line = root.getBoundingClientRect().top + root.clientHeight / 4;
      const passed = heads.filter((h) => h.getBoundingClientRect().top <= line);
      onSection(passed.length ? Number(passed[passed.length - 1].id.slice(4)) : 0);
    };
    const onScroll = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(update); };
    root.addEventListener("scroll", onScroll, { passive: true });
    update();
    return () => { root.removeEventListener("scroll", onScroll); cancelAnimationFrame(frame); };
  }, [artRef, blocks, onSection]);
}

/**
 * 展开状态以「块序号:编号」记：点哪一处的编号就展开哪一处的旁注。
 * 宽屏同一时间只展开一条，点别处或按 Esc 收起；窄屏（旁注排在段落下方）可同时展开多条，维持原样。
 */
function useNotes(artRef: RefObject<HTMLDivElement | null>) {
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [active, setActive] = useState<string | null>(null);
  const reveal = useRef<string | null>(null);
  const close = () => { setOpen(new Set()); setActive(null); };
  const toggle = (key: string, id: string, fromCite: boolean) => {
    const opening = !open.has(key);
    const wide = !!artRef.current && isWide(artRef.current);
    const next = new Set(wide ? [] : open);
    if (opening) next.add(key); else next.delete(key);
    reveal.current = opening && fromCite ? key : null;
    setOpen(next);
    setActive(opening ? id : null);
  };
  useEffect(() => {
    const art = artRef.current;
    if (!art || open.size === 0) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && isWide(art)) close(); };
    const onDown = (e: Event) => {
      if (isWide(art) && !(e.target as HTMLElement).closest(".gl-pop, .art .cc, .art .gl")) close();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => { document.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onDown); };
  }, [artRef, open]);
  return { open, active, toggle, reveal };
}

/** 正文：每块右侧是它的旁注栏；正文里的 [C#] 按状态着色，点开对应旁注 */
export function TextTab({ blocks, claims, sid, onSection }: {
  blocks: Block[]; claims: Map<string, LedgerClaim>; sid: string; onSection: (i: number) => void;
}) {
  const { t } = useT();
  const artRef = useRef<HTMLDivElement>(null);
  const { open, active, toggle, reveal } = useNotes(artRef);
  const slots = useMemo(() => slotsOf(blocks), [blocks]);
  useGlossAlign(artRef, blocks);
  useSectionSpy(artRef, blocks, onSection);

  useLayoutEffect(() => {
    const art = artRef.current;
    art?.querySelectorAll(".cc.on").forEach((c) => c.classList.remove("on"));
    if (active) art?.querySelectorAll(`.cc[data-c="${active}"]`).forEach((c) => c.classList.add("on"));
    const [blk, id] = reveal.current?.split(":") ?? [];
    const pop = id && art?.querySelector<HTMLElement>(`.blk[data-i="${blk}"] .gl.open[data-c="${id}"] .gl-pop`);
    if (pop) pop.scrollIntoView({ block: "nearest", behavior: "smooth" });
    reveal.current = null;
  }, [active, open, reveal]);

  const onClick = (e: MouseEvent<HTMLDivElement>) => {
    const el = e.target as HTMLElement;
    if (el.closest("a") || (el.closest(".gl-pop") && !el.closest(".gl-x"))) return;
    const hit = el.closest<HTMLElement>(".cc, .gl");
    const blk = hit?.closest<HTMLElement>(".blk");
    if (hit?.dataset.c && blk) toggle(`${blk.dataset.i}:${hit.dataset.c}`, hit.dataset.c, hit.classList.contains("cc"));
  };

  return (
    <div className="art" ref={artRef} onClick={onClick}>
      <div className="legend">
        <span>{t("dossier.text.legend")}</span>
        {LEGEND.map((s) => <StatusBadge key={s} status={s} />)}
      </div>
      {blocks.map((b, i) => (
        <BlockView key={i} index={i} block={b} slots={slots[i]} claims={claims} sid={sid}
                   openKey={b.ids.filter((id) => open.has(`${i}:${id}`)).join(",")}
                   active={active && b.ids.includes(active) ? active : null} />
      ))}
    </div>
  );
}
