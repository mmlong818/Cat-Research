import { useCallback, useState } from "react";
import { toast } from "sonner";
import { Icon } from "../../components/ui/Icon";
import { Dialog } from "../../components/ui/Dialog";
import { useT, type TKey } from "../../i18n";
import { runMode, type CaseState } from "../../lib/live/model";
import { live } from "../../lib/live/store";

/** 暂停只在检查点生效：点了先显示"正在暂停"，收到 paused 事件才是"已暂停"；停止走 POST /stop，保留稿件 */
export function Controls({ s }: { s: CaseState }) {
  const { t } = useT();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const mode = runMode(s);
  const fail = (e: unknown) => toast.error(t("case.toast.failed", { m: e instanceof Error ? e.message : String(e) }));
  const act = (fn: () => Promise<void>) => { setBusy(true); fn().catch(fail).finally(() => setBusy(false)); };
  const close = useCallback(() => setAsking(false), []);
  const stop = () => { setAsking(false); act(() => live.stop(s.taskId)); };
  if (mode === "done") return null;
  const hintKey = mode === "paused" ? "case.ctl.hint.paused" : mode === "pausing" ? "case.ctl.hint.pausing" : "case.ctl.hint.running";
  return (
    <div className="fieldset">
      <div className="row">
        {mode === "running" && <button className="btn" disabled={busy} onClick={() => act(() => live.pause(s.taskId))}><Icon name="pause" />{t("case.ctl.pause")}</button>}
        {mode === "pausing" && <button className="btn is-loading" disabled>{t("case.ctl.pausing")}</button>}
        {mode === "paused" && <button className="btn" disabled={busy} onClick={() => act(() => live.resume(s.taskId))}><Icon name="play" />{t("case.ctl.resume")}</button>}
        {mode === "resuming" && <button className="btn is-loading" disabled>{t("case.ctl.resuming")}</button>}
        <button className={`btn btn--danger${s.stopping ? " is-loading" : ""}`} disabled={s.stopping} onClick={() => setAsking(true)}>
          {!s.stopping && <Icon name="stop" />}{t("case.ctl.stop")}</button>
      </div>
      <p className="hint mt-m">{t(hintKey as TKey, { g: s.pauseGate ?? "" })}<br />{t("case.ctl.hint.stop")}</p>
      {asking && (
        <Dialog title={t("case.stopDlg.title")} confirm={t("case.stopDlg.ok")} danger onConfirm={stop} onClose={close}>
          {t("case.stopDlg.body")}
        </Dialog>
      )}
    </div>
  );
}
