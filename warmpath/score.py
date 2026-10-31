"""Overlap detection + explainable tie strength (docs/PLAN.md §3).  Owner: Member B.

v1 implementation of the scoring table. Pure functions, no API calls, so they're easy to unit test.
"""
from __future__ import annotations

import re
from datetime import date

from rapidfuzz import fuzz

from .models import Evidence, Factor, Overlap, Person, Stint, Tie

TODAY = date.today()


def _months(a: date, b: date) -> float:
    return max(0.0, (b - a).days / 30.44)


def _norm_company(name: str) -> str:
    s = re.sub(r"\(.*?\)", "", name.lower())
    s = re.sub(r"\b(inc|llc|ltd|pvt|private|limited|corp|corporation|technologies|technology|labs|co)\b\.?", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def same_company(x: Stint, y: Stint) -> bool:
    if x.company_id and y.company_id:
        return x.company_id == y.company_id
    return fuzz.token_set_ratio(_norm_company(x.company_name), _norm_company(y.company_name)) >= 92


def find_overlaps(a: Person, b: Person, min_months: float = 2) -> list[Overlap]:
    out: list[Overlap] = []
    for x in a.stints:
        for y in b.stints:
            if not (x.start and y.start) or not same_company(x, y):
                continue
            s, e = max(x.start, y.start), min(x.end or TODAY, y.end or TODAY)
            m = _months(s, e)
            if m >= min_months:
                out.append(Overlap(company_name=x.company_name, company_id=x.company_id, start=s, end=e,
                                   months=round(m, 1), a_stint_ref=x.ref, b_stint_ref=y.ref))
    # one overlap per company (keep the longest)
    best: dict[str, Overlap] = {}
    for o in out:
        k = str(o.company_id or _norm_company(o.company_name))
        if k not in best or o.months > best[k].months:
            best[k] = o
    return sorted(best.values(), key=lambda o: -o.months)


def _stint(p: Person, ref: str) -> Stint | None:
    return next((s for s in p.stints if s.ref == ref), None)


def _size_points(headcount: int | None) -> tuple[float, str]:
    if headcount is None:
        return 6.0, "company size unknown"
    for limit, pts in ((50, 25), (200, 18), (1000, 10), (10000, 5)):
        if headcount <= limit:
            return float(pts), f"~{headcount} people, so they likely worked closely"
    return 2.0, f"~{headcount:,} people, a large org, so the tie is weaker"


def _ev_stint(p: Person, s: Stint) -> Evidence:
    end = s.end.isoformat()[:7] if s.end else "present"
    start = s.start.isoformat()[:7] if s.start else "?"
    return Evidence(claim=f"{p.name}: {s.title or 'role'} at {s.company_name}, {start} → {end}",
                    kind="crustdata", endpoint=p.source_endpoint or "/person/search", ref=s.ref, url=p.profile_url)


def score_tie(a: Person, b: Person) -> Tie:
    overlaps = find_overlaps(a, b)
    factors: list[Factor] = []
    if overlaps:
        main = overlaps[0]
        sa, sb = _stint(a, main.a_stint_ref), _stint(b, main.b_stint_ref)
        ev = [e for e in (_ev_stint(a, sa) if sa else None, _ev_stint(b, sb) if sb else None) if e]
        pts = 40 * min(1.0, main.months / 24)
        factors.append(Factor("overlap_months", main.months, round(pts, 1),
                              f"Overlapped {main.months:.0f} months at {main.company_name} "
                              f"({main.start.isoformat()[:7]} → {main.end.isoformat()[:7]})", ev))
        hc = (sa.company_headcount if sa else None) or (sb.company_headcount if sb else None)
        pts, why = _size_points(hc)
        factors.append(Factor("company_size", hc, pts, f"{main.company_name}: {why}", ev[:1]))
        if sa and sb:
            if sa.function and sa.function == sb.function:
                factors.append(Factor("same_function", sa.function, 10, f"Both in {sa.function}", ev))
            elif sa.title and sb.title and fuzz.token_set_ratio(sa.title, sb.title) >= 70:
                factors.append(Factor("similar_title", f"{sa.title} / {sb.title}", 7,
                                      "Similar roles, likely the same team", ev))
            if sa.location and sb.location and fuzz.partial_ratio(sa.location, sb.location) >= 85:
                factors.append(Factor("same_location", sa.location, 5, f"Both based in {sa.location}", ev))
        years_ago = _months(main.end, TODAY) / 12
        rec = 10.0 if years_ago <= 3 else max(0.0, 10 - 2 * (years_ago - 3))
        if rec:
            factors.append(Factor("recency", round(years_ago, 1), round(rec, 1),
                                  "Overlap is recent" if years_ago <= 3 else f"Overlap ended {years_ago:.0f} years ago"))
        for extra in overlaps[1:]:
            factors.append(Factor("repeat_colleagues", extra.company_name, 10,
                                  f"Also worked together at {extra.company_name} ({extra.months:.0f} mo)"))
    for sa in a.schools:
        for sb in b.schools:
            if _same_school(sa.name, sb.name) and _years_overlap(sa, sb):
                factors.append(Factor("classmates", sa.name, 15, f"Studied at {sa.name} at the same time", [
                    Evidence(f"{a.name}: {sa.name}", "crustdata", a.source_endpoint, sa.ref, a.profile_url),
                    Evidence(f"{b.name}: {sb.name}", "crustdata", b.source_endpoint, sb.ref, b.profile_url)]))
                break
    score = min(100.0, sum(fct.contribution for fct in factors))
    kind = "colleague" if overlaps else ("classmate" if any(f.name == "classmates" for f in factors) else "colleague")
    return Tie(a=a, b=b, score=round(score, 1), factors=factors, overlaps=overlaps, kind=kind)


def _same_school(a: str, b: str) -> bool:
    from .discover import school_variants
    va = {v.lower().replace(",", "") for v in school_variants(a)}
    vb = {v.lower().replace(",", "") for v in school_variants(b)}
    return bool(va & vb) or fuzz.token_set_ratio(a, b) >= 90


def _years_overlap(x, y) -> bool:
    if not (x.start and y.start):
        return False  # without dates we can't claim they were classmates
    return max(x.start, y.start) <= min(x.end or TODAY, y.end or TODAY)
