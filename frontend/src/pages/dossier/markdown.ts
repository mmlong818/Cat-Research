import { marked } from "marked";
import DOMPurify from "dompurify";
import { iconHtml, type IconName } from "../../components/ui/Icon";
import type { LedgerClaim } from "../../lib/types";
import { CITE, splitIds } from "./model";

export interface Block {
  kind: "h1" | "h2" | "h3" | "flow";
  html: string;
  ids: string[];   // 本块引用的声明编号（去重，按出现顺序）
  cont: boolean;   // 拆开的列表里第二条起：与上一条之间不留段距
  sec?: number;    // 二级标题的章序号，正文目录用
}

export type ChipLabel = (id: string, claim?: LedgerClaim) => string;

export const STATUS_ICON: Partial<Record<LedgerClaim["status"], IconName>> = {
  supported: "check", disputed: "warning", overruled: "prohibit", unverifiable: "question",
};

const HAS_CITE = /\[C\d+/;
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

export interface BlockOptions {
  label: ChipLabel;
  live: boolean;   // 正文：编号是可点的按钮、二级标题带 id="sec-N"；附件里的草稿只着色，不带 id（避免重复）
}

function chip(id: string, claim: LedgerClaim | undefined, { label, live }: BlockOptions): string {
  const icon = claim && STATUS_ICON[claim.status] ? iconHtml(STATUS_ICON[claim.status]!) : "";
  const cls = `cc ${claim ? claim.status : "ext"}`;
  const text = esc(label(id, claim));
  return live
    ? `<button type="button" class="${cls}" data-c="${id}" aria-label="${text}">${id}${icon}</button>`
    : `<span class="${cls}" title="${text}">${id}${icon}</span>`;
}

/** 文本节点里的 [C#] 换成声明编号（只动文本节点，不碰属性），返回引用到的编号 */
function linkCites(root: Element, claims: Map<string, LedgerClaim>, opts: BlockOptions): string[] {
  const ids: string[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const hits: Text[] = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) if (HAS_CITE.test(n.nodeValue ?? "")) hits.push(n as Text);
  for (const node of hits) {
    const html = esc(node.nodeValue ?? "").replace(CITE, (_, group: string) =>
      splitIds(group).map((id) => { ids.push(id); return chip(id, claims.get(id), opts); }).join(""));
    const tpl = document.createElement("template");
    tpl.innerHTML = html;
    node.replaceWith(tpl.content);
  }
  return [...new Set(ids)];
}

function kindOf(tag: string): Block["kind"] {
  if (tag === "H1") return "h1";
  if (tag === "H2") return "h2";
  return /^H[3-6]$/.test(tag) ? "h3" : "flow";
}

/** 列表按条拆开（编号用 start 接上），旁注能对齐到每一条，不会整张列表的注挤在一起 */
function pieces(el: Element): { el: Element; cont: boolean }[] {
  const items = Array.from(el.children).filter((c) => c.tagName === "LI");
  if (!/^(OL|UL)$/.test(el.tagName) || items.length < 2) return [{ el, cont: false }];
  const start = Number(el.getAttribute("start") ?? 1);
  return items.map((li, i) => {
    const list = el.cloneNode(false) as Element;
    if (el.tagName === "OL") list.setAttribute("start", String(start + i));
    list.appendChild(li);
    return { el: list, cont: i > 0 };
  });
}

/**
 * 报告 Markdown → 按顶层元素切成的块（每块在正文里占一行，右边是它的旁注）。
 * 报告来自网页抓取 + 模型生成，属不可信内容：先经 DOMPurify 清理，再只在文本节点里插入声明编号。
 */
export function toBlocks(md: string, claims: Map<string, LedgerClaim>, opts: BlockOptions): Block[] {
  const frag = DOMPurify.sanitize(marked.parse(md, { async: false }) as string, { RETURN_DOM_FRAGMENT: true });
  const blocks: Block[] = [];
  let sec = -1;
  for (const top of Array.from(frag.children)) {
    top.querySelectorAll("a[href]").forEach((a) => { a.setAttribute("target", "_blank"); a.setAttribute("rel", "noopener noreferrer"); });
    for (const { el, cont } of pieces(top)) {
      const ids = linkCites(el, claims, opts);
      const kind = kindOf(el.tagName);
      if (kind === "h2") sec += 1;
      if (kind === "h2" && opts.live) el.id = `sec-${sec}`;
      const html = el.tagName === "TABLE" ? `<div class="tbl">${el.outerHTML}</div>` : el.outerHTML;
      blocks.push({ kind, html, ids, cont, ...(kind === "h2" ? { sec } : {}) });
    }
  }
  return blocks;
}
