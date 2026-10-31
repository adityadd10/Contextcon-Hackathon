"""MCP server so any agent (Claude Code / Desktop) can use WarmPath.  Owner: Member C.

    uv run python -m warmpath.mcp_server                       # stdio
    claude mcp add warmpath -- uv run --directory <repo> python -m warmpath.mcp_server

Tools: find_warm_paths(request) · explain_tie(a, b) · graph_path(a, b). Every answer carries its Evidence.
"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .graphdb import GraphStore
from .models import to_dict
from .score import score_tie

mcp = MCPServer(
    name="warmpath",
    instructions="WarmPath finds warm-intro paths to a person, scored by verified co-employment on Crustdata's "
                 "identity graph. Every tie cites Crustdata records. It never contacts anyone: drafts go to outbox/.",
)


def _tie(t) -> dict:
    """Compact, cited view of a Tie for agents."""
    return {"between": [t.a.name, t.b.name], "person_ids": [t.a.person_id, t.b.person_id],
            "score": round(t.score, 1), "kind": t.kind,
            "factors": [{"points": round(f.contribution, 1), "why": f.explanation,
                         "evidence": [to_dict(e) for e in f.evidence]} for f in t.factors]}


@mcp.tool()
async def find_warm_paths(request: str) -> dict:
    """Find warm-intro paths for a free-text request, e.g. "warm intro to the head of data at Swiggy via IIT Bombay".

    Returns the resolved target, ranked paths (each tie with scored, cited factors), intro drafts written to
    outbox/ (never sent), warnings, and the credits spent.
    """
    from .pipeline import run
    r = await run(request)
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
    g = GraphStore()
    try:
        a, b = g.person(person_a), g.person(person_b)
        if not a or not b:
            return {"error": "person not in the WarmPath graph yet. Run find_warm_paths or a crawl first."}
        return _tie(score_tie(a, b))
    finally:
        g.close()


@mcp.tool()
def graph_path(person_a: int, person_b: int, max_hops: int = 4) -> dict:
    """Strongest chain of verified relationships between two people in the WarmPath graph (crustdata_person_ids)."""
    g = GraphStore()
    try:
        ids = g.strongest_path(person_a, person_b, max_hops=max_hops)
        if not ids:
            return {"found": False, "stats": g.stats()}
        people = [g.person(i) for i in ids]
        return {"found": True, "hops": len(ids) - 1, "chain": [p.name for p in people],
                "ties": [_tie(score_tie(x, y)) for x, y in zip(people, people[1:])]}
    finally:
        g.close()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
