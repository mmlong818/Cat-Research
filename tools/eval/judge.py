"""盲评：同一独立评审员对两份报告做两两比较（两种顺序各一次）+ 事实抽查 + 客观指标。

用法: python -m tools.eval.judge Q2 <候选报告.md> --baseline <基线报告.md> [--out 结果.json]
A 是基线，B 是候选；报告先匿名化，去掉版本号等痕迹。
评审员固定为 JUDGE，换评审员会让历史分数不可比。
"""
import argparse
import json
import random
import re
from urllib.parse import urlparse

import config
from llm import LLMError, LLMRequest, call, call_many
from research.ledger import QUALITY_HEADINGS
from tools.eval.questions import QUESTIONS

JUDGE = "claude-opus-5"
DIMS = ["accuracy", "completeness", "depth", "recency", "clarity"]
DIM_ZH = {"accuracy": "准确性与可核实性", "completeness": "完整性", "depth": "分析深度",
          "recency": "时效性", "clarity": "清晰度与结构"}

PAIR_SCHEMA = {
    "type": "object",
    "properties": {
        **{f"{side}_{d}": {"type": "number"} for side in ("X", "Y") for d in DIMS},
        "winner": {"type": "string", "enum": ["X", "Y", "tie"]},
        "reason": {"type": "string"},
    },
    "required": [f"{side}_{d}" for side in ("X", "Y") for d in DIMS] + ["winner", "reason"],
    "additionalProperties": False,
}

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["supported", "contradicted", "unverifiable"]},
        "evidence_url": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["verdict", "evidence_url", "note"],
    "additionalProperties": False,
}

# 行内引用（报告格式各异）：[12] / [1,3] / \[R2\] / [⑤] / [官] / 裸 URL
CITATION = re.compile(
    r"\\?\[(?:R?\d+(?:[,，、\-–]\s*R?\d+)*|官|[^\]\n]{0,6}[①-⑳][^\]\n]{0,6})\\?\]|https?://")
REFERENCE_LINE = re.compile(r"^(?:\*\*)?\\?\[R?\d+\\?\]|^\d+\.\s|★|https?://")
QUALITY_APPENDIX = re.compile(r"\n-{3,}\n## (?:" + "|".join(re.escape(h) for h in QUALITY_HEADINGS.values()) + ")")


def anonymize(text: str) -> str:
    """去掉质量附录与版本痕迹，避免评审员据此认出来源。"""
    text = QUALITY_APPENDIX.split(text)[0]
    text = re.sub(r"[（(]第[一二三四五六七八九十\d]+版[）)]", "", text)
    lines = [ln for ln in text.splitlines()
             if not re.search(r"第\s*[一二三四五六七八九十\d]+\s*[版轮]|上一版|本版|版本[:：]", ln)]
    return "\n".join(lines)


def metrics(text: str) -> dict:
    urls = sorted({u.rstrip(".,;:)）】") for u in re.findall(r"https?://[^\s)\]>\"'）】]+", text)})
    domains = {urlparse(u).netloc.lower().removeprefix("www.") for u in urls}
    sentences = [s.strip() for s in re.split(r"[。\n！？]", text) if len(s.strip()) >= 15]
    numeric = [s for s in sentences if re.search(r"\d", s)]
    cited = [s for s in numeric if CITATION.search(s)]
    return {"chars": len(text), "unique_urls": len(urls), "distinct_domains": len(domains),
            "numeric_sentences": len(numeric),
            "numeric_cited_ratio": round(len(cited) / len(numeric), 3) if numeric else None}


def pair_prompt(question: str, x: str, y: str) -> str:
    dims = "、".join(f"{d}（{DIM_ZH[d]}）" for d in DIMS)
    return f"""你是独立的研究报告评审专家。下面是针对同一研究问题的两份报告 X 与 Y，来源未知。
研究问题：{question}

请分别给 X、Y 在以下维度打 1-10 分：{dims}。
准确性以你的知识判断明显错误、内部矛盾、无出处的关键数字为扣分依据；时效性看是否覆盖到问题要求的最新时段。
最后给出总体更好的一份（winner：X / Y / tie），reason 用 3-5 句说明关键差异。不要因为篇幅长就给高分。

===== 报告 X =====
{x}

===== 报告 Y =====
{y}"""


