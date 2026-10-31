"""Overlap detection + explainable tie strength (docs/PLAN.md §3).  Owner: Member B.

Pure functions, no API calls, so they're easy to unit test. Every Factor carries Evidence: Crustdata
stint/school records, or a `derived` record that says what was computed from them.

Hardest case: "both at Google" means little. Overlap points are discounted at big companies unless there is
a team signal (same function, similar title or same location), so a long overlap on a small team beats two
strangers who happen to share a 50k-person employer.
"""
from __future__ import annotations

import math
import re
from datetime import date, timedelta

from rapidfuzz import fuzz

from . import headcount
from .models import Evidence, Factor, Overlap, Person, School, Stint, Tie

TODAY = date.today()
ASSUMED_TENURE = timedelta(days=365)   # past stint with no end date: assume it lasted at most a year
# share of the overlap points kept at each company size when there's no sign they were on the same team
SIZE_DISCOUNT = ((1000, 0.8), (10000, 0.55))
SIZE_DISCOUNT_HUGE = 0.35
TEAM_BONUS = 0.35                       # same function/title/location gives back this much of the discount
THIN_PENALTY = 8.0                      # per person with a 1-role, no-education record
KNEE = 70.0                             # scores are linear up to here, then compressed so strong ties stay distinct


def calibrate(raw: float) -> float:
    """Sum of factor points → 0-100. Linear below KNEE (thresholds keep their meaning), soft cap above it,
    so raw 100 → 89 and raw 115 → 93 instead of both saturating at 100."""
    raw = max(0.0, raw)
    if raw <= KNEE:
        return round(raw, 1)
    return round(KNEE + (100 - KNEE) * (1 - math.exp(-(raw - KNEE) / (100 - KNEE))), 1)


def tie_score(factors: list[Factor]) -> float:
    """Use this after adding a factor to a tie (e.g. web proof) instead of adding points to tie.score."""
    return calibrate(sum(f.contribution for f in factors))


def _months(a: date, b: date) -> float:
    return max(0.0, (b - a).days / 30.44)


