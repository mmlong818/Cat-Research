"""
路径解析：开发模式用项目根目录，PyInstaller 打包模式用用户可写目录
"""
import os
import sys

_FROZEN = getattr(sys, "frozen", False)


def _user_data_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "cat-research")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~/Library/Application Support"), "cat-research")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "cat-research")


def project_root() -> str:
    """开发模式 = 源码根；打包模式 = 用户数据目录（可写）"""
    if _FROZEN:
        d = _user_data_dir()
        os.makedirs(d, exist_ok=True)
        return d
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_path(*parts: str) -> str:
    p = os.path.join(project_root(), *parts)
    os.makedirs(os.path.dirname(p) if os.path.splitext(p)[1] else p, exist_ok=True)
    return p
