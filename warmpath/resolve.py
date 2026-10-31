"""Resolve the target company + person from a TargetSpec.  Owner: Member A."""
from __future__ import annotations

import re
from datetime import date

from rapidfuzz import fuzz

from . import events as ev
from .crust import Crust, CrustError, all_of, any_of, f, to_company, to_person
from .events import Emit
from .models import Company, Person, TargetSpec

SENIORITY = [("chief", 6), ("cxo", 6), ("cto", 6), ("ceo", 6), ("founder", 5), ("vp", 5), ("vice president", 5),
             ("head", 5), ("director", 4), ("principal", 3), ("lead", 3), ("manager", 2), ("senior", 1)]
STOP = {"the", "of", "at", "for", "and", "whoever", "runs", "leads", "heads", "person", "someone", "guy", "girl"}


LEGAL = re.compile(r"\b(inc|llc|ltd|limited|pvt|private|corp|corporation|technologies|technology|labs|co)\b\.?", re.I)


async def resolve_company(c: Crust, query: str, emit: Emit) -> Company | None:
    """Resolve a messy company mention. Fallback chain, cheapest first:
    identify(as typed) → identify(cleaned name) → identify(guessed domains) → web search for the company page →
    identify(profile URL). Identify calls are free; the web search costs 1 credit."""
    q = query.strip().strip(".,")
    tried: list[str] = []

    async def attempt(label: str, **kw) -> list[dict]:
        tried.append(label)
        try:
            rows = await c.company_identify(**kw)
        except CrustError as e:
            ev.warn(emit, f"Company identify failed for '{label}': {e.message}")
            return []
        return [m for row in rows or [] for m in (row.get("matches") or [])]

    matches: list[dict] = []
    if re.search(r"linkedin\.com/company/", q):
        matches = await attempt(q, profile_urls=[q])
    elif re.fullmatch(r"(https?://)?(www\.)?[\w\-]+\.[a-z.]{2,}/?", q, re.I):
        matches = await attempt(q, domains=[re.sub(r"^(https?://)?(www\.)?", "", q).strip("/")])
    else:
        matches = await attempt(q, names=[q])
        clean = " ".join(LEGAL.sub("", q).split()).title()
        if not matches and clean and clean != q:
            matches = await attempt(clean, names=[clean])
        slug = re.sub(r"[^a-z0-9]", "", clean.lower())
        if not matches and slug:
            matches = await attempt(f"{slug}.com/.in/.io/.ai",
                                    domains=[f"{slug}.com", f"{slug}.in", f"{slug}.io", f"{slug}.ai"])
        if not matches and slug:  # typos ("swigy") and unusual names: let web search find the company page
            try:
                res = await c.web_search(f"{clean or q} company", site="linkedin.com/company")
                url = next((r["url"] for r in res.get("results") or [] if "linkedin.com/company/" in r.get("url", "")), None)
            except CrustError:
                url = None
            if url:
                matches = await attempt(url, profile_urls=[url])
    if not matches:
        ev.warn(emit, f"No company in Crustdata matches '{q}' (tried: {'; '.join(tried)})")
        return None
    cands = [to_company(m) for m in matches[:5]]
    # prefer the strongest match, then the closest name, then the biggest company (the famous one is usually meant)
    best = max(cands, key=lambda co: ((co.confidence or 0), fuzz.ratio(co.name.lower(), q.lower()),
                                      _range_low(co.employee_count_range)))
    if len(tried) > 1:
        ev.step(emit, "resolve", "progress", f"'{q}' resolved via fallback",
                f"→ {best.name} after: {' → '.join(tried)}")
    return best


ROLE_ACRONYMS = {"cto": "chief technology officer", "ceo": "chief executive officer", "cfo": "chief financial officer",
                 "coo": "chief operating officer", "cpo": "chief product officer", "cmo": "chief marketing officer",
                 "cio": "chief information officer", "chro": "chief human resources officer", "cdo": "chief data officer",
                 "ciso": "chief information security officer", "vp": "vice president", "svp": "senior vice president",
                 "md": "managing director", "gm": "general manager", "em": "engineering manager", "pm": "product manager"}


