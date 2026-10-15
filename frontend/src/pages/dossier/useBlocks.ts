import { useMemo } from "react";
import type { LedgerClaim } from "../../lib/types";
import { useT, type TKey } from "../../i18n";
import { toBlocks, type Block, type ChipLabel } from "./markdown";

/** 报告 / 草稿 Markdown 切块；声明编号的读屏文字随界面语言 */
export function useBlocks(md: string | null, claims: Map<string, LedgerClaim>, live: boolean): Block[] {
  const { t } = useT();
  return useMemo(() => {
    if (md == null) return [];
    const label: ChipLabel = (id, c) =>
      c ? t("dossier.chip", { id, s: t(`dossier.status.${c.status}` as TKey) }) : t("dossier.chipUnknown", { id });
    return toBlocks(md, claims, { label, live });
  }, [md, claims, live, t]);
}
