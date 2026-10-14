import { KEY_PROVIDERS } from "../../lib/api";
import type { ProfileChoice, SettingsInfo } from "../../lib/api";
import { useT } from "../../i18n";
import { CompatSection } from "./CompatSection";
import { KeyField } from "./KeyField";
import { ProfileSection } from "./ProfileSection";
import { SearchSection } from "./SearchSection";
import { sectionTitle } from "./styles";
import type { useSettingsForm } from "./useSettingsForm";

interface Props {
  f: ReturnType<typeof useSettingsForm>;
  settings: SettingsInfo;
  draft: ProfileChoice;
}

/** 设置弹窗的各区块，从上到下：默认提供方、各家 API Key、OpenAI 兼容端点、联网搜索 */
export function SettingsBody({ f, settings, draft }: Props) {
  const { t } = useT();
  return (
    <>
      <ProfileSection settings={settings} draft={draft} ready={f.ready} compatModels={f.compat} onChange={f.setDraft} />
      <div style={sectionTitle}>{t("common.apiKeys")}</div>
      {KEY_PROVIDERS.map((p) => (
        <KeyField key={p} name={p} info={settings.providers[p]} value={f.inputs[p]}
          hint={p === "claude" ? t("common.claudeNote") : undefined}
          onChange={(v) => f.setInput(p, v)} onClear={() => f.clear(p)} />
      ))}
      <CompatSection info={settings.providers.compat} form={f.compat} keyInput={f.inputs.compat}
        onForm={f.setCompat} onKeyInput={(v) => f.setInput("compat", v)} onClearKey={() => f.clear("compat")} />
      <SearchSection info={settings.search} backend={f.backend} inputs={f.inputs}
        onBackend={f.setBackend} onInput={f.setInput} onClear={f.clear} />
    </>
  );
}
