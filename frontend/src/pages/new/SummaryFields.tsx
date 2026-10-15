import { useState, type ReactNode } from "react";
import { Icon } from "../../components/ui/Icon";
import { useT, type TKey } from "../../i18n";
import { setDraft, type Draft, type FieldKey, type Fields } from "./draft";

type TextKey = "objective" | "scope" | "timeframe" | "exclude" | "extra";

/** 这一栏最近一次由研究助理第几轮写入（从 1 数，只数研究助理的回答） */
function writtenIn(d: Draft, key: string): number | null {
  let n = 0;
  let last: number | null = null;
  for (const turn of d.turns) {
    if (turn.who !== "ai") continue;
    n += 1;
    if (turn.wrote?.includes(key)) last = n;
  }
  return last;
}

const edit = (key: FieldKey, patch: (d: Draft) => Draft) =>
  setDraft((d) => ({ ...patch(d), edited: d.edited.includes(key) ? d.edited : [...d.edited, key] }));

const editField = (key: keyof Fields, value: Fields[keyof Fields]) =>
  edit(key, (d) => ({ ...d, fields: { ...d.fields, [key]: value } }));

function Label({ d, k, label, extra }: { d: Draft; k: FieldKey; label: string; extra?: ReactNode }) {
  const { t } = useT();
  const turn = writtenIn(d, k);
  return (
    <div className="flabel">{label}
      {d.edited.includes(k)
        ? <span className="tag" title={t("new.f.editedHint")}>{t("new.f.edited")}</span>
        : turn != null && <span className="tag accent">{t("new.f.turn", { n: turn })}</span>}
      {extra}
    </div>
  );
}

function TextField({ d, k, rows }: { d: Draft; k: TextKey; rows: number }) {
  const { t } = useT();
  const label = t(`new.f.${k}` as TKey);
  return (
    <div className="cf">
      <Label d={d} k={k} label={label} />
      <textarea className="ta" rows={rows} value={d.fields[k]} aria-label={label}
                placeholder={k === "extra" ? t("new.f.extraPh") : undefined}
                onChange={(e) => editField(k, e.target.value)} />
    </div>
  );
}

function AspectsField({ d }: { d: Draft }) {
  const { t } = useT();
  const [text, setText] = useState("");
  const list = d.fields.aspects;
  const add = () => {
    const v = text.trim();
    if (v && !list.includes(v)) editField("aspects", [...list, v]);
    setText("");
  };
  return (
    <div className="cf">
      <Label d={d} k="aspects" label={t("new.f.aspects")} extra={<span className="muted">{t("new.f.aspectsCount", { n: list.length })}</span>} />
      <div className="ents">
        {list.map((a) => (
          <span className="chip" key={a}>{a}
            <button className="x" title={t("new.f.remove")} aria-label={`${t("new.f.remove")} ${a}`}
                    onClick={() => editField("aspects", list.filter((x) => x !== a))}><Icon name="x" small /></button>
          </span>
        ))}
      </div>
      <div className="row mt-m">
        <div className="input ents-add">
          <input value={text} placeholder={t("new.f.aspectPh")} aria-label={t("new.f.aspectAdd")}
                 onChange={(e) => setText(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
        </div>
        <button className="btn btn--sm" onClick={add} disabled={!text.trim()}><Icon name="plus" small />{t("new.f.aspectAdd")}</button>
      </div>
    </div>
  );
}

/** 委托单上由对话生成、可以直接改的栏：研究问题、目标、范围、时间口径、重点方面、排除项、特别要求 */
export function SummaryFields({ d }: { d: Draft }) {
  const { t } = useT();
  return (
    <>
      <div className="cf">
        <Label d={d} k="question" label={t("new.f.question")} />
        <textarea className="ta" rows={2} value={d.question} aria-label={t("new.f.question")}
                  onChange={(e) => edit("question", (x) => ({ ...x, question: e.target.value }))} />
        {d.question.trim() !== d.asked && d.asked && <p className="hint mt-s">{t("new.f.questionHint")}</p>}
      </div>
      <TextField d={d} k="objective" rows={4} />
      <TextField d={d} k="scope" rows={2} />
      <TextField d={d} k="timeframe" rows={1} />
      <AspectsField d={d} />
      <TextField d={d} k="exclude" rows={2} />
      <TextField d={d} k="extra" rows={3} />
    </>
  );
}
