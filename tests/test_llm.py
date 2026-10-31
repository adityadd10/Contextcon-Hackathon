import asyncio

import httpx
import pytest

from warmpath import llm


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(llm, "API_KEY", "k")
    monkeypatch.setattr(llm, "MODELS", ["m1", "m2", "m3"])
    monkeypatch.setattr(llm, "MAX_CALLS", 6)
    monkeypatch.setattr(llm, "_down_until", 0.0)
    monkeypatch.setattr(llm, "_calls", 0)
    monkeypatch.setattr(llm, "_blocked", set())
    monkeypatch.setattr(llm, "_cache", {})
    monkeypatch.delenv("WARMPATH_LLM", raising=False)


def _server(monkeypatch, answers):
    """Fake OpenRouter: answers[model] = status code, or a string to return as content."""
    seen = []

    async def post(self, url, json):
        seen.append(json["model"])
        a = answers.get(json["model"], 500)
        if isinstance(a, str):
            return httpx.Response(200, json={"choices": [{"message": {"content": a}}]})
        return httpx.Response(a, json={})
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    return seen


def test_kill_switch():
    assert llm.available()
    import os
    os.environ["WARMPATH_LLM"] = "0"
    try:
        assert not llm.available()
    finally:
        del os.environ["WARMPATH_LLM"]


def test_outage_tries_each_model_once_then_cools_down(monkeypatch):
    calls = []

    async def boom(self, *a, **k):
        calls.append(1)
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    assert asyncio.run(llm.complete("s", "u")) is None
    assert len(calls) == 3 and not llm.available()
    assert asyncio.run(llm.complete_json("s", "u2")) is None and len(calls) == 3


def test_429_falls_through_403_is_remembered(monkeypatch):
    seen = _server(monkeypatch, {"m1": 403, "m2": 429, "m3": "hello"})
    assert asyncio.run(llm.complete("s", "a")) == "hello"
    assert asyncio.run(llm.complete("s", "b")) == "hello"
    assert seen == ["m1", "m2", "m3", "m2", "m3"]          # m1 (403) never retried


def test_cache_and_call_cap(monkeypatch):
    monkeypatch.setattr(llm, "MAX_CALLS", 2)
    seen = _server(monkeypatch, {"m1": "ok"})
    assert asyncio.run(llm.complete("s", "a")) == "ok"
    assert asyncio.run(llm.complete("s", "a")) == "ok" and len(seen) == 1   # cached, free
    assert asyncio.run(llm.complete("s", "b")) == "ok" and llm.calls_used() == 2
    assert not llm.available() and asyncio.run(llm.complete("s", "c")) is None and len(seen) == 2


def test_complete_json_tolerates_fences(monkeypatch):
    async def fenced(*a, **k):
        return 'Sure!\n```json\n{"company": "Swiggy"}\n```'
    monkeypatch.setattr(llm, "complete", fenced)
    assert asyncio.run(llm.complete_json("s", "u")) == {"company": "Swiggy"}
