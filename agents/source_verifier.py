"""
SourceVerifierAgent - 来源可信度验证智能体
对研究收集的所有来源进行多维度可信度评估
"""
import json
import os

import config as _config
from agents.llm_agent import LLMAgent, write_json_atomic
from llm import LLMError
from tools.domain_checker import assess_source_list

CONFIDENCE = ["high", "medium", "low", "unknown"]
CATEGORIES = ["academic", "government", "news", "research", "general"]


SOURCE_VERIFIER_SYSTEM_PROMPT = """你是一位专业的信息来源可信度评估专家，专注于判断信息来源的权威性、准确性和可靠性。

## 你的职责
对研究收集到的所有来源进行系统性评估，帮助确保最终研究结论基于高质量来源。

## 评估维度
1. **域名权威性** - 来源网站是否是公认的权威机构
2. **内容相关性** - 来源内容与研究问题的相关程度
3. **信息时效性** - 来源信息是否足够新鲜
4. **多源验证** - 重要结论是否有多个来源交叉印证

## 评分
- domain_score 取 0-100；tier 取 1-4（4 为未知域名，需在 warning 中说明）
- 规则引擎给出的初评分可作参考，你可以根据上下文调整，但调整幅度大时在 warning 中说明理由"""


SOURCE_SCHEMA = {
    "type": "object",
    "properties": {
        "verified_sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "domain_score": {"type": "number"},
                    "confidence_level": {"type": "string", "enum": CONFIDENCE},
                    "tier": {"type": "integer"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "is_reliable": {"type": "boolean"},
                    "warning": {"type": "string"},
                },
                "required": ["url", "title", "domain_score", "confidence_level", "tier",
                             "category", "is_reliable", "warning"],
                "additionalProperties": False,
            },
        },
        "recommendation": {"type": "string"},
    },
    "required": ["verified_sources", "recommendation"],
    "additionalProperties": False,
}


class SourceVerifierAgent(LLMAgent):
    def __init__(self, model: str | None = None):
        super().__init__(name="来源验证员", system_prompt=SOURCE_VERIFIER_SYSTEM_PROMPT,
                         model=model or _config.SOURCE_VERIFIER_MODEL, schema=SOURCE_SCHEMA)

    def verify_sources(self, workspace: str) -> tuple:
        """评估研究来源，返回 (结果 dict, 文件路径)。

        模型调用失败时返回规则引擎的评估结果（标记 degraded）。
        """
        output_file = os.path.join(workspace, "08_verification", "source_verification.json")
        sources = self._collect_sources_from_research(os.path.join(workspace, "04_research"))
        if not sources:
            result = summarize([], "研究阶段没有收集到任何来源。")
            write_json_atomic(output_file, result)
            return result, output_file

        pre = assess_source_list(sources)
        rule_view = [{k: s.get(k) for k in ("url", "title", "final_score", "tier", "category",
                                            "confidence_level", "flags")} for s in pre["sources"]]
        prompt = f"""请评估下面 {len(sources)} 个研究来源的可信度，每个来源输出一条 verified_sources 记录。

## 来源列表（含规则引擎初评分 final_score）
{json.dumps(rule_view, ensure_ascii=False, indent=2)}"""

        try:
            data = self.ask(prompt, output_file,
                            lambda d: summarize(d["verified_sources"], d["recommendation"]))
            return data, output_file
        except LLMError as e:
            print(f"  [警告] 来源验证模型调用失败，使用规则引擎评估（degraded）: {e}", flush=True)
            result = summarize(_rule_entries(pre["sources"]), "模型不可用，以下为规则引擎评估。")
            result.update(degraded=True, degraded_reason=str(e))
            write_json_atomic(output_file, result)
            return result, output_file

    def _collect_sources_from_research(self, research_dir: str) -> list:
        """从研究文件中提取 URL 来源"""
        import re
        sources: list[dict[str, str]] = []
        seen_urls = set()
        research_path = research_dir.replace('/', os.sep)

        if not os.path.exists(research_path):
            return sources

        for fname in os.listdir(research_path):
            if not fname.endswith('.md'):
                continue
            fpath = os.path.join(research_path, fname)
            try:
                with open(fpath, encoding='utf-8') as f:
                    content = f.read()
                # 提取 URL
                urls = re.findall(r'https?://[^\s\)\]\"\'>]+', content)
                for url in urls:
                    url = url.rstrip('.,;:)')
                    if url not in seen_urls:
                        seen_urls.add(url)
                        # 尝试从上下文提取标题
                        idx = content.find(url)
                        surrounding = content[max(0, idx-100):idx+100]
                        title_match = re.search(r'\[([^\]]+)\]', surrounding)
                        title = title_match.group(1) if title_match else url.split('/')[2]
                        sources.append({"url": url, "title": title})
            except Exception as e:
                print(f"  [来源验证] 读取/解析 {fname} 失败，跳过: {e!r}", flush=True)
                continue

        return sources


def summarize(entries: list, recommendation: str) -> dict:
    """由逐条来源评估确定性地计算汇总字段。"""
    for e in entries:
        e["domain_score"] = min(max(float(e["domain_score"]), 0.0), 100.0)
    scores = [e["domain_score"] for e in entries]
    avg = sum(scores) / len(scores) if scores else 0.0
    ranked = sorted(entries, key=lambda e: e["domain_score"], reverse=True)
    return {
        "total_sources": len(entries),
        "verified_sources": entries,
        "summary": {
            "high_confidence_count": sum(1 for e in entries if e["confidence_level"] == "high"),
            "medium_confidence_count": sum(1 for e in entries if e["confidence_level"] == "medium"),
            "low_confidence_count": sum(1 for e in entries if e["confidence_level"] == "low"),
            "average_score": round(avg, 1),
            "overall_quality": _quality(avg) if entries else "poor",
            "recommendation": recommendation,
        },
        "unreliable_sources": [e["url"] for e in entries if not e["is_reliable"]],
        "top_sources": [e["url"] for e in ranked if e["is_reliable"]][:5],
    }


def _quality(avg: float) -> str:
    """与 domain_checker.assess_source_list 的分档一致。"""
    return ("excellent" if avg >= 80 else "good" if avg >= 65
            else "fair" if avg >= 50 else "poor")


def _rule_entries(assessed: list) -> list:
    level = {"very_low": "low"}
    return [{
        "url": s.get("url", ""),
        "title": s.get("title", ""),
        "domain_score": s.get("final_score", 0),
        "confidence_level": level.get(s.get("confidence_level"), s.get("confidence_level", "unknown")),
        "tier": s.get("tier", 4),
        "category": s.get("category", "general"),
        "is_reliable": s.get("final_score", 0) >= 60,
        "warning": ", ".join(s.get("flags") or []),
    } for s in assessed]
