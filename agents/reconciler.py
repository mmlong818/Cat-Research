"""
ReconcilerAgent - 声明对账智能体
找出台账中语义重复（含中英文表述同一事实）与互相矛盾的声明，写回台账。
模型给出的编号先校验再落账，不合法的条目跳过并记录，不中断流程。
"""
import config as _config
from agents.llm_agent import LLMAgent
from research.ledger import NEITHER, Ledger, LedgerError

RECONCILER_SYSTEM_PROMPT = """你是研究证据对账员，负责维护一份声明台账的一致性。

## 重复（duplicates）
两条声明陈述的是同一个事实（同一主体、同一指标、同一时间，数字一致），即使语言不同（中文/英文）或措辞不同。
keep 选信息更完整的一条，drop 为另一条。

## 矛盾（contradictions）
两条声明针对同一主体、同一指标、同一时间点给出不相容的事实（例如同一产品量产时间 2027 vs 2029、同一良率 85% vs 60%）。
以下情况不是矛盾：不同时间点的数据、不同口径（如电芯级 vs 系统级）、预测与已发生事实、不同主体。
topic 用一句话说明两者冲突在哪里。

## 与已有矛盾的关系
「已有矛盾」清单是台账里已登记的矛盾（编号、双方声明、冲突点、裁决）。新发现的冲突若与某条已有矛盾是同一冲突点\
（同一主体、同一指标、同一时间点），先判断新旧声明是否陈述同一事实：是则合并重复声明（duplicates），\
让冲突落在已有矛盾上；若是不同的声明（陈述了不同的事实，如"已建成"与"2026 年起搭载"），\
仍应登记为新矛盾，不要为避免重复而漏登冲突。

只报告你有把握的条目；每条至少要涉及一条「本轮新增声明」。"""

_PAIR = {"type": "object", "additionalProperties": False}
RECONCILE_SCHEMA = {
    "type": "object",
    "properties": {
        "duplicates": {"type": "array", "items": {**_PAIR,
            "properties": {"keep": {"type": "string"}, "drop": {"type": "string"}},
            "required": ["keep", "drop"]}},
        "contradictions": {"type": "array", "items": {**_PAIR,
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}, "topic": {"type": "string"}},
            "required": ["a", "b", "topic"]}},
    },
    "required": ["duplicates", "contradictions"],
    "additionalProperties": False,
}


def _lines(claims: dict) -> str:
    return "\n".join(f"[{cid}] {c['text']}" for cid, c in claims.items())


def _contradiction_lines(ledger: Ledger) -> str:
    def verdict(x):
        r = x["resolution"]
        if r is None:
            return "未裁决"
        return "两方存疑" if r["sides_with"] == NEITHER else f"已裁决：{ledger.canonical(r['sides_with'])} 胜"
    return "\n".join(f"[{xid}] {' 与 '.join(ledger.canonical(c) for c in x['claims'])}：{x['topic'] or '（无说明）'}"
                     f"（{verdict(x)}）" for xid, x in ledger.contradictions.items())


class ReconcilerAgent(LLMAgent):
    def __init__(self, model: str | None = None):
        super().__init__(name="对账员", system_prompt=RECONCILER_SYSTEM_PROMPT,
                         model=model or _config.SUPPORT_MODEL, schema=RECONCILE_SCHEMA)

    def reconcile(self, workspace: str, since_round: int = 0) -> dict:
        """对账 since_round 之后（含）新增的声明；返回 {merged, contradictions, skipped}。"""
        ledger = Ledger.load(workspace)
        citable = ledger.citable()
        new = {cid: c for cid, c in citable.items() if c["round"] >= since_round}
        if not new:
            return {"merged": 0, "contradictions": 0, "skipped": 0}
        old = {cid: c for cid, c in citable.items() if cid not in new}
        prompt = (f"## 本轮新增声明（{len(new)} 条）\n{_lines(new)}\n\n"
                  f"## 已有声明（{len(old)} 条）\n{_lines(old) or '（无）'}\n\n"
                  f"## 已有矛盾（{len(ledger.contradictions)} 处）\n{_contradiction_lines(ledger) or '（无）'}")
        data = self._invoke(self.request(prompt, schema=RECONCILE_SCHEMA)).data
        stats = apply_reconciliation(ledger, data, set(new))
        ledger.save()
        print(f"  [对账员] 合并重复 {stats['merged']} 条，新增矛盾 {stats['contradictions']} 处，"
              f"跳过无效条目 {stats['skipped']} 条", flush=True)
        return stats


def apply_reconciliation(ledger: Ledger, data: dict, new_ids: set) -> dict:
    """校验并落账；每条必须涉及新声明、编号存在且可引用。"""
    stats = {"merged": 0, "contradictions": 0, "skipped": 0}
    for d in data["duplicates"]:
        keep, drop = d["keep"], d["drop"]
        if keep == drop or not ({keep, drop} & new_ids) or not _citable(ledger, keep, drop):
            stats["skipped"] += 1
            continue
        ledger.merge(keep, drop)
        stats["merged"] += 1
    for x in data["contradictions"]:
        a, b = x["a"], x["b"]
        if a == b or not ({a, b} & new_ids) or not _citable(ledger, a, b):
            stats["skipped"] += 1
            continue
        try:
            before = len(ledger.contradictions)
            ledger.add_contradiction(a, b, x["topic"])
            stats["contradictions"] += len(ledger.contradictions) - before
        except LedgerError:
            stats["skipped"] += 1
    return stats


def _citable(ledger: Ledger, *cids) -> bool:
    citable = ledger.citable()
    return all(c in citable for c in cids)
