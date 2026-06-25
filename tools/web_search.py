"""
网络搜索工具 - 使用智谱 Web Search API
替代 DuckDuckGo，解决国内访问问题
"""
import json
import time
import requests
from typing import Optional


def _zhipu_search(query: str, max_results: int = 8,
                  recency_filter: str = "year") -> list:
    """
    调用智谱网络搜索 API
    返回结果列表 [{title, url, snippet}]
    recency_filter: noLimit / year / month / week / day
    """
    from config import ZHIPU_API_KEY

    headers = {
        "Authorization": f"Bearer {ZHIPU_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "search_query": query[:70],          # 最长70字符
        "search_engine": "search_std",        # 智谱基础搜索
        "count": min(max_results, 20),
        "content_size": "medium",             # medium=摘要, high=详细
        "search_recency_filter": recency_filter
    }

    resp = requests.post(
        "https://open.bigmodel.cn/api/paas/v4/web_search",
        headers=headers,
        json=payload,
        timeout=15
    )
    resp.raise_for_status()
    data = resp.json()

    results = []
    for item in data.get("search_result", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("content", "")
        })
    return results


def _auto_recency(query: str) -> str:
    """
    根据查询词自动选择时效过滤：
    - 含 after:YYYY-MM-DD 明确指定日期 → 不限（由查询词自身控制）
    - 含"历史""背景"等词 或 含6个月前的年份 → noLimit
    - 默认：year（近一年，覆盖6个月窗口）
    """
    import re
    from config import DATE_6M_AGO_ISO, PREV2_YEAR

    # 查询中已有 after: 日期过滤，交给搜索引擎处理
    if re.search(r'\bafter:\d{4}-\d{2}-\d{2}', query):
        return "noLimit"

    # 含"历史""背景"等背景类词
    bg_keywords = ["history", "origin", "background", "历史", "起源", "背景", "基础"]
    if any(k in query.lower() for k in bg_keywords):
        return "noLimit"

    # 含两年前及更早的年份
    old_years = "|".join(str(y) for y in range(2000, PREV2_YEAR + 1))
    if re.search(rf'\b({old_years})\b', query):
        return "noLimit"

    # 默认：近一年（覆盖6个月研究窗口）
    return "year"


def web_search(query: str, max_results: int = 8) -> str:
    """
    搜索网络信息，优先使用智谱 API，失败时降级到 DuckDuckGo
    返回 JSON 格式的搜索结果列表
    """
    # 优先：智谱搜索 API
    try:
        recency = _auto_recency(query)
        results = _zhipu_search(query, max_results, recency_filter=recency)
        if results:
            return json.dumps({
                "status": "success",
                "source": "zhipu",
                "query": query,
                "count": len(results),
                "results": results
            }, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [搜索] 智谱搜索失败: {str(e)[:80]}，降级到 DuckDuckGo", flush=True)

    # 降级：DuckDuckGo
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")
                })

        return json.dumps({
            "status": "success",
            "source": "duckduckgo",
            "query": query,
            "count": len(results),
            "results": results
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({
            "status": "error",
            "query": query,
            "error": str(e),
            "results": []
        }, ensure_ascii=False, indent=2)


def web_fetch(url: str, max_chars: int = 6000) -> str:
    """
    获取网页内容，提取并返回纯文本
    """
    try:
        from bs4 import BeautifulSoup

        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }

        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        if response.encoding and response.encoding.lower() not in ('utf-8', 'utf8'):
            content = response.content.decode(response.encoding, errors='replace')
        else:
            content = response.text

        soup = BeautifulSoup(content, 'html.parser')
        for tag in soup(["script", "style", "nav", "footer", "header",
                          "aside", "advertisement", "noscript"]):
            tag.decompose()

        main_content = (
            soup.find('article') or soup.find('main') or
            soup.find(id='content') or soup.find(id='main') or
            soup.find(class_='content') or soup.body or soup
        )
        text = main_content.get_text(separator='\n', strip=True) if main_content else soup.get_text(separator='\n', strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = '\n'.join(lines)

        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[内容已截断，原文共 {len(text)} 字符]"

        return f"[URL: {url}]\n\n{text}"

    except requests.exceptions.Timeout:
        return f"[错误] 请求超时: {url}"
    except requests.exceptions.HTTPError as e:
        return f"[错误] HTTP 错误 {e.response.status_code}: {url}"
    except Exception as e:
        return f"[错误] 无法获取页面内容: {url}\n原因: {str(e)}"
