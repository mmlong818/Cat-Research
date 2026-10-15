import { useState } from "react";
import { useT } from "../../i18n";
import { N, rich } from "../../i18n/rich";
import { Icon } from "../../components/ui/Icon";
import { MAX_ACTIVE } from "../../components/shell/useDesk";
import type { Draft, Lang } from "./draft";
import type { Busy, Failure } from "./useCommission";
import { SummaryFields } from "./SummaryFields";
import { SettingsFields } from "./SettingsFields";
import { ModelField } from "./ModelField";
import { Transcript } from "./Talk";

interface Props {
  d: Draft;
  uiLang: Lang;
  active: number;
  busy: Busy;
  failure: Failure | null;
  onSign: () => void;
  onBack: () => void;
  onOpenDesk: () => void;
}

/** 满 2 份在办：签发会被后端以 429 拒绝，按钮置灰并说明原因 */
function FullNote({ active, onOpenDesk, detail }: { active: number; onOpenDesk: () => void; detail?: string }) {
  const { t } = useT();
  return (
    <span className="full-note"><Icon name="warning" />
      <span>{detail ?? t("new.full", { n: active })}
        <button className="btn btn--link" onClick={onOpenDesk}>{t("new.full.go")}</button></span>
    </span>
  );
}

/** 对话记录（只读）：默认收起，展开后只能看，不能在这里接着聊 */
function ChatLog({ d }: { d: Draft }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const rounds = d.turns.filter((x) => x.who === "ai").length;
  if (rounds === 0) return <p className="chatlog hint">{t("new.log.none")}</p>;
  return (
    <div className="chatlog">
      <button className="btn btn--text chatlog-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <Icon name={open ? "caret-down" : "caret-right"} />{rich(t("new.log.title"), { n: <N>{rounds}</N> })}
        <span className="muted"> · {t(open ? "new.log.hide" : "new.log.show")}</span>
      </button>
      {open && <Transcript turns={d.turns} />}
    </div>
  );
}

/** 底部：左边回去再聊，右边签发；满 2 份在办的提示与签发失败原因都在签发按钮旁 */
function ReviewBar({ d, active, busy, failure, onSign, onBack, onOpenDesk }: Omit<Props, "uiLang">) {
  const { t } = useT();
  const full = active >= MAX_ACTIVE;
  const signing = busy === "sign";
  return (
    <div className="review-bar">
      <button className="btn" onClick={onBack} disabled={signing}><Icon name="arrow-left" />{t("new.back")}</button>
      <span className="sp" />
      <div className="sign-side">
        {full || failure?.kind === "full"
          ? <FullNote active={active} onOpenDesk={onOpenDesk} detail={failure?.kind === "full" ? failure.message : undefined} />
          : <span className="hint">{active > 0 && rich(t("new.sign.active"), { n: <N>{active}</N>, max: <N>{MAX_ACTIVE}</N> })}{t("new.sign.hint")}</span>}
        <button className={`btn btn--primary btn--lg${signing ? " is-loading" : ""}`} onClick={onSign}
                disabled={full || signing || !d.question.trim()}>
          {!signing && <Icon name="pen" />}{t(signing ? "new.signing" : "new.sign")}
        </button>
      </div>
      {failure?.kind === "sign" && <p className="form-err" role="alert">{t("new.err.sign", { msg: failure.message })}</p>}
    </div>
  );
}

/** 第 2 步 · 核对委托单：只读的对话记录 + 全宽委托单（左：问题与范围各栏；右：办案设置与承办模型）+ 底部签发 */
export function CommissionForm(p: Props) {
  const { t } = useT();
  return (
    <>
      <ChatLog d={p.d} />
      <div className="form-h review-h"><h3>{t("new.form.title")}</h3>
        <p>{t(p.d.clarifyId ? "new.form.sub" : "new.form.subBlank")}{" "}{t("new.f.editedHint")}</p></div>
      <div className="run-grid review-grid">
        <div className="run-left"><SummaryFields d={p.d} /></div>
        <div className="run-right">
          <SettingsFields d={p.d} uiLang={p.uiLang} />
          <ModelField value={p.d.model} />
        </div>
      </div>
      <ReviewBar {...p} />
    </>
  );
}