async def resolve_target(c: Crust, spec: TargetSpec, emit: Emit) -> tuple[Person | None, Company | None]:
    if not (spec.person_name or spec.role or spec.company or spec.profile_url or _bare_profile_url(spec.raw)):
        bare = " ".join(re.sub(r"[^\w&.\- ]", " ", spec.raw or "").split())
        if 0 < len(bare.split()) <= 4:  # "Swiggy", "Zepto Pvt Ltd": a bare company name
            spec.company = bare
            ev.step(emit, "resolve", "progress", f"Treating '{bare}' as a company", "no person or role was given")
    company = await resolve_company(c, spec.company, emit) if spec.company else None
    if company:
        ev.step(emit, "resolve", "progress", "Resolved company",
                f"{company.name} (crustdata_company_id {company.company_id}, {company.employee_count_range or '?'} people)")

    url = spec.profile_url or _bare_profile_url(spec.raw)
    if url:
        return await enrich_one(c, normalize_profile_url(url), emit), company

    if company and not spec.person_name and not spec.role:
        # "intro to Swiggy": nobody named, so default to the company's leadership and say so
        spec.role = "founder ceo"
        ev.step(emit, "resolve", "progress", "No person or role given",
                f"defaulting to {company.name}'s leadership (founder / CEO); name a role to change this")

    cands: list[dict] = []
    if spec.person_name:
        name_exact = f("basic_profile.name", "[.]", spec.person_name)   # (.) is fuzzy: "Kunal" also hits "Krunal"
        at_co = f("experience.employment_details.company_id", "=", company.company_id) if company and company.company_id else None
        cands = await _search(c, all_of(name_exact, at_co) if at_co else name_exact, emit)
        if not cands and at_co:
            cands = await _search(c, all_of(f("basic_profile.name", "(.)", spec.person_name), at_co), emit)
        if not cands and company:  # not indexed under that company: find their profile on the web, then enrich
            found = await _web_profile(c, spec.person_name, company.name, emit)
            if found:
                return found, company
        if not cands:
            cands = await _search(c, name_exact, emit)
    elif spec.role and company and company.company_id:
        expanded = " ".join(ROLE_ACRONYMS.get(w, w) for w in spec.role.lower().split())
        if expanded != spec.role.lower() and spec.role != "founder ceo":
            ev.step(emit, "resolve", "progress", f"Reading '{spec.role}' as '{expanded}'")
            spec.role = expanded
        words = [w for w in re.findall(r"[a-z]+", spec.role.lower()) if w not in STOP]
        seniority_words = {kw for kw, _ in SENIORITY}
        topic = [w for w in words if w not in seniority_words] or words
        # strict → loose → topic word only (then rank by seniority). Live data: Swiggy has nobody titled exactly
        # "Head of Data", but 300+ current titles containing "data", among them the real data leaders.
        topic_word = max(topic, key=len) if topic else spec.role
        senior = any_of(*(f("experience.employment_details.current.title", "[.]", w)
                          for w in ("head", "vp", "vice president", "director", "chief", "lead", "principal")))
        if spec.role == "founder ceo":
            attempts = [("leadership title", any_of(*(f("experience.employment_details.current.title", "[.]", w)
                                                     for w in ("founder", "ceo", "chief executive", "managing director"))), 25)]
        else:
            attempts = []
        attempts += [("exact title", f("experience.employment_details.current.title", "[.]", spec.role), 10),
                    (f"'{topic_word}' + senior title", all_of(f("experience.employment_details.current.title", "[.]",
                                                                 topic_word), senior), 25),
                    ("all words", f("experience.employment_details.current.title", "(.)", " ".join(words)), 10),
                    (f"'{max(topic, key=len)}' + seniority", f("experience.employment_details.current.title", "[.]",
                                                            max(topic, key=len)), 25)]
        for label, title_cond, lim in attempts:
            cands = await _search(c, all_of(f("experience.employment_details.current.company_id", "=",
                                              company.company_id), title_cond), emit, limit=lim)
            if cands:
                if label != "exact title":
                    ev.step(emit, "resolve", "progress", f"No exact '{spec.role}' title, matched by {label}",
                            f"{len(cands)} candidates at {company.name}")
                break
    if not cands:
        who = spec.person_name and f"anyone named '{spec.person_name}'" or spec.role and f"a '{spec.role}'" or "the person"
        where = f" at {company.name}" if company else ""
        hint = "" if company or not spec.company else f" (and the company '{spec.company}' wasn't found)"
        ev.warn(emit, f"Crustdata has no record of {who}{where}{hint}. Check the spelling, or paste a LinkedIn profile URL.")
        return None, company

    people = [to_person(p, "/person/search") for p in cands]
    ranked = sorted(people, key=lambda p: -_target_rank(p, spec, company))
    best = ranked[0]
    why = []
    if company and any(st.is_current and st.company_id == company.company_id for st in best.stints):
        why.append(f"currently at {company.name}")
    elif company and any(st.company_id == company.company_id for st in best.stints):
        why.append(f"was at {company.name} (may have moved on)")
        ev.warn(emit, f"{best.name} is no longer at {company.name} according to Crustdata. The intro may be outdated.")
    elif company:
        why.append(f"no {company.name} role on record")
        ev.warn(emit, f"No '{spec.person_name or spec.role}' with {company.name} in their history is in Crustdata. "
                      f"Best match is {best.name} ({best.current_title or 'unknown role'}), who may be a different "
                      f"person. Paste their LinkedIn URL to be sure.")
    if spec.role:
        why.append(f"title '{best.current_title}' best matches '{spec.role}'")
    ev.step(emit, "resolve", "progress", "Picked target",
            f"{best.name} · {best.current_title or ''} (best of {len(people)} candidates"
            + (f"; {', '.join(why)}" if why else "") + ")")
    if len(ranked) > 1 and spec.person_name and not company:
        ev.warn(emit, f"{len(ranked)} people match '{spec.person_name}' and no company was given. "
                      f"Picked {best.name} ({best.current_title}). Add the company to be sure.")
    # search profiles can be partial; enrich for the full dated career
    if best.profile_url:
        full = await enrich_one(c, best.profile_url, emit)
        if full and full.stints:
            return full, company
    return best, company


