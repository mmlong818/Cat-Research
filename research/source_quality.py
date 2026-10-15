"""
来源可信度判定（确定性，纯函数）：给声明表标注、给核查挑选排序用。

判定顺序（任一命中即「低可信」）：
  1. 规则库的低可信类别：社交媒体 / 自媒体平台 / 聚合与 AI 生成研报站（tools.domain_checker），不受评分影响
  2. 来源验证阶段（08_verification/source_verification.json）把该 URL 列入 unreliable_sources
  3. 来源验证阶段给出的 domain_score < LOW_SCORE
  4. 验证文件里没有该 URL（或没有验证文件）时，回落到规则引擎的 final_score < LOW_SCORE
阈值取 50 而不是 60：规则引擎对「未收录的 https 域名」一律给 50（base 45 + https 5），按 60 判会把所有未收录
域名都算低可信，标注失去区分度；50 以下只剩验证阶段明确压低的、无 https 或带可疑特征的域名。tier 不单独使用
（tier 4 只表示域名未收录，分数已反映验证阶段的判断）。
"""
import json
import os
import re

from tools.domain_checker import assess_url, low_credibility_category

LOW_SCORE = 50
VERIFICATION_FILE = os.path.join("08_verification", "source_verification.json")


def _norm_url(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url.strip().rstrip("/").lower())


def load_verification(workspace: str) -> dict | None:
    """读来源验证结果；文件不存在或损坏时返回 None（调用方回落到规则引擎）。"""
    try:
        with open(os.path.join(workspace, VERIFICATION_FILE), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def index_verification(data: dict | None) -> dict:
    """把验证结果整理成按规范化 URL 查找的索引：{"scores": {url: 分数}, "unreliable": {url}}；格式不对的条目忽略。"""
    scores: dict = {}
    unreliable: set = set()
    if isinstance(data, dict):
        entries = data.get("verified_sources")
        for e in entries if isinstance(entries, list) else []:
            score = e.get("domain_score") if isinstance(e, dict) else None
            if isinstance(e, dict) and isinstance(e.get("url"), str) and isinstance(score, int | float) \
                    and not isinstance(score, bool):
                scores[_norm_url(e["url"])] = score
        urls = data.get("unreliable_sources")
        unreliable = {_norm_url(u) for u in urls if isinstance(u, str)} if isinstance(urls, list) else set()
    return {"scores": scores, "unreliable": unreliable}


def is_low_credibility(url: str, index: dict | None = None) -> bool:
    """URL 是否低可信来源；index 为 index_verification 的结果（None 表示没有验证结果，只用规则）。"""
    if low_credibility_category(url):
        return True
    key = _norm_url(url)
    if index:
        if key in index["unreliable"]:
            return True
        if key in index["scores"]:
            return index["scores"][key] < LOW_SCORE
    return assess_url(url)["final_score"] < LOW_SCORE
