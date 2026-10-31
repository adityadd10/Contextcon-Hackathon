"""Offline fake of the Crustdata API (WARMPATH_FAKE=1). An in-memory fake (response shapes copied from docs.crustdata.com).

Lets the whole pipeline run offline: `Crust(api_key="x", transport=FakeCrust().transport())`.
Implements a small filter evaluator: =, in, (.), [.], =>, =< plus and/or groups.
"""
from __future__ import annotations

import json
import re

import httpx

COMPANIES = {
    1001: {"name": "Swiggy", "primary_domain": "swiggy.com", "employee_count_range": "5001-10000", "headcount": 6000},
    2002: {"name": "Tiny Analytics", "primary_domain": "tinyanalytics.io", "employee_count_range": "11-50", "headcount": 30},
    3003: {"name": "Flipkart", "primary_domain": "flipkart.com", "employee_count_range": "10001+", "headcount": 30000},
    4004: {"name": "SeedCo", "primary_domain": "seedco.in", "employee_count_range": "11-50", "headcount": 25},
}


def role(cid, title, start, end=None, function="Data"):
    return {"name": COMPANIES[cid]["name"], "crustdata_company_id": cid, "title": title,
            "start_date": f"{start}T00:00:00+00:00", "end_date": f"{end}T00:00:00+00:00" if end else None,
            "function_category": function, "company_headcount_latest": COMPANIES[cid]["headcount"]}


def person(pid, name, title, roles, schools=(), slug=None):
    current = [r for r in roles if not r["end_date"]]
    past = [r for r in roles if r["end_date"]]
    return {"crustdata_person_id": pid,
            "basic_profile": {"name": name, "headline": title, "current_title": title,
                              "location": {"raw": "Bengaluru, Karnataka, India"},
                              "last_updated": "2026-10-01T00:00:00Z"},
            "social_handles": {"professional_network_identifier": {
                "profile_url": f"https://www.linkedin.com/in/{slug or name.lower().replace(' ', '-')}"}},
            "experience": {"employment_details": {"current": current, "past": past}},
            "education": {"schools": [{"school": s, "degree": "B.Tech", "start_date": f"{y}-07-01",
                                       "end_date": f"{y + 4}-05-01"} for s, y in schools]}}


PEOPLE = [
    person(1, "Priya Sharma", "Head of Data", [role(1001, "Head of Data", "2022-03-01"),
                                               role(2002, "Data Lead", "2018-01-01", "2022-02-01"),
                                               role(3003, "Data Scientist", "2015-06-01", "2017-12-01")],
           [("Indian Institute of Technology Bombay", 2011)]),
    person(2, "Rahul Verma", "Staff Engineer", [role(4004, "Staff Engineer", "2022-04-01", function="Engineering"),
                                                 role(2002, "Data Engineer", "2018-06-01", "2022-03-01")],
           [("IIT Bombay", 2013)]),
    person(3, "Neha Iyer", "Product Manager", [role(3003, "Analyst", "2016-01-01", "2017-06-01"),
                                               role(1001, "PM", "2019-01-01", "2020-01-01", "Product")],
           [("IIT Bombay", 2012)]),
    person(4, "Arjun Rao", "Data Engineer", [role(1001, "Data Engineer", "2023-01-01")], [("BITS Pilani", 2015)]),
    person(5, "Priya Sharma", "Teacher", [role(3003, "Trainer", "2010-01-01", "2011-01-01", "Education")]),
    person(9, "Aditya Seed", "Founder", [role(4004, "Founder", "2021-01-01", function="Engineering")],
           [("IIT Bombay", 2018)], slug="aditya-seed"),
]
REDACTED = "https://www.linkedin.com/in/redacted-person"


def get(d, path):
    """Collect every value at a dotted path, flattening lists (current+past for employment_details)."""
    vals = [d]
    for part in path.split("."):
        nxt = []
        for v in vals:
            if isinstance(v, list):
                v = [x.get(part) if isinstance(x, dict) else None for x in v]
                nxt += [x for x in v if x is not None]
            elif isinstance(v, dict):
                if part not in v and "current" in v and "past" in v:   # employment_details.X = any role
                    key = "crustdata_company_id" if part == "company_id" else part
                    nxt += [r.get(key) for r in (v["current"] or []) + (v["past"] or [])]
                elif part == "company_id" and "crustdata_company_id" in v:
                    nxt.append(v["crustdata_company_id"])
                else:
                    nxt.append(v.get(part))
        vals = []
        for x in nxt:
            (vals.extend if isinstance(x, list) else vals.append)(x) if x is not None else None
    return vals


