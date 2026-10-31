"""Company size *during* an overlap, from Crustdata's headcount history.  Owner: Member B.

Stints only carry the latest headcount, so two people who worked together at a 300-person Razorpay get scored as if
it had 4,000. `/company/enrich` (fields=["headcount"]) returns a weekly `headcount.timeseries`; we keep it in a small
registry that `score.score_tie` reads, so scoring stays pure (no I/O).

    await headcount.load(c, [897127, 5702])      # 2 credits per company, cached; call once before scoring
    headcount.size_during(897127, start, end)    # → (people, "2,155 people in 2021-08 (earliest on record)")

History starts around 2021, so for older overlaps we use the earliest point and say so. Never extrapolated.
"""
from __future__ import annotations

from datetime import date

from .crust import Crust, CrustError, parse_date

HISTORY: dict[int, list[tuple[date, int]]] = {}


def register(company_id: int, enrich_row: dict) -> None:
    """Store the headcount series from one /company/enrich row (any nesting depth)."""
    series = _find(enrich_row, "timeseries")
    points = []
    for p in series if isinstance(series, list) else []:
        d, n = parse_date((p or {}).get("date")), (p or {}).get("employee_count")
        if d and isinstance(n, (int, float)) and n > 0:
            points.append((d, int(n)))
    if points:
        HISTORY[int(company_id)] = sorted(points)


async def load(c: Crust, company_ids: list[int]) -> int:
    """Fetch history for companies not loaded yet. Returns how many have history. Failures are ignored."""
    todo = [i for i in dict.fromkeys(company_ids) if i and int(i) not in HISTORY]
    for k in range(0, len(todo), 25):
        try:
            rows = await c.company_enrich(todo[k:k + 25], fields=["basic_info", "headcount"])
        except CrustError:
            continue
        for cid, row in zip(todo[k:k + 25], rows or []):
            register(cid, row)
    return sum(1 for i in company_ids if i and int(i) in HISTORY)


def size_during(company_id: int | None, start: date, end: date) -> tuple[int, str] | None:
    """Smallest recorded headcount inside [start, end]: closest to when they met. None without history."""
    pts = HISTORY.get(int(company_id)) if company_id else None
    if not pts or end < pts[0][0]:
        return None
    inside = [p for p in pts if start <= p[0] <= end]
    if inside:
        d, n = min(inside, key=lambda p: p[1])
        note = f"{n:,} people in {d.isoformat()[:7]}"
        if start < pts[0][0]:
            note += " (earliest on record; the overlap started before that)"
        return n, note
    return None


def _find(obj, key: str):
    if isinstance(obj, dict):
        if key in obj and obj[key]:
            return obj[key]
        obj = list(obj.values())
    if isinstance(obj, list):
        for v in obj:
            if (r := _find(v, key)) is not None:
                return r
    return None
