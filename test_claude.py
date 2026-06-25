import shutil, subprocess, json

CLAUDE = shutil.which("claude")

def call_claude_json_inline(instructions_and_prompt: str, timeout: int = 60) -> str:
    """Instructions fully embedded in prompt, no --append-system-prompt."""
    cmd = [
        CLAUDE, "-p", instructions_and_prompt,
        "--output-format", "json",
        "--max-turns", "1",
        "--dangerously-skip-permissions",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"rc={r.returncode} | {r.stdout[:100]}")
    wrapper = json.loads(r.stdout)
    result_text = wrapper.get("result", "").strip()
    if result_text.startswith("```"):
        parts = result_text.split("```")
        result_text = parts[1] if len(parts) > 1 else result_text
        if result_text.startswith("json"):
            result_text = result_text[4:]
    return result_text.strip()


# Test intent - fully inline prompt
intent_prompt = """You are an intent clarification AI. Output ONLY valid JSON, no other text.

JSON schema (fill in the values):
{
  "text": "<your reply to the user in Chinese>",
  "guesses": [{"text": "<intent guess in Chinese>", "confidence": <0-100>}],
  "questions": [{"id": "q1", "text": "<follow-up question>", "options": [{"id": "opt1", "text": "<option>"}, {"id": "other", "text": "其他..."}]}],
  "profile": {"context": "<user context>", "painPoint": "<pain point>", "desiredOutcome": "<desired outcome>", "constraints": [], "confidence": <0-100>, "keywords": []},
  "shouldCrystallize": false
}

User message: 我想写一份项目报告但不知道从哪开始

Respond with ONLY the JSON. No explanation, no markdown fences."""

try:
    raw = call_claude_json_inline(intent_prompt)
    data = json.loads(raw)
    print("INTENT OK")
    print("  text:", data.get("text", "")[:60])
    print("  guesses:", len(data.get("guesses", [])))
    print("  confidence:", data.get("profile", {}).get("confidence"))
    print("  shouldCrystallize:", data.get("shouldCrystallize"))
except Exception as e:
    print("INTENT FAIL:", type(e).__name__, str(e)[:100])
    try:
        print("  raw:", repr(raw[:200]))
    except:
        pass

# Test expand - fully inline prompt
expand_prompt = """You are a lateral thinking expert. Output ONLY a valid JSON array, no other text.

Required format (3 items):
[
  {
    "id": "<unique string>",
    "title": "<10 chars max title in Chinese>",
    "description": "<50-100 char description in Chinese>",
    "dimension": "<one of: 文化参考维度|跨行业类比维度|人物角色维度|时间维度|反向思考维度>",
    "creativityScore": <1-10>,
    "feasibilityScore": <1-10>,
    "keywords": ["<keyword1>", "<keyword2>"]
  }
]

Topic: 提高远程团队协作效率

Respond with ONLY the JSON array. No explanation, no markdown fences."""

try:
    raw2 = call_claude_json_inline(expand_prompt)
    data2 = json.loads(raw2)
    print("\nEXPAND OK - count:", len(data2))
    if data2:
        print("  first keys:", list(data2[0].keys()))
        print("  first title:", data2[0].get("title", ""))
        print("  first dimension:", data2[0].get("dimension", ""))
except Exception as e:
    print("EXPAND FAIL:", type(e).__name__, str(e)[:100])
    try:
        print("  raw:", repr(raw2[:300]))
    except:
        pass