def match(p, flt):
    if "op" in flt:
        res = [match(p, c) for c in flt["conditions"]]
        return all(res) if flt["op"] == "and" else any(res)
    vals, op, want = get(p, flt["field"]), flt["type"], flt["value"]
    low = [str(v).lower() for v in vals]
    if op == "=":
        return any(v == want or str(v).lower() == str(want).lower() for v in vals)
    if op == "in":
        return any(v in want for v in vals)
    if op == "(.)":
        words = re.findall(r"\w+", str(want).lower())
        return any(all(w in v for w in words) for v in low)
    if op == "[.]":
        return any(str(want).lower() in v for v in low)
    if op in ("=>", "=<"):
        return any((str(v) >= str(want)) if op == "=>" else (str(v) <= str(want)) for v in vals)
    raise ValueError(f"unsupported op {op}")


class FakeCrust:
    def __init__(self, fail_first_with_429: bool = True):
        self.calls: list[tuple[str, dict]] = []
        self._429 = fail_first_with_429

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content or b"{}")
        path = req.url.path
        self.calls.append((path, body))
        if self._429:
            self._429 = False
            return httpx.Response(429, headers={"retry-after": "0"}, json={"error": {"message": "slow down"}})
        hdr = {"x-credits-used": "1"}
        if path == "/company/identify":
            key, vals = next(iter(body.items()))
            out = []
            for v in vals:
                ms = [{"confidence_score": 0.9, "company_data": {"crustdata_company_id": cid, "basic_info": {
                    "crustdata_company_id": cid, **{k: c[k] for k in ("name", "primary_domain", "employee_count_range")}}}}
                      for cid, c in COMPANIES.items()
                      if str(v).lower() in (c["name"].lower(), c["primary_domain"],
                                            f"https://www.linkedin.com/company/{c['primary_domain'].split('.')[0]}")]
                out.append({"matched_on": v, "match_type": key[:-1], "matches": ms})
            return httpx.Response(200, json=out, headers={"x-credits-used": "0"})
        if path == "/person/search":
            hits = [p for p in PEOPLE if match(p, body["filters"])][: body.get("limit", 25)]
            return httpx.Response(200, json={"profiles": hits, "next_cursor": None, "total_count": len(hits)},
                                  headers={"x-credits-used": str(0.23 * len(hits))})
        if path == "/person/enrich":
            out = []
            for url in body["professional_network_profile_urls"]:
                if url.rstrip("/").lower() == REDACTED.lower():
                    out.append({"matched_on": url, "match_status": "redacted", "matches": []})
                    continue
                p = next((p for p in PEOPLE if p["social_handles"]["professional_network_identifier"]["profile_url"]
                          .rstrip("/") == url.rstrip("/")), None)
                out.append({"matched_on": url, "match_type": "professional_network_profile_url",
                            "match_status": "matched" if p else "not_found",
                            "matches": [{"confidence_score": 1.0, "person_data": p}] if p else []})
            return httpx.Response(200, json=out, headers=hdr)
        if path == "/web/search/live":
            q = body["query"]
            res = []
            if body.get("site") == "linkedin.com/company":
                from rapidfuzz import fuzz
                term = q.replace(" company", "").lower()
                res = [{"source": "web", "title": c["name"], "url": f"https://www.linkedin.com/company/{c['primary_domain'].split('.')[0]}",
                        "snippet": "", "position": 1} for c in COMPANIES.values() if fuzz.ratio(term, c["name"].lower()) >= 75]
            if "Rahul Verma" in q and "Priya Sharma" in q:
                res = [{"source": "web", "title": "Rahul Verma and Priya Sharma talk data at Tiny Analytics",
                        "url": "https://blog.tinyanalytics.io/team", "snippet": "Rahul Verma and Priya Sharma ...",
                        "position": 1}]
            return httpx.Response(200, json={"success": True, "query": q, "results": res}, headers=hdr)
        return httpx.Response(404, json={"error": {"type": "not_found", "message": path}})
