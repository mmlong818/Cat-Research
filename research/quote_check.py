"""
摘录核对（确定性，纯函数）：声明里的数字与时间表述，必须能在研究员给出的原文片段中找到。

只做两类检查，不做地点 / 主体匹配，物理单位也不换算（GWh/MWh 只比数字本身）：
  1. 数字：声明中的阿拉伯数字（含小数、千分位、百分比、范围两端、年份）归一化后都须出现在片段里；
     片段里的中文数字（二、十五、一百二十、二〇二七）做有限归一后参与比对。季度 / 半年 / 月份里的数字
     算时间表述，不再按普通数字重复检查；媒体名里的数字（21世纪、36氪）不算数据。
     量级词（万 / 亿 / 万亿 / 조 / 억 / 만 / thousand / million / billion / trillion / M / B 等）：声明里带量级词的数字
     按绝对值（相对误差 ≤0.5%）与片段里的数字比较（530亿 = 53 billion）；不带量级词的数字仍只比数字本身。
     范围后的量级词作用于两端（60-70万 = 60万-70万）；不带量级词的声明数字也可等于片段里带量级词的数（600,000 = 60万）；
     会计负数 ($0.3) million、韩文千位拆写（4천700억 = 4700억）、英文数字词（three / twenty-five）按对应数字比对。
     片段里一个 4 位年份（19xx / 20xx）都没有时，声明里的年份数字不作要求。
  2. 时间表述：季度（第二季度 / 二季度 / Q2 / 2Q / second quarter / 2분기 / 第2四半期）、
     半年（上半年 / H1 / first half / 상반기 / 上半期 / 上期；下半年 / H2 / second half / 하반기 / 下半期 / 下期）、
     月份（3月 / 三月 / March / Mar / 3월）、
     年底（年底 / 年末 / end of 2026 / year-end / end of fiscal 2027 / 财年末 / 年度末 / 期末 / 연말 / 지난해 말）
     归一化后，声明里出现的每个值都须出现在片段里；片段里多出来的不算违规。
     「前三季度」「later this year」这类不能确定对应关系的说法不识别。
     年底也认 We ended 2025 / ended the year。
     声明里紧邻「报告 / 报道 / 称 / 披露」的「N月」（「7月报告称」「7月韩媒报道」「（2025年11月）称」）是来源发布日期，
     不要求片段包含；中间夹别的主体（「7月宁德时代称」）的月份是事件月份，照常核对。
片段为空 / 缺失 → 不一致，明细为「缺原文片段」。
"""
import re
import unicodedata
from typing import NamedTuple

QUOTE_MAX_CHARS = 300
MISSING = "缺原文片段"

_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_RUN = re.compile(r"[零〇一二两三四五六七八九十百]+")
_ORDINAL = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4}
_MONTH_NAMES = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
                "oct": 10, "nov": 11, "dec": 12}

_NUMBER = re.compile(r"(?<![\d.])(?:\d{1,3}(?:,\d{3})+(?!\d)(?:\.\d+)?|\d+(?:\.\d+)?)")
# 媒体名里的数字不是数据，声明里常带"21世纪经济报道称"这类转述前缀
_OUTLET_NAMES = re.compile(r"21世纪|36氪|24/7 Wall St\.?")

_MAGNITUDE = {"万亿": 1e12, "千万": 1e7, "百万": 1e6, "千亿": 1e11, "百亿": 1e10, "亿": 1e8, "億": 1e8, "万": 1e4,
              "조": 1e12, "억": 1e8, "만": 1e4, "thousand": 1e3, "million": 1e6, "mn": 1e6, "billion": 1e9, "bn": 1e9,
              "trillion": 1e12, "tn": 1e12, "m": 1e6, "b": 1e9}
