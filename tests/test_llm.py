import asyncio

import httpx

from warmpath import llm


def test_kill_switch_and_cooldown(monkeypatch):
    monkeypatch.setattr(llm, "API_KEY", "k")
    monkeypatch.setattr(llm, "_down_until", 0.0)
    assert llm.available()
    monkeypatch.setenv("WARMPATH_LLM", "0")
    assert not llm.available()
    monkeypatch.delenv("WARMPATH_LLM")

    calls = []

    async def boom(self, *a, **k):
        calls.append(1)
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    assert asyncio.run(llm.complete("s", "u")) is None
    assert len(calls) == len(llm.MODELS)             # tried each model once
    assert not llm.available()                         # then cools down instead of re-waiting
    assert asyncio.run(llm.complete_json("s", "u")) is None and len(calls) == len(llm.MODELS)


def test_complete_json_tolerates_fences(monkeypatch):
    async def fenced(*a, **k):
        return 'Sure!\n```json\n{"company": "Swiggy"}\n```'
    monkeypatch.setattr(llm, "complete", fenced)
    assert asyncio.run(llm.complete_json("s", "u")) == {"company": "Swiggy"}
