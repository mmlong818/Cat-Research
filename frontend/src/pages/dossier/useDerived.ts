import { useMemo } from "react";
import type { Dossier } from "./useDossier";
import { bodyOf, citedIds, claimIndex, sectionsOf, sentenceIndex, statusCounts, summaryOf } from "./model";

/** 卷宗各页共用的派生数据：都从真实接口的返回值推出来 */
export function useDerived(d: Dossier) {
  return useMemo(() => {
    const body = bodyOf(d.report);
    const history = d.meta.score_history ?? [];
    const finalScore = d.meta.final_score ?? d.entry?.final_score ?? null;
    const stopReason = [...d.audit].reverse().find((e) => e.kind === "loop_stop")?.payload.reason;
    return {
      body,
      history,
      finalScore,
      finalDraft: d.entry?.final_draft ?? null,
      bestDraft: d.entry?.best_scored_draft ?? null,
      citations: d.entry?.citations ?? null,
      stopReason: typeof stopReason === "string" ? stopReason : null,
      claims: claimIndex(d.ledger),
      counts: statusCounts(d.ledger),
      sections: sectionsOf(body),
      summary: summaryOf(body),
      cited: citedIds(body).length,
      sentences: sentenceIndex(body),
      cycles: d.meta.total_cycles ?? d.entry?.total_cycles ?? d.reviews.length,
    };
  }, [d]);
}

export type Derived = ReturnType<typeof useDerived>;