# 量级词；单个 M / B 须紧贴数字，小写 m / b 只在数字前有货币符号时算（$5m），2GWh 的 G、10MWh 的 M 都不是量级
_MAG_WORD = r"万亿|千万|百万|千亿|百亿|[亿億万조억만]|(?i:thousand|million|billion|trillion|mn|bn|tn)(?![A-Za-z])"
# 会计负数 ($0.3) million：右括号夹在数字与量级词之间
_QUANTITY = re.compile(rf"({_NUMBER.pattern})(?:\s*\)?\s*({_MAG_WORD})|([MBmb])(?![A-Za-z0-9]))?")
_RANGE_SEP = re.compile(r"\s*[-–—~〜至到]\s*|\s+to\s+", re.IGNORECASE)  # 60-70万：量级词作用于范围两端
_CN_QUANTITY = re.compile(rf"({_CN_RUN.pattern})(?:\s*(万亿|千万|百万|千亿|百亿|[亿億万]))?")
_YEAR_NO = re.compile(r"(?:19|20)\d\d")
# 年份样的数字后面紧跟单位（2000 units / 2000 MWh）时是数量，不是年份
_UNIT_AFTER = re.compile(r"\s*(?:[kKMGT]?Wh|[kKMG]?W|mAh|Ah|V|kg|g|km|mm|cm|nm|%|units?|vehicles?|cells?|cycles?"
                         r"|tons?|tonnes?|yuan|won|dollars|[个辆台吨次元人项家条座倍])(?![A-Za-z])")

# 韩文千位 / 百位拆写：4천700억 = 4700억，3천5백억 = 3500억，5백억 = 500억
_KO_SPLIT = re.compile(r"(\d+)\s*천\s*(?:(\d+)\s*백\s*)?(\d+)?\s*(?=[억만조])|(\d+)\s*백\s*(\d+)?\s*(?=[억만조])")
_WORD_UNIT = {w: i for i, w in enumerate(("one", "two", "three", "four", "five", "six", "seven", "eight", "nine"), 1)}
_WORD_SMALL = dict(_WORD_UNIT, **{w: i for i, w in enumerate(
    ("ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
     "nineteen"), 10)})
