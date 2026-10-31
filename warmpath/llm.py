"""Minimal OpenAI-compatible chat client (default: OpenRouter free models).

Every caller MUST have a rule-based fallback: free models rate-limit and go down.
`complete_json()` returns None on any failure instead of raising.

env:
  OPENROUTER_API_KEY   (or LLM_API_KEY)
  LLM_BASE_URL         default https://openrouter.ai/api/v1
  LLM_MODELS           comma-separated fallback chain, first that answers wins
  LLM_MAX_CALLS        network calls allowed per process, default 6 (free tier = 50 requests/day per key)
  WARMPATH_LLM         set to 0 to force the rule-based fallbacks (demo: "LLM off still works")

429 → try the next model; 403 → skip that model for the rest of the process. Answers are cached in memory by
(system, user), so a re-run of the same request costs no LLM calls.
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
    # verified 31 Oct 11:55 (docs/UPDATES.md)
    "nvidia/nemotron-3-ultra-550b-a55b:free,google/gemma-4-31b-it:free,nvidia/nemotron-3.5-lightning:free,"
    "google/gemma-4-26b-a4b-it:free",
).split(",") if m.strip()]
MAX_CALLS = int(os.getenv("LLM_MAX_CALLS", "6"))
COOLDOWN_S = 120.0          # after every model failed, skip the LLM for this long instead of re-waiting

_down_until = 0.0
_calls = 0
_blocked: set[str] = set()  # models that answered 403: not usable with this key
_cache: dict[tuple[str, str], str] = {}


def available() -> bool:
    return (bool(API_KEY) and os.getenv("WARMPATH_LLM", "1") != "0" and time.monotonic() >= _down_until
            and _calls < MAX_CALLS)


def calls_used() -> int:
    return _calls


async def complete(system: str, user: str, *, temperature: float = 0.2, max_tokens: int = 1200,
                   timeout: float = 20.0, deadline_s: float = 45.0) -> str | None:
    """First model in MODELS that answers wins. None if all fail, the cap is hit or the deadline passes."""
    global _down_until, _calls
    if (system, user) in _cache:
        return _cache[(system, user)]
    if not available():
        return None
    start = time.monotonic()
    headers = {"Authorization": f"Bearer {API_KEY}", "HTTP-Referer": "https://github.com/warmpath",
               "X-Title": "WarmPath"}
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=timeout, headers=headers) as client:
        for model in MODELS:
            if model in _blocked:
                continue
            if time.monotonic() - start > deadline_s or _calls >= MAX_CALLS:
                break
            _calls += 1
            try:
                r = await client.post("/chat/completions", json={
                    "model": model, "temperature": temperature, "max_tokens": max_tokens,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                })
                if r.status_code == 403:
                    _blocked.add(model)
                if r.status_code != 200:   # 429 / 5xx / 403: next model
                    continue
                content = r.json()["choices"][0]["message"]["content"]
                if content:
                    _cache[(system, user)] = content
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
