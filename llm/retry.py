"""限流/服务端暂时故障的退避重试（5/15/30 秒 + 抖动）。sleep 可注入，测试不真等。"""
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")
Sleep = Callable[[float], Awaitable[None]]
BACKOFF_SECONDS = (5, 15, 30)


async def with_backoff(fn: Callable[[], Awaitable[T]], retryable: Callable[[BaseException], bool],
                       sleep: Sleep, label: str) -> T:
    """执行 fn；可重试的异常按 BACKOFF_SECONDS 退避后重来，用尽或不可重试时原样抛出。"""
    for delay in (*BACKOFF_SECONDS, None):
        try:
            return await fn()
        except Exception as e:
            if delay is None or not retryable(e):
                raise
            wait = delay + random.uniform(0, delay * 0.2)
            print(f"  [llm] {label} 暂时不可用（{type(e).__name__}），{wait:.0f}s 后重试", flush=True)
            await sleep(wait)
    raise AssertionError("unreachable")
