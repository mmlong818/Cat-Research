"""
研究参数解析：把「用户覆盖值 + 深度档位」合并成本次任务实际生效的完整参数。
改进循环的轮数范围由 resolve_cycles 唯一决定（orchestrator 的 LoopPolicy 与参数快照共用），
快照（resolve_params）写入任务创建审计与 00_session.json，便于事后复核"这次到底按什么参数跑的"。
"""
import config as _config  # 运行时读取 _config.*（API 可在运行中修改模型与档位）
from llm.keys import CLIENT_TOOLS_PROVIDERS, selected_search_backend
from llm.profiles import Profile, default_profile


def resolve_cycles(preset: dict, min_cycles: int | None, max_cycles: int | None) -> tuple[int, int]:
    """显式传入的正整数轮数覆盖档位；最小轮数不超过最大轮数。"""
    max_eff = max_cycles if (max_cycles and max_cycles > 0) else preset["max_cycles"]
    min_eff = min(min_cycles if (min_cycles and min_cycles > 0) else preset["min_cycles"], max_eff)
    return min_eff, max_eff


def resolve_params(depth: str | None = None, language: str = "zh", min_cycles: int | None = None,
                   max_cycles: int | None = None, max_queries: int | None = None,
                   profile: Profile | None = None, ask_loop: bool = False) -> dict:
    """完整参数快照：档位预设被用户覆盖值（轮数、查询数）改写后的结果，加上语言与提供方、核心/辅助模型名、联网搜索后端。
    profile 为本次任务的模型配置档；不传时取默认配置档（设置页保存的，否则当前 config 的模型）。"""
    depth = depth or _config.DEFAULT_DEPTH
    preset = _config.DEPTH_PRESETS[depth]
    min_eff, max_eff = resolve_cycles(preset, min_cycles, max_cycles)
    profile = profile or default_profile()
    search_backend = selected_search_backend() if profile.provider in CLIENT_TOOLS_PROVIDERS else None
    return {
        "depth": depth, "language": language, "ask_loop": ask_loop,
        "min_cycles": min_eff, "max_cycles": max_eff,
        "queries": max_queries or preset["queries"],
        "supplements": preset["supplements"], "source_supplement": preset["source_supplement"],
        "verify": preset["verify"], "recheck": preset["recheck"],
        "provider": profile.provider, "core_model": profile.core, "support_model": profile.support,
        "search_backend": search_backend,  # 仅 client_tools 提供方（智谱、兼容端点）用到，其余为 None
    }
