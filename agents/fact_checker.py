"""
FactCheckerAgent - 基于声明台账的事实核查
1. 裁决台账中尚未裁决的矛盾（每处一次独立联网调用，并行）
2. 独立核实关键声明：优先挑选本应有一手记录的（标准、法规、披露等），其次含数字、来源少的声明，
   每条一次独立调用（tools.fact_tools）
证据等级兜底（确定性）：supported / 判胜方须有 primary 或 authority 证据，仅媒体来源时按无法核实 / 两方存疑处理。
整体置信度只按「独立核实」的声明计算（证实 1、无法核实 0.5、有争议 0），由 Python 确定性给出。
"""
import os
import re

import config as _config
from agents.llm_agent import LLMAgent, write_json_atomic
from llm import LLMError, call_many
from research.ledger import NEITHER, Ledger, citation_counts
from research.source_quality import load_verification
from tools.fact_tools import (
    EVIDENCE_TIERS,
    SOURCE_HIERARCHY_PROMPT,
    STRONG_TIERS,
    cross_reference_claims,
    verification_outcome,
)

MAX_VERIFY = 8
CONFIDENCE_WEIGHT = {"supported": 1.0, "unverifiable": 0.5, "disputed": 0.0}

ADJUDICATE_SYSTEM_PROMPT = f"""你是独立的事实裁决员。研究资料中有两条声明互相矛盾，请用 WebSearch / WebFetch
查找权威、尽量一手且最新的来源判断哪一条正确：
- A 或 B：primary 或 authority 级来源明确支持其中一条
- neither：两条都无法被可靠来源证实，只有媒体证据，或权威来源之间本身存在分歧

{SOURCE_HIERARCHY_PROMPT}
reason 写明判断依据；evidence_url 填你实际读到的关键来源（没有则填空串）。
evidence_tier：填你作出判断所依据证据中的最高等级（primary / authority / media），没有可靠证据填 none。\
只有 media 证据时选 neither。"""

ADJUDICATE_SCHEMA = {
    "type": "object",
    "properties": {
        "sides_with": {"type": "string", "enum": ["A", "B", NEITHER]},
        "reason": {"type": "string"},
        "evidence_url": {"type": "string"},
        "evidence_tier": {"type": "string", "enum": EVIDENCE_TIERS},
    },
    "required": ["sides_with", "reason", "evidence_url", "evidence_tier"],
    "additionalProperties": False,
}

# 本应有一手记录的声明：标准/法规政策/公司披露/专利论文等（中英文关键词）
# ASCII 词前不得紧跟字母或数字，如 512GB 不算 GB
PRIMARY_RECORD_PATTERN = re.compile(
    r"标准|国标|行标|团标|法规|法律|条例|办法|政策|通知|公告|发布|颁布|实施|施行|生效|批准|核准|备案|认证"
    r"|财报|年报|季报|半年报|招股|产能|专利|论文"
    r"|投产|量产|产线|生产线|基地|工厂|开工|选址|落地|建成"  # 生产/项目类事实：产线在哪、何时投产
    r"|(?<![A-Za-z0-9])(?:GB/T|GB(?![A-Za-z/])|ISO|IEC|IEEE|DOI|10-K|10-Q|8-K"
    r"|standard|regulation|directive|announce|filing|annual report|quarterly report|earnings"
    r"|patent|certif|approv|effective date|promulgat|enact"
    r"|plants?(?![A-Za-z-])|(?:giga-?)?factor(?:y|ies)(?![A-Za-z])|production lines?|mass production"
    r"|groundbreaking|break ground)",
    re.IGNORECASE)


