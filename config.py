"""
猫叔的深思熟虑 - 全局配置（Claude CLI 模式）
"""
import os
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


# === 网络时间（启动时从互联网获取，多重备选）===
def _fetch_network_time() -> datetime:
    """从网络获取当前时间，依次尝试多个源，失败则使用系统时间"""
    import requests
    from email.utils import parsedate_to_datetime

    # 方案1: worldtimeapi（境外可用）
    try:
        r = requests.get("http://worldtimeapi.org/api/ip", timeout=3)
        dt_str = r.json().get("datetime", "")[:19]
        return datetime.fromisoformat(dt_str)
    except Exception:
        pass

    # 方案2: 苏宁时间 API（国内可用）
    try:
        r = requests.get("https://quan.suning.com/getSysTime.do", timeout=3)
        ts = r.json().get("sysTime2", "")  # 格式: "2026-03-21 14:30:00"
        if ts:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    # 方案3: 读取 HTTP 响应头 Date 字段
    for url in ["https://www.baidu.com", "https://www.bing.com"]:
        try:
            r = requests.head(url, timeout=3)
            date_str = r.headers.get("Date", "")
            if date_str:
                return parsedate_to_datetime(date_str).replace(tzinfo=None)
        except Exception:
            pass

    # 最终备选：系统时间
    print("  [init] Network time unavailable, using system time.", flush=True)
    return datetime.now()


def _months_ago(dt: datetime, months: int) -> datetime:
    """计算 N 个月前的日期，处理月末溢出"""
    import calendar
    total_months = dt.year * 12 + (dt.month - 1) - months
    year, month = divmod(total_months, 12)
    month += 1
    max_day = calendar.monthrange(year, month)[1]
    return dt.replace(year=year, month=month, day=min(dt.day, max_day))


print("[init] Fetching current time from network...", flush=True)
CURRENT_DATETIME: datetime = _fetch_network_time()
CURRENT_DATE_STR: str    = CURRENT_DATETIME.strftime("%Y年%m月%d日")
CURRENT_DATE_ISO: str    = CURRENT_DATETIME.strftime("%Y-%m-%d")
CURRENT_YEAR: int        = CURRENT_DATETIME.year
PREV_YEAR: int           = CURRENT_YEAR - 1
PREV2_YEAR: int          = CURRENT_YEAR - 2
CURRENT_YEAR_HALF: str   = (
    f"{CURRENT_YEAR}年上半年" if CURRENT_DATETIME.month <= 6
    else f"{CURRENT_YEAR}年下半年"
)

# 精确日期窗口
DATE_3M_AGO: datetime = _months_ago(CURRENT_DATETIME, 3)
DATE_6M_AGO: datetime = _months_ago(CURRENT_DATETIME, 6)
DATE_3M_AGO_STR: str  = DATE_3M_AGO.strftime("%Y年%m月%d日")
DATE_6M_AGO_STR: str  = DATE_6M_AGO.strftime("%Y年%m月%d日")
DATE_3M_AGO_ISO: str  = DATE_3M_AGO.strftime("%Y-%m-%d")
DATE_6M_AGO_ISO: str  = DATE_6M_AGO.strftime("%Y-%m-%d")

print(f"[init] Current date : {CURRENT_DATE_STR}", flush=True)
print(f"[init] 3-month cutoff: {DATE_3M_AGO_STR}", flush=True)
print(f"[init] 6-month cutoff: {DATE_6M_AGO_STR}", flush=True)

# === 持久化设置文件（用户通过 UI 设置的模型等保存于此）===
def _resolve_user_dir() -> str:
    """打包模式用 %APPDATA%/cat-research，开发模式用项目根目录"""
    import sys as _sys
    if getattr(_sys, "frozen", False):
        if _sys.platform == "win32":
            base = os.environ.get("APPDATA") or os.path.expanduser("~")
        elif _sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Application Support")
        else:
            base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        d = os.path.join(base, "cat-research")
        os.makedirs(d, exist_ok=True)
        return d
    return os.path.dirname(__file__)

_USER_DIR = _resolve_user_dir()
_SETTINGS_FILE = os.path.join(_USER_DIR, "settings.json")

