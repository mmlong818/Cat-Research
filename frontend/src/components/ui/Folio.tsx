import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./Icon";
import { useT } from "../../i18n";

/** 对开页抽屉：从右侧滑入，Esc 或点遮罩关闭，关闭后焦点回到打开它的元素。 */
export function Folio({ crumb, onClose, children }: { crumb: string; onClose: () => void; children: ReactNode }) {
  const { t } = useT();
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus();
    };
  }, [onClose]);
  return createPortal(
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="folio" role="dialog" aria-modal="true" aria-label={crumb}>
        <div className="folio-bar">
          <button className="iconbtn" onClick={onClose} title={t("common.back")}><Icon name="arrow-left" /></button>
          <span className="crumb">{crumb}</span>
          <span className="sp" />
          <button className="iconbtn" ref={closeRef} onClick={onClose} title={t("common.close")}><Icon name="x" /></button>
        </div>
        <div className="folio-body">{children}</div>
      </aside>
    </>,
    document.body,
  );
}
