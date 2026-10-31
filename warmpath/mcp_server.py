"""MCP server so any agent (Claude Code / Desktop) can use WarmPath.  Owner: Member C.

    uv run python -m warmpath.mcp_server                       # stdio
    claude mcp add warmpath -- uv run --directory <repo> python -m warmpath.mcp_server

Tools: find_warm_paths(request) · explain_tie(a, b) · graph_path(a, b). Every answer carries its Evidence.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3

from mcp.server.mcpserver import MCPServer

from .graphdb import GraphStore
from .models import to_dict
from .score import score_tie

RUN_TIMEOUT = float(os.getenv("WARMPATH_RUN_TIMEOUT", "240"))
MAX_QUERY = 1000
_busy = asyncio.Lock()  # one paid pipeline run at a time, even if an agent fires calls in parallel

mcp = MCPServer(
    name="warmpath",
    instructions="WarmPath finds warm-intro paths to a person, scored by verified co-employment on Crustdata's "
                 "identity graph. Every tie cites Crustdata records. It never contacts anyone: drafts go to outbox/.",
)


def _tie(t) -> dict:
    """Compact, cited view of a Tie for agents."""
    return {"between": [t.a.name, t.b.name], "person_ids": [t.a.person_id, t.b.person_id],
            "score": round(t.score, 1), "kind": t.kind,
            "verified": getattr(t, "verified", False), "verification": getattr(t, "verification", ""),
            "factors": [{"points": round(f.contribution, 1), "why": f.explanation,
                         "evidence": [to_dict(e) for e in f.evidence]} for f in t.factors]}


@mcp.tool()
async def find_warm_paths(request: str) -> dict:
    """Find warm-intro paths for a free-text request, e.g. "warm intro to the head of data at Swiggy via IIT Bombay".

    Returns the resolved target, ranked paths (each tie with scored, cited factors), intro drafts written to
    outbox/ (never sent), warnings, and the credits spent.
    """
    from .pipeline import run
    from .server import clean_query
    text = clean_query(request)
    if not text:
        return {"error": "empty request. Say who to reach, e.g. 'head of data at Swiggy via IIT Bombay'."}
    if len(text) > MAX_QUERY:
        return {"error": f"request too long ({len(text)} chars). Keep it under {MAX_QUERY}."}
    if not os.getenv("CRUSTDATA_API_KEY") and os.getenv("WARMPATH_FAKE") != "1":
        return {"error": "CRUSTDATA_API_KEY is not set for the MCP server (or set WARMPATH_FAKE=1 for the offline demo)."}
    try:
        async with _busy:
            r = await asyncio.wait_for(run(text), timeout=RUN_TIMEOUT)
    except asyncio.TimeoutError:
        return {"error": f"run timed out after {RUN_TIMEOUT:.0f} s (Crustdata slow or rate-limited). Try again."}
    except Exception as e:  # never crash the agent's session
        return {"error": f"{type(e).__name__}: {e}"}
    if not r.target:
        return {"error": "could not resolve the target. Add the company name or a profile URL.",
                "warnings": r.warnings, "credits_used": r.credits_used}
    return {
        "target": r.target and {"name": r.target.name, "person_id": r.target.person_id,
                                "title": r.target.current_title, "profile_url": r.target.profile_url},
        "company": r.target_company and r.target_company.name,
        "paths": [{"rank": p.rank, "score": round(p.score, 1), "chain": [n.name for n in p.nodes],
                   "why": p.why, "ties": [_tie(t) for t in p.ties]} for p in r.paths],
        "drafts": [to_dict(d) for d in r.drafts],
        "warnings": r.warnings, "credits_used": r.credits_used, "api_calls": len(r.audit),
    }


@mcp.tool()
def explain_tie(person_a: int, person_b: int) -> dict:
    """Explain how well two people in the WarmPath graph know each other (crustdata_person_ids), with citations."""
    if person_a == person_b:
        return {"error": "give two different people"}
    try:
        g = GraphStore()
    except sqlite3.Error as e:
        return {"error": f"graph database unavailable: {e}"}
    try:
        a, b = g.person(person_a), g.person(person_b)
        if not a or not b:
            return {"error": "person not in the WarmPath graph yet. Run find_warm_paths or a crawl first."}
        return _tie(score_tie(a, b))
    except sqlite3.Error as e:
        return {"error": f"graph database busy: {e}"}
    finally:
        g.close()


@mcp.tool()
def graph_path(person_a: int, person_b: int, max_hops: int = 4) -> dict:
    """Strongest chain of verified relationships between two people in the WarmPath graph (crustdata_person_ids)."""
    if person_a == person_b:
        return {"error": "give two different people"}
    max_hops = max(1, min(6, max_hops))
    try:
        g = GraphStore()
    except sqlite3.Error as e:
        return {"error": f"graph database unavailable: {e}"}
    try:
        missing = [i for i in (person_a, person_b) if not g.person(i)]
        if missing:
            return {"found": False, "reason": f"person {missing[0]} is not in the WarmPath graph yet"}
        ids = g.strongest_path(person_a, person_b, max_hops=max_hops)
        if not ids or len(ids) < 2:
            return {"found": False, "reason": f"no chain within {max_hops} hops", "stats": g.stats()}
        people = [g.person(i) for i in ids]
        if any(p is None for p in people):
            return {"found": False, "reason": "graph changed while reading; try again"}
        return {"found": True, "hops": len(ids) - 1, "chain": [p.name for p in people],
                "ties": [_tie(score_tie(x, y)) for x, y in zip(people, people[1:])]}
    except sqlite3.Error as e:
        return {"error": f"graph database busy: {e}"}
    finally:
        g.close()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
