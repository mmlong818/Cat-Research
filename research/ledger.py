"""
声明台账（借鉴 loopx deep_research 的证据账本）

来源 S* ← 声明 C*（关联一个或多个来源）；矛盾 X* 把两条声明配对，必须裁决。
规则由代码强制，而不是依赖模型自觉：
  1. 被推翻（overruled）的声明不得在报告中引用
  2. 未裁决矛盾中的声明不得引用；存在未裁决矛盾时不得判定质量达标
  3. 裁决为「两方都不可靠」的矛盾，其声明只能在同一段落中成对引用
存储：{workspace}/08_verification/ledger.json，原子写；进程内并发写入加锁。
"""
import json
import os
import re
import threading
from dataclasses import dataclass, field

from research.quote_check import QUOTE_MAX_CHARS, check_quote
from research.source_quality import index_verification, is_low_credibility
from tools.file_tools import ensure_parent_dir

LEDGER_FILE = os.path.join("08_verification", "ledger.json")
STATUSES = ("unchecked", "supported", "disputed", "unverifiable", "overruled", "merged")
UNCITABLE = ("overruled", "merged")
# 给写作者/分析师看的状态说法（中文自然语言）；unchecked 不标注，避免英文状态词漏进报告
STATUS_LABELS = {"unchecked": "", "supported": "已核实", "disputed": "存疑", "unverifiable": "待核实",
                 "overruled": "已被推翻", "merged": "已合并"}
LOW_CREDIBILITY_TAG = "(来源可信度低) "  # 声明表里接在状态标注之后；现算，不写入台账
EXTRACTION_TAG = "(摘录待核) "  # 声明表里接在可信度标注之后；依据台账里持久化的 extraction 标记
NEITHER = "neither"
CITE =re.compile(r"\[(C\d+(?:\s*[,，、]\s*C\d+)*)\]")

# 程序生成的报告附录标题，按报告语言各一套。生成时按语言取，按标题切分/识别时两种都认（旧报告与新报告通用），
# 其他模块（orchestrator、tools/eval/judge.py）也引用这里，不要在别处再写死标题。
REFS_HEADINGS = {"zh": "声明来源", "en": "Claim sources"}
QUALITY_HEADINGS = {"zh": "研究质量报告", "en": "Research quality report"}
VIOLATIONS_HEADINGS = {"zh": "引用问题（未能在改进轮次中消除）", "en": "Citation issues (not resolved during revision)"}


def heading_for(headings: dict, language: str) -> str:
    return headings.get(language, headings["zh"])


def _any_heading(headings: dict) -> str:
    return "|".join(re.escape(h) for h in headings.values())


class LedgerError(ValueError):
    """违反台账规则的操作（带可执行的修复提示）"""


def _norm_text(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text).lower()


def _status_tag(status: str) -> str:
    label = STATUS_LABELS.get(status, "")
    return f"({label}) " if label else ""


def _pair_note(partners: list) -> str:
    """声明表行内标注：与哪些声明说法冲突、须同段一并引用（现算，不落盘；写作者不得抄进报告，由 label_leak 检查）。"""
    return f"  （与 {'、'.join(partners)} 说法冲突，须同段一并引用）" if partners else ""


def _norm_url(url: str) -> str:
    url = url.strip().rstrip("/").lower()
    return re.sub(r"^https?://(www\.)?", "", url)


