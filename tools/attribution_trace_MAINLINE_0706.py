"""MAINLINE attribution trace — one controlled OpenAI call, marker MAINLINE_TRACE_0706.

Resolves the API key EXACTLY as the live bot does (os.environ first, then
.env via load_dotenv without override), makes ONE chat call, and prints the
masked key fingerprint, response id, model, and token usage. Read-only
against the organism; no trading modules touched.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

pre = bool((os.environ.get("OPENAI_API_KEY") or "").strip())
load_dotenv()
key = (os.environ.get("OPENAI_API_KEY") or "").strip()
src = "OS environment (overrides .env)" if pre else ".env (no OS override present)"
print(f"key source : {src}")
print(f"key        : {key[:12]}...{key[-6:]} (len {len(key)})")

from openai import OpenAI
client = OpenAI(api_key=key, timeout=30)
resp = client.chat.completions.create(
    model=os.getenv("AI_MODEL", "gpt-4o-mini"),
    messages=[{"role": "user",
               "content": "Reply with exactly: MAINLINE_TRACE_0706"}],
    max_tokens=12,
)
print(f"response id: {resp.id}")
print(f"model      : {resp.model}")
print(f"reply      : {resp.choices[0].message.content!r}")
u = resp.usage
print(f"usage      : prompt={u.prompt_tokens} completion={u.completion_tokens} total={u.total_tokens}")
print("VERDICT    : real HTTP round-trip completed on the key above.")
