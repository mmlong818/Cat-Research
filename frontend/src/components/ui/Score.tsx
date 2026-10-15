import { f2 } from "../../lib/format";

/** 分数色阶：阈值 8 / 7 / 6 / 5.5，线长 = (分数 − 5) × 14px，最短 6px */
const tier = (s: number) => (s >= 8 ? "t5" : s >= 7 ? "t4" : s >= 6 ? "t3" : s >= 5.5 ? "t2" : "t1");

export function Tick({ score }: { score: number }) {
  return <span className={`tick ${tier(score)}`} style={{ width: Math.max(6, Math.round((score - 5) * 14)) }} />;
}

export function Score({ score }: { score: number }) {
  return (
    <span className="score">
      <span className="num">{f2(score)}</span>
      <Tick score={score} />
    </span>
  );
}
