"""Web UI + API: uv run uvicorn warmpath.server:app --reload  →  http://localhost:8000   Owner: Member C.

GET /                         single-page UI (static/index.html)
GET /api/run?q=...            SSE stream of pipeline events (PLAN §6); &mock=1 replays fixtures/mock_events.jsonl
GET /api/crawl?seeds=a,b      SSE stream of crawl events (&depth=1&budget=80)
GET /api/graph/stats          node/edge counts
GET /api/graph/subgraph       ?center=person:123&depth=2 (omit center for the whole recent graph)
GET /api/graph/path?a=1&b=2   strongest chain between two people, with every hop's tie + evidence
GET /api/graph/tie?a=1&b=2    one KNOWS edge explained: factors, overlaps, citations
GET /api/graph/brokers        super-connectors (betweenness)

Failure policy: stream endpoints never fail with a bare HTTP error. Bad input, a missing key, a crash, a timeout or a
busy server all arrive as an `error` event followed by `end`, so the UI can always say what went wrong.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Iterator

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .graphdb import GraphStore
from .models import to_dict
from .score import score_tie

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MOCK = ROOT.parent / "fixtures" / "mock_events.jsonl"
MOCK_DELAY = float(os.getenv("WARMPATH_MOCK_DELAY", "0.25"))
RUN_TIMEOUT = float(os.getenv("WARMPATH_RUN_TIMEOUT", "240"))  # live runs take 15-60 s; anything past this is stuck
HEARTBEAT = 15.0                                                 # keep proxies from closing a quiet stream
MAX_QUERY = 1000
MAX_SEEDS = 10
PROFILE_URL = re.compile(r"^https?://([a-z]{2,3}\.)?(www\.)?linkedin\.com/in/[^/?#\s]+/?$", re.I)

app = FastAPI(title="WarmPath")
# One pipeline or crawl at a time: both spend credits and write the same SQLite graph.
_busy = asyncio.Lock()


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def _friendly(e: BaseException) -> str:
    msg = str(e) or type(e).__name__
    if "CRUSTDATA_API_KEY" in msg:
        return msg + " (or switch on 'offline replay' in the UI)"
    if isinstance(e, sqlite3.OperationalError):
        return f"Graph database busy or unreadable ({msg}). Try again in a moment."
    return f"{type(e).__name__}: {msg}"


async def _stream(job: Callable[[Callable[[dict], None]], Awaitable[object]], *, exclusive: bool = True,
                  request: Request | None = None) -> AsyncIterator[str]:
    """Run `job(emit)` in the background and yield each emitted event as an SSE frame.

    Always ends with an `end` event. Errors, timeouts and a busy server become `error` events.
    """
    q: asyncio.Queue[dict | None] = asyncio.Queue()

    async def runner() -> None:
        try:
            waited = exclusive and _busy.locked()
            if waited:
                q.put_nowait({"type": "step", "id": "queue", "status": "start",
                              "label": "Waiting for the run in progress to finish", "detail": ""})
            async with (_busy if exclusive else _NoLock()):
                if waited:
                    q.put_nowait({"type": "step", "id": "queue", "status": "done", "label": "Our turn", "detail": ""})
                await asyncio.wait_for(job(q.put_nowait), timeout=RUN_TIMEOUT)
        except asyncio.TimeoutError:
            q.put_nowait({"type": "error", "message": f"Stopped after {RUN_TIMEOUT:.0f} s with no result. "
                                                      "Crustdata may be slow or rate-limiting; partial results are in reports/."})
        except asyncio.CancelledError:
            raise
        except Exception as e:  # surface failures to the UI instead of a silently dead stream
            q.put_nowait({"type": "error", "message": _friendly(e)})
        finally:
            q.put_nowait(None)

    task = asyncio.create_task(runner())
    try:
        while True:
            try:
                e = await asyncio.wait_for(q.get(), timeout=HEARTBEAT)
            except asyncio.TimeoutError:
                if request is not None and await request.is_disconnected():
                    break
                yield ": ping\n\n"
                continue
            if e is None:
                break
            yield _sse(e)
        yield _sse({"type": "end"})
    finally:
        task.cancel()  # client went away → stop spending credits


class _NoLock:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc) -> None:
        return None


def _sse_response(gen: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"cache-control": "no-cache", "x-accel-buffering": "no"})


def _sse_error(message: str) -> StreamingResponse:
    """A stream that only reports a problem: the UI shows it instead of a generic 'connection closed'."""
    async def gen() -> AsyncIterator[str]:
        yield _sse({"type": "error", "message": message})
        yield _sse({"type": "end"})
    return _sse_response(gen())


async def _replay(emit: Callable[[dict], None]) -> None:
    if not MOCK.exists():
        raise FileNotFoundError(f"replay file missing: {MOCK.name}")
    for n, line in enumerate(MOCK.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            emit(json.loads(line))
        except json.JSONDecodeError:
            emit({"type": "warning", "message": f"Skipped a corrupt line ({n}) in the replay file"})
        await asyncio.sleep(MOCK_DELAY)


def clean_query(q: str) -> str:
    """Collapse whitespace and control characters; the parser gets plain text."""
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", q or "")).strip()


def parse_seeds(raw: str) -> tuple[list[str], list[str]]:
    """Split a comma/space/newline list of profile URLs into (valid, rejected). Deduplicates, keeps order."""
    valid, rejected, seen = [], [], set()
    for u in re.split(r"[,\s]+", raw or ""):
        raw_u = u.strip().strip("<>\"'")
        if not raw_u:
            continue
        u = raw_u if re.match(r"^https?://", raw_u, re.I) else "https://" + raw_u
        if not PROFILE_URL.match(u):
            rejected.append(raw_u)
            continue
        # same profile written differently (http/https, www, trailing slash) is enriched (and paid for) once
        key = re.sub(r"^https?://(www\.)?", "", u.lower()).rstrip("/")
        if key not in seen:
            seen.add(key)
            valid.append(u)
    return valid, rejected


# ------------------------------------------------------------------ pages

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "fake": os.getenv("WARMPATH_FAKE") == "1",
            "live_key": bool(os.getenv("CRUSTDATA_API_KEY")), "mock_available": MOCK.exists(),
            "busy": _busy.locked()}


# ------------------------------------------------------------------ streams

@app.get("/api/run")
async def api_run(request: Request, q: str = "", mock: bool = False) -> StreamingResponse:
    if mock:
        return _sse_response(_stream(_replay, exclusive=False, request=request))
    text = clean_query(q)
    if not text:
        return _sse_error("Type who you want to reach, e.g. 'warm intro to the head of data at Swiggy'.")
    if len(text) > MAX_QUERY:
        return _sse_error(f"That request is {len(text)} characters. Keep it under {MAX_QUERY}: "
                          "name the person or role and the company.")
    if not os.getenv("CRUSTDATA_API_KEY") and os.getenv("WARMPATH_FAKE") != "1":
        return _sse_error("No CRUSTDATA_API_KEY on the server. Add it to .env, start with WARMPATH_FAKE=1, "
                          "or switch on 'offline replay'.")
    from .pipeline import run
    return _sse_response(_stream(lambda emit: run(text, emit), request=request))


@app.get("/api/crawl")
async def api_crawl(request: Request, seeds: str = "", depth: int = 1, budget: float = 80) -> StreamingResponse:
    urls, rejected = parse_seeds(seeds or os.getenv("WARMPATH_SEEDS", ""))
    if not urls:
        why = f" Not profile URLs: {', '.join(rejected[:3])}." if rejected else ""
        return _sse_error("Give at least one profile URL like https://www.linkedin.com/in/<name>, "
                          "or set WARMPATH_SEEDS." + why)
    if not os.getenv("CRUSTDATA_API_KEY") and os.getenv("WARMPATH_FAKE") != "1":
        return _sse_error("No CRUSTDATA_API_KEY on the server, so the crawl can't call Crustdata.")
    depth = max(1, min(3, depth))
    budget = max(1.0, min(500.0, budget))

    async def job(emit: Callable[[dict], None]) -> None:
        from .crawl import crawl
        from .crust import Crust
        for u in rejected:
            emit({"type": "warning", "message": f"Skipped, not a profile URL: {u}"})
        if len(urls) > MAX_SEEDS:
            emit({"type": "warning", "message": f"Crawling the first {MAX_SEEDS} of {len(urls)} seeds"})
        g = GraphStore()
        try:
            async with Crust(budget=budget) as c:
                stats = await crawl(c, g, urls[:MAX_SEEDS], depth=depth, emit=emit)
                emit({"type": "graph", "stats": stats})
                emit({"type": "done", "result": {"stats": stats, "credits_used": round(c.credits_used, 2),
                                                 "audit": to_dict(c.audit)}})
        finally:
            g.close()

    return _sse_response(_stream(job, request=request))


# ------------------------------------------------------------------ graph explorer

@contextmanager
def _graph() -> Iterator[GraphStore]:
    try:
        g = GraphStore()
    except sqlite3.Error as e:
        raise HTTPException(503, f"graph database unavailable: {e}")
    try:
        yield g
    except sqlite3.OperationalError as e:  # e.g. "database is locked" while a run is writing
        raise HTTPException(503, f"graph database busy: {e}. Try again in a moment.")
    finally:
        g.close()


@app.exception_handler(HTTPException)
async def _http_error(_: Request, e: HTTPException) -> JSONResponse:
    return JSONResponse({"error": e.detail}, status_code=e.status_code)


@app.get("/api/graph/stats")
def graph_stats() -> dict:
    with _graph() as g:
        return g.stats()


@app.get("/api/graph/subgraph")
def graph_subgraph(center: str | None = Query(None, max_length=200), depth: int = Query(2, ge=1, le=4),
                   limit: int = Query(300, ge=1, le=2000)) -> dict:
    if center and not re.fullmatch(r"person:\d+", center):
        raise HTTPException(400, "center must look like person:<crustdata_person_id>")
    with _graph() as g:
        if center and not g.person(int(center.split(":")[1])):
            raise HTTPException(404, f"{center} is not in the graph yet")
        return g.subgraph(center=center or None, depth=depth, limit=limit)


def _explain(g: GraphStore, a: int, b: int) -> dict:
    if a == b:
        raise HTTPException(400, "pick two different people")
    pa, pb = g.person(a), g.person(b)
    if not pa or not pb:
        raise HTTPException(404, f"person {a if not pa else b} is not in the graph yet")
    tie = score_tie(pa, pb)  # recomputed from stored records, so every factor carries its Evidence
    return to_dict(tie)


@app.get("/api/graph/tie")
def graph_tie(a: int, b: int) -> dict:
    with _graph() as g:
        return _explain(g, a, b)


@app.get("/api/graph/path")
def graph_path(a: int, b: int, max_hops: int = Query(4, ge=1, le=6)) -> dict:
    if a == b:
        raise HTTPException(400, "pick two different people")
    with _graph() as g:
        missing = [i for i in (a, b) if not g.person(i)]
        if missing:
            return {"found": False, "reason": f"person {missing[0]} is not in the graph yet", "ids": [], "people": [], "ties": []}
        ids = g.strongest_path(a, b, max_hops=max_hops)
        if not ids or len(ids) < 2:
            return {"found": False, "reason": f"no chain of verified relationships within {max_hops} hops",
                    "ids": [], "people": [], "ties": []}
        people = [g.person(i) for i in ids]
        if any(p is None for p in people):
            return {"found": False, "reason": "the graph changed while reading it; try again", "ids": [], "people": [], "ties": []}
        ties = [_explain(g, x, y) for x, y in zip(ids, ids[1:])]
        return {"found": True, "ids": ids, "hops": len(ids) - 1,
                "people": [{"person_id": p.person_id, "name": p.name, "title": p.current_title,
                            "profile_url": p.profile_url} for p in people],
                "ties": ties}


@app.get("/api/graph/brokers")
def graph_brokers(top: int = Query(10, ge=1, le=50)) -> list[dict]:
    with _graph() as g:
        return g.super_connectors(top=top)
