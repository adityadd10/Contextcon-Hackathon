"""Minimal OpenAI-compatible chat client (default: OpenRouter free models).

Every caller MUST have a rule-based fallback: free models rate-limit and go down.
`complete_json()` returns None on any failure instead of raising.

env:
  OPENROUTER_API_KEY   (or LLM_API_KEY)
  LLM_BASE_URL         default https://openrouter.ai/api/v1
  LLM_MODELS           comma-separated fallback chain, first that answers wins
  WARMPATH_LLM         set to 0 to force the rule-based fallbacks (demo: "LLM off still works")
"""
from __future__ import annotations

import json
import os
import re
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("LLM_API_KEY") or ""
MODELS = [m.strip() for m in os.getenv(
    "LLM_MODELS",
    "meta-llama/llama-3.3-70b-instruct:free,deepseek/deepseek-chat-v3-0324:free,"
    "google/gemini-2.0-flash-exp:free,mistralai/mistral-small-3.1-24b-instruct:free",
).split(",") if m.strip()]


COOLDOWN_S = 120.0          # after every model failed, skip the LLM for this long instead of re-waiting
_down_until = 0.0


def available() -> bool:
    return bool(API_KEY) and os.getenv("WARMPATH_LLM", "1") != "0" and time.monotonic() >= _down_until


async def complete(system: str, user: str, *, temperature: float = 0.2, max_tokens: int = 1200,
                   timeout: float = 20.0, deadline_s: float = 45.0) -> str | None:
    """First model in MODELS that answers wins. None if all fail or the overall deadline passes."""
    global _down_until
    if not available():
        return None
    start = time.monotonic()
    headers = {"Authorization": f"Bearer {API_KEY}", "HTTP-Referer": "https://github.com/warmpath",
               "X-Title": "WarmPath"}
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=timeout, headers=headers) as client:
        for model in MODELS:
            if time.monotonic() - start > deadline_s:
                break
            try:
                r = await client.post("/chat/completions", json={
                    "model": model, "temperature": temperature, "max_tokens": max_tokens,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                })
                if r.status_code != 200:
                    continue
                content = r.json()["choices"][0]["message"]["content"]
                if content:
                    return content
            except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
                continue
    _down_until = time.monotonic() + COOLDOWN_S
    return None


async def complete_json(system: str, user: str, **kw) -> dict | None:
    """Ask for JSON; tolerate ```json fences and leading prose. None on failure."""
    text = await complete(system + "\nRespond with ONLY a JSON object, no prose.", user, **kw)
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