_WORD_TENS = {w: i * 10 for i, w in enumerate(
    ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"), 2)}
_WORD_UNDER_100 = rf"(?:(?:{'|'.join(_WORD_TENS)})(?:[\s-]+(?:{'|'.join(_WORD_UNIT)}))?|{'|'.join(_WORD_SMALL)})"
_WORD_NUMBER = re.compile(
    rf"\b(?:(?:(?:a|{'|'.join(_WORD_UNIT)})[\s-]+)?hundred(?:[\s-]+(?:and[\s-]+)?{_WORD_UNDER_100})?|{_WORD_UNDER_100})"
    r"(?:\s+(thousand|million|billion|trillion)(?![A-Za-z]))?\b", re.IGNORECASE)

_MONTH_NO = r"(?:0?[1-9]|1[0-2])"
_DAY_NO = r"(?:0?[1-9]|[12]\d|3[01])"
_CN_OR_DIGIT = r"\d{1,2}|[一二三四五六七八九十]{1,3}"
_QN = r"[一二三四1-4]"
_YEAR_TAIL = r"(?:['’]?(\d{4}|\d{2}))?(?![A-Za-z0-9])"


def _cn_int(s: str) -> int | None:
    """中文数字串转整数：十 / 百 位值（二十五、一百二十）或逐位（二〇二七）；含无法识别的字符返回 None。"""
    if not s:
        return None
    if "十" not in s and "百" not in s:
        digits = [_CN_DIGIT.get(ch) for ch in s]
        return None if None in digits else int("".join(map(str, digits)))
    total = cur = 0
    for ch in s:
        if ch in _CN_DIGIT:
            cur = _CN_DIGIT[ch]
        elif ch == "十":
            total, cur = total + (cur or 1) * 10, 0
        else:
            total, cur = total + cur * 100, 0
    return total + cur


def _num_value(tok: str) -> int | None:
    return int(tok) if tok.isdigit() else _cn_int(tok)


def _norm_number(tok: str) -> str:
    tok = tok.replace(",", "")
    if "." in tok:
        tok = tok.rstrip("0").rstrip(".")
    return str(int(tok)) if tok.isdigit() else tok


def _year(tok: str | None) -> list:
    if not tok:
        return []
    return [str(int(tok) if len(tok) == 4 else 2000 + int(tok))]


# 每个时间规则：(正则, 处理函数)；处理函数返回 (时间值列表, 额外数字列表)，返回 None 表示这处匹配不算时间表述。
# 时间值：("Q", 1-4) / ("H", 1-2) / ("M", 1-12) / ("YE",)
def _quarter_range(m):
    return [("Q", _num_value(m[1])), ("Q", _num_value(m[2]))], []


def _quarter_cn(m):
    return [("Q", _num_value(m[1] or m[2]))], []


def _skip(m):
    return [], []


def _half_cn(m):
    return [("H", 1 if (m[1] or m[2] or m[3]) in "上상" else 2)], []


def _ordinal_half(m):
    n = _ORDINAL[m[1].lower()]
    return ([("H", n)], []) if n <= 2 else None


def _ordinal_quarter(m):
    return [("Q", _ORDINAL[m[1].lower()])], []


def _letter_first(m):
    kind, n = m[1], int(m[2])
    return ([(kind if kind == "Q" else "H", n)], _year(m[3])) if n <= (4 if kind == "Q" else 2) else None


def _digit_first(m):
    return ([("Q", int(m[1]))] if m[1] else [("H", int(m[2]))]), _year(m[3])


def _month_range(m):
    a, b = _num_value(m[1]), _num_value(m[2])
    return ([("M", a), ("M", b)], []) if a and b and a <= 12 and b <= 12 else None


def _month_cn(m):
    n = _num_value(m[1])
    return ([("M", n)], []) if n and 1 <= n <= 12 else None


def _month_en(m):
    return [("M", _MONTH_NAMES[m.group(0)[:3].lower()])], []


def _iso_date(m):
    return [("M", int(m[2]))], [_norm_number(m[1])] + ([_norm_number(m[3])] if m[3] else [])


def _year_end(m):
    return [("YE",)], []


_EN_MONTHS = (r"\b(?:(?i:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|june?|july?|aug(?:ust)?"
              r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)|May|MAY)\b")
_TIME_RULES = [
    (re.compile(rf"(?<!\d)((?:19|20)\d\d)[-/]({_MONTH_NO})(?:[-/]({_DAY_NO}))?(?!\d)"), _iso_date),
    (re.compile(rf"(?<!\d)((?:19|20)\d\d)\.({_MONTH_NO})\.({_DAY_NO})(?!\d)"), _iso_date),  # 点号只认完整日期
    (re.compile(rf"前\s*{_QN}\s*个?\s*季度"), _skip),
    (re.compile(rf"第?\s*({_QN})\s*[至到~\-]\s*第?\s*({_QN})\s*个?\s*季度"), _quarter_range),
    (re.compile(rf"第?\s*({_QN})\s*个?\s*季度|第\s*({_QN})\s*季(?![度节])"), _quarter_cn),
    (re.compile(rf"(?<![\d.])제?\s*([1-4])\s*분기|第?\s*({_QN})\s*四半期"), _quarter_cn),
    (re.compile(r"([上下])半[年期]|([상하])반기|(?<=[年度\d])([上下])期(?![末间])"), _half_cn),
    (re.compile(r"\b(first|1st|second|2nd|third|3rd|fourth|4th)[\s-]+quarter\b", re.IGNORECASE), _ordinal_quarter),
    (re.compile(r"\b(first|1st|second|2nd)[\s-]+half\b", re.IGNORECASE), _ordinal_half),
    (re.compile(r"(?:(?<![A-Za-z0-9])|(?<=\d{4}))([QH])([1-9])(?:['’]\s?(\d{4}|\d{2}))?(?![A-Za-z0-9])"),
     _letter_first),
    (re.compile(rf"(?<![A-Za-z0-9.])(?:([1-4])Q|([12])H){_YEAR_TAIL}"), _digit_first),
    (re.compile(rf"(?<![\d.])({_CN_OR_DIGIT})\s*[-~至到]\s*({_CN_OR_DIGIT})\s*[月월]"), _month_range),
    (re.compile(rf"(?<![\d.])({_CN_OR_DIGIT})\s*[月월]"), _month_cn),
    (re.compile(_EN_MONTHS), _month_en),
    (re.compile(r"年底|(?<!十)年末|岁末|年终(?!奖)|财年[末底]|年度末|(?<![度期季半])期末|(?-i:\bYE)[\s-]?(?:20)?\d\d\b"
                r"|연말|(?:지난해|작년|올해|금년|내년|전년)\s*말|\d{4}\s*년\s*말"
                r"|\b(?:year[\s-]?end|fy[\s-]?end)\b"
                r"|\bend[\s-]+of[\s-]+(?:the[\s-]+|this[\s-]+|next[\s-]+)?"
                r"(?:year|20\d\d|fiscal[\s-]+(?:year(?:[\s-]+20\d\d)?|20\d\d)|fy[\s-]?(?:20)?\d\d)\b|\bend-20\d\d\b"
                r"|\bend(?:ed|ing)\s+(?:(?:the|fiscal)\s+)*(?:year(?!['’]s)|(?:fy\s?)?20\d\d|fy\s?\d\d)\b"
                r"(?!\s+(?:[QH][1-4]|quarter|half|month)\b)",
                re.IGNORECASE), _year_end),
]
# 声明里的"7月报告称"：月份是来源的发布日期，不是声明陈述的事实（片段里的月份不动）。
# 月份与报道动词之间可夹媒体修饰（韩媒 / 外媒 / 据…），或月份在括号里后接动词（Electrek（2025年11月）称）；
# 夹别的主体（宁德时代称）的月份是事件月份，不豁免
_SOURCE_VERB = (r"(?:(?:的\s*)?(?:报告|报道|研报|公告|称|表示|指出|披露|数据显示)"
                r"|(?:发布|公布|发表)的\s*(?:报告|报道|数据|研报|文章|公告))")
_SOURCE_MEDIA = r"(?:据(?:[一-龥]{0,3}媒体?)?|[一-龥]{1,3}媒体?|媒体)"
_SOURCE_DATE = re.compile(
    r"(?<![\d.])(?:\d{4}\s*年\s*)?(?:\d{1,2}|[一二三四五六七八九十]{1,3})\s*月(?:份)?"
    rf"(?=\s*(?:(?:{_SOURCE_MEDIA}\s*)?{_SOURCE_VERB}|[)\]】]\s*{_SOURCE_VERB}))"
    rf"|{_EN_MONTHS}(?=(?:['’]s)?\s+report(?:s|ed)?\b)")


def _scan_times(text: str) -> tuple:
    """返回 (时间值集合, 额外数字列表, 去掉时间表述后的文本)；已被前面规则占用的位置不再被后面的规则匹配。"""
    taken: list = []
    values: set = set()
    extra: list = []
    for pattern, handler in _TIME_RULES:
        for m in pattern.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            out = handler(m)
            if out is None:
                continue
            taken.append(m.span())
            values.update(out[0])
            extra += out[1]
    rest = list(text)
    for s, e in taken:
        rest[s:e] = " " * (e - s)
    return values, extra, "".join(rest)


class _Qty(NamedTuple):
    norm: str
    mult: float | None  # 量级倍数；None = 数字不带量级词
    value: float
    label: str
    is_year: bool
    half_unit: float = 0.0  # 按声明写到的精度，四舍五入允许的误差（已乘量级）


def _ko_split(text: str) -> str:
    def join(m):
        if m[1]:
            return str(int(m[1]) * 1000 + int(m[2] or 0) * 100 + int(m[3] or 0))
        return str(int(m[4]) * 100 + int(m[5] or 0))
    return _KO_SPLIT.sub(join, text)


def _magnitude_of(m, text: str) -> tuple:
    """_QUANTITY 匹配 → (量级倍数或 None, 量级后缀原文)。"""
    word, letter = m[2], m[3]
    if letter and letter.islower() and not (m.start() and text[m.start() - 1] in "$€£¥"):
        letter = None
    mult = _MAGNITUDE[(word or letter or "").lower()] if word or letter else None
    return mult, m[0][len(m[1]):] if mult else ""


def _arabic_quantities(text: str) -> list:
    found = [[m, *_magnitude_of(m, text)] for m in _QUANTITY.finditer(text)]
    for i in range(len(found) - 2, -1, -1):  # 60-70万：范围右端的量级词作用于左端
        cur, nxt = found[i], found[i + 1]
        if cur[1] is None and nxt[1] is not None and _RANGE_SEP.fullmatch(text[cur[0].end():nxt[0].start()]):
            cur[1:] = nxt[1:]
    out = []
    for m, mult, suffix in found:
        norm = _norm_number(m[1])
        is_year = mult is None and bool(_YEAR_NO.fullmatch(m[1])) and not _UNIT_AFTER.match(text, m.end())
        value = float(m[1].replace(",", "")) * (mult or 1)
        decimals = len(m[1].split(".")[1]) if "." in m[1] else 0
        half_unit = 0.5 * 10 ** -decimals * (mult or 1)
        out.append(_Qty(norm, mult, value, (m[1] + suffix).strip() if mult else norm, is_year, half_unit))
    return out


def _word_int(words: str) -> int:
    n = 0
    for w in re.split(r"[\s-]+", words.lower()):
        n = (n or 1) * 100 if w == "hundred" else n + (_WORD_SMALL.get(w) or _WORD_TENS.get(w, 0))
    return n


def _word_quantities(text: str) -> list:
    """英文数字词（three / twenty-five / two hundred fifty / three million）。"""
    out = []
    for m in _WORD_NUMBER.finditer(text):
        mult = _MAGNITUDE[m[1].lower()] if m[1] else None
        n = _word_int(m[0][:m.start(1) - m.start()] if m[1] else m[0])
        out.append(_Qty(str(n), mult, n * (mult or 1), m[0], False, 0.5 * (mult or 1)))
    return out


def _cn_quantities(text: str) -> list:
    out = []
    for m in _CN_QUANTITY.finditer(text):
        n = _cn_int(m[1])
        if n is not None:
            mult = _MAGNITUDE[m[2]] if m[2] else None
            out.append(_Qty(str(n), mult, n * (mult or 1), m[0], False, 0.5 * (mult or 1)))
    return out


# 量级换算本身精确；声明按自己写到的精度四舍五入（17.0 billion ≈ 170.5亿），超出半个末位单位即不同（$860.0M ≠ $859.0M）
_FLOAT_REL_EPS = 1e-9


def _near(n: _Qty, values: list) -> bool:
    return any(abs(v - n.value) <= n.half_unit + _FLOAT_REL_EPS * max(abs(v), abs(n.value)) for v in values)


def _number_found(n: _Qty, raw: set, plain: set, values: list, scaled: list) -> bool:
    if n.mult is None:  # 不带量级词的声明数字：同数字本身，或恰等于片段里带量级词的数（600,000 = 60万）
        return n.norm in raw or _near(n, scaled)
    return n.norm in plain or _near(n, values)


def _missing_numbers(claim_rest: str, claim_extra: list, quote: str, quote_extra: list) -> list:
    """声明里片段对不上的数字（标签列表）。片段没有任何年份时声明里的年份不算缺。"""
    qty = _arabic_quantities(quote) + _cn_quantities(quote) + _word_quantities(quote)
    raw = {n.norm for n in qty} | set(quote_extra)
    plain = {n.norm for n in qty if n.mult is None} | set(quote_extra)
    values = [n.value for n in qty]
    scaled = [n.value for n in qty if n.mult is not None]
    has_year = any(_YEAR_NO.fullmatch(n) for n in raw)
    extras = [_Qty(e, None, float(e), e, bool(_YEAR_NO.fullmatch(e))) for e in claim_extra]
    missing = {n.label: n for n in _arabic_quantities(claim_rest) + extras
               if not _number_found(n, raw, plain, values, scaled)}
    return [label for label, n in missing.items() if has_year or not n.is_year]


def _time_label(v: tuple) -> str:
    kind = v[0]
    if kind == "Q":
        return f"Q{v[1]}"
    if kind == "H":
        return f"{'上' if v[1] == 1 else '下'}半年(H{v[1]})"
    return f"{v[1]}月" if kind == "M" else "年底"


def _labels(values) -> str:
    return "、".join(_time_label(v) for v in sorted(values))


def check_quote(claim: str, quote: str | None) -> tuple:
    """(声明文本, 原文片段) → (是否一致, 不一致明细)；一致时明细为空串。"""
    if not quote or not quote.strip():
        return False, MISSING
    c = _ko_split(unicodedata.normalize("NFKC", claim))
    q = _ko_split(unicodedata.normalize("NFKC", quote))
    claim_times, claim_extra, claim_rest = _scan_times(_SOURCE_DATE.sub(" ", _OUTLET_NAMES.sub(" ", c)))
    quote_times, quote_extra, _ = _scan_times(q)
    missing_numbers = _missing_numbers(claim_rest, claim_extra, q, quote_extra)
    missing_times = claim_times - quote_times
    problems = []
    if missing_numbers:
        problems.append(f"数字 {'、'.join(missing_numbers)} 未见于原文片段")
    if missing_times:
        seen = f"片段中的时间表述：{_labels(quote_times)}" if quote_times else "片段中没有季度、半年、月份或年底表述"
        problems.append(f"时间表述 {_labels(missing_times)} 未见于原文片段（{seen}）")
    return (False, "；".join(problems)) if problems else (True, "")
