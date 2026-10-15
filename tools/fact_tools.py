"""
事实核查工具：对单条声明做独立交叉验证

每条声明各开一次独立调用（互不共享上下文），由模型自行用 WebSearch/WebFetch
从多个角度（直接检索、数据出处、反向质疑）寻找独立来源，返回结构化判定。
"""

from llm import LLMError, LLMRequest, call_many

VERDICTS = ["supported", "disputed", "unverifiable", "insufficient"]
EVIDENCE_TIERS = ["primary", "authority", "media", "none"]
STRONG_TIERS = ("primary", "authority")

# 裁决与独立核实共用：证据层级与一手记录优先
SOURCE_HIERARCHY_PROMPT = """证据层级（由高到低）：
- primary 一手官方记录：标准全文/标准信息平台、法律法规与政府公文原文、交易所/监管披露、公司官方公告或财报原文、\
论文原文/DOI、官方数据库
- authority 权威机构报告、行业协会/研究机构的原始发布
- media 新闻、自媒体、转载、研报转述
对本应有一手记录的声明（标准编号与发布/实施日期、法规政策条文与日期、官方统计数据、公司财务或产能公告、论文结论），\
必须先尝试检索原始记录，再看媒体：中国国家标准查 openstd.samr.gov.cn / std.samr.gov.cn，法规政策查 gov.cn 等。\
找到的一手记录压倒任意数量的媒体说法。
多家媒体复述同一说法只算一个来源；不得以"报道多、细节一致"作为判断理由。"""

_EVIDENCE = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"url": {"type": "string"}, "title": {"type": "string"}},
        "required": ["url", "title"],
        "additionalProperties": False,
    },
}

CROSS_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": VERDICTS},
        "confidence": {"type": "number"},
        "supporting": _EVIDENCE,
        "contradicting": _EVIDENCE,
        "explanation": {"type": "string"},
        "evidence_tier": {"type": "string", "enum": EVIDENCE_TIERS},
    },
    "required": ["verdict", "confidence", "supporting", "contradicting", "explanation", "evidence_tier"],
    "additionalProperties": False,
}

CROSS_CHECK_SYSTEM = f"""你是独立事实核查员。只根据你亲自检索到的独立来源判断一条声明，不依赖任何先验材料。
从至少两个角度检索：直接检索声明本身、检索数据的原始出处、检索是否有质疑或反驳。
verdict：supported（有独立来源支持）/ disputed（有来源反驳）/ unverifiable（检索不到相关信息）/ \
insufficient（证据不足以判断）。
confidence 取 0.0-1.0；supporting / contradicting 只列实际读过的来源。

{SOURCE_HIERARCHY_PROMPT}
evidence_tier：填你支持或反驳该声明所依据证据中的最高等级（primary / authority / media），没有任何可用证据填 none。\
只有 media 证据时，不要给 supported 或 disputed。"""


def verification_outcome(verdict: str, tier: str | None, explanation: str) -> tuple[str, str]:
    """独立核实结果 → (台账状态, 备注)。supported / disputed 必须有 primary 或 authority 证据，
    只有媒体（或没有）证据时一律记为 unverifiable，避免媒体互相转述或互相打架时误判。"""
    status = {"supported": "supported", "disputed": "disputed"}.get(verdict, "unverifiable")
    if status != "unverifiable" and tier not in STRONG_TIERS:
        return "unverifiable", f"仅媒体来源，未找到一手或权威来源（模型原判 {verdict}）：{explanation}"
    return status, explanation


def cross_reference_claims(claims: list[str], model: str,
                           max_parallel: int = 3) -> list[dict | None]:
    """并行独立核查多条声明；返回与 claims 同序的列表，单条失败时该位置为 None。"""
    reqs = [LLMRequest(prompt=f"请核查这条声明：\n\n{c}", system=CROSS_CHECK_SYSTEM, model=model,
                       effort="low", tools=("WebSearch", "WebFetch"),
                       schema=CROSS_CHECK_SCHEMA, max_turns=10)
            for c in claims]
    out: list[dict | None] = []
    for claim, r in zip(claims, call_many(reqs, max_concurrency=max_parallel), strict=True):
        if isinstance(r, LLMError):
            print(f"  [事实核查] 独立核查失败，跳过该声明: {claim[:40]}… ({r})", flush=True)
            out.append(None)
            continue
        data = r.data
        data["confidence"] = min(max(float(data["confidence"]), 0.0), 1.0)
        out.append(data)
    return out
