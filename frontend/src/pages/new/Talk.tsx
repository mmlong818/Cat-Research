import { useState } from "react";
import { Icon } from "../../components/ui/Icon";
import { useT, type TKey } from "../../i18n";
import { N, rich } from "../../i18n/rich";
import type { Draft, Turn } from "./draft";
import type { Busy, Failure } from "./useCommission";

/** 研究助理的回答里只认 **加粗**（其余原样显示，换行保留） */
function Said({ text, className }: { text: string; className: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return <p className={className}>{parts.map((p, i) => (i % 2 ? <strong key={i}>{p}</strong> : p))}</p>;
}

function Wrote({ keys }: { keys: string[] }) {
  const { t, lang } = useT();
  if (keys.length === 0) return null;
  const names = keys.map((k) => t(`new.f.${k}` as TKey)).join(lang === "zh" ? "、" : ", ");
  return <div className="fx"><Icon name="check" small />{t("new.talk.wrote", { f: names })}</div>;
}

/** 对话笔录：第 1 步里接着聊，第 2 步里只读展开 */
export function Transcript({ turns, thinking = false }: { turns: Turn[]; thinking?: boolean }) {
  const { t } = useT();
  return (
    <ol className="talk">
      {turns.map((turn, i) => (
        <li key={i} className={turn.who}>
          <span className="who">{t(turn.who === "me" ? "new.talk.me" : "new.talk.ai")}</span>
          <div><Said className="said" text={turn.text} />{turn.wrote && <Wrote keys={turn.wrote} />}</div>
        </li>
      ))}
      {thinking && (
        <li className="ai">
          <span className="who">{t("new.talk.ai")}</span>
          <div><p className="said thinking">{t("new.ask.thinking")}</p></div>
        </li>
      )}
    </ol>
  );
}

/** 对话末尾的回答框：整页唯一的输入区；研究助理思考时暂不可写 */
function ReplyBox({ busy, ready, onReply }: { busy: Busy; ready: boolean; onReply: (text: string) => Promise<boolean> }) {
  const { t } = useT();
  const [text, setText] = useState("");
  const send = async () => { if (text.trim() && (await onReply(text))) setText(""); };
  return (
    <div className="reply">
      <div className="input">
        <textarea rows={2} value={text} placeholder={t("new.reply.ph")} aria-label={t("new.reply.label")} disabled={!ready}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void send(); }} />
      </div>
      <button className={`btn${busy === "reply" ? " is-loading" : ""}`} onClick={() => void send()}
              disabled={!text.trim() || !ready}>{busy !== "reply" && <Icon name="send" />}{t("new.reply.send")}</button>
    </div>
  );
}

/** 问过至少一轮才出现；助理认为问清楚了（ready）时加提示，按钮更醒目 */
function Proceed({ d, busy, onReview }: { d: Draft; busy: Busy; onReview: () => void }) {
  const { t } = useT();
  const ready = d.ready && busy === null;
  return (
    <div className="proceed">
      <span className="hint">{t("new.reply.hint")}</span>
      <span className="sp" />
      {ready && <span className="ready-hint"><Icon name="check" small />{t("new.readyHint")}</span>}
      <button className={`btn btn--primary${ready ? " btn--lg is-ready" : ""}`} onClick={onReview} disabled={busy !== null}>
        {t("new.toReview")}<Icon name="arrow-right" /></button>
    </div>
  );
}

/** 第 1 步 · 对话中：笔录 + 末尾的回答框 + 「问够了，去核对委托单」 */
export function Talk({ d, busy, failure, onReply, onReview }: {
  d: Draft; busy: Busy; failure: Failure | null; onReply: (text: string) => Promise<boolean>; onReview: () => void;
}) {
  const { t } = useT();
  const aiTurns = d.turns.filter((x) => x.who === "ai").length;
  return (
    <>
      <div className="sec-h talk-h"><h3>{t("new.talk.title")}</h3>
        {aiTurns > 0 && <span className="meta">{rich(t(d.ready ? "new.talk.ready" : "new.talk.waiting"), { n: <N>{aiTurns}</N> })}</span>}</div>
      <Transcript turns={d.turns} thinking={busy === "ask" || busy === "reply"} />
      {failure?.kind === "clarify" && (
        <div className="banner mt-m" role="alert"><Icon name="warning" /><span>{t("new.err.clarify", { msg: failure.message })}</span></div>
      )}
      <ReplyBox busy={busy} ready={!!d.clarifyId && busy === null} onReply={onReply} />
      {aiTurns > 0 && <Proceed d={d} busy={busy} onReview={onReview} />}
    </>
  );
}