@dataclass
class Ledger:
    sources: dict = field(default_factory=dict)         # S1 -> {url, title, published, round}
    # 声明另可带 quotes（{来源编号: 原文片段}）与 extraction（摘录待核标记 {ok, detail}），无则不写
    claims: dict = field(default_factory=dict)          # C1 -> {text, sources, round, status, note}
    contradictions: dict = field(default_factory=dict)  # X1 -> {claims:[a,b], topic, resolution}
    path: str | None = None

    def __post_init__(self):
        self._lock = threading.RLock()

    # ── 持久化 ──
    @classmethod
    def load(cls, workspace: str) -> "Ledger":
        path = os.path.join(workspace, LEDGER_FILE)
        data = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        return cls(sources=data.get("sources", {}), claims=data.get("claims", {}),
                   contradictions=data.get("contradictions", {}), path=path)

    def save(self):
        with self._lock:
            ensure_parent_dir(self.path)
            tmp = f"{self.path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"sources": self.sources, "claims": self.claims,
                           "contradictions": self.contradictions}, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)

    # ── 写入 ──
    def add_source(self, url: str, title: str = "", published: str = "", round_num: int = 0) -> str:
        with self._lock:
            key = _norm_url(url)
            for sid, s in self.sources.items():
                if _norm_url(s["url"]) == key:
                    return sid
            sid = f"S{len(self.sources) + 1}"
            self.sources[sid] = {"url": url.strip(), "title": title, "published": published,
                                 "round": round_num}
            return sid

    def add_claim(self, text: str, source_url: str = "", source_title: str = "",
                  published: str = "", round_num: int = 0, quote: str | None = None) -> tuple:
        """登记一条声明；文本重复时只追加来源。返回 (声明编号, 是否新声明)。
        quote 是该来源页面的原文片段：按来源存进 claims[cid]["quotes"]，并据此重算「摘录待核」标记；
        None 表示调用方不提供片段（旧数据 / 非研究员写入），不存储也不核对。"""
        with self._lock:
            sid = self.add_source(source_url, source_title, published, round_num) if source_url else None
            key = _norm_text(text)
            for cid, c in self.claims.items():
                if _norm_text(c["text"]) == key:
                    if sid and sid not in c["sources"]:
                        c["sources"].append(sid)
                    self._record_quote(c, sid, quote)
                    return cid, False
            cid = f"C{len(self.claims) + 1}"
            self.claims[cid] = {"text": text.strip(), "sources": [sid] if sid else [],
                                "round": round_num, "status": "unchecked", "note": ""}
            self._record_quote(self.claims[cid], sid, quote)
            return cid, True

    def _record_quote(self, claim: dict, sid: str | None, quote: str | None):
        if quote is None or not sid:
            return
        quotes = claim.setdefault("quotes", {})
        if not quotes.get(sid):  # 同一来源重复登记时保留先到的非空片段
            quotes[sid] = quote.strip()[:QUOTE_MAX_CHARS]
        self._refresh_extraction(claim)

    def _refresh_extraction(self, claim: dict):
        """按各来源的片段重算「摘录待核」：所有来源的片段都不一致或缺失才标记（没有登记片段的旧来源按缺失算），
        任一来源的片段一致就清除。标记只记在声明上，不改 status。"""
        results = [(sid, *check_quote(claim["text"], claim["quotes"].get(sid, ""))) for sid in claim["sources"]]
        if not results or any(ok for _, ok, _ in results):
            claim.pop("extraction", None)
        else:
            detail = "；".join(f"{sid}：{d}" for sid, _, d in results)
            claim["extraction"] = {"ok": False, "detail": detail[:300]}

    def clear_extraction(self, cid: str):
        with self._lock:
            self._require(cid)
            self.claims[cid].pop("extraction", None)

    def merge(self, keep: str, drop: str):
        """把重复声明 drop 并入 keep（来源与原文片段合并，drop 标为 merged，引用时应改用 keep）。"""
        with self._lock:
            self._require(keep, drop)
            k, d = self.claims[keep], self.claims[drop]
            k["sources"] += [s for s in d["sources"] if s not in k["sources"]]
            if d.get("quotes"):
                quotes = k.setdefault("quotes", {})
                for sid, q in d["quotes"].items():
                    quotes[sid] = quotes.get(sid) or q
            if "quotes" in k:
                self._refresh_extraction(k)
            self._repoint_contradictions(drop, keep)
            d.update(status="merged", note=f"与 {keep} 重复，请改引 {keep}", merged_into=keep)
            self.dedupe_contradictions()

    def dedupe_contradictions(self) -> int:
        """合并后 canonical 化的声明对相同的矛盾只保留编号最小的一处，返回删除数。
        裁决取更强者（A/B 胜负 > 两方存疑 > 未裁决），同强度取编号最小者那处的；最终是胜负裁决时重放一次，
        让两条声明的状态与之一致。不做语义去重：只认声明对完全相同。"""
        with self._lock:
            groups: dict = {}
            for xid, x in self.contradictions.items():
                groups.setdefault(tuple(sorted(self.canonical(c) for c in x["claims"])), []).append(xid)
            removed = 0
            for pair, xids in groups.items():
                if len(pair) == 2 and len(xids) > 1:
                    self._collapse(pair, sorted(xids, key=lambda i: int(i[1:])))
                    removed += len(xids) - 1
            return removed

    def _collapse(self, pair: tuple, xids: list):
        def rank(xid):
            r = self.contradictions[xid]["resolution"]
            return 0 if r is None else 1 if r["sides_with"] == NEITHER else 2
        keeper = xids[0]
        best = max(xids, key=lambda i: (rank(i), -int(i[1:])))
        resolution = self.contradictions[best]["resolution"]
        self.contradictions[keeper].update(claims=list(pair), resolution=resolution)
        for xid in xids[1:]:
            del self.contradictions[xid]
        if resolution and resolution["sides_with"] != NEITHER:
            self.resolve(keeper, self.canonical(resolution["sides_with"]), resolution["reason"],
                         resolution.get("evidence_url", ""))

    def _repoint_contradictions(self, drop: str, keep: str):
        """被合并声明所在的矛盾转到保留的声明上，裁决结果与争议状态随之转移。"""
        for x in self.contradictions.values():
            if drop not in x["claims"]:
                continue
            other = next(c for c in x["claims"] if c != drop)
            if other == keep:
                continue  # 与保留者本身构成的矛盾：合并判断与矛盾判断冲突，保持原样
            x["claims"] = sorted([other, keep])
            r = x["resolution"]
            if r is None or self.claims[keep]["status"] == "overruled":
                continue
            if r["sides_with"] == drop:
                r["sides_with"] = keep
                self.claims[keep].update(status="supported", note=f"继承 {drop} 的裁决结果")
            elif r["sides_with"] == NEITHER:
                self.claims[keep].update(status="disputed", note=f"继承 {drop} 的争议：须成对引用")

    def canonical(self, cid: str) -> str:
        """沿合并链找到最终保留的声明编号（未合并的返回自身）。"""
        seen = set()
        while cid in self.claims and self.claims[cid].get("merged_into") and cid not in seen:
            seen.add(cid)
            cid = self.claims[cid]["merged_into"]
        return cid

    def set_status(self, cid: str, status: str, note: str = ""):
        if status not in STATUSES:
            raise LedgerError(f"未知状态 {status}，可选：{STATUSES}")
        with self._lock:
            self._require(cid)
            self.claims[cid].update(status=status, note=note)

    def add_contradiction(self, a: str, b: str, topic: str = "") -> str:
        with self._lock:
            self._require(a, b)
            if a == b:
                raise LedgerError(f"矛盾需要两条不同的声明，收到 {a}")
            pair = sorted([a, b])
            for xid, x in self.contradictions.items():
                if sorted(x["claims"]) == pair:
                    return xid
            xid = f"X{max((int(i[1:]) for i in self.contradictions), default=0) + 1}"  # 去重会删编号，不能用数量
            self.contradictions[xid] = {"claims": pair, "topic": topic, "resolution": None}
            return xid

    def resolve(self, xid: str, sides_with: str, reason: str, evidence_url: str = ""):
        """裁决矛盾：sides_with 为其中一条声明（另一条被推翻），或 'neither'（两条都标为争议）。"""
        with self._lock:
            if xid not in self.contradictions:
                raise LedgerError(f"不存在的矛盾 {xid}")
            x = self.contradictions[xid]
            if sides_with != NEITHER and sides_with not in x["claims"]:
                raise LedgerError(f"{xid} 只能裁决为 {x['claims']} 之一或 '{NEITHER}'，收到 {sides_with}")
            x["resolution"] = {"sides_with": sides_with, "reason": reason, "evidence_url": evidence_url}
            for cid in x["claims"]:
                if self.claims[cid]["status"] == "overruled":
                    continue  # 已被其他裁决推翻：有可靠证据证明其错误，不再被覆盖
                if sides_with == NEITHER:
                    self.set_status(cid, "disputed", f"{xid}：两方证据都不足，须成对引用")
                elif cid == sides_with:
                    self.set_status(cid, "supported", f"{xid} 裁决胜出")
                else:
                    self.set_status(cid, "overruled", f"{xid} 裁决被推翻：{reason}")

    def _require(self, *cids):
        missing = [c for c in cids if c not in self.claims]
        if missing:
            raise LedgerError(f"不存在的声明 {missing}")

    # ── 查询 ──
    def unresolved(self) -> list:
        return [xid for xid, x in self.contradictions.items() if x["resolution"] is None]

    def new_claims_in_round(self, round_num: int) -> int:
        return sum(1 for c in self.claims.values() if c["round"] == round_num)

    def citable(self) -> dict:
        """可引用的声明（排除被推翻与被合并的）。"""
        return {cid: c for cid, c in self.claims.items() if c["status"] not in UNCITABLE}

    def low_credibility_claims(self, verification: dict | None = None) -> set:
        """全部来源都是低可信来源的声明编号（没有来源的不算）；verification 为 source_verification.json 的内容。"""
        index = index_verification(verification)
        out = set()
        for cid, c in self.claims.items():
            urls = [self.sources[s]["url"] for s in c["sources"] if s in self.sources]
            if urls and all(is_low_credibility(u, index) for u in urls):
                out.add(cid)
        return out

    def extraction_issue_claims(self) -> set:
        """被标记「摘录待核」的声明编号：所有来源的片段都与声明的数字 / 时间对不上或缺失（research.quote_check）。"""
        return {cid for cid, c in self.claims.items() if c.get("extraction", {}).get("ok") is False}

    def claims_table(self, verification: dict | None = None) -> str:
        """给分析师/写作者的声明表：编号、状态（中文，未核查不标注）、来源可信度低标注、摘录待核标注、内容、来源编号；
        卷入未裁决矛盾的声明单列为暂不可引用。低可信标注现算不落盘，verification 缺省时只用规则引擎判定；
        摘录待核标注来自台账里持久化的 extraction 标记。"""
        blocked = {self.canonical(cid) for xid in self.unresolved() for cid in self.contradictions[xid]["claims"]}
        low = self.low_credibility_claims(verification)
        flagged = self.extraction_issue_claims()
        partners = self._neither_partners()
        lines = [f"[{cid}] {_status_tag(c['status'])}{LOW_CREDIBILITY_TAG if cid in low else ''}"
                 f"{EXTRACTION_TAG if cid in flagged else ''}{c['text']}"
                 f"  — 来源 {','.join(c['sources']) or '无'}{_pair_note(partners.get(cid, []))}"
                 for cid, c in self.citable().items() if cid not in blocked]
        pairs = [f"{xid}: {' 与 '.join(self.canonical(c) for c in x['claims'])} 须在同一段落成对引用"
                 for xid, x in self.contradictions.items() if self.live_neither_pair(x)]
        if pairs:
            lines += ["", "## 成对引用要求"] + pairs
        if blocked:
            lines += ["", f"## 暂不可引用（矛盾尚未裁决）：{', '.join(sorted(blocked, key=lambda c: int(c[1:])))}"]
        return "\n".join(lines)

    def live_neither_pair(self, x: dict) -> tuple | None:
        """仍有效的「两方存疑」成对引用要求：返回 canonical 化的声明对（升序）；
        矛盾不是 neither、两边合并成同一条，或任一方已不可引用（被推翻/合并链终点被推翻）时返回 None（要求作废）。"""
        if not x["resolution"] or x["resolution"]["sides_with"] != NEITHER:
            return None
        pair = tuple(sorted(self.canonical(c) for c in x["claims"]))
        if len(set(pair)) != 2 or any(c not in self.claims or self.claims[c]["status"] in UNCITABLE for c in pair):
            return None
        return pair

    def _neither_partners(self) -> dict:
        """两方存疑且仍有效的矛盾里，每条声明（canonical 编号）对应的冲突对方编号（按编号升序、去重）。"""
        out: dict = {}
        for x in self.contradictions.values():
            pair = self.live_neither_pair(x)
            if pair:
                out.setdefault(pair[0], set()).add(pair[1])
                out.setdefault(pair[1], set()).add(pair[0])
        return {cid: sorted(ps, key=lambda c: int(c[1:])) for cid, ps in out.items()}

    def references(self, cited: set, language: str = "zh") -> str:
        """报告附录：被引用的声明 → 来源 URL。"""
        sep, no_source = ("; ", "(no source)") if language == "en" else ("；", "（无来源）")
        rows = []
        for cid in sorted(cited, key=lambda c: int(c[1:])):
            c = self.claims.get(cid)
            if not c:
                continue
            urls = sep.join(self.sources[s]["url"] for s in c["sources"] if s in self.sources)
            rows.append(f"- **[{cid}]** {c['text']} — {urls or no_source}")
        return "\n".join(rows)

    def view(self) -> dict:
        """报告页用的只读视图：计数、每处矛盾的双方声明（含来源）与裁决，以及全部有效声明（不含已合并的）。
        声明带原文引语 quotes（{来源编号: 片段}，旧数据为空）与核查备注 note，来源带发布日期 published。"""
        def claim(cid):
            c = self.claims[cid]
            return {"id": cid, "text": c["text"], "status": c["status"], "note": c.get("note", ""),
                    "quotes": dict(c.get("quotes") or {}),
                    "sources": [{"id": s, "url": self.sources[s]["url"], "title": self.sources[s]["title"],
                                 "published": self.sources[s].get("published", "")}
                                for s in c["sources"] if s in self.sources]}
        return {
            "counts": {"claims": len(self.claims), "citable": len(self.citable()), "sources": len(self.sources),
                       "contradictions": len(self.contradictions), "unresolved": len(self.unresolved())},
            "contradictions": [{"id": xid, "topic": x["topic"], "claims": [claim(c) for c in x["claims"]],
                                "resolution": x["resolution"]} for xid, x in self.contradictions.items()],
            "claims": [claim(cid) for cid in sorted(self.claims, key=lambda c: int(c[1:]))
                       if self.claims[cid]["status"] != "merged"],
        }