async def _web_profile(c: Crust, name: str, company: str, emit: Emit) -> Person | None:
    """Crustdata Web Search for the person's profile page, then enrich it (2 credits). Only accepts a page whose
    title carries the full name, and a profile that actually lists the company."""
    try:
        res = await c.web_search(f'"{name}" {company}', site="linkedin.com/in")
    except CrustError:
        return None
    for r in (res.get("results") or [])[:5]:
        url, title = r.get("url") or "", (r.get("title") or "").lower()
        if "linkedin.com/in/" in url and all(part in title for part in name.lower().split()):
            p = await enrich_one(c, normalize_profile_url(url), emit)
            if p and any(fuzz.token_set_ratio(company.lower(), st.company_name.lower()) >= 85 for st in p.stints):
                ev.step(emit, "resolve", "progress", f"Found {p.name} via web search",
                        f"not indexed under {company}; profile located with /web/search/live, then enriched")
                return p
    return None


BARE_PROFILE = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/([\w\-%]+)", re.I)


def _bare_profile_url(text: str) -> str | None:
    m = BARE_PROFILE.search(text or "")
    return m.group(0) if m else None


def normalize_profile_url(url: str) -> str:
    """'linkedin.com/in/x', 'in.linkedin.com/in/x?trk=..' → 'https://www.linkedin.com/in/x/'"""
    m = BARE_PROFILE.search(url)
    return f"https://www.linkedin.com/in/{m.group(1)}/" if m else url.strip()


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
    # thin records (1 role, no school) are often mis-attributed: prefer well-documented profiles
    score += 3 * min(len(p.stints), 6) + (4 if p.schools else 0)
    if company and spec.role == "founder ceo":
        here = [s for s in p.stints if s.company_id == company.company_id and s.start]
        if here:  # leadership default: founders and long-tenured leaders of *this* company first
            months = max(((s.end or date.today()) - s.start).days / 30.44 for s in here)
            score += min(months, 120) / 3 + (25 if any("found" in (s.title or "").lower() for s in here) else 0)
    return score


def _range_low(r: str | None) -> int:
    m = re.match(r"(\d+)", (r or "").replace(",", ""))
    return int(m.group(1)) if m else 0
