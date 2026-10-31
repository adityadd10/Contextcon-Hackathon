"""Find connectors: people whose employment overlapped with the target, inside the requester's network.
Owner: Member A.

Join key = canonical crustdata_company_id. Date overlap is checked client-side (score.find_overlaps)
because search filters match across *any* role, not the same role.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import date

from . import events as ev
from .crust import Crust, CrustError, all_of, any_of, f, to_person
from .events import Emit
from .models import Person, Stint, TargetSpec
from .resolve import resolve_company

BIG_COMPANY = 1000
TEAM_WORDS = ["data", "analytics", "machine learning", "ml", "ai", "product", "design", "growth", "marketing", "sales",
              "finance", "engineering", "platform", "infrastructure", "security", "mobile", "android", "ios",
              "backend", "frontend", "research", "operations", "hr", "people", "recruit", "legal", "strategy"]


def team_keyword(title: str | None) -> str | None:
    t = (title or "").lower()
    return next((w for w in TEAM_WORDS if re.search(rf"\b{re.escape(w)}\b", t)), None)


MAX_STINTS = int(os.getenv("WARMPATH_MAX_STINTS", "4"))
PER_QUERY = int(os.getenv("WARMPATH_PER_QUERY", "25"))
CO = "experience.employment_details.company_id"


async def load_seeds(c: Crust, spec: TargetSpec, emit: Emit) -> list[Person]:
    urls = list(spec.network.seed_profile_urls)
    urls += [u.strip() for u in os.getenv("WARMPATH_SEEDS", "").split(",") if u.strip() and u.strip() not in urls]
    if not urls:
        return []
    try:
        rows = await c.person_enrich(urls[:25])
    except CrustError as e:
        ev.warn(emit, f"Could not load seed profiles: {e.message}")
        return []
    seeds = []
    for row in rows:
        if row.get("matches"):
            seeds.append(to_person(row["matches"][0]["person_data"], "/person/enrich"))
        else:
            ev.warn(emit, f"Seed {row.get('matched_on')}: {row.get('match_status', 'not found')}")
    return seeds


def rank_stints(target: Person, limit: int = MAX_STINTS) -> list[Stint]:
    """Stints most likely to produce strong ties: small company, long tenure, recent."""
    today = date.today()

    def value(s: Stint) -> float:
        months = ((s.end or today) - s.start).days / 30.44 if s.start else 6
        hc = s.company_headcount or 500
        size = 3.0 if hc <= 50 else 2.0 if hc <= 200 else 1.2 if hc <= 1000 else 0.6
        recency = 1.0 if not s.end else max(0.3, 1 - (today - s.end).days / 3650)
        return min(months, 48) * size * recency

    seen, out = set(), []
    for s in sorted((s for s in target.stints if s.company_id), key=value, reverse=True):
        if s.company_id not in seen:
            seen.add(s.company_id)
            out.append(s)
    return out[:limit]


ABBREV = {"IIT": "Indian Institute of Technology", "IIM": "Indian Institute of Management",
          "IIIT": "International Institute of Information Technology", "NIT": "National Institute of Technology",
          "BITS": "Birla Institute of Technology and Science"}


def school_variants(name: str) -> list[str]:
    """'IIT Bombay' → also 'Indian Institute of Technology Bombay' (profiles use both spellings)."""
    out = [name]
    for short, long in ABBREV.items():
        if name.upper().startswith(short + " "):
            out.append(long + name[len(short):])
        elif name.lower().startswith(long.lower()):
            out.append(short + name[len(long):].replace(",", ""))
    return out


async def network_filter(c: Crust, spec: TargetSpec, emit: Emit, exclude_ids: set[int] | None = None) -> dict | None:
    conds = [f("education.schools.school", "(.)", v) for s in spec.network.schools for v in school_variants(s)]
    if spec.network.companies:
        cos = await asyncio.gather(*(resolve_company(c, n, emit) for n in spec.network.companies))
        ids = [co.company_id for co in cos if co and co.company_id]
        dropped = [co.name for co in cos if co and co.company_id in (exclude_ids or set())]
        if dropped:  # "via Swiggy people" to reach someone at Swiggy would make everyone there "in network"
            ev.warn(emit, f"Ignoring {', '.join(dropped)} as a network filter because it's the target's own employer")
        ids = [i for i in ids if i not in (exclude_ids or set())]
        if ids:
            conds.append(f(CO, "in", ids))
    return any_of(*conds) if conds else None


async def find_connectors(c: Crust, target: Person, spec: TargetSpec, seeds: list[Person], emit: Emit) -> list[Person]:
    stints = rank_stints(target)
    net = await network_filter(c, spec, emit, exclude_ids={s.company_id for s in target.stints if s.company_id})
    queries: list[tuple[str, dict]] = []
    for s in stints:
        label = f"{s.company_name}" + (f" ∩ {', '.join(spec.network.schools)}" if spec.network.schools else "")
        conds = [f(CO, "=", s.company_id), net]
        if (s.company_headcount or 0) > BIG_COMPANY:
            # at a big employer "same company" means little: narrow to people who joined before the target left
            # and who share the target's team keyword (e.g. "data"), the colleagues most likely to know them
            if s.end:
                conds.append(f("experience.employment_details.start_date", "=<", s.end.isoformat()))
            if (kw := team_keyword(s.title)):
                conds.append(f("experience.employment_details.title", "[.]", kw))
                label += f" ∩ '{kw}' team"
        queries.append((label, all_of(*conds)))
    # 2-hop: people who worked at one of the seeds' companies AND one of the target's companies
    seed_cos = sorted({st.company_id for sd in seeds for st in sd.stints if st.company_id})
    tgt_cos = [s.company_id for s in stints]
    if seed_cos and tgt_cos:
        queries.append(("bridges between your team's companies and the target's",
                        {"op": "and", "conditions": [f(CO, "in", seed_cos[:20]), f(CO, "in", tgt_cos)]}))

    found: dict[int, Person] = {}
    skip = {target.person_id, *(sd.person_id for sd in seeds)}

    async def one(label: str, flt: dict) -> None:
        try:
            res = await c.person_search(flt, limit=PER_QUERY)
        except CrustError as e:
            ev.warn(emit, f"Search '{label}' failed: {e.message}")
            return
        profiles = res.get("profiles") or []
        ev.step(emit, "discover", "progress", f"Searched {label}",
                f"{len(profiles)} of {res.get('total_count', '?')} people returned")
        for p in profiles:
            person = to_person(p, "/person/search")
            if person.person_id and person.person_id not in skip:
                found.setdefault(person.person_id, person)

    await asyncio.gather(*(one(lbl, flt) for lbl, flt in queries))
    return list(found.values())