def _cited_ids(text: str) -> set:
    return {i.strip() for m in CITE.findall(text) for i in re.split(r"[,，、]", m)}


def _paragraph_violations(ledger: Ledger, ids: set) -> list:
    out = []
    for cid in sorted(ids):
        c = ledger.claims.get(cid)
        if c is None:
            out.append({"type": "unknown", "claim": cid, "detail": "台账中不存在该声明编号"})
        elif c["status"] in UNCITABLE:
            out.append({"type": c["status"], "claim": cid, "detail": c["note"]})
    for xid, x in ledger.contradictions.items():
        pair = {ledger.canonical(c) for c in x["claims"]}  # 成对声明被合并时，要求随之转到保留的声明
        hit = ids & pair
        if not hit:
            continue
        if x["resolution"] is None:
            out += [{"type": "unresolved", "claim": cid, "detail": f"{xid} 尚未裁决"} for cid in sorted(hit)]
        elif hit != pair and ledger.live_neither_pair(x):
            out.append({"type": "unpaired", "claim": sorted(hit)[0],
                        "detail": f"{xid} 须与 {' / '.join(sorted(pair))} 在同一段落成对引用"})
    return out


def remap_citations(ledger: Ledger, text: str) -> str:
    """把正文中被合并声明的编号改写为最终保留的编号（同一括号内去重，保持顺序）。"""
    def fix(m):
        ids = []
        for i in re.split(r"[,，、]", m.group(1)):
            cid = ledger.canonical(i.strip())
            if cid not in ids:
                ids.append(cid)
        return f"[{', '.join(ids)}]"
    return CITE.sub(fix, text)