class FactCheckerAgent(LLMAgent):
    def __init__(self, model: str | None = None):
        super().__init__(name="事实核查员", system_prompt=ADJUDICATE_SYSTEM_PROMPT,
                         model=model or _config.FACT_CHECKER_MODEL, schema=ADJUDICATE_SCHEMA,
                         tools=["WebSearch", "WebFetch"], max_turns=20)
        self.adjudication_tiers: list[str] = []  # 最近一次裁决各矛盾所依据的证据等级

    def adjudicate(self, workspace: str) -> int:
        """并行裁决所有未决矛盾，返回成功裁决的数量；单处失败只告警（保持未决）。"""
        ledger = Ledger.load(workspace)
        pending = ledger.unresolved()
        self.adjudication_tiers = []
        if not pending:
            return 0
        self.check_stop()
        print(f"\n🤖 智能体 [{self.name}] 裁决 {len(pending)} 处矛盾（{self.model}）...", flush=True)
        reqs = [self.request(_adjudicate_prompt(ledger, xid), schema=ADJUDICATE_SCHEMA) for xid in pending]
        resolved = 0
        for xid, r in zip(pending, call_many(reqs, max_concurrency=3), strict=True):
            if isinstance(r, LLMError):
                print(f"  [事实核查员] 裁决 {xid} 失败，保持未决: {r}", flush=True)
                continue
            self.report_usage(r, f"（裁决 {xid}）")
            a, b = ledger.contradictions[xid]["claims"]
            tier = r.data.get("evidence_tier")
            side, reason = adjudication_outcome({"A": a, "B": b}.get(r.data["sides_with"], NEITHER), tier,
                                                r.data["reason"])
            ledger.resolve(xid, side, reason, r.data["evidence_url"])
            self.adjudication_tiers.append(tier if tier in EVIDENCE_TIERS else "none")
            resolved += 1
        ledger.save()
        return resolved

    def check_facts(self, workspace: str, limit: int = MAX_VERIFY) -> tuple:
        """裁决未决矛盾 + 独立核实至多 limit 条关键声明，结果写入 fact_check.json。

        一条都没核实成功（含没有可核实的声明）时抛 LLMError，由编排层按「事实核查缺失」处理；
        裁决结果已先落账，不受影响。
        """
        resolved = self.adjudicate(workspace)
        ledger = Ledger.load(workspace)
        targets = pick_for_verification(ledger, limit, load_verification(workspace))
        self.check_stop()
        checks = cross_reference_claims([ledger.claims[c]["text"] for c in targets], self.model) if targets else []
        tiers: dict[str, str | None] = {}
        for cid, r in zip(targets, checks, strict=True):
            if r is not None:
                tiers[cid] = r.get("evidence_tier")
                status, note = verification_outcome(r["verdict"], tiers[cid], r["explanation"])
                ledger.set_status(cid, status, note[:300])
                _clear_extraction_if_supported(ledger, cid, status)
        ledger.save()
        result = summarize_fact_check(ledger, targets, resolved, tiers, self.adjudication_tiers)
        if result["total_claims_checked"] == 0:
            raise LLMError("没有成功核实的声明，事实核查未完成" if targets else "台账中没有可核实的声明")
        out = os.path.join(workspace, "08_verification", "fact_check.json")
        write_json_atomic(out, result)
        return result, out

    def recheck(self, workspace: str, draft_text: str, limit: int) -> list:
        """承重声明补核：独立核实稿件中被引用最多、仍未核查、本应有一手记录的至多 limit 条声明，
        结果按证据等级规则写回台账；返回实际发起核实的声明编号（limit 为 0 或没有候选时不发起调用）。"""
        ledger = Ledger.load(workspace)
        targets = pick_load_bearing(ledger, draft_text, limit, load_verification(workspace)) if limit > 0 else []
        if not targets:
            return []
        self.check_stop()
        checks = cross_reference_claims([ledger.claims[c]["text"] for c in targets], self.model)
        for cid, r in zip(targets, checks, strict=True):
            if r is not None:
                status, note = verification_outcome(r["verdict"], r.get("evidence_tier"), r["explanation"])
                ledger.set_status(cid, status, note[:300])
                _clear_extraction_if_supported(ledger, cid, status)
        ledger.save()
        return targets


def _adjudicate_prompt(ledger: Ledger, xid: str) -> str:
    x = ledger.contradictions[xid]

    def side(cid):
        c = ledger.claims[cid]
        urls = "；".join(ledger.sources[s]["url"] for s in c["sources"] if s in ledger.sources)
        return f"{c['text']}\n  原始来源：{urls or '无'}"

    a, b = x["claims"]
    return (f"冲突点：{x['topic']}\n\n声明 A：{side(a)}\n\n声明 B：{side(b)}\n\n"
            f"今天是 {_config.CURRENT_DATE_STR}，请裁决。")


def adjudication_outcome(side: str, tier: str | None, reason: str) -> tuple[str, str]:
    """裁决结果 → (生效的胜方, 理由)。判 A/B 须有 primary 或 authority 证据；
    只有媒体（或没有）证据时不推翻任何一方，按 neither（两方存疑）处理。"""
    if side != NEITHER and tier not in STRONG_TIERS:
        return NEITHER, f"仅有媒体证据，按两方存疑处理（模型原判倾向一方，证据等级 {tier or 'none'}）：{reason}"
    return side, reason


def _clear_extraction_if_supported(ledger: Ledger, cid: str, status: str):
    """独立核实判 supported（verification_outcome 已保证有 primary / authority 证据）时清除「摘录待核」：
    核实针对的是声明文字本身，且证据独立于研究员的摘录，原文片段对不上的风险已被一手 / 权威来源证实所覆盖。"""
    if status == "supported":
        ledger.clear_extraction(cid)


