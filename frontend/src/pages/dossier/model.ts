import type { LedgerClaim, LedgerView } from "../../lib/types";
import { crId, f2 } from "../../lib/format";
import type { Lang } from "../../i18n";

export type ClaimStatus = LedgerClaim["status"];
export const STATUS_ORDER: ClaimStatus[] = ["unchecked", "merged", "unverifiable", "disputed", "supported", "overruled"];

// 与后端 research/ledger.py 的 CITE 一致：[C12] 或 [C1, C2]
export const CITE = /\[(C\d+(?:\s*[,，、]\s*C\d+)*)\]/g;
export const splitIds = (group: string) => group.split(/\s*[,，、]\s*/);

// 与后端 _GENERATED_APPENDIX 一致：「声明来源」「研究质量报告」（中英标题都认）及之后都不是正文
const APPENDIX = /\n#{1,6}[ \t]*(?:声明来源|Claim sources|研究质量报告|Research quality report)[ \t]*(?:\n|$)/;

export function bodyOf(md: string): string {
  const m = APPENDIX.exec(md);
  return (m ? md.slice(0, m.index) : md).replace(/\n-{3,}\s*$/, "").trimEnd();
}

/** 正文引用过的声明编号（去重，按出现顺序） */
export function citedIds(body: string): string[] {
  const seen = new Set<string>();
  for (const m of body.matchAll(CITE)) splitIds(m[1]).forEach((id) => seen.add(id));
  return [...seen];
}

export const sectionsOf = (body: string) => [...body.matchAll(/^## (.+)$/gm)].map((m) => m[1].trim());

export interface Summary {
  dek: string;
  conclusions: { head: string; text: string }[];
}

/** 摘要：正文第一个二级标题下的首段与编号列表（核心结论） */
export function summaryOf(body: string): Summary | null {
  const head = /^## .+$/m.exec(body);
  if (!head) return null;
  const rest = body.slice(head.index + head[0].length);
  const end = rest.search(/^## /m);
  const lines = (end >= 0 ? rest.slice(0, end) : rest).split("\n").map((l) => l.trim())
    .filter((l) => l && !/^-{3,}$/.test(l) && !l.startsWith("#"));
  const numbered = /^\d+\.\s+/;
  const conclusions = lines.filter((l) => numbered.test(l)).map((l) => {
    const item = l.replace(numbered, "");
    const bold = item.match(/^\*\*(.+?)\*\*\s*(.*)$/);
    return bold ? { head: bold[1], text: bold[2] } : { head: item, text: "" };
  });
  return { dek: lines.find((l) => !numbered.test(l)) ?? "", conclusions };
}

export const claimIndex = (view: LedgerView | null) => new Map((view?.claims ?? []).map((c) => [c.id, c]));

/** 各状态的声明数，口径是全台账：已合并的不在视图的声明列表里，用总数减出来 */
export function statusCounts(view: LedgerView | null): Record<ClaimStatus, number> {
  const counts = Object.fromEntries(STATUS_ORDER.map((s) => [s, 0])) as Record<ClaimStatus, number>;
  for (const c of view?.claims ?? []) counts[c.status] += 1;
  counts.merged = Math.max(0, (view?.counts.claims ?? 0) - (view?.claims.length ?? 0));
  return counts;
}

const plain = (s: string) =>
  s.replace(CITE, "").replace(/\*\*/g, "").replace(/\|/g, " ").replace(/^[-\s\d.#>]+/, "").replace(/\s+/g, " ").trim();

/** 声明编号 → 报告里第一次引用它的那句话 */
export function sentenceIndex(body: string): Map<string, string> {
  const index = new Map<string, string>();
  for (const part of body.split(/(?<=[。！？])|\n/)) {
    for (const m of part.matchAll(CITE)) {
      splitIds(m[1]).forEach((id) => { if (!index.has(id)) index.set(id, plain(part)); });
    }
  }
  return index;
}

/** 下载与附件列表里的可读文件名 */
export function draftFileName(sid: string, lang: Lang, draft: number | null, score: number | null, isFinal: boolean) {
  const zh = lang === "zh";
  if (draft == null) return `${crId(sid)}_${zh ? "报告" : "report"}.md`;
  const parts = [crId(sid), zh ? `第${draft}版` : `v${draft}`];
  if (score != null) parts.push(f2(score));
  if (isFinal) parts.push(zh ? "终稿" : "final");
  return `${parts.join("_")}.md`;
}

export const DIMS = ["completeness", "accuracy", "depth", "clarity", "usefulness", "sources", "simplicity"] as const;

// 与后端 config.QUALITY_THRESHOLD 一致：评审分达到它（且结论验证达标）才可提前结束改进循环
export const QUALITY_THRESHOLD = 8;
