import { f2 } from "../../lib/format";
import { useT } from "../../i18n";
import { QUALITY_THRESHOLD } from "./model";

const W = 640, H = 220, L = 44, R = 96, T = 18, B = 44;

/** 评分轨迹：每轮评审的平均分（第 N 轮评第 N−1 版），虚线是达标线，琥珀点是终稿 */
export function ScoreChart({ history, finalDraft }: { history: number[]; finalDraft: number | null }) {
  const { t } = useT();
  if (history.length === 0) return null;
  const lo = Math.floor((Math.min(...history, QUALITY_THRESHOLD) - 0.25) * 2) / 2;
  const hi = Math.ceil((Math.max(...history, QUALITY_THRESHOLD) + 0.25) * 2) / 2;
  const x = (i: number) => (history.length === 1 ? (L + W - R) / 2 : L + (i * (W - L - R)) / (history.length - 1));
  const y = (v: number) => T + ((hi - v) / (hi - lo)) * (H - T - B);
  const grid = Array.from({ length: Math.round((hi - lo) * 2) + 1 }, (_, i) => lo + i / 2);
  const last = history.length - 1;
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label={t("dossier.proc.chartLabel", { s: history.map(f2).join(", ") })}>
      {grid.map((v) => (
        <g key={v}>
          <line className={v === QUALITY_THRESHOLD ? "th" : "gd"} x1={L} x2={W - R + 20} y1={y(v)} y2={y(v)} />
          <text className="n" x={L - 8} y={y(v) + 4} textAnchor="end">{v.toFixed(1)}</text>
        </g>
      ))}
      <text x={W - R + 24} y={y(QUALITY_THRESHOLD) + 4}>{t("dossier.proc.threshold")} <tspan className="n">{f2(QUALITY_THRESHOLD)}</tspan></text>
      <polyline className="ln" points={history.map((v, i) => `${x(i)},${y(v)}`).join(" ")} />
      {history.map((v, i) => (
        <g key={i}>
          <circle className={`pt${i === finalDraft ? " best" : ""}`} cx={x(i)} cy={y(v)} r={i === finalDraft ? 6 : 4.5} />
          <circle className="hit" cx={x(i)} cy={y(v)} r={16}>
            <title>{t("dossier.proc.pointTip", { c: i + 1, v: i, s: f2(v) })}{i > 0 ? t("dossier.proc.gain", { g: `${v >= history[i - 1] ? "+" : ""}${f2(v - history[i - 1])}` }) : ""}</title>
          </circle>
          <text x={x(i)} y={H - 22} textAnchor="middle">{t("dossier.proc.round", { n: i + 1 })}</text>
          <text x={x(i)} y={H - 8} textAnchor="middle">{t("dossier.proc.ofDraft", { n: i })}</text>
        </g>
      ))}
      <text className="lbl n" x={x(0) + 10} y={y(history[0]) + 18}>{f2(history[0])}</text>
      {last > 0 && (
        <text className="lbl" x={x(last) + 12} y={y(history[last]) - 10}>
          <tspan className="n">{f2(history[last])}</tspan>{last === finalDraft ? ` ${t("dossier.proc.finalMark")}` : ""}
        </text>
      )}
    </svg>
  );
}
