"""
ResearcherAgent - 网络研究智能体

两种模式：
- 综合模式（synthesis/agentic，默认）：依赖 BaseAgent 的工具循环，模型自主搜索/抓取/核查并综合。
- 收割模式（harvest，枚举型任务自动启用）：Python 驱动逐页抓取 → LLM 抽取结构化事件
  → 去重累加进持久化台账（events_ledger.json）→ 循环至枯竭或达页数预算。
  专为"汇总近一年所有投资事件"这类穷举枚举任务设计，事件即抽即存，不怕上下文压缩丢失。
"""
import os
import re
import json
import config as _config
from agents.base_agent import BaseAgent
from config import (RESEARCHER_MODEL, HARVEST_MAX_PAGES, HARVEST_DRY_STREAK,
                    HARVEST_RESULTS_PER_QUERY, MAX_FETCH_CHARS)
from tools.web_search import web_search, web_fetch
from tools.file_tools import write_file, read_json, write_json, _extract_json_from_text

# 触发收割模式的关键词（出现在研究问题/目标中）
_ENUM_KEYWORDS = [
    "所有", "全部", "汇总", "清单", "名单", "列举", "逐一", "逐个", "每一", "每个",
    "尽可能多", "完整的", "全面收集", "所有可查", "list all", "every", "all the",
    "enumerate", "comprehensive list", "exhaustive",
]


def _build_researcher_system_prompt() -> str:
    today   = _config.CURRENT_DATE_STR
    d3m     = _config.DATE_3M_AGO_STR
    d6m     = _config.DATE_6M_AGO_STR
    d6m_iso = _config.DATE_6M_AGO_ISO
    d3m_iso = _config.DATE_3M_AGO_ISO
    return f"""你是一位专业的全球网络研究员，擅长从互联网上收集、筛选和整理高质量的多语言信息。

## 你的职责
1. 执行搜索查询获取相关信息
2. 对有价值的链接进行深度抓取
3. 识别和筛选高质量、可靠的信息源
4. 将收集到的信息系统地整理和保存

## 时效性原则（核心）
今天是 **{today}**。研究时间窗口：**{d6m} 至今**（近6个月）。
- `[近3个月]`：{d3m} 至 {today} → 优先；`[3-6个月前]`：{d6m} 至 {d3m}；`[6个月以上]`：标注"历史参考"
- 搜索词加 "after:{d3m_iso}" / "after:{d6m_iso}" 控制时效

## 多语言原则
科技/AI 话题必须包含英文搜索；政策/经济兼顾中英文；至少覆盖中英文两个语种。

## 输出要求
将研究结果保存为结构化文件，包含：每个主题的信息摘要（注明时间）、重要数据、关键引述、来源列表（标题+URL+时间）。"""


RESEARCHER_SYSTEM_PROMPT = _build_researcher_system_prompt()


class ResearcherAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="研究员",
            system_prompt=RESEARCHER_SYSTEM_PROMPT,
            model=RESEARCHER_MODEL
        )

    # ────────────────────────────────────────────────────────────────
    # 模式分发
    # ────────────────────────────────────────────────────────────────
    def research(self, workspace: str, plan: dict, round_num: int = 1,
                 additional_queries: list = None) -> str:
        if self._is_enumeration(plan):
            print(f"  [研究员] 检测到枚举型任务 → 启用收割模式（最多 {HARVEST_MAX_PAGES} 页/轮）", flush=True)
            return self._research_harvest(workspace, plan, round_num, additional_queries)
        return self._research_agentic(workspace, plan, round_num, additional_queries)

    def _is_enumeration(self, plan: dict) -> bool:
        text = f"{plan.get('question', '')} {plan.get('objective', '')} {plan.get('expected_output', '')}"
        return any(kw in text for kw in _ENUM_KEYWORDS)

    # ────────────────────────────────────────────────────────────────
    # 收割模式
    # ────────────────────────────────────────────────────────────────
    def _research_harvest(self, workspace: str, plan: dict, round_num: int,
                          additional_queries: list = None) -> str:
        research_dir = os.path.join(workspace, "04_research")
        os.makedirs(research_dir, exist_ok=True)
        output_file = os.path.join(research_dir, f"round_{round_num}.md")
        ledger_file = os.path.join(research_dir, "events_ledger.json")

        question = plan.get("question") or plan.get("objective") or "该主题"

        # 载入已有台账（跨轮累积）
        ledger = read_json(ledger_file)
        if not isinstance(ledger, dict) or "events" not in ledger:
            ledger = {"events": [], "seen_urls": []}
        events = ledger["events"]
        seen_urls = set(ledger.get("seen_urls", []))
        index = {self._event_key(e): i for i, e in enumerate(events)}

        # 构建查询列表
        queries = [q.get("query", "") for q in plan.get("search_queries", []) if q.get("query")]
        if additional_queries:
            queries += [q if isinstance(q, str) else q.get("query", "") for q in additional_queries]
        # 去重保序
        seen_q, q_list = set(), []
        for q in queries:
            q = q.strip()
            if q and q not in seen_q:
                seen_q.add(q); q_list.append(q)

        pages = 0
        dry = 0
        new_total = 0
        start_count = len(events)

        # 查询队列（可在过程中追加实体扩展查询）
        queue = list(q_list)
        queried = set(q_list)
        expanded = False

        while queue and pages < HARVEST_MAX_PAGES and dry < HARVEST_DRY_STREAK:
            if self.stop_event and self.stop_event.is_set():
                break
            q = queue.pop(0)
            self._print_progress(f"🔍 收割搜索: {q[:60]}")
            try:
                sr = json.loads(web_search(q, max_results=HARVEST_RESULTS_PER_QUERY))
            except Exception as e:
                print(f"  [研究员] 搜索失败 '{q[:40]}': {str(e)[:80]}", flush=True)
                sr = {"results": []}

            for r in sr.get("results", []):
                if pages >= HARVEST_MAX_PAGES or dry >= HARVEST_DRY_STREAK:
                    break
                if self.stop_event and self.stop_event.is_set():
                    break
                url = (r.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                self._print_progress(f"🌐 抓取: {url[:70]}")
                page = web_fetch(url, max_chars=MAX_FETCH_CHARS)
                pages += 1
                if not page or page.startswith("[错误]") or len(page) < 200:
                    dry += 1
                    continue

                recs = self._extract_records(page, url, question)
                added = 0
                for rec in recs:
                    if not isinstance(rec, dict) or self._is_noise(rec):
                        continue
                    rec["source_url"] = rec.get("source_url") or url
                    k = self._event_key(rec)
                    if k in index:
                        # 合并补充缺失字段
                        existing = events[index[k]]
                        for f, v in rec.items():
                            if v and not existing.get(f):
                                existing[f] = v
                    else:
                        index[k] = len(events)
                        events.append(rec)
                        added += 1
                new_total += added
                dry = 0 if added > 0 else dry + 1
                self._print_progress(f"✔ 抽取 {len(recs)} 条，新增 {added}（台账共 {len(events)}）")

            # 初始查询跑完 → 实体扩展（滚雪球）：按台账高频投资方/被投企业反向补查
            if not queue and not expanded and pages < HARVEST_MAX_PAGES:
                expanded = True
                exp = self._expansion_queries(events, queried)
                if exp:
                    print(f"  [研究员] 实体扩展：追加 {len(exp)} 个投资方/企业反向查询", flush=True)
                    queue.extend(exp)
                    queried.update(exp)

        # 持久化台账
        ledger = {"events": events, "seen_urls": list(seen_urls),
                  "question": question, "last_round": round_num}
        write_json(ledger_file, ledger)

        # 从台账生成研究文件（逐条枚举）
        md = self._ledger_to_markdown(events, question, round_num, pages, new_total)
        write_file(output_file, md)
        print(f"  [研究员] 收割完成：本轮抓取 {pages} 页，新增 {len(events) - start_count} 条，"
              f"台账累计 {len(events)} 条事件", flush=True)
        return output_file

    def _extract_records(self, page_text: str, url: str, question: str) -> list:
        """用 LLM 从单页正文抽取结构化事件/条目，返回 list[dict]。"""
        prompt = f"""从以下网页正文中，抽取与研究问题相关的所有**离散事件/条目**（逐个独立列出，不要合并）。

研究问题：{question}
网页URL：{url}

网页正文：
{page_text[:5000]}

要求：
- 只抽取正文中**真实存在**的条目，不要编造、不要推测
- **地域限定：被投方必须是中国大陆企业/机构**。被投方是外国公司（如 OpenAI、Anthropic、甲骨文/Oracle、xAI、Mistral、英伟达等）的事件**一律不要抽取**，即使文中提及；但**外国机构作为投资方投资中国企业**的事件要保留
- **只抽取股权融资/投资事件**（某企业获得投资/融资、被收购、IPO）；**排除**：公司自身资本开支、财报营收、股票回购、产品发布、模型调用量、人才招聘、活动等**非投资内容**
- `entity` 必须是**被投/被投资的中国企业**；**不要**把投资方本身（如腾讯、阿里、红杉等）当作 entity；不要用"中国互联网巨头（…）"这类笼统列表
- 同一企业同一轮融资只输出**一条**（不要因金额措辞不同而重复）
- 每个独立事件一个对象，字段：
  {{"entity":"被投企业","counterparties":"投资方（逗号分隔，逐个机构名，不要写笼统列表）","amount":"金额/规模（原文）","round":"轮次/阶段/类型","date":"时间","detail":"一句话要点（目的/背景）"}}
- 字段无信息留空字符串
- 若本页没有相关投资事件，返回空数组 []

直接输出 JSON 数组，用 ```json ... ``` 包裹，不要其他文字。"""
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4000,
                temperature=0.1,
                stream=False,
            )
            text = (resp.choices[0].message.content or "").strip()
            if resp.usage:
                self._total_input_tokens += getattr(resp.usage, "prompt_tokens", 0) or 0
                self._total_output_tokens += getattr(resp.usage, "completion_tokens", 0) or 0
        except Exception as e:
            print(f"  [研究员] 抽取失败 {url[:50]}: {str(e)[:80]}", flush=True)
            return []

        data = None
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            data = _extract_json_from_text(text)
        if isinstance(data, dict):
            data = data.get("events") or data.get("items") or [data]
        return data if isinstance(data, list) else []

    # 噪音过滤：非股权投资类（不计入投资事件）
    _NOISE_ROUND = ("资本开支", "回购", "人才引进", "红包", "capex", "营收", "调用量", "支出")
    # 非中国主体标记（出现在 entity 中则判定为非中国，排除）
    _NON_CN_MARK = ("全球", "美国", "海外", "欧洲", "硅谷", "日本", "韩国", "印度", "东南亚", "国际")

    # 外国被投主体（地域过滤：研究限定中国，外国公司作为"被投方"应排除）
    _FOREIGN_ENTITY = (
        "openai", "anthropic", "oracle", "甲骨文", "xai", "mistral", "meta",
        "google", "谷歌", "microsoft", "微软", "英伟达", "nvidia", "databricks",
        "perplexity", "cohere", "ssi", "scale ai", "安全超级智能", "figure ai",
        "特斯拉", "tesla", "软银", "softbank", "amazon", "亚马逊", "apple", "苹果",
        "samsung", "三星", "stability ai",
    )

    @staticmethod
    def _norm_entity(s) -> str:
        s = re.sub(r'[（(\[【].*?[）)\]】]', '', str(s or ''))   # 去括号注释
        s = re.sub(r'[\s·,，。、/]+', '', s).lower()
        s = re.sub(r'(股份)?(有限)?(责任)?公司$|集团$|科技$|技术$|智能$|网络$|信息$', '', s)
        return s[:20]

    @staticmethod
    def _norm_round(s) -> str:
        s = re.sub(r'\s+', '', str(s or '')).lower()
        s = s.replace('战略投资', '战略').replace('战略融资', '战略')
        s = s.replace('融资', '').replace('轮', '').replace('阶段', '')
        return s[:10]

    @staticmethod
    def _event_key(e: dict) -> tuple:
        # 按 实体+轮次 归一去重（不含 amount，避免措辞差异导致重复行）
        return (ResearcherAgent._norm_entity(e.get("entity")),
                ResearcherAgent._norm_round(e.get("round")))

    @classmethod
    def _is_noise(cls, e: dict) -> bool:
        ent = (e.get("entity") or "").strip()
        if not ent:
            return True
        blob = f"{e.get('round','')}{e.get('detail','')}"
        if any(kw in blob for kw in cls._NOISE_ROUND):
            return True
        # 地域过滤：被投方是外国公司 / 非中国主体 → 排除（外国机构作为投资方不受影响）
        ent_l = ent.lower()
        if any(f in ent_l for f in cls._FOREIGN_ENTITY):
            return True
        if any(m in ent for m in cls._NON_CN_MARK):
            return True
        return False

    @staticmethod
    def _ledger_to_markdown(events: list, question: str, round_num: int,
                            pages: int, new_total: int) -> str:
        lines = [
            f"# 研究结果（收割模式）- 第{round_num}轮",
            f"## 研究问题：{question}",
            f"> 本轮抓取 {pages} 页，台账累计 **{len(events)}** 条事件",
            "",
            "## 事件台账（逐条枚举）",
            "",
            "| # | 主体 | 相关方 | 金额/规模 | 轮次/类型 | 时间 | 要点 | 来源 |",
            "|---|------|--------|-----------|-----------|------|------|------|",
        ]
        for i, e in enumerate(events, 1):
            cells = [
                str(i),
                (e.get("entity") or "").replace("|", "/"),
                (e.get("counterparties") or "").replace("|", "/"),
                (e.get("amount") or "").replace("|", "/"),
                (e.get("round") or "").replace("|", "/"),
                (e.get("date") or "").replace("|", "/"),
                (e.get("detail") or "").replace("|", "/")[:80],
                (e.get("source_url") or "").replace("|", "/"),
            ]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
        lines.append("## 来源列表")
        seen = set()
        for e in events:
            u = e.get("source_url") or ""
            if u and u not in seen:
                seen.add(u)
                lines.append(f"- {u}")
        return "\n".join(lines) + "\n"

    _INV_ALIAS = {
        "阿里巴巴": "阿里", "阿里巴巴集团": "阿里", "阿里云": "阿里",
        "腾讯投资": "腾讯", "腾讯控股": "腾讯",
        "字节": "字节跳动", "百度风投": "百度", "京东集团": "京东",
        "红杉中国": "红杉", "红杉资本": "红杉", "高瓴资本": "高瓴", "高瓴创投": "高瓴",
        "IDG资本": "IDG", "深创投": "深圳创投",
    }
    _INV_SKIP = {"等", "老股东", "战略投资方", "产业资本", "未公开", "未披露",
                 "其他", "多家机构", "多家", "多家投资方", "若干", "未知"}

    @staticmethod
    def _split_parties(s) -> list:
        parts = re.split(r'[,，、/；;]+', str(s or ''))
        out = []
        for p in parts:
            p = p.strip()
            if not p or len(p) < 2:
                continue
            if "巨头" in p or len(p) > 16:   # 跳过"中国互联网巨头（…）"这类列表 blob
                continue
            p = ResearcherAgent._INV_ALIAS.get(p, p)
            if p in ResearcherAgent._INV_SKIP:
                continue
            out.append(p)
        return out

    def _expansion_queries(self, events: list, queried: set) -> list:
        """从台账高频投资方反向生成"投资方→被投"查询（滚雪球扩展覆盖）"""
        from collections import Counter
        inv = Counter()
        for e in events:
            for p in self._split_parties(e.get("counterparties")):
                inv[p] += 1
        skip = {"等", "老股东", "战略投资方", "产业资本", "未公开", "未披露", "其他", "多家机构"}
        out = []
        for name, _ in inv.most_common(20):
            if name in skip or len(name) < 2:
                continue
            q = f"{name} 投资 人工智能 AI 2026 融资 被投企业"
            if q not in queried:
                out.append(q)
        return out[:15]

    # ────────────────────────────────────────────────────────────────
    # 综合/agentic 模式（普通话题，依赖 BaseAgent 工具循环）
    # ────────────────────────────────────────────────────────────────
    def _research_agentic(self, workspace: str, plan: dict, round_num: int,
                          additional_queries: list = None) -> str:
        research_dir = os.path.join(workspace, "04_research")
        os.makedirs(research_dir, exist_ok=True)
        output_file = os.path.join(research_dir, f"round_{round_num}.md")
        summary_file = os.path.join(research_dir, "research_summary.md")

        queries = plan.get("search_queries", [])
        if additional_queries:
            for q in additional_queries:
                queries.append({"query": q, "purpose": "补充研究", "priority": "high", "category": "补充"})

        if round_num == 1:
            exec_queries = [q for q in queries if q.get("priority") in ("high", "medium")][:12]
        else:
            exec_queries = queries[-8:]

        from tools.verification_registry import load_registry, add_executed_query, save_registry
        registry = load_registry(workspace)
        executed = set(registry.get("executed_queries", []))

        original_count = len(exec_queries)
        exec_queries = [q for q in exec_queries if q.get("query", "").strip() not in executed]
        skipped = original_count - len(exec_queries)
        if skipped > 0:
            print(f"  [研究员] 跳过 {skipped} 个已执行的查询，执行 {len(exec_queries)} 个新查询", flush=True)

        if not exec_queries:
            print(f"  [研究员] 所有查询均已执行，跳过本轮研究", flush=True)
            return output_file

        skip_note = (f"\n\n注意：{skipped} 个查询在前轮已执行，已跳过，专注于以上 {len(exec_queries)} 个新查询。"
                     if skipped > 0 else "")
        queries_text = json.dumps(exec_queries, ensure_ascii=False, indent=2)

        task = f"""【今天 {_config.CURRENT_DATE_STR}｜优先层：{_config.DATE_3M_AGO_STR} 至今｜补充层：{_config.DATE_6M_AGO_STR} 至 {_config.DATE_3M_AGO_STR}｜超出6个月需标注"历史参考"】

请执行以下研究任务，深入收集关于"{plan.get('question', '该主题')}"的信息。

## 研究目标
{plan.get('objective', '深入研究该主题')}

## 需要执行的搜索查询（第 {round_num} 轮）
{queries_text}

## 执行步骤
1. 对每个搜索查询使用 web_search 工具进行搜索
2. 从搜索结果中选择最有价值的 3-5 个链接，使用 web_fetch 工具获取详细内容
3. 整理所有收集到的信息
4. 将完整研究结果以 Markdown 格式保存到：{output_file}
5. 将研究摘要（最重要的发现）保存到：{summary_file}

注意：必须实际执行搜索并获取页面内容，不要捏造信息！{skip_note}"""

        self.run(task)

        for q in exec_queries:
            add_executed_query(registry, q.get("query", ""))
        save_registry(workspace, registry)

        return output_file


