import { useCallback, useState } from "react";
import { useLocation } from "wouter";
import { ApiError, clarify, research, type ClarifySummary, type ClarifyTurn } from "../../lib/api";
import {
  FIELD_KEYS, depthRequest, getDraft, modelRequest, resetDraft, setDraft, setStep, type Draft, type Fields, type Lang,
} from "./draft";

export type Busy = "ask" | "reply" | "sign" | null;
export interface Failure { kind: "clarify" | "sign" | "full"; message: string }

const fieldsOf = (s: ClarifySummary) => ({
  objective: s.objective ?? "", scope: s.scope ?? "", timeframe: s.timeframe ?? "",
  aspects: Array.isArray(s.key_aspects) ? s.key_aspects : [], exclude: s.exclude ?? "",
});

/** 研究助理的一轮回答并入草稿：你手动改过的栏不覆盖；记下这一轮写进了哪些栏 */
function mergeTurn(d: Draft, res: ClarifyTurn): Draft {
  const incoming = fieldsOf(res.summary ?? ({} as ClarifySummary));
  const free = (k: (typeof FIELD_KEYS)[number]) => !d.edited.includes(k);
  const wrote = FIELD_KEYS.filter((k) =>
    free(k) && incoming[k].length > 0 && JSON.stringify(d.fields[k]) !== JSON.stringify(incoming[k]));
  const fields: Fields = {
    ...d.fields,
    objective: free("objective") ? incoming.objective : d.fields.objective,
    scope: free("scope") ? incoming.scope : d.fields.scope,
    timeframe: free("timeframe") ? incoming.timeframe : d.fields.timeframe,
    aspects: free("aspects") ? incoming.aspects : d.fields.aspects,
    exclude: free("exclude") ? incoming.exclude : d.fields.exclude,
  };
  return { ...d, summary: res.summary, fields, ready: !!res.ready, turns: [...d.turns, { who: "ai", text: res.message, wrote }] };
}

/** 签发时的摘要：以委托单上的内容为准 */
const summaryOf = (d: Draft): ClarifySummary => ({
  ...(d.summary as ClarifySummary),
  objective: d.fields.objective, scope: d.fields.scope, timeframe: d.fields.timeframe,
  key_aspects: d.fields.aspects, exclude: d.fields.exclude,
});

/** 跳过提问时没有澄清会话：委托单上手填的各栏按后端 summary_to_brief 的写法拼成补充说明，随 POST /api/research 带上 */
function briefOf(d: Draft): string | undefined {
  const f = d.fields;
  const lines = [
    f.objective.trim() && `研究目标：${f.objective.trim()}`,
    f.scope.trim() && `研究范围：${f.scope.trim()}`,
    f.aspects.length > 0 && `重点方面：${f.aspects.join("、")}`,
    f.timeframe.trim() && `时间范围：${f.timeframe.trim()}`,
    f.exclude.trim() && `排除内容：${f.exclude.trim()}`,
    f.extra.trim() && `特别要求：${f.extra.trim()}`,
  ].filter(Boolean);
  return lines.length ? lines.join("\n") : undefined;
}

const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** 签发：澄清过的走 confirm（带改过的摘要、研究问题、研究目标与特别要求），跳过提问的直接 POST /api/research（带手填的委托单）；返回任务编号 */
async function submit(d: Draft, uiLang: Lang): Promise<string> {
  const common = { ...depthRequest(d), language: d.lang ?? uiLang, ask_loop: d.askLoop, ...modelRequest(d.model) };
  const { task_id } = d.clarifyId
    ? await clarify.confirm(d.clarifyId, {
      ...common, summary: summaryOf(d), question: d.question.trim(),
      goal: d.fields.objective.trim() || undefined, extra_note: d.fields.extra.trim() || undefined,
    })
    : await research.start(d.question.trim(), { ...common, clarification: briefOf(d) });
  return task_id;
}

/** 跑一个动作的状态：进行中的是哪个、失败原因（429 = 已达并发上限，单独说明） */
function useRunner() {
  const [busy, setBusy] = useState<Busy>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const run = useCallback(async (kind: Busy, fn: () => Promise<void>, fail: Failure["kind"]) => {
    setBusy(kind);
    setFailure(null);
    try {
      await fn();
      return true;
    } catch (e) {
      const full = e instanceof ApiError && e.status === 429;
      setFailure({ kind: full ? "full" : fail, message: messageOf(e) });
      return false;
    } finally {
      setBusy(null);
    }
  }, []);
  return { busy, failure, setFailure, run };
}

/** 委托台的动作：交给研究助理、回复、签发（经澄清 confirm，或跳过提问直接 POST /api/research） */
export function useCommission(uiLang: Lang) {
  const [, navigate] = useLocation();
  const { busy, failure, setFailure, run } = useRunner();

  /** 交给研究助理；没回应时退回问题框（问题还在框里），出错原因显示在框下 */
  const ask = useCallback(async () => {
    const q = getDraft().question.trim();
    if (!q) return;
    setDraft((d) => ({ ...d, asked: q, clarifyId: null, turns: [{ who: "me", text: q }], ready: false }));
    const ok = await run("ask", async () => {
      const res = await clarify.start(q, modelRequest(getDraft().model));
      setDraft((d) => mergeTurn({ ...d, clarifyId: res.clarify_id }, res));
    }, "clarify");
    if (!ok) setDraft((d) => ({ ...d, turns: [] }));
  }, [run]);

  /** 回复失败时撤回这条，原文留在输入框里（由调用方按返回值决定是否清空） */
  const reply = useCallback(async (text: string) => {
    const id = getDraft().clarifyId;
    if (!id || !text.trim()) return false;
    setDraft((d) => ({ ...d, turns: [...d.turns, { who: "me", text: text.trim() }] }));
    const ok = await run("reply", async () => {
      const res = await clarify.reply(id, text.trim());
      setDraft((d) => mergeTurn(d, res));
    }, "clarify");
    if (!ok) setDraft((d) => ({ ...d, turns: d.turns.slice(0, -1) }));
    return ok;
  }, [run]);

  const sign = useCallback(() => {
    const d = getDraft();
    if (!d.question.trim()) return;
    void run("sign", async () => {
      const taskId = await submit(d, uiLang);
      resetDraft();
      navigate(`/case/${taskId}`);
    }, "sign");
  }, [run, uiLang, navigate]);

  const restart = useCallback(() => { setFailure(null); resetDraft(); }, [setFailure]);
  /** 去第 2 步核对（问够了，或空状态里跳过提问）；回第 1 步接着聊，委托单上的修改都保留 */
  const review = useCallback(() => { setFailure(null); setStep(2); }, [setFailure]);
  const back = useCallback(() => { setFailure(null); setStep(1); }, [setFailure]);

  return { busy, failure, ask, reply, sign, restart, review, back };
}
