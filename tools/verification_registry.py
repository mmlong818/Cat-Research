"""
verification_registry.py - 跨轮次验证注册表
已验证的来源、已执行的查询存入此文件（声明见 research/ledger.py），后续步骤直接跳过已验证内容。
注册表路径：{workspace}/08_verification/verified_registry.json
"""
import json
import os
from datetime import datetime

from tools.file_tools import ensure_parent_dir

_REGISTRY_FILENAME = os.path.join("08_verification", "verified_registry.json")

def _registry_path(workspace: str) -> str:
    return os.path.join(workspace, _REGISTRY_FILENAME)

def load_registry(workspace: str) -> dict:
    """加载注册表，不存在则返回空注册表"""
    path = _registry_path(workspace)
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):  # 文件不可读或 JSON 损坏时回退为空注册表
            pass
    return {
        "verified_sources": {},     # url -> {score, tier, confidence_level, cycle}
        "executed_queries": [],     # [query_str, ...]
        "created_at": datetime.now().isoformat()
    }

def save_registry(workspace: str, registry: dict):
    """保存注册表"""
    path = _registry_path(workspace)
    ensure_parent_dir(path)
    registry["updated_at"] = datetime.now().isoformat()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)

# ── 来源 ──
def is_source_verified(registry: dict, url: str) -> bool:
    return url in registry.get("verified_sources", {})

def add_source_result(registry: dict, url: str, result: dict, cycle: int = 0):
    registry.setdefault("verified_sources", {})[url] = {
        **result, "cycle": cycle, "verified_at": datetime.now().isoformat()
    }

# ── 查询 ──
def is_query_executed(registry: dict, query: str) -> bool:
    return query.strip() in registry.get("executed_queries", [])

def add_executed_query(registry: dict, query: str):
    q = query.strip()
    if q and q not in registry.get("executed_queries", []):
        registry.setdefault("executed_queries", []).append(q)

def get_executed_queries(registry: dict) -> list:
    return registry.get("executed_queries", [])
