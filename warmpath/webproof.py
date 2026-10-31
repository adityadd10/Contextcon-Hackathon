"""Web co-occurrence evidence for a tie (co-authored papers, co-founded companies, talks).  Owner: Member B.

A page counts only if it names both people in full (first + last name close together). Profile pages and
contact directories are skipped: "people also viewed" sidebars mention strangers side by side.
"""
from __future__ import annotations

import re

from .crust import Crust, CrustError
from .models import Evidence, Factor, Person

SKIP_HOSTS = re.compile(r"linkedin\.com/(?:in|pub)/|rocketreach|zoominfo|signalhire|contactout|apollo\.io|"
                        r"lusha|crunchbase\.com/person|theorg\.com|peoplefinder|facebook\.com|instagram\.com", re.I)
KINDS = [("co-founded", r"co-?found|founders?\b|founded by"),
         ("co-authored", r"arxiv|scholar|paper|journal|proceedings|ieee|acm\b|et al"),
         ("spoke together", r"talk|panel|podcast|webinar|keynote|summit|conference|meetup"),
         ("in the news together", r".")]
POINTS = 15.0


async def web_cooccurrence(c: Crust, a: Person, b: Person) -> Factor | None:
    if not (_usable(a.name) and _usable(b.name)):
        return None
    q = f'"{a.name}" "{b.name}"'
    try:
        res = await c.web_search(q, sources=["web", "news"])
    except CrustError:
        return None
    hits = []
    for r in (res.get("results") if isinstance(res, dict) else None) or []:
        if not isinstance(r, dict):
            continue
        url = r.get("url") or ""
        if not url or SKIP_HOSTS.search(url):
            continue
        text = f"{r.get('title') or ''} {r.get('snippet') or ''}"
        if mentions(text, a.name) and mentions(text, b.name):
            hits.append((r, _kind(f"{url} {text}")))
    if not hits:
        return None
    ev = [Evidence(claim=f"Web page mentions both ({kind}): {(h.get('title') or h.get('url') or '')[:90]}", kind="web",
                   endpoint="/web/search/live", ref=f"web:{h.get('url')}", url=h.get("url"), call_id=c.last_call_id)
          for h, kind in hits[:3]]
    kinds = sorted({k for _, k in hits})
    return Factor("web_cooccurrence", len(hits), POINTS,
                  f"{len(hits)} web page(s) mention {a.name} and {b.name} together ({', '.join(kinds)})", ev)


def mentions(text: str, name: str) -> bool:
    """Full name present: first and last name within two words of each other (allows a middle name/initial)."""
    parts = [re.escape(p) for p in name.lower().split() if len(p) > 1]
    if len(parts) < 2:
        return False
    return bool(re.search(rf"\b{parts[0]}\b(?:\W+\w+){{0,2}}?\W+{parts[-1]}\b", text.lower()))


def _usable(name: str | None) -> bool:
    return bool(name) and name != "?" and len([p for p in name.split() if len(p) > 1]) >= 2


def _kind(text: str) -> str:
    return next(k for k, pat in KINDS if re.search(pat, text, re.I))