def _load_settings_file() -> dict:
    """加载 settings.json，不存在则返回空 dict"""
    if os.path.exists(_SETTINGS_FILE):
        try:
            with open(_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_settings(data: dict):
    """将设置持久化到 settings.json"""
    existing = _load_settings_file()
    existing.update(data)
    with open(_SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

# 加载持久化设置
_saved = _load_settings_file()

# === OpenAI 兼容 API 配置（智谱 GLM）===
# 供 BaseAgent / ClarifierAgent 的 OpenAI 客户端使用
API_KEY = (os.environ.get("ZHIPU_API_KEY", "")
           or os.environ.get("OPENAI_API_KEY", "")
           or _saved.get("api_key", ""))
API_BASE_URL = (os.environ.get("ZHIPU_BASE_URL", "")
                or os.environ.get("OPENAI_BASE_URL", "")
                or _saved.get("base_url", "")
                or "https://open.bigmodel.cn/api/paas/v4/")
# 向后兼容别名（web_search.py 用 ZHIPU_API_KEY 调智谱搜索 API）
ZHIPU_API_KEY = API_KEY
ZHIPU_BASE_URL = API_BASE_URL

# === 模型配置（Claude CLI）===
# 【核心模型】负责推理、规划、研究、分析、写作
CORE_MODEL = (os.environ.get("CORE_MODEL", "")
              or _saved.get("core_model", "")
              or "claude-sonnet-4-6")
ORCHESTRATOR_MODEL       = CORE_MODEL
PLANNER_MODEL            = CORE_MODEL
RESEARCHER_MODEL         = CORE_MODEL
ANALYST_MODEL            = CORE_MODEL
WRITER_MODEL             = CORE_MODEL

# 【辅助模型】负责评审、来源验证、事实核查、结论验证
SUPPORT_MODEL = (os.environ.get("SUPPORT_MODEL", "")
                 or _saved.get("support_model", "")
                 or "claude-haiku-4-5-20251001")
CRITIC_MODEL                 = SUPPORT_MODEL
SOURCE_VERIFIER_MODEL        = SUPPORT_MODEL
FACT_CHECKER_MODEL           = SUPPORT_MODEL
CONCLUSION_VALIDATOR_MODEL   = SUPPORT_MODEL

# === 工作空间配置 ===
WORKSPACE_DIR = os.path.join(_USER_DIR, "workspace")
os.makedirs(WORKSPACE_DIR, exist_ok=True)

# === 研究配置 ===
MAX_IMPROVEMENT_CYCLES = 5         # 最多改进循环次数
MIN_IMPROVEMENT_CYCLES = 2         # 强制最少2次
MAX_AGENT_TURNS = 40               # 单个智能体最大交互轮数
MAX_SEARCH_RESULTS = 8             # 每次搜索最多返回结果数
MAX_FETCH_CHARS = 6000             # 每个网页最多提取字符数
QUALITY_THRESHOLD = 8.0            # 质量阈值（满分10分），高于此值才可提前结束

# === 显示配置 ===
SHOW_AGENT_THOUGHTS = True         # 是否显示智能体工作细节
SEPARATOR = "=" * 70

# === 上下文压缩配置 ===
COMPRESS_THRESHOLD_CHARS = int(os.environ.get("COMPRESS_THRESHOLD_CHARS", "100000"))
COMPRESS_KEEP_RECENT = int(os.environ.get("COMPRESS_KEEP_RECENT", "6"))

# === 收割模式（穷举枚举型研究）配置 ===
# 枚举型任务（"汇总所有/全部事件/清单"等）时，researcher 切换为收割循环：
# 逐页抓取 → LLM 抽取结构化事件 → 去重累加进台账 → 循环至枯竭/达预算
HARVEST_MAX_PAGES = int(os.environ.get("HARVEST_MAX_PAGES", "50"))          # 每轮最多抓取页数
HARVEST_DRY_STREAK = int(os.environ.get("HARVEST_DRY_STREAK", "8"))         # 连续 N 页无新事件则停
HARVEST_RESULTS_PER_QUERY = int(os.environ.get("HARVEST_RESULTS_PER_QUERY", "12"))  # 每查询取多少结果

# === 子进程隔离配置 ===
USE_SUBPROCESS = os.environ.get("USE_SUBPROCESS", "false").lower() == "true"
SUBPROCESS_AGENTS = [a.strip() for a in os.environ.get("SUBPROCESS_AGENTS", "researcher,analyst,writer").split(",") if a.strip()]