# ── 报告清洁检查：台账状态词与修订痕迹不得出现在报告正文 ──
STATUS_WORD = re.compile(r"(?<![A-Za-z0-9_-])(supported|disputed|unverifiable|overruled|unchecked|merged)"
                         r"(?![A-Za-z0-9_-])", re.IGNORECASE)
_LINK_OR_URL = re.compile(r"https?://\S+|\]\([^)\n]*\)")
_GENERATED_APPENDIX = re.compile(
    rf"\n#{{1,6}}[ \t]*(?:{_any_heading(REFS_HEADINGS)}|{_any_heading(QUALITY_HEADINGS)})(?=[ \t]*(?:\n|$))")
# 行首（允许引用块、标题、加粗、列表、括号等装饰符）出现修订说明 / 改版日志 / 相比上一版 之类的编辑痕迹
REVISION_LOG = re.compile(
    r"^[ \t>#*_\-•·【\[（(]*(?:"
    r"修订说明|修订记录|修订日志|修订摘要|改版说明|改版日志|改版记录|变更日志"
    r"|本版(?:修订|改动|变更|修改|更新)|本[次轮](?:修订|改版)"
    r"|(?:相比|相较于?|较|对比|与)上一版|上一版(?:的)?(?:问题|改动|修订|不足)"
    r"|根据(?:评审|审稿|上一轮)(?:意见|反馈)|第\s*\d+\s*版(?:修订|改动|相比|对比|变更)"
    r"|revision\s+(?:notes?|log|summary|history)|change\s?log|what(?:'s|\s+has)?\s+changed"
    r"|changes\s+(?:from|since|in)\s+(?:the\s+)?(?:previous|prior|last)\s+(?:version|draft)"
    r"|(?:compared\s+(?:to|with)|relative\s+to)\s+(?:the\s+)?(?:previous|prior|last)\s+(?:version|draft)"
    r")", re.IGNORECASE | re.MULTILINE)


