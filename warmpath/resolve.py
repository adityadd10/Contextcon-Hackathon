"""Resolve the target company + person from a TargetSpec.  Owner: Member A."""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from . import events as ev
from .crust import Crust, CrustError, all_of, f, to_company, to_person
from .events import Emit
from .models import Company, Person, TargetSpec

SENIORITY = [("chief", 6), ("cxo", 6), ("cto", 6), ("ceo", 6), ("founder", 5), ("vp", 5), ("vice president", 5),
             ("head", 5), ("director", 4), ("principal", 3), ("lead", 3), ("manager", 2), ("senior", 1)]
STOP = {"the", "of", "at", "for", "and", "whoever", "runs", "leads", "heads", "person", "someone", "guy", "girl"}


async def resolve_company(c: Crust, query: str, emit: Emit) -> Company | None:
    q = query.strip()
    try:
        if re.search(r"linkedin\.com/company/", q):
            rows = await c.company_identify(profile_urls=[q])
        elif re.fullmatch(r"(https?://)?(www\.)?[\w\-]+\.[a-z.]{2,}/?", q, re.I):
            rows = await c.company_identify(domains=[re.sub(r"^(https?://)?(www\.)?", "", q).strip("/")])
        else:
            rows = await c.company_identify(names=[q])
    except CrustError as e:
        ev.warn(emit, f"Company identify failed for '{q}': {e.message}")
        return None
    matches = (rows[0].get("matches") if rows else None) or []
    if not matches:
        ev.warn(emit, f"No company in Crustdata matches '{q}'")
        return None
    cands = [to_company(m) for m in matches[:5]]
    # prefer the strongest name match, then the biggest company (the famous one is usually meant)
    best = max(cands, key=lambda co: ((co.confidence or 0), fuzz.ratio(co.name.lower(), q.lower()),
                                      _range_low(co.employee_count_range)))
    return best


async def resolve_target(c: Crust, spec: TargetSpec, emit: Emit) -> tuple[Person | None, Company | None]:
    company = await resolve_company(c, spec.company, emit) if spec.company else None
    if company:
        ev.step(emit, "resolve", "progress", "Resolved company",
                f"{company.name} (crustdata_company_id {company.company_id}, {company.employee_count_range or '?'} people)")

    if spec.profile_url:
        return await enrich_one(c, spec.profile_url, emit), company

    cands: list[dict] = []
    if spec.person_name:
        cond = [f("basic_profile.name", "(.)", spec.person_name)]
        if company and company.company_id:
            cond.append(f("experience.employment_details.company_id", "=", company.company_id))
        cands = await _search(c, all_of(*cond), emit)
        if not cands and company:  # maybe they left the company: retry on name only
            cands = await _search(c, cond[0], emit)
    elif spec.role and company and company.company_id:
        words = [w for w in re.findall(r"[a-z]+", spec.role.lower()) if w not in STOP]
        for title_cond in (f("experience.employment_details.current.title", "[.]", spec.role),
                           f("experience.employment_details.current.title", "(.)", " ".join(words))):
            cands = await _search(c, all_of(f("experience.employment_details.current.company_id", "=",
                                              company.company_id), title_cond), emit)
            if cands:
                break
    if not cands:
        return None, company

    people = [to_person(p, "/person/search") for p in cands]
    best = max(people, key=lambda p: _target_rank(p, spec, company))
    ev.step(emit, "resolve", "progress", "Picked target",
            f"{best.name} · {best.current_title or ''} (from {len(people)} candidates)")
    # search profiles can be partial; enrich for the full dated career
    if best.profile_url:
        full = await enrich_one(c, best.profile_url, emit)
        if full and full.stints:
            return full, company
    return best, company


async def enrich_one(c: Crust, url: str, emit: Emit) -> Person | None:
    try:
        rows = await c.person_enrich([url])
    except CrustError as e:
        ev.warn(emit, f"Enrich failed for {url}: {e.message}")
        return None
    row = rows[0] if rows else {}
    status = row.get("match_status", "matched" if row.get("matches") else "not_found")
    if status == "redacted":
        ev.warn(emit, f"{url}: this person asked Crustdata to remove their data. Skipping them.")
        return None
    if not row.get("matches"):
        ev.warn(emit, f"{url}: not found in Crustdata yet")
        return None
    return to_person(row["matches"][0]["person_data"], "/person/enrich")


async def _search(c: Crust, filters: dict, emit: Emit, limit: int = 10) -> list[dict]:
    try:
        res = await c.person_search(filters, limit=limit)
    except CrustError as e:
        ev.warn(emit, f"Person search failed: {e.message}")
        return []
    return res.get("profiles") or []


def _target_rank(p: Person, spec: TargetSpec, company: Company | None) -> float:
    title = (p.current_title or p.headline or "").lower()
    score = 0.0
    if spec.person_name:
        score += fuzz.token_set_ratio(spec.person_name.lower(), p.name.lower())
    if spec.role:
        score += fuzz.token_set_ratio(spec.role.lower(), title)
        score += 8 * max((pts for kw, pts in SENIORITY if kw in title), default=0)
    if company and any(s.is_current and s.company_id == company.company_id for s in p.stints):
        score += 40
    return score


def _range_low(r: str | None) -> int:
    m = re.match(r"(\d+)", (r or "").replace(",", ""))
    return int(m.group(1)) if m else 0
