import { Icon, type IconName } from "./Icon";
import { useT, type TKey } from "../../i18n";

const STAMPS: Record<string, { cls: string; icon: IconName | null }> = {
  running: { cls: "run", icon: null },
  completed: { cls: "gold", icon: "check" },
  stopped: { cls: "warn", icon: "pause" },
  interrupted: { cls: "warn", icon: "pause" },
  failed: { cls: "danger", icon: "x" },
  unknown: { cls: "", icon: "dash" },
};

/** 会话状态印章：颜色 + 图标 + 文字（运行中用脉冲点代替图标）。 */
export function Stamp({ status, small = false }: { status?: string | null; small?: boolean }) {
  const { t } = useT();
  const key = status && STAMPS[status] ? status : "unknown";
  const { cls, icon } = STAMPS[key];
  return (
    <span className={`stamp ${cls}${small ? " sm" : ""}`}>
      {icon ? <Icon name={icon} /> : <span className="live" />}
      {t(`shell.stamp.${key}` as TKey)}
    </span>
  );
}
