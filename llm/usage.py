"""一次 LLMRequest 内（可能多次 API 调用）的用量与费用累计，输出为 Claude Code modelUsage 形状。"""
from dataclasses import dataclass

from llm.models import ModelSpec, cost_usd


@dataclass
class Usage:
    spec: ModelSpec
    input_tokens: int = 0      # 全部输入，含缓存命中与缓存写入
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    searches: int = 0
    fetches: int = 0
    cost: float = 0.0
    calls: int = 0

    def add_call(self, input_tokens: int, cached: int, output: int, reasoning: int = 0,
                 cache_write: int = 0, searches: int = 0) -> None:
        """记一次 API 调用；长上下文倍率按单次调用的输入量判断。"""
        self.calls += 1
        self.input_tokens += input_tokens
        self.cached_tokens += cached
        self.cache_write_tokens += cache_write
        self.output_tokens += output
        self.reasoning_tokens += reasoning
        self.searches += searches
        self.cost += cost_usd(self.spec, input_tokens, cached, output, cache_write, searches)

    def add_local_tools(self, searches: int, fetches: int, search_price: float) -> None:
        """本地工具循环里调用的搜索 API 按所选搜索后端的单价（美元/次）计费；本地抓取不计费。"""
        self.searches += searches
        self.fetches += fetches
        self.cost += searches * search_price

    def model_usage(self) -> dict:
        return {self.spec.id: {
            "inputTokens": self.input_tokens - self.cached_tokens - self.cache_write_tokens,
            "cacheReadInputTokens": self.cached_tokens,
            "cacheCreationInputTokens": self.cache_write_tokens,
            "outputTokens": self.output_tokens,
            "reasoningOutputTokens": self.reasoning_tokens,
            "webSearchRequests": self.searches,
            "webFetchRequests": self.fetches,
            "costUSD": self.cost,
        }}
