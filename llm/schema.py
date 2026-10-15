"""结构化输出的通用处理：strict 化 schema、写进提示词、从文本解析 JSON、本地 jsonschema 校验。"""
import json
from typing import Any

from jsonschema import Draft202012Validator

MAX_REPAIRS = 2  # 提示词约束模式下，校验失败后带错误信息重试的次数


def strict_schema(schema: Any) -> Any:
    """每个 object 显式 additionalProperties: false；返回副本，不改调用方的 schema。"""
    if isinstance(schema, list):
        return [strict_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: strict_schema(v) for k, v in schema.items()}
    if out.get("type") == "object":
        out.setdefault("additionalProperties", False)
    return out


def all_required(schema: Any) -> bool:
    """OpenAI strict 模式要求每个 object 的全部属性都列入 required。"""
    if isinstance(schema, list):
        return all(all_required(s) for s in schema)
    if not isinstance(schema, dict):
        return True
    if schema.get("type") == "object" and set(schema.get("properties", {})) - set(schema.get("required", [])):
        return False
    return all(all_required(v) for v in schema.values())


def schema_instruction(schema: dict) -> str:
    return ("\n\n## 输出格式（必须遵守）\n只输出一个 JSON 对象：不要输出任何其他文字，不要用 Markdown 代码块包裹。"
            "该 JSON 必须符合以下 JSON Schema：\n" + json.dumps(schema, ensure_ascii=False))


def repair_instruction(problem: str) -> str:
    return (f"你上一条回复不符合输出要求：{problem}\n"
            "请重新给出完整答案：只输出一个符合 JSON Schema 的 JSON 对象，不要输出其他内容。")


def parse_json(text: str) -> Any:
    """从模型文本中取出 JSON 对象（容忍代码块包裹与前后多余文字）；失败抛 ValueError。"""
    s = text.strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("回复中没有 JSON 对象")
    try:
        return json.loads(s[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败：{e}") from e


def schema_errors(data: Any, schema: dict, limit: int = 5) -> list[str]:
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
    return [f"{'/'.join(map(str, e.path)) or '(根)'}: {e.message}" for e in errors[:limit]]


def parse_valid(text: str, schema: dict) -> Any:
    """解析并校验；不合格抛 ValueError（信息可直接反馈给模型）。"""
    data = parse_json(text)
    problems = schema_errors(data, schema)
    if problems:
        raise ValueError("JSON 不符合 schema：" + "；".join(problems))
    return data
