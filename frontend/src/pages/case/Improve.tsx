import { Icon } from "../../components/ui/Icon";
import { Tick } from "../../components/ui/Score";
import { useT } from "../../i18n";
import { N, rich } from "../../i18n/rich";
import { f2 } from "../../lib/format";
import { isLive, type CaseState } from "../../lib/live/model";

/** 改进阶段的逐轮记录：每轮评审分（带分数色阶短线）、进行中的一轮、循环结束原因 */
export function Improve({ s }: { s: CaseState }) {
  const { t } = useT();
  const rounds = [...s.rounds].sort((a, b) => a.cycle - b.cycle);
  const last = rounds[rounds.length - 1];
  if (rounds.length === 0 && !s.loopStop) return null;
  return (
    <ul className="sub rounds">
      {rounds.map((r) => {
        const now = r === last && r.score == null && isLive(s) && !s.loopStop;
        return (
          <li key={r.cycle} className={now ? "now" : ""}>
            <span className="t">{r.at.slice(11, 19)}</span>
            <Icon name={r.score != null ? "check" : "dot"} />
            <span>
              {r.score != null
                ? <>{rich(t("case.round.done"), { n: <N>{r.cycle}</N>, s: <N>{f2(r.score)}</N> })} <Tick score={r.score} /></>
                : now ? rich(t("case.round.now"), { n: <N>{r.cycle}</N>, max: <N>{r.max}</N> })
                  : rich(t("case.round.wait"), { n: <N>{r.cycle}</N> })}
            </span>
          </li>
        );
      })}
      {s.loopStop && (
        <li><span className="t" /><Icon name="check" /><span>{t("case.loopStop", { r: s.loopStop.reason })}</span></li>
      )}
    </ul>
  );
}
