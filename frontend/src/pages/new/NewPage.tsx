import { Fragment } from "react";
import { Masthead } from "../../components/ui/Masthead";
import { Icon } from "../../components/ui/Icon";
import { useDesk } from "../../components/shell/useDesk";
import { useOpenDesk } from "../../components/shell/Shell";
import { useT, type TKey } from "../../i18n";
import { N, rich } from "../../i18n/rich";
import { useDraft, type Draft } from "./draft";
import { useCommission } from "./useCommission";
import { AskBox } from "./AskBox";
import { Talk } from "./Talk";
import { CommissionForm } from "./CommissionForm";
import "./new.css";

const STEP_KEYS: TKey[] = ["new.steps.ask", "new.steps.review", "new.steps.sign"];

/** 步骤条：1 说清问题 → 2 核对委托单 → 签发，标出当前步 */
function Steps({ step }: { step: 1 | 2 }) {
  const { t } = useT();
  return (
    <ol className="steps" aria-label={t("new.steps.label")}>
      {STEP_KEYS.map((k, i) => {
        const state = i + 1 < step ? "done" : i + 1 === step ? "on" : "";
        return (
          <Fragment key={k}>
            {i > 0 && <li className="arrow" aria-hidden="true"><Icon name="arrow-right" small /></li>}
            <li className={state} aria-current={state === "on" ? "step" : undefined}>
              {i < 2 && <span className="no num">{state === "done" ? <Icon name="check" small /> : i + 1}</span>}{t(k)}
            </li>
          </Fragment>
        );
      })}
    </ol>
  );
}

function Lede({ d }: { d: Draft }) {
  const { t } = useT();
  const rounds = d.turns.filter((x) => x.who === "ai").length;
  if (d.step === 2) return <p className="dateline">{t(d.clarifyId ? "new.lede.review" : "new.lede.reviewBlank")}</p>;
  if (rounds > 0) return <p className="dateline">{rich(t("new.lede.talk"), { n: <N>{rounds}</N> })}</p>;
  return <p className="dateline">{t("new.lede.ask")}</p>;
}

/** 委托台 /new：分两步，先和研究助理把问题说清楚，再全宽核对委托单并签发；任何时刻页面上只有一个可输入区域 */
export default function NewPage() {
  const { t, lang } = useT();
  const onOpenDesk = useOpenDesk();
  const d = useDraft();
  const { active } = useDesk();
  const c = useCommission(lang);
  const started = d.turns.length > 0 || d.step === 2;
  return (
    <div className="wrap commission">
      <Masthead title={t("new.title")}
                tools={started && <button className="linkbtn" onClick={c.restart}><Icon name="resume" />{t("new.restart")}</button>}>
        <span className="issue">{t(started ? "new.issue.talk" : "new.issue.empty")}</span>
      </Masthead>
      <Steps step={d.step} />
      <Lede d={d} />
      {d.step === 2 ? (
        <CommissionForm d={d} uiLang={lang} active={active.length} busy={c.busy} failure={c.failure}
                        onSign={c.sign} onBack={c.back} onOpenDesk={onOpenDesk} />
      ) : (
        <div className="step-col">
          {d.turns.length > 0
            ? <Talk d={d} busy={c.busy} failure={c.failure} onReply={c.reply} onReview={c.review} />
            : <AskBox d={d} active={active.length} busy={c.busy} failure={c.failure} onAsk={c.ask} onSkip={c.review} />}
        </div>
      )}
    </div>
  );
}
