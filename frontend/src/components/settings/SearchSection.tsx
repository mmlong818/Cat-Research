import { SEARCH_BACKENDS } from "../../lib/api";
import type { SearchBackend, SettingsInfo } from "../../lib/api";
import { useT, type TKey } from "../../i18n";
import { KeyField } from "./KeyField";
import { note, sectionTitle } from "./styles";
import type { KeyInputs } from "./useSettingsForm";

function BackendRadio({ name, info, checked, onSelect }: {
  name: SearchBackend; info: SettingsInfo["search"]["backends"][SearchBackend]; checked: boolean; onSelect: () => void;
}) {
  const { t } = useT();
  return (
    <button
      type="button" role="radio" aria-checked={checked} onClick={onSelect}
      style={{
        flex: 1, padding: "8px 6px", borderRadius: 8, cursor: "pointer", textAlign: "center",
        border: `1px solid ${checked ? "var(--accent)" : "var(--border)"}`,
        background: checked ? "var(--accent-dim)" : "var(--surface2)",
        color: checked ? "var(--accent)" : "var(--text)",
      }}
    >
      <div style={{ fontSize: 13, fontWeight: checked ? 700 : 500 }}>{t(`common.search.${name}` as TKey)}</div>
      <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 2 }}>{t("common.search.price", { price: info.price_usd })}</div>
      <div style={{ fontSize: 11, color: info.has_key ? "var(--success)" : "var(--text4)" }}>
        {t(info.has_key ? "common.search.keyOk" : "common.search.keyNone")}
      </div>
    </button>
  );
}

interface Props {
  info: SettingsInfo["search"];
  backend: SearchBackend;
  inputs: KeyInputs;
  onBackend: (b: SearchBackend) => void;
  onInput: (name: SearchBackend, v: string) => void;
  onClear: (name: SearchBackend) => void;
}

/** 联网搜索后端：单选（单价、key 状态）+ 所选后端的 key。智谱的 key 与智谱提供方共用，只给说明，不重复放输入框。 */
export function SearchSection({ info, backend, inputs, onBackend, onInput, onClear }: Props) {
  const { t } = useT();
  const extra = backend === "bocha" ? "common.search.bochaNote" : backend === "tavily" ? "common.search.tavilyNote" : null;
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={sectionTitle}>{t("common.search.title")}</div>
      <div style={note}>{t("common.search.note")}</div>
      <div role="radiogroup" style={{ display: "flex", gap: 8, margin: "8px 0 12px" }}>
        {SEARCH_BACKENDS.map((b) => (
          <BackendRadio key={b} name={b} info={info.backends[b]} checked={backend === b} onSelect={() => onBackend(b)} />
        ))}
      </div>
      {extra && <div style={note}>{t(extra)}</div>}
      {backend === "zhipu"
        ? <div style={note}>{t("common.search.zhipuNote")}</div>
        : <KeyField name={backend} info={info.backends[backend]} value={inputs[backend]}
            onChange={(v) => onInput(backend, v)} onClear={() => onClear(backend)} />}
    </div>
  );
}