def _norm_company(name: str) -> str:
    s = re.sub(r"\(.*?\)", "", name.lower())
    s = re.sub(r"\b(inc|llc|ltd|pvt|private|limited|corp|corporation|technologies|technology|labs|co|software|"
               r"solutions|services|systems|india|global|international|group|holdings|ventures|company)\b\.?", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def same_company(x: Stint, y: Stint) -> bool:
    if x.company_id and y.company_id:
        return x.company_id == y.company_id
    a, b = _norm_company(x.company_name), _norm_company(y.company_name)
    # whole-name similarity, not word subsets: "lime" (Lime Labs) must not match "lime spot india"
    return bool(a and b) and fuzz.token_sort_ratio(a, b) >= 92


def stint_end(s: Stint) -> tuple[date | None, bool]:
    """(end date, assumed?). Current roles end today; a past role with no end date is capped at a year."""
    if s.end:
        return s.end, False
    if s.is_current:
        return TODAY, False
    if s.start:
        return min(TODAY, s.start + ASSUMED_TENURE), True
    return None, False


def find_overlaps(a: Person, b: Person, min_months: float = 2) -> list[Overlap]:
    out: list[tuple[str, Overlap]] = []
    for x in a.stints:
        for y in b.stints:
            if not (x.start and y.start) or not same_company(x, y):
                continue
            (xe, _), (ye, _) = stint_end(x), stint_end(y)
            if not (xe and ye) or xe < x.start or ye < y.start:
                continue  # bad dates on the record: no claim
            s, e = max(x.start, y.start), min(xe, ye)
            m = _months(s, e)
            if m >= min_months:
                # name and grouping key must not depend on argument order: score_tie(a, b) == score_tie(b, a)
                name = min(x.company_name, y.company_name) if not (x.company_id or y.company_id) else (
                    x.company_name if x.company_id else y.company_name)
                key = str(x.company_id or y.company_id or min(_norm_company(x.company_name),
                                                             _norm_company(y.company_name)))
                out.append((key, Overlap(company_name=name, company_id=x.company_id or y.company_id, start=s,
                                         end=e, months=round(m, 1), a_stint_ref=x.ref, b_stint_ref=y.ref)))
    # one overlap per company: title changes split a tenure into several stints, so join windows that touch
    by_co: dict[str, list[Overlap]] = {}
    for key, o in out:
        by_co.setdefault(key, []).append(o)
    merged = []
    for group in by_co.values():
        group.sort(key=lambda o: (o.start, o.end, min(o.a_stint_ref, o.b_stint_ref)))
        runs: list[list[Overlap]] = []
        for o in group:
            if runs and (o.start - max(x.end for x in runs[-1])).days <= 45:
                runs[-1].append(o)
            else:
                runs.append([o])
        best = None
        for run in runs:
            s, e = run[0].start, max(x.end for x in run)
            latest = max(run, key=lambda x: (x.end, x.start))   # cite the most recent stints
            o = Overlap(latest.company_name, latest.company_id, s, e, round(_months(s, e), 1),
                        latest.a_stint_ref, latest.b_stint_ref)
            if best is None or o.months > best.months:
                best = o
        merged.append(best)
    return sorted(merged, key=lambda o: (-o.months, o.company_name))


def _stint(p: Person, ref: str) -> Stint | None:
    return next((s for s in p.stints if s.ref == ref), None)


def _size_points(headcount: int | None, basis: str = "") -> tuple[float, str]:
    if headcount is None:
        return 6.0, "company size unknown"
    basis = basis or f"~{headcount:,} people (latest headcount)"
    for limit, pts, why in ((50, 25, "a small team, so they likely worked closely"),
                            (200, 18, "small enough that they likely knew each other"),
                            (1000, 10, "a mid-size company"), (10000, 5, "a large company")):
        if headcount <= limit:
            return float(pts), f"{basis}, {why}"
    return 2.0, f"{basis}, a large org, so the tie is weaker"


def _size_keep(headcount: int | None) -> float:
    if headcount is None or headcount <= 200:
        return 1.0
    for limit, keep in SIZE_DISCOUNT:
        if headcount <= limit:
            return keep
    return SIZE_DISCOUNT_HUGE


def _ev_stint(p: Person, s: Stint) -> Evidence:
    end = s.end.isoformat()[:7] if s.end else ("present" if s.is_current else "end date missing")
    start = s.start.isoformat()[:7] if s.start else "?"
    return Evidence(claim=f"{p.name}: {s.title or 'role'} at {s.company_name}, {start} → {end}",
                    kind="crustdata", endpoint=p.source_endpoint or "/person/search", ref=s.ref, url=p.profile_url)


def _ev_school(p: Person, s: School) -> Evidence:
    yrs = f", {s.start.year}–{s.end.year if s.end else 'present'}" if s.start else ""
    return Evidence(claim=f"{p.name}: {s.degree or 'studied'} at {s.name}{yrs}", kind="crustdata",
                    endpoint=p.source_endpoint or "/person/search", ref=s.ref, url=p.profile_url)


def _derived(claim: str, *refs: str) -> Evidence:
    return Evidence(claim=claim, kind="derived", endpoint="computed", ref=" + ".join(r for r in refs if r))


def _pair_ev(a: Person, b: Person, o: Overlap) -> list[Evidence]:
    sa, sb = _stint(a, o.a_stint_ref), _stint(b, o.b_stint_ref)
    return [e for e in (_ev_stint(a, sa) if sa else None, _ev_stint(b, sb) if sb else None) if e]


def score_tie(a: Person, b: Person) -> Tie:
    if a is b or (a.person_id is not None and a.person_id == b.person_id):
        return Tie(a=a, b=b, score=0.0, kind="self")
    overlaps = find_overlaps(a, b)
    factors: list[Factor] = []
    if overlaps:
        main = overlaps[0]
        sa, sb = _stint(a, main.a_stint_ref), _stint(b, main.b_stint_ref)
        ev = _pair_ev(a, b, main)
        window = f"{main.start.isoformat()[:7]} → {main.end.isoformat()[:7]}"
        assumed = [p.name for p, s in ((a, sa), (b, sb)) if s and stint_end(s)[1]]
        note = f"; end date missing for {', '.join(assumed)}, assumed ≤1 year" if assumed else ""
        overlap_pts = 40 * min(1.0, main.months / 24)
        factors.append(Factor("overlap_months", main.months, round(overlap_pts, 1),
                              f"Overlapped {main.months:.0f} months at {main.company_name} ({window}){note}", ev))

        hc = next((h for h in (sa.company_headcount if sa else None, sb.company_headcount if sb else None)
                   if isinstance(h, (int, float)) and h > 0), None)       # 0 / negative = unknown, not "tiny"
        basis, size_ev = "", ev[:1]
        if hist := headcount.size_during(main.company_id, main.start, main.end):   # size *during* the overlap
            hc, basis = hist[0], hist[1]
            size_ev = [Evidence(f"{main.company_name} headcount: {hist[1]}", "crustdata", "/company/enrich",
                                f"company:{main.company_id}#headcount.timeseries")]
        pts, why = _size_points(hc, basis)
        factors.append(Factor("company_size", hc, pts, f"{main.company_name}: {why}", size_ev))

        team: list[str] = []
        if sa and sb:
            if sa.function and sa.function == sb.function:
                fpts = 10.0 if (hc or 0) <= 1000 else 6.0
                factors.append(Factor("same_function", sa.function, fpts, f"Both in {sa.function}", ev))
                team.append("same function")
            elif not (sa.function and sb.function) and (kw := _team(sa.title)) and kw == _team(sb.title):
                # function_category is usually empty on live data: fall back to the team named in both titles
                factors.append(Factor("same_team", kw, 8.0 if (hc or 0) <= 1000 else 5.0,
                                      f"Both titles name the {kw} team", ev))
                team.append(f"{kw} team")
            if sa.title and sb.title and fuzz.token_set_ratio(sa.title.lower(), sb.title.lower()) >= 70:
                factors.append(Factor("similar_title", f"{sa.title} / {sb.title}", 7.0 if not team else 3.0,
                                      "Similar roles, likely the same team", ev))
                team.append("similar titles")
            if sa.location and sb.location and fuzz.partial_ratio(sa.location.lower(), sb.location.lower()) >= 85:
                factors.append(Factor("same_location", sa.location, 5.0, f"Both based in {sa.location}", ev))
                team.append("same location")
            if abs((sa.start - sb.start).days) <= 62 and (hc or 0) <= 1000:  # same cohort only means something small
                factors.append(Factor("joined_together", sa.start.isoformat()[:7], 5.0,
                                      f"Joined {main.company_name} within two months of each other", ev))

        keep = _size_keep(hc)
        if keep < 1.0:
            if team:
                keep = min(1.0, keep + TEAM_BONUS)
            if keep < 1.0:
                cut = -round(overlap_pts * (1 - keep), 1)
                why = (f"{main.company_name} is large (~{hc:,}), and " +
                       (f"only a weak team signal ({', '.join(team)})" if team else "nothing shows the same team") +
                       ", so overlapping dates alone may not mean they met")
                factors.append(Factor("big_company_discount", keep, cut, why, ev[:1]))

        years_ago = _months(main.end, TODAY) / 12
        rec = 10.0 if years_ago <= 3 else max(0.0, 10 - 2 * (years_ago - 3))
        if rec:
            factors.append(Factor("recency", round(years_ago, 1), round(rec, 1),
                                  "Overlap is recent (ended within 3 years)" if years_ago <= 3
                                  else f"Overlap ended {years_ago:.0f} years ago",
                                  [_derived(f"Overlap at {main.company_name} " +
                                            ("is ongoing (both still there)" if main.end >= TODAY
                                             else f"ended {main.end.isoformat()[:7]}"),
                                            main.a_stint_ref, main.b_stint_ref)]))
        for extra in overlaps[1:]:
            factors.append(Factor("repeat_colleagues", extra.company_name, 10.0,
                                  f"Also worked together at {extra.company_name} ({extra.months:.0f} mo, "
                                  f"{extra.start.isoformat()[:7]} → {extra.end.isoformat()[:7]})",
                                  _pair_ev(a, b, extra)))
    for sa_ in a.schools:
        for sb_ in b.schools:
            if _same_school(sa_.name, sb_.name) and _years_overlap(sa_, sb_):
                factors.append(Factor("classmates", sa_.name, 15.0, f"Studied at {sa_.name} at the same time",
                                      [_ev_school(a, sa_), _ev_school(b, sb_)]))
                break
        else:
            continue
        break
    thin = [p for p in (a, b) if len(p.stints) <= 1 and not p.schools]
    if factors and thin:   # a 1-role, no-education record is often partial or a junk profile
        who = " and ".join(p.name for p in thin)
        factors.append(Factor("thin_profile", len(thin), -THIN_PENALTY * len(thin),
                              f"{who}: only one role and no education on record, so this tie is less certain",
                              [_derived(f"{p.name}: {len(p.stints)} role(s), 0 schools on record",
                                        *(s.ref for s in p.stints)) for p in thin]))
    score = tie_score(factors)
    kind = "colleague" if overlaps else ("classmate" if any(f.name == "classmates" for f in factors) else "colleague")
    return Tie(a=a, b=b, score=score, factors=factors, overlaps=overlaps, kind=kind)


def _team(title: str | None) -> str | None:
    from .discover import team_keyword
    return team_keyword(title)


def _same_school(a: str, b: str) -> bool:
    if not (a or "").strip(" ?") or not (b or "").strip(" ?"):
        return False                                    # unnamed schools prove nothing
    from .discover import school_variants
    va = {v.lower().replace(",", "") for v in school_variants(a)}
    vb = {v.lower().replace(",", "") for v in school_variants(b)}
    return bool(va & vb) or fuzz.token_set_ratio(a, b) >= 90


def _years_overlap(x: School, y: School) -> bool:
    if not (x.start and y.start):
        return False  # without dates we can't claim they were classmates
    return max(x.start, y.start) <= min(x.end or TODAY, y.end or TODAY)
