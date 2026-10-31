"""Web co-occurrence evidence for a tie (co-authored papers, co-founded companies, talks).  Owner: Member B."""
from __future__ import annotations

from .crust import Crust, CrustError
from .models import Evidence, Factor, Person


async def web_cooccurrence(c: Crust, a: Person, b: Person) -> Factor | None:
    q = f'"{a.name}" "{b.name}"'
    try:
        res = await c.web_search(q, sources=["web", "news"])
    except CrustError:
        return None
    hits = []
    for r in res.get("results") or []:
        text = f"{r.get('title', '')} {r.get('snippet', '')}".lower()
        if _mentions(text, a.name) and _mentions(text, b.name):
            hits.append(r)
    if not hits:
        return None
    ev = [Evidence(claim=f"Web page mentions both: {h.get('title', '')[:90]}", kind="web",
                   endpoint="/web/search/live", ref=f"web:{h.get('url')}", url=h.get("url"), call_id=c.last_call_id)
          for h in hits[:3]]
    return Factor("web_cooccurrence", len(hits), 15.0,
                  f"{len(hits)} web page(s) mention {a.name} and {b.name} together", ev)


def _mentions(text: str, name: str) -> bool:
    parts = [p for p in name.lower().split() if len(p) > 1]
    return bool(parts) and parts[0] in text and parts[-1] in text
