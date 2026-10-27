"""Check that Nightshift is running and that the agent can talk to it.

Never prints the token. Usage: python check_nightshift.py
"""
import os
import sys
import urllib.request

from dotenv import load_dotenv

load_dotenv()

from llm import DEFAULT_BASE_URL, DEFAULT_MODEL, nightshift_token  # noqa: E402

base = os.getenv("NIGHTSHIFT_BASE_URL", DEFAULT_BASE_URL)
model = os.getenv("NIGHTSHIFT_MODEL", DEFAULT_MODEL)
ok = True


def step(name, fn):
    global ok
    try:
        detail = fn()
        print(f"[PASS] {name}" + (f": {detail}" if detail else ""))
    except Exception as exc:
        ok = False
        print(f"[FAIL] {name}: {exc}")


def health():
    root = base.rsplit("/v1", 1)[0]
    with urllib.request.urlopen(root + "/healthz", timeout=5) as r:
        return f"HTTP {r.status}"


def token():
    nightshift_token()
    return "found (not shown)"


def models():
    from openai import OpenAI
    client = OpenAI(base_url=base, api_key=nightshift_token(), timeout=30)
    ids = [m.id for m in client.models.list().data]
    return ", ".join(ids[:15]) + (" ..." if len(ids) > 15 else "")


def chat():
    from openai import OpenAI
    client = OpenAI(base_url=base, api_key=nightshift_token(), timeout=180)
    res = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": "Say hello in five words."}])
    return f"model={res.model!r} reply={res.choices[0].message.content.strip()[:80]!r}"


print(f"Nightshift at {base}, model {model}")
step("Runtime is up (/healthz)", health)
step("Runtime token", token)
step("Models listed", models)
step("Chat request", chat)
print("\nAll good: set LLM_MODE=nightshift in .env" if ok else "\nFix the FAIL lines above.")
sys.exit(0 if ok else 1)