def judge_pair(question: str, a: str, b: str) -> list:
    """两种顺序各评一次，结果统一换算回 A/B。"""
    out = []
    for order in ("AB", "BA"):
        x, y = (a, b) if order == "AB" else (b, a)
        r = call(LLMRequest(prompt=pair_prompt(question, x, y), system="你是严谨、中立的评审专家。",
                            model=JUDGE, effort="high", schema=PAIR_SCHEMA, max_turns=3, timeout=1800))
        d = r.data
        side = {"X": order[0], "Y": order[1]}
        scores = {side[s]: {k: d[f"{s}_{k}"] for k in DIMS} for s in ("X", "Y")}
        winner = "tie" if d["winner"] == "tie" else side[d["winner"]]
        out.append({"order": order, "scores": scores, "winner": winner, "reason": d["reason"]})
    return out


def sample_claims(text: str, n: int = 5, seed: int = 20260929) -> list:
    """固定种子抽取含数字的陈述句，同一份报告每次抽到的相同。"""
    sentences = [re.sub(r"^[-*>\s]+", "", s.strip()) for s in re.split(r"[。\n！？]", text)]
    cands = [s for s in sentences
             if 25 <= len(s) <= 220 and re.search(r"\d", s)
             and not s.startswith(("|", "#")) and not REFERENCE_LINE.search(s)]
    return random.Random(seed).sample(cands, min(n, len(cands)))


def check_claims(claims: list) -> list:
    reqs = [LLMRequest(
        prompt=f"请核实下面这条来自研究报告的陈述（今天是 {config.CURRENT_DATE_STR}）。"
               f"用 WebSearch/WebFetch 查找可靠来源，判断它是否被来源证实。\n\n陈述：{c}",
        system="你是独立事实核查员。只依据你实际读到的来源判断：supported（来源证实，数字/时间基本一致）、"
               "contradicted（来源给出不同事实）、unverifiable（找不到可靠来源）。",
        model=JUDGE, effort="medium", tools=("WebSearch", "WebFetch"), schema=CHECK_SCHEMA,
        max_turns=15, timeout=900) for c in claims]
    out = []
    for c, r in zip(claims, call_many(reqs, max_concurrency=3), strict=True):
        if isinstance(r, LLMError):
            out.append({"claim": c, "verdict": "error", "evidence_url": "", "note": str(r)})
        else:
            out.append({"claim": c, **r.data})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("label", choices=sorted(QUESTIONS))
    ap.add_argument("candidate", help="候选报告（B）")
    ap.add_argument("--baseline", required=True, help="基线报告（A）")
    ap.add_argument("--out", default="judge_result.json")
    args = ap.parse_args(argv)
    path_a = args.baseline

    with open(path_a, encoding="utf-8") as fa, open(args.candidate, encoding="utf-8") as fb:
        a, b = anonymize(fa.read()), anonymize(fb.read())
    result = {"label": args.label, "A": path_a, "B": args.candidate, "judge": JUDGE,
              "metrics": {"A": metrics(a), "B": metrics(b)}}
    print("metrics", json.dumps(result["metrics"], ensure_ascii=False), flush=True)
    result["pairwise"] = judge_pair(QUESTIONS[args.label], a, b)
    for p in result["pairwise"]:
        print("pairwise", p["order"], "winner=", p["winner"], json.dumps(p["scores"]), flush=True)
    result["fact_check"] = {side: check_claims(sample_claims(t)) for side, t in (("A", a), ("B", b))}
    for side, items in result["fact_check"].items():
        print("fact_check", side, [i["verdict"] for i in items], flush=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("DONE", args.out, flush=True)


if __name__ == "__main__":
    main()