def _split_quota(cands: list, limit: int) -> list:
    """cands 为 (非高风险, ...排序键, 声明编号) 元组。高风险（低可信或摘录待核）声明最多占 limit 的一半（向上取整），
    其余名额给非高风险声明；任一侧候选不足时名额让给另一侧，总数尽量填满 limit。
    返回顺序：高风险份额、非高风险份额、回补的高风险。"""
    limit = max(limit, 0)
    ranked = sorted(cands)
    low = [c[-1] for c in ranked if not c[0]]
    other = [c[-1] for c in ranked if c[0]]
    head = low[:(limit + 1) // 2]
    tail = other[:limit - len(head)]
    return head + tail + low[len(head):len(head) + limit - len(head) - len(tail)]


def pick_for_verification(ledger: Ledger, limit: int = MAX_VERIFY, verification: dict | None = None) -> list:
    """未核查的可引用声明（须含数字或命中一手记录关键词；被标「摘录待核」的不受此限）。排序键：
    (高风险者优先, 摘录待核者优先, 本应有一手记录者优先, 含数字者优先, 来源数, 声明编号)；
    高风险 = 摘录待核（原文片段对不上声明的数字 / 时间，research.quote_check）或全部来源低可信，
    高风险声明合为一队，最多占 limit 的一半（向上取整），其余名额按同一排序给其他声明（_split_quota）。
    低可信指全部来源都是社交媒体 / 自媒体 / 聚合站或验证阶段评分低（research.source_quality），
    verification 为 source_verification.json 的内容（缺省只用规则引擎）。
    来源数的方向因组而异：本应有一手记录的声明，来源越多越优先（多家媒体复述的往往是同一条转述，
    越被转述越该回头查原始记录）；其余含数字的声明来源越少越优先（单一来源风险最高）。"""
    flagged = ledger.extraction_issue_claims()
    risky = ledger.low_credibility_claims(verification) | flagged
    cands = []
    for cid, c in ledger.citable().items():
        if c["status"] != "unchecked":
            continue
        primary, digit = bool(PRIMARY_RECORD_PATTERN.search(c["text"])), bool(re.search(r"\d", c["text"]))
        if primary or digit or cid in flagged:
            n = len(c["sources"])
            cands.append((cid not in risky, cid not in flagged, not primary, not digit, -n if primary else n,
                          int(cid[1:]), cid))
    return _split_quota(cands, limit)


def pick_load_bearing(ledger: Ledger, draft_text: str, limit: int, verification: dict | None = None) -> list:
    """承重声明：稿件中被引用、仍未核查、且本应有一手记录（命中关键词）的可引用声明。
    排序键：(高风险者优先, 摘录待核者优先, 被引用次数多者优先, 声明编号)；高风险（摘录待核或全部来源低可信）
    同样合为一队、最多占 limit 的一半（_split_quota）。"""
    citable = ledger.citable()
    flagged = ledger.extraction_issue_claims()
    risky = ledger.low_credibility_claims(verification) | flagged
    cands = [(cid not in risky, cid not in flagged, -n, int(cid[1:]), cid)
             for cid, n in citation_counts(ledger, draft_text).items()
             if cid in citable and citable[cid]["status"] == "unchecked"
             and PRIMARY_RECORD_PATTERN.search(citable[cid]["text"])]
    return _split_quota(cands, limit)


def _tier_counts(tiers) -> dict:
    counts = dict.fromkeys(EVIDENCE_TIERS, 0)
    for t in tiers:
        counts[t if t in counts else "none"] += 1
    return counts


def summarize_fact_check(ledger: Ledger, targets: list, resolved: int, tiers: dict | None = None,
                         adjudication_tiers: list | None = None) -> dict:
    tiers = tiers or {}
    checked = [cid for cid in targets if ledger.claims[cid]["status"] in CONFIDENCE_WEIGHT]
    status = {cid: ledger.claims[cid]["status"] for cid in checked}
    xs = list(ledger.contradictions.values())
    sides = [x["resolution"]["sides_with"] for x in xs if x["resolution"]]
    supported = sum(1 for s in status.values() if s == "supported")
    return {
        "total_claims_checked": len(checked),
        "claims": [{"id": cid, "claim": ledger.claims[cid]["text"], "verdict": status[cid],
                    "note": ledger.claims[cid]["note"]} for cid in checked],
        "overall_confidence": (round(sum(CONFIDENCE_WEIGHT[s] for s in status.values()) / len(checked), 3)
                               if checked else 0.0),
        "high_confidence_claims": supported,
        "disputed_claims": [ledger.claims[c]["text"][:80] for c in checked if status[c] == "disputed"],
        "unverifiable_claims": [ledger.claims[c]["text"][:80] for c in checked if status[c] == "unverifiable"],
        "evidence_tiers": _tier_counts(tiers[cid] for cid in checked if cid in tiers),
        "adjudication_evidence_tiers": _tier_counts(adjudication_tiers or []),
        "contradictions": {"total": len(xs), "resolved": len(sides), "resolved_this_run": resolved,
                           "neither": sides.count(NEITHER), "unresolved": len(ledger.unresolved())},
        "fact_check_summary": (f"独立核实 {len(checked)} 条关键声明，证实 {supported} 条；"
                               f"台账共 {len(xs)} 处矛盾，已裁决 {len(sides)} 处。"),
    }