# 全网范围的「不存在」断言（只见于 / 唯一来源 / 没有其他报道）：台账来源数只反映本研究检索到的范围，
# 同一句里没有范围限定语就算违规。按报告语言各一套（模式, 范围限定语, 断句）
_ABSENCE_CHECKS = {
    # 「只见于/仅见于」只在指向特定来源时算（只见于该来源 / 仅见于一份报告）；
    # 「只见于媒体转述 / 二手摘要 / 自媒体」是给弱证据加限定，不算
    "zh": (re.compile(r"(?:只见于|仅见于)(?:该|这一?|此|单一|唯一|一个|一份|一篇|一条|单个)?"
                      r"(?:来源|报道|报告|文章|研报)"
                      r"|唯一(?:的)?来源|没有其他(?:来源|报道)|未见其他(?:来源|报道)"),
           re.compile(r"本研究|检索到|本次检索|我们检索|检索范围|检索结果|搜索到"),
           re.compile(r"[。！？\n]")),
    "en": (re.compile(r"only\s+(?:found|reported|appears)\s+in\s+(?:this|that|the|a\s+single|a|one)\s+"
                      r"(?:source|report|article)\b|sole\s+source\b|no\s+other\s+(?:source|report)s?\b",
                      re.IGNORECASE),
           re.compile(r"\bin\s+(?:the|our)\s+(?:sources|search|research)\b", re.IGNORECASE),
           re.compile(r"(?<=[.!?])\s+|\n")),
}
_ABSENCE_HINTS = {
    "zh": "「{s}」是无范围限定的断言，请改为带限定的表述，如「本研究检索到的来源中仅见于……」",
    "en": '"{s}" asserts absence without a scope; qualify it, e.g. "only found in the sources retrieved here"',
}


