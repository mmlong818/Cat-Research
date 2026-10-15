"""
猫叔的深思熟虑 - 全局配置（Claude CLI 模式）
"""
import json
import os
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()


# === 当前日期（用于提示词中的时效窗口）===
def _months_ago(dt: datetime, months: int) -> datetime:
    """计算 N 个月前的日期，处理月末溢出"""
    import calendar
    total_months = dt.year * 12 + (dt.month - 1) - months
    year, month = divmod(total_months, 12)
    month += 1
    max_day = calendar.monthrange(year, month)[1]
    return dt.replace(year=year, month=month, day=min(dt.day, max_day))


CURRENT_DATETIME: datetime = datetime.now()
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

# === 持久化设置文件（用户通过 UI 设置的模型等保存于此）===
_SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

def _load_settings_file() -> dict:
    """加载 settings.json，不存在则返回空 dict"""
    if os.path.exists(_SETTINGS_FILE):
        try:
            with open(_SETTINGS_FILE, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):  # 文件不可读或 JSON 损坏时回退为空设置
            pass
    return {}

# 加载持久化设置
_saved = _load_settings_file()

# === 模型配置（Claude CLI）===
# 【核心模型】负责推理、规划、研究、分析、写作
CORE_MODEL = (os.environ.get("CORE_MODEL", "")
              or _saved.get("core_model", "")
              or "claude-opus-5-5")
ORCHESTRATOR_MODEL       = CORE_MODEL
PLANNER_MODEL            = CORE_MODEL
RESEARCHER_MODEL         = CORE_MODEL
ANALYST_MODEL            = CORE_MODEL
WRITER_MODEL             = CORE_MODEL

# 【辅助模型】负责评审、来源验证、事实核查、结论验证
SUPPORT_MODEL = (os.environ.get("SUPPORT_MODEL", "")
                 or _saved.get("support_model", "")
                 or "claude-sonnet-5-5")
CRITIC_MODEL                 = SUPPORT_MODEL
SOURCE_VERIFIER_MODEL        = SUPPORT_MODEL
FACT_CHECKER_MODEL           = SUPPORT_MODEL
CONCLUSION_VALIDATOR_MODEL   = SUPPORT_MODEL

# === 工作空间配置 ===
WORKSPACE_DIR = os.path.join(os.path.dirname(__file__), "workspace")

# === 研究配置 ===
# 研究深度分档：规划查询数、评审轮数范围、循环内补充研究次数上限、来源质量差时是否补充研究、事实核查的声明条数、
# 改进循环中对最优稿承重声明（被引用最多、未核查、本应有一手记录）的补核条数
DEFAULT_DEPTH = "standard"
DEPTH_PRESETS = {
    "quick":    {"queries": 6,  "min_cycles": 1, "max_cycles": 1, "supplements": 0, "source_supplement": False,
                 "verify": 8, "recheck": 0},
    "standard": {"queries": 10, "min_cycles": 2, "max_cycles": 3, "supplements": 2, "source_supplement": True,
                 "verify": 12, "recheck": 3},
    "deep":     {"queries": 15, "min_cycles": 2, "max_cycles": 5, "supplements": 3, "source_supplement": True,
                 "verify": 16, "recheck": 5},
}
QUALITY_THRESHOLD = 8.0            # 评审分达到此值（且结论验证达标）才可提前结束
CONCLUSION_THRESHOLD = 7.5         # 结论验证平均分达标线
NO_GAIN_PATIENCE = 1               # 连续多少轮评审分未超过最优分即停止