# ────────────────────────────────────────────────────────────────────
# 从事件台账确定性生成报告附录（保证报告 100% 覆盖台账，不依赖 LLM 自觉）
# ────────────────────────────────────────────────────────────────────
def build_ledger_appendix(workspace: str) -> str:
    """读取 events_ledger.json，生成「投资事件全表」+「投资方汇总表」Markdown。无台账则返回空串。"""
    import os
    from collections import defaultdict
    from tools.file_tools import read_json

    led = read_json(os.path.join(workspace, "04_research", "events_ledger.json"))
    if not isinstance(led, dict):
        return ""
    events = led.get("events", [])
    if not events:
        return ""

    def esc(s):
        return str(s or "").replace("|", "/").replace("\n", " ")

    lines = [f"\n\n---\n## 附录A：投资事件全表（共 {len(events)} 条，自动汇编自研究台账，无遗漏）\n",
             "| # | 被投企业 | 投资方 | 金额/规模 | 轮次 | 时间 | 要点 | 来源 |",
             "|---|---------|--------|-----------|------|------|------|------|"]
    for i, e in enumerate(events, 1):
        lines.append("| " + " | ".join([
            str(i), esc(e.get("entity")), esc(e.get("counterparties")),
            esc(e.get("amount")), esc(e.get("round")), esc(e.get("date")),
            esc(e.get("detail"))[:80], esc(e.get("source_url")),
        ]) + " |")

    roll = defaultdict(list)
    for e in events:
        ent = e.get("entity") or ""
        for p in ResearcherAgent._split_parties(e.get("counterparties")):
            if ent:
                roll[p].append(ent)
    lines.append(f"\n## 附录B：投资方汇总（共 {len(roll)} 个，按出手次数排序）\n")
    lines.append("| 投资方 | 出手次数 | 投资标的 |")
    lines.append("|--------|---------|---------|")
    for inv, ents in sorted(roll.items(), key=lambda x: -len(x[1])):
        uniq = list(dict.fromkeys(ents))
        lines.append(f"| {esc(inv)} | {len(uniq)} | {esc('、'.join(uniq))[:200]} |")

    return "\n".join(lines) + "\n"
