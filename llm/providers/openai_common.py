"""openai SDK 的公共部分（OpenAI 与智谱共用）：延迟导入、错误分类、退避判断。

openai 包延迟导入：只用 Claude 的用户即使没装 openai，也不影响 llm 层导入。
"""
from collections.abc import Collection
from types import ModuleType

from llm.keys import redact
from llm.types import LLMBlockedError, LLMConfigError, LLMError, LLMPermanentError, LLMQuotaError


def openai_sdk() -> ModuleType:
    try:
        import openai
    except ImportError as e:
        raise LLMConfigError("未安装 openai 包：请运行 pip install -r requirements.txt") from e
    return openai


async def close_client(client) -> None:
    """每次调用新建的 SDK 客户端必须在事件循环关闭前关掉，否则回收时报 Event loop is closed。"""
    close = getattr(client, "close", None)
    if close is not None:
        await close()


def is_transient(e: BaseException, permanent_codes: Collection[str] = ()) -> bool:
    """429 / 5xx / 连接与超时错误可退避重试；额度、欠费、内容拦截等错误码除外。"""
    openai = openai_sdk()
    if getattr(e, "code", None) in permanent_codes:
        return False
    return isinstance(e, (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError))


def to_llm_error(e: BaseException, label: str, key: str, quota_codes: Collection[str] = (),
                 blocked_codes: Collection[str] = ()) -> LLMError:
    """把 openai SDK 异常转成本层错误；认证类错误不带原始信息（可能回显 key 片段）。"""
    openai = openai_sdk()
    code = getattr(e, "code", None) or ""
    status = getattr(e, "status_code", "")
    tag = f"HTTP {status}" + (f" code={code}" if code else "")
    if isinstance(e, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return LLMConfigError(f"{label} API Key 无效或无权限（{tag}），请到设置页检查")
    message = redact(str(getattr(e, "message", e)), key)[:500]
    if code in quota_codes or code == "insufficient_quota":
        return LLMQuotaError(f"{label} 账户额度不足、欠费或已达使用上限（{tag}）：{message}")
    if code in blocked_codes:
        return LLMBlockedError(f"{label} 内容安全拦截（{tag}）：{message}")
    if isinstance(e, openai.NotFoundError):
        return LLMConfigError(f"{label} 不认识该模型或接口（{tag}）：{message}")
    if isinstance(e, (openai.BadRequestError, openai.UnprocessableEntityError)):
        return LLMPermanentError(f"{label} 拒绝了请求参数（{tag}）：{message}")
    if is_transient(e):
        return LLMError(f"{label} 暂时不可用（已退避重试）：{type(e).__name__} {message}")
    return LLMError(f"{label} 调用失败：{type(e).__name__} {message}")
