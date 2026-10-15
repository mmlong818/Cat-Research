import { useState } from "react";
import { Icon } from "../../components/ui/Icon";
import { useT } from "../../i18n";
import { STAGES, isLive, type CaseState, type DirectiveMsg } from "../../lib/live/model";
import { live } from "../../lib/live/store";
import { clockTime } from "../../lib/format";
import { agentNames } from "./humanize";

const STEPS = ["queued", "ack", "applied"] as const;
const RANK = { failed: -1, sending: 0, queued: 1, ack: 2, applied: 3 } as const;

/** 回执下面那一行说明：在哪个检查点读取、用到了哪些智能体；任务结束后说明停在哪一步的原因 */
function Note({ m, ended }: { m: DirectiveMsg; ended: boolean }) {
  const { t, lang } = useT();
  if (m.state === "failed") return <span className="hint err">{t("case.rc.failed", { m: m.error ?? "" })}</span>;
  if (m.state === "applied") return <span className="hint">{t("case.rc.usedBy", { a: agentNames(t, m.agents, lang === "zh" ? "、" : ", ") })}</span>;
  if (m.state === "ack") return <span className="hint">{t(ended ? "case.rc.unused" : "case.rc.readAt", { g: m.gate ?? "" })}</span>;
  if (m.state === "queued") return <span className="hint">{t(ended ? "case.rc.unread" : "case.rc.waiting")}</span>;
  return <span className="hint">{t("case.rc.sending")}</span>;
}

/** 三段回执：已收到 → 已读取 → 已用上 */
function Receipt({ m, ended }: { m: DirectiveMsg; ended: boolean }) {
  const { t } = useT();
  return (
    <div className="receipt">
      <span className="num">{clockTime(m.sentAt)}</span>
      <p>{m.text}</p>
      <ol className="rc-steps" aria-label={t(`case.rc.${m.state === "failed" ? "sending" : m.state}`)}>
        {STEPS.map((step) => (
          <li key={step} className={RANK[m.state] >= RANK[step] ? "on" : ""}>
            <Icon name={RANK[m.state] >= RANK[step] ? "check" : "dash"} small />{t(`case.rc.${step}`)}
          </li>
        ))}
      </ol>
      <Note m={m} ended={ended} />
    </div>
  );
}

export function Directives({ s }: { s: CaseState }) {
  const { t } = useT();
  const [text, setText] = useState("");
  // 改进循环之后没有检查点，再发的消息不会被读取：进入收尾就不再收
  const open = isLive(s) && !s.loopStop && s.stage < STAGES.indexOf("finish");
  const send = () => {
    const v = text.trim();
    if (!v) return;
    setText("");
    live.send(s.taskId, v).catch(() => {}); // 失败写在这条的回执里
  };
  return (
    <div className="fieldset">
      <div className="flabel">{t("case.dir.title")}</div>
      {open ? (
        <>
          <textarea className="ta mt-s" rows={3} value={text} placeholder={t("case.dir.ph")} aria-label={t("case.dir.label")}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send(); }} />
          <div className="row mt-m"><span className="hint">{t("case.dir.hint")}</span><span className="sp" />
            <button className="btn" onClick={send} disabled={!text.trim()}><Icon name="send" />{t("case.dir.send")}</button></div>
        </>
      ) : <p className="hint mt-s">{t("case.dir.closed")}</p>}
      {s.messages.map((m) => <Receipt key={m.id} m={m} ended={!open} />)}
    </div>
  );
}
