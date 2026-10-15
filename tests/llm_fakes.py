"""多模型调用层测试共用的假客户端、假响应与假错误（不发真实请求，不真等待）。"""
from types import SimpleNamespace

SECRET = "sk-test-SECRET-0123456789"


class Recorder:
    """按剧本依次返回结果或抛出异常，并记录每次调用的参数。"""

    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []
        self.closed = 0

    async def close(self) -> None:
        self.closed += 1

    def next(self, kwargs):
        self.calls.append(kwargs)
        out = self.outcomes.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out


class FakeSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def api_error(cls, status: int, code: str | None = None, message: str = "boom"):
    """构造 openai SDK 的 HTTP 错误（body 与 SDK 解包 {"error": {...}} 后的形状一致）。"""
    body = {"message": message, **({"code": code} if code else {})}
    response = SimpleNamespace(status_code=status, headers={}, request=None)
    return cls(f"Error code: {status} - {message}", response=response, body=body)


def connection_error():
    import openai
    return openai.APIConnectionError(message="connection reset", request=None)


# ── OpenAI Responses API ─────────────────────────────────────────────────────

def oa_response(text="ok", *, input_tokens=100, cached=0, output=20, reasoning=5, searches=0,
                status="completed", reason=None, refusal=None):
    content = [SimpleNamespace(type="refusal", refusal=refusal)] if refusal else \
        [SimpleNamespace(type="output_text", text=text, annotations=[])]
    items = [SimpleNamespace(type="web_search_call", action=SimpleNamespace(type="search"))
             for _ in range(searches)]
    items.append(SimpleNamespace(type="message", content=content))
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output,
                            input_tokens_details=SimpleNamespace(cached_tokens=cached),
                            output_tokens_details=SimpleNamespace(reasoning_tokens=reasoning))
    return SimpleNamespace(id="resp_1", status=status, error=None, output=items, usage=usage,
                           incomplete_details=SimpleNamespace(reason=reason) if reason else None,
                           output_text="" if refusal else text)


def oa_client(outcomes):
    rec = Recorder(outcomes)

    async def create(**kwargs):
        return rec.next(kwargs)

    return SimpleNamespace(responses=SimpleNamespace(create=create), close=rec.close), rec


# ── 智谱 chat.completions（流式）────────────────────────────────────────────

def _chunk(delta=None, finish=None, usage=None):
    choices = [SimpleNamespace(delta=delta or SimpleNamespace(content=None, tool_calls=None),
                               finish_reason=finish)]
    return SimpleNamespace(id="chat_1", choices=choices, usage=usage)


def _delta(content=None, tool_calls=None, reasoning=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls, reasoning_content=reasoning)


def _tool_deltas(calls):
    """每个工具调用拆成两段增量（名字 + 前半参数，后半参数），模拟流式拼接。"""
    first, second = [], []
    for i, (name, args) in enumerate(calls):
        half = len(args) // 2
        first.append(SimpleNamespace(index=i, id=f"call_{i}", type="function",
                                     function=SimpleNamespace(name=name, arguments=args[:half])))
        second.append(SimpleNamespace(index=i, id=None, type=None,
                                      function=SimpleNamespace(name=None, arguments=args[half:])))
    return first, second


def zp_stream(content="", tool_calls=(), finish=None, prompt=100, cached=0, completion=20):
    finish = finish or ("tool_calls" if tool_calls else "stop")
    chunks = [_chunk(_delta(reasoning="先想一想"))]
    if content:
        mid = len(content) // 2
        chunks += [_chunk(_delta(content=content[:mid])), _chunk(_delta(content=content[mid:]))]
    if tool_calls:
        first, second = _tool_deltas(tool_calls)
        chunks += [_chunk(_delta(tool_calls=first)), _chunk(_delta(tool_calls=second))]
    usage = SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=cached))
    chunks.append(_chunk(finish=finish, usage=usage))
    return chunks


def zp_client(outcomes):
    rec = Recorder(outcomes)

    async def create(**kwargs):
        chunks = rec.next(kwargs)

        async def gen():
            for c in chunks:
                yield c
        return gen()

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=rec.close), rec