# 声明表里的内部标注（状态标签用括号包着，来源可信度标签，摘录待核标签，成对引用的行内标注）不得原样出现在中文报告里
_LABEL_LEAK = re.compile(r"来源可信度低|摘录待核|[(（](?:已核实|存疑|待核实)[)）]"
                         r"|与\s*\[?C\d+[^。\n]{0,20}?说法冲突(?:[，,]\s*须同段一并引用)?|须同段一并引用")


def _label_leak_violations(body: str) -> list:
    found = dict.fromkeys(m.group(0) for m in _LABEL_LEAK.finditer(_LINK_OR_URL.sub(" ", body)))
    return [{"type": "label_leak", "claim": "", "detail": f"出现台账内部标注「{label}」，请改写为自然语言"}
            for label in found]


def _absence_violations(body: str, language: str) -> list:
    pattern, qualifier, split = _ABSENCE_CHECKS[language]
    sentences = split.split(_LINK_OR_URL.sub(" ", body))
    return [{"type": "absence_claim", "claim": "", "detail": _ABSENCE_HINTS[language].format(s=s.strip()[:60])}
            for s in sentences if pattern.search(s) and not qualifier.search(s)]


def report_hygiene_violations(text: str, language: str = "zh") -> list:
    """报告正文的清洁检查（不含程序生成的「声明来源」「研究质量报告」附录（中英标题都认）、URL 与链接目标）：
    英文台账状态词（英文报告里这些是普通词，不检查）每个词一条；修订日志式行首合并为一条；
    中文报告里出现声明表内部标注（来源可信度低、摘录待核、括号形式的已核实/存疑/待核实、
    「与 Cxx 说法冲突，须同段一并引用」）每种一条（label_leak）；
    指向特定来源、无范围限定的「只见于该来源 / 唯一来源」类不存在断言每句一条（absence_claim，中英各用各的模式）。"""
    body = _GENERATED_APPENDIX.split(text, maxsplit=1)[0]
    out = []
    if language == "zh":
        found = {w.lower() for w in STATUS_WORD.findall(_LINK_OR_URL.sub(" ", body))}
        out += [{"type": "status_word", "claim": "", "detail": f"出现 {w}，请改写为自然语言"} for w in sorted(found)]
    lines = [m.group(0) + body[m.end():].split("\n", 1)[0] for m in REVISION_LOG.finditer(body)]
    if lines:
        quoted = "；".join(f"「{line.strip()[:30]}」" for line in lines[:3])
        out.append({"type": "revision_log", "claim": "", "detail": f"{quoted}，请删除整段，报告只呈现成稿内容"})
    if language == "zh":
        out += _label_leak_violations(body)
    return out + _absence_violations(body, "en" if language == "en" else "zh")


