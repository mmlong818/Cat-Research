import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useT } from "../../i18n";

interface Props {
  title: string;
  children: ReactNode;
  confirm: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

/** 二次确认对话框（.dialog）：Esc 或点遮罩取消，打开时焦点落在"取消"上，关闭后回到打开它的元素。 */
export function Dialog({ title, children, confirm, danger = false, busy = false, onConfirm, onClose }: Props) {
  const { t } = useT();
  const cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus();
    };
  }, [onClose]);
  return createPortal(
    <div className="dialog-back" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="dialog" role="alertdialog" aria-modal="true" aria-label={title}>
        <h3>{title}</h3>
        <p>{children}</p>
        <div className="btns">
          <button className="btn" ref={cancelRef} onClick={onClose}>{t("common.cancel")}</button>
          <button className={`btn ${danger ? "btn--danger-solid" : "btn--primary"}${busy ? " is-loading" : ""}`}
                  onClick={onConfirm} disabled={busy}>{confirm}</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
