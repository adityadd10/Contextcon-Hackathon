"""Crustdata API client: retries, per-endpoint pacing, disk cache, audit trail, credit budget.

Usage:
    async with Crust() as c:
        rows = await c.person_enrich(["https://www.linkedin.com/in/abhilashchowdhary/"])
        person = to_person(rows[0]["matches"][0]["person_data"], "/person/enrich")

Docs: https://docs.crustdata.com/llms.txt  (headers: authorization Bearer + x-api-version 2025-11-01)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from .models import CallRecord, Company, Person, School, Stint

load_dotenv()

BASE_URL = "https://api.crustdata.com"
API_VERSION = "2025-11-01"
CACHE_DIR = Path(os.getenv("WARMPATH_CACHE_DIR", ".cache/crust"))

# requests/minute from the docs; we pace slightly under these
RPM = {
    "/person/search": 30, "/person/enrich": 15, "/company/identify": 30,
    "/company/enrich": 15, "/company/search": 30, "/job/search": 30,
    "/web/search/live": 10, "/web/enrich/live": 10,
}
PERSON_FIELDS = ["basic_profile", "experience", "education", "social_handles"]


class CrustError(Exception):
    def __init__(self, status: int, message: str, endpoint: str):
        super().__init__(f"{endpoint} → {status}: {message}")
        self.status, self.message, self.endpoint = status, message, endpoint


class BudgetExceeded(CrustError):
    pass


class Crust:
    def __init__(self, api_key: str | None = None, budget: float | None = None,
                 use_cache: bool | None = None, timeout: float = 45.0,
                 transport: httpx.AsyncBaseTransport | None = None, pace: bool = True):
        if transport is None and os.getenv("WARMPATH_FAKE") == "1":
            from .fake import FakeCrust  # offline demo world: no key, no credits
            transport, api_key, pace = FakeCrust(fail_first_with_429=False).transport(), "fake", False
        self.api_key = api_key or os.getenv("CRUSTDATA_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("CRUSTDATA_API_KEY missing: put it in .env (or WARMPATH_FAKE=1 for the offline demo world)")
        self.budget = budget if budget is not None else float(os.getenv("WARMPATH_BUDGET", "60"))
        self.use_cache = use_cache if use_cache is not None else os.getenv("WARMPATH_CACHE", "1") == "1"
        self.pace = pace
        self.audit: list[CallRecord] = []
        self.credits_used = 0.0
        self._last_call: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._client = httpx.AsyncClient(
            base_url=BASE_URL, timeout=timeout, transport=transport,
            headers={"authorization": f"Bearer {self.api_key}", "x-api-version": API_VERSION,
                     "content-type": "application/json"},
        )
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    async def __aenter__(self) -> "Crust":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------ core

    async def post(self, endpoint: str, body: dict, est_credits: float = 1.0) -> Any:
        key = hashlib.sha256(json.dumps([endpoint, body], sort_keys=True).encode()).hexdigest()[:24]
        cache_file = CACHE_DIR / f"{key}.json"
        call_id = f"c{len(self.audit) + 1:03d}"

        if self.use_cache and cache_file.exists():
            data = json.loads(cache_file.read_text())
            self._record(call_id, endpoint, body, 200, 0.0, data, cached=True)
            return data

        if self.credits_used + est_credits > self.budget:
            raise BudgetExceeded(402, f"run budget {self.budget} credits would be exceeded", endpoint)

        if self.pace:
            await self._pace(endpoint)
        last_err: CrustError | None = None
        for attempt in range(4):
            try:
                r = await self._client.post(endpoint, json=body)
            except httpx.HTTPError as e:  # network blip / timeout
                last_err = CrustError(0, f"{type(e).__name__}: {e}", endpoint)
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            credits = _float(r.headers.get("x-credits-used"))
            if r.status_code == 429 or r.status_code >= 500:
                ra = r.headers.get("retry-after")
                retry_after = _float(ra) if ra is not None else 2.0 * (attempt + 1)
                last_err = CrustError(r.status_code, r.text[:300], endpoint)
                await asyncio.sleep(min(retry_after, 20))
                continue
            try:
                data = r.json()
            except ValueError:
                data = {"raw": r.text}
            self.credits_used += credits
            if r.status_code >= 400:
                msg = (data.get("error") or {}).get("message", r.text[:300]) if isinstance(data, dict) else r.text[:300]
                self._record(call_id, endpoint, body, r.status_code, credits, data, error=msg)
                raise CrustError(r.status_code, msg, endpoint)
            self._record(call_id, endpoint, body, r.status_code, credits, data)
            if self.use_cache:
                cache_file.write_text(json.dumps(data))
            return data
        self._record(call_id, endpoint, body, last_err.status if last_err else 0, 0.0, None,
                     error=str(last_err))
        raise last_err or CrustError(0, "unknown failure", endpoint)

    async def _pace(self, endpoint: str) -> None:
        lock = self._locks.setdefault(endpoint, asyncio.Lock())
        async with lock:
            gap = 60.0 / (RPM.get(endpoint, 15) * 0.9)
            wait = self._last_call.get(endpoint, 0) + gap - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call[endpoint] = time.monotonic()

    def _record(self, call_id, endpoint, body, status, credits, data, cached=False, error=None):
        digest = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
        self.audit.append(CallRecord(call_id=call_id, endpoint=endpoint, request=body, status=status,
                                     credits=credits, sha256=digest, ts=time.time(),
                                     cached=cached, error=error))

    @property
    def last_call_id(self) -> str | None:
        return self.audit[-1].call_id if self.audit else None

    # ------------------------------------------------------------ endpoints

    async def person_enrich(self, profile_urls: list[str], fields: list[str] | None = None) -> list[dict]:
        return await self.post("/person/enrich", {
            "professional_network_profile_urls": profile_urls[:25],
            "fields": fields or PERSON_FIELDS,
        }, est_credits=len(profile_urls))

    async def person_search(self, filters: dict, limit: int = 25, fields: list[str] | None = None,
                            cursor: str | None = None) -> dict:
        body: dict[str, Any] = {"filters": filters, "limit": limit,
                                "fields": fields or ["crustdata_person_id", *PERSON_FIELDS]}
        if cursor:
            body["cursor"] = cursor
        # 0.03 base + 0.1 experience + 0.1 education (+0.1 per premium filter group): ~0.33/result upper-typical
        return await self.post("/person/search", body, est_credits=0.33 * limit)

    async def company_identify(self, *, names: list[str] | None = None, domains: list[str] | None = None,
                               profile_urls: list[str] | None = None) -> list[dict]:
        body = ({"domains": domains} if domains else
                {"professional_network_profile_urls": profile_urls} if profile_urls else {"names": names})
        return await self.post("/company/identify", body, est_credits=0)

    async def company_enrich(self, company_ids: list[int], fields: list[str] | None = None) -> list[dict]:
        return await self.post("/company/enrich", {
            "crustdata_company_ids": company_ids[:25], "fields": fields or ["basic_info", "headcount"],
        }, est_credits=2 * len(company_ids))

    async def web_search(self, query: str, sources: list[str] | None = None, site: str | None = None) -> dict:
        body: dict[str, Any] = {"query": query, "sources": sources or ["web"]}
        if site:
            body["site"] = site
        return await self.post("/web/search/live", body, est_credits=1)

    async def web_fetch(self, urls: list[str]) -> list[dict]:
        return await self.post("/web/enrich/live", {"urls": urls[:10]}, est_credits=len(urls))


# ---------------------------------------------------------------- filter helpers

def f(field: str, op: str, value: Any) -> dict:
    return {"field": field, "type": op, "value": value}


def all_of(*conds: dict) -> dict:
    conds = tuple(c for c in conds if c)
    return conds[0] if len(conds) == 1 else {"op": "and", "conditions": list(conds)}


def any_of(*conds: dict) -> dict:
    conds = tuple(c for c in conds if c)
    return conds[0] if len(conds) == 1 else {"op": "or", "conditions": list(conds)}


# ---------------------------------------------------------------- raw JSON → models

def parse_date(v: Any) -> date | None:
    if not v:
        return None
    if isinstance(v, (int, float)):
        if 1900 <= v <= 2100:                     # education uses start_year / end_year
            return date(int(v), 1, 1)
        return datetime.fromtimestamp(v).date()
    s = str(v)
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(s[:25] if "T" in s else s[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _stint(raw: dict, ref: str, is_current: bool) -> Stint:
    return Stint(
        company_name=raw.get("name") or raw.get("company_name") or "?",
        company_id=raw.get("crustdata_company_id") or raw.get("company_id"),
        title=raw.get("title"),
        start=parse_date(raw.get("start_date")),
        end=None if is_current else parse_date(raw.get("end_date")),
        is_current=is_current,
        function=raw.get("function_category"),
        seniority=raw.get("seniority_level"),
        location=raw.get("location") if isinstance(raw.get("location"), str) else None,
        company_headcount=raw.get("company_headcount_latest"),
        ref=ref,
    )


GENERIC_EMPLOYERS = re.compile(
    r"^\s*(self[\s-]?employed|freelanc\w*|independent( consultant)?|stealth( mode)?( startup)?|confidential|"
    r"various|n/?a|none|unemployed|career break|own business|personal|private practice|startup)\s*$", re.I)


def is_generic_employer(name: str | None) -> bool:
    """'Self-employed' etc. are not shared workplaces, so two freelancers never 'worked together'."""
    return not name or bool(GENERIC_EMPLOYERS.match(name))


def to_person(pd: dict, endpoint: str) -> Person:
    """Map a Crustdata person_data / search profile dict to Person. Tolerates missing sections."""
    bp = pd.get("basic_profile") or {}
    pid = pd.get("crustdata_person_id")
    tag = f"person:{pid}"
    emp = (pd.get("experience") or {}).get("employment_details") or {}
    stints = [_stint(r, f"{tag}#experience.current[{i}]", True) for i, r in enumerate(emp.get("current") or [])]
    stints += [_stint(r, f"{tag}#experience.past[{i}]", False) for i, r in enumerate(emp.get("past") or [])]
    stints = [st for st in stints if not is_generic_employer(st.company_name)]
    schools = [School(name=s.get("school") or "?", degree=s.get("degree"), field_of_study=s.get("field_of_study"),
                      start=parse_date(s.get("start_date") or s.get("start_year")),
                      end=parse_date(s.get("end_date") or s.get("end_year")),
                      ref=f"{tag}#education.schools[{i}]")
               for i, s in enumerate((pd.get("education") or {}).get("schools") or [])]
    loc = bp.get("location")
    handles = (pd.get("social_handles") or {}).get("professional_network_identifier") or {}
    return Person(
        name=bp.get("name") or "?", person_id=pid, headline=bp.get("headline"),
        current_title=bp.get("current_title") or (stints[0].title if stints else None),
        location=(loc.get("raw") or loc.get("full_location")) if isinstance(loc, dict) else loc,
        profile_url=handles.get("profile_url"), stints=stints, schools=schools,
        last_updated=bp.get("last_updated"), source_endpoint=endpoint,
    )


def to_company(match: dict) -> Company:
    cd = match.get("company_data") or match
    bi = cd.get("basic_info") or {}
    hc = cd.get("headcount") or {}
    return Company(
        name=bi.get("name") or "?", company_id=cd.get("crustdata_company_id") or bi.get("crustdata_company_id"),
        domain=bi.get("primary_domain"), profile_url=bi.get("professional_network_url"),
        headcount=hc.get("total") if isinstance(hc, dict) else None,
        employee_count_range=bi.get("employee_count_range"), year_founded=bi.get("year_founded"),
        industries=bi.get("industries") or [], confidence=match.get("confidence_score"),
    )