def citation_counts(ledger: Ledger, text: str) -> dict:
    """正文中各声明被引用的次数（括号内多个编号各计一次；被合并的声明记到最终保留的编号上；不含附录）。"""
    counts: dict = {}
    for m in CITE.findall(body_of(text)):
        for i in re.split(r"[,，、]", m):
            cid = ledger.canonical(i.strip())
            counts[cid] = counts.get(cid, 0) + 1
    return counts


def check_citations(ledger: Ledger, text: str, language: str = "zh") -> dict:
    """按段落检查草稿的声明引用与报告清洁度；返回被引用的编号、违规列表与数字句引用覆盖率。"""
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    cited, violations, seen = set(), [], set()
    for para in paragraphs:
        ids = _cited_ids(para)
        cited |= ids
        for v in _paragraph_violations(ledger, ids):
            key = (v["type"], v["claim"])
            if key not in seen:
                seen.add(key)
                violations.append(v)
    violations += report_hygiene_violations(text, language)
    sentences = [s for s in re.split(r"[。！？\n]", text) if re.search(r"\d", s) and len(s.strip()) >= 15]
    covered = sum(1 for s in sentences if CITE.search(s))
    return {"cited": sorted(cited, key=lambda c: int(c[1:])), "violations": violations,
            "numeric_coverage": round(covered / len(sentences), 3) if sentences else None}


# ── 草稿的声明来源附录 ──
def refs_marker(language: str = "zh") -> str:
    return f"\n\n---\n## {heading_for(REFS_HEADINGS, language)}\n"


REFS_MARKER = refs_marker("zh")
_REFS_SPLIT = re.compile(rf"\n\n---\n## (?:{_any_heading(REFS_HEADINGS)})\n")
VIOLATION_LABELS = {"unknown": "不存在的声明编号", "overruled": "引用了已被推翻的声明",
                    "merged": "引用了被合并的重复声明", "unresolved": "引用了尚未裁决的矛盾声明",
                    "unpaired": "争议声明未成对引用", "status_word": "报告正文出现英文台账状态词",
                    "revision_log": "报告含修订说明/改版日志等编辑痕迹",
                    "absence_claim": "出现无范围限定的「只见于该来源/唯一来源」类断言",
                    "label_leak": "报告正文出现声明表的内部标注"}
VIOLATION_LABELS_EN = {"unknown": "Claim ID not in the ledger", "overruled": "Cites an overruled claim",
                       "merged": "Cites a duplicate claim that was merged",
                       "unresolved": "Cites a claim in an unresolved contradiction",
                       "unpaired": "Disputed claim not cited as a pair",
                       "status_word": "Ledger status words in the report body",
                       "revision_log": "Report contains revision notes or change-log traces",
                       "absence_claim": "Unscoped \"only found in / sole source\" assertion",
                       "label_leak": "Ledger-table labels in the report body"}


def body_of(text: str) -> str:
    """去掉系统附加的「声明来源」附录（中英标题都认），只留正文（引用检查只针对正文）。"""
    return _REFS_SPLIT.split(text)[0].rstrip()


def with_references(ledger: Ledger, text: str, language: str = "zh") -> tuple:
    """按当前台账重写正文中被合并的编号并重新生成「声明来源」附录（语言随报告）；返回 (新文本, 引用检查结果)。"""
    body = remap_citations(ledger, body_of(text))
    check = check_citations(ledger, body, language)
    empty = "(no claims cited in the body)" if language == "en" else "（正文未引用任何声明）"
    refs = ledger.references(set(check["cited"]), language) or empty
    return f"{body}{refs_marker(language)}{refs}\n", check


def format_violations(violations: list, language: str = "zh") -> str:
    labels, colon = (VIOLATION_LABELS_EN, ": ") if language == "en" else (VIOLATION_LABELS, "：")

    def line(v):
        tag = "[" + v["claim"] + "] " if v["claim"] else ""  # 清洁类违规不针对某条声明
        return f"- {tag}{labels[v['type']]}{colon}{v['detail']}"
    return "\n".join(line(v) for v in violations)
