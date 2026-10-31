"""Web UI + API: uv run uvicorn warmpath.server:app --reload  →  http://localhost:8000   Owner: Member C.

GET /                         single-page UI (static/index.html)
GET /api/run?q=...            SSE stream of pipeline events (PLAN §6); &mock=1 replays fixtures/mock_events.jsonl
GET /api/crawl?seeds=a,b      SSE stream of crawl events (&depth=1&budget=80)
GET /api/graph/stats          node/edge counts
GET /api/graph/subgraph       ?center=person:123&depth=2 (omit center for the whole recent graph)
GET /api/graph/path?a=1&b=2   strongest chain between two people, with every hop's tie + evidence
GET /api/graph/tie?a=1&b=2    one KNOWS edge explained: factors, overlaps, citations
GET /api/graph/brokers        super-connectors (betweenness)
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from .graphdb import GraphStore
from .models import to_dict
from .score import score_tie

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MOCK = ROOT.parent / "fixtures" / "mock_events.jsonl"
MOCK_DELAY = float(os.getenv("WARMPATH_MOCK_DELAY", "0.25"))

app = FastAPI(title="WarmPath")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


async def _stream(job: Callable[[Callable[[dict], None]], Awaitable[object]]) -> AsyncIterator[str]:
    """Run `job(emit)` in the background and yield each emitted event as an SSE frame."""
    q: asyncio.Queue[dict | None] = asyncio.Queue()

    async def runner() -> None:
        try:
            await job(q.put_nowait)
        except Exception as e:  # surface failures to the UI instead of a silent dead stream
            q.put_nowait({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            q.put_nowait(None)

    task = asyncio.create_task(runner())
    try:
        while (e := await q.get()) is not None:
            yield _sse(e)
        yield _sse({"type": "end"})
    finally:
        task.cancel()  # client went away → stop spending credits


def _sse_response(gen: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"cache-control": "no-cache", "x-accel-buffering": "no"})


async def _replay(emit: Callable[[dict], None]) -> None:
    for line in MOCK.read_text().splitlines():
        if line.strip():
            emit(json.loads(line))
            await asyncio.sleep(MOCK_DELAY)


# ------------------------------------------------------------------ pages

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "fake": os.getenv("WARMPATH_FAKE") == "1",
            "live_key": bool(os.getenv("CRUSTDATA_API_KEY")), "mock_available": MOCK.exists()}


# ------------------------------------------------------------------ streams

@app.get("/api/run")
async def api_run(q: str = Query("", max_length=2000), mock: bool = False) -> StreamingResponse:
    if mock:
        return _sse_response(_stream(_replay))
    if not q.strip():
        raise HTTPException(400, "q is required")
    from .pipeline import run
    return _sse_response(_stream(lambda emit: run(q.strip(), emit)))


@app.get("/api/crawl")
async def api_crawl(seeds: str = "", depth: int = Query(1, ge=1, le=3),
                    budget: float = Query(80, gt=0, le=1000)) -> StreamingResponse:
    urls = [u.strip() for u in (seeds or os.getenv("WARMPATH_SEEDS", "")).split(",") if u.strip()]
    if not urls:
        raise HTTPException(400, "give seeds=<profile_url>,<profile_url> or set WARMPATH_SEEDS")

    async def job(emit: Callable[[dict], None]) -> None:
        from .crawl import crawl
        from .crust import Crust
        g = GraphStore()
        try:
            async with Crust(budget=budget) as c:
                stats = await crawl(c, g, urls, depth=depth, emit=emit)
                emit({"type": "graph", "stats": stats})
                emit({"type": "done", "result": {"stats": stats, "credits_used": round(c.credits_used, 2),
                                                 "audit": to_dict(c.audit)}})
        finally:
            g.close()

    return _sse_response(_stream(job))


# ------------------------------------------------------------------ graph explorer

def _graph() -> GraphStore:
    return GraphStore()


@app.get("/api/graph/stats")
def graph_stats() -> dict:
    g = _graph()
    try:
        return g.stats()
    finally:
        g.close()


@app.get("/api/graph/subgraph")
def graph_subgraph(center: str | None = None, depth: int = Query(2, ge=1, le=4),
                   limit: int = Query(300, ge=1, le=2000)) -> dict:
    g = _graph()
    try:
        return g.subgraph(center=center or None, depth=depth, limit=limit)
    finally:
        g.close()


def _explain(g: GraphStore, a: int, b: int) -> dict:
    pa, pb = g.person(a), g.person(b)
    if not pa or not pb:
        raise HTTPException(404, "person not in graph")
    tie = score_tie(pa, pb)  # recomputed from stored records, so every factor carries its Evidence
    return to_dict(tie)


@app.get("/api/graph/tie")
def graph_tie(a: int, b: int) -> dict:
    g = _graph()
    try:
        return _explain(g, a, b)
    finally:
        g.close()


@app.get("/api/graph/path")
def graph_path(a: int, b: int, max_hops: int = Query(4, ge=1, le=6)) -> dict:
    g = _graph()
    try:
        ids = g.strongest_path(a, b, max_hops=max_hops)
        if not ids:
            return {"found": False, "ids": [], "people": [], "ties": []}
        people = [g.person(i) for i in ids]
        ties = [_explain(g, x, y) for x, y in zip(ids, ids[1:])]
        return {"found": True, "ids": ids, "hops": len(ids) - 1,
                "people": [{"person_id": p.person_id, "name": p.name, "title": p.current_title,
                            "profile_url": p.profile_url} for p in people if p],
                "ties": ties}
    finally:
        g.close()


@app.get("/api/graph/brokers")
def graph_brokers(top: int = Query(10, ge=1, le=50)) -> list[dict]:
    g = _graph()
    try:
        return g.super_connectors(top=top)
    finally:
        g.close()
