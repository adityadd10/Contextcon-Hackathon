"""Free-text request → TargetSpec.  Owner: Member B.

LLM first (OpenRouter), rule-based fallback always available.
"""
from __future__ import annotations

import re

from . import llm
from .models import NetworkSpec, TargetSpec

PROFILE_RE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[\w\-%]+/?", re.I)
DOMAIN_RE = re.compile(r"\b([a-z0-9\-]+\.(?:com|io|ai|in|co|org|net|app|dev|tech))\b", re.I)
SCHOOL_ALIASES = {
    "iitb": "IIT Bombay", "iit bombay": "IIT Bombay", "iit-b": "IIT Bombay", "iit delhi": "IIT Delhi",
    "iitd": "IIT Delhi", "iit madras": "IIT Madras", "iitm": "IIT Madras", "iit kanpur": "IIT Kanpur",
    "iit kharagpur": "IIT Kharagpur", "bits pilani": "BITS Pilani", "stanford": "Stanford University",
    "iim ahmedabad": "IIM Ahmedabad", "iima": "IIM Ahmedabad", "mit": "Massachusetts Institute of Technology",
}
PURPOSE_WORDS = {
    "hiring": ["hire", "hiring", "recruit", "candidate"],
    "sales": ["sell", "sales", "demo", "pitch", "customer", "buyer"],
    "fundraising": ["raise", "fundrais", "investor", "vc", "seed round", "series"],
    "referral": ["referral", "refer me", "job at", "internship", "intern"],
}

SYSTEM = """You turn a request for a warm introduction into JSON with keys:
person_name (string|null), profile_url (string|null), company (string|null: company name or domain),
role (string|null: the role/title of the person to reach if no name given, e.g. "head of data"),
purpose (one of hiring|sales|fundraising|referral|other),
schools (list of school names the intro path should go through, expanded e.g. "IITB" -> "IIT Bombay"),
companies (list of companies the intro path should go through), max_paths (int, default 5).
Use null when unknown. Never invent names."""


async def parse_request(text: str) -> TargetSpec:
    spec = parse_rules(text)
    data = await llm.complete_json(SYSTEM, text) if llm.available() else None
    if not data:
        return spec
    spec.person_name = data.get("person_name") or spec.person_name
    spec.profile_url = spec.profile_url or data.get("profile_url")
    spec.company = data.get("company") or spec.company
    spec.role = data.get("role") or spec.role
    if data.get("purpose") in PURPOSE_WORDS or data.get("purpose") == "other":
        spec.purpose = data["purpose"]
    spec.network.schools = _dedupe([*spec.network.schools, *(data.get("schools") or [])])
    spec.network.companies = _dedupe([*spec.network.companies, *(data.get("companies") or [])])
    if isinstance(data.get("max_paths"), int):
        spec.max_paths = max(1, min(10, data["max_paths"]))
    spec.parser = "llm"
    return spec


def parse_rules(text: str) -> TargetSpec:
    t = " ".join(text.split())
    low = t.lower()
    spec = TargetSpec(raw=text, network=NetworkSpec())
    urls = PROFILE_RE.findall(t)
    if urls:
        spec.profile_url = urls[0]
        spec.network.seed_profile_urls = urls[1:]
    for alias, canon in SCHOOL_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", low):
            spec.network.schools.append(canon)
    spec.network.schools = _dedupe(spec.network.schools)
    for purpose, words in PURPOSE_WORDS.items():
        if any(w in low for w in words):
            spec.purpose = purpose  # type: ignore[assignment]
            break
    # "<role> at <Company>" / "<Name> from <Company>"
    m = re.search(r"\b(?:at|from|@)\s+([A-Z0-9][\w&.\-]*(?:\s+[A-Z][\w&.\-]*)*)", t)
    if m:
        spec.company = m.group(1).strip(" .,")
    elif (d := DOMAIN_RE.search(t)) and "linkedin" not in d.group(1).lower():
        spec.company = d.group(1)
    m = re.search(r"\b(?:to|reach|meet)\s+(?:the\s+|whoever\s+(?:runs|leads|heads)\s+)?([a-z][\w\s\-/]{2,40}?)\s+(?:at|of|from|@)\s",
                  t, re.I)
    if m:
        role = m.group(1).strip()
        if role.split()[0][:1].isupper() and len(role.split()) <= 3 and not _looks_like_role(role):
            spec.person_name = role
        else:
            spec.role = role
    return spec


def _looks_like_role(s: str) -> bool:
    return bool(re.search(r"head|vp|director|cto|ceo|cfo|founder|lead|manager|engineer|data|product|recruit|"
                          r"design|market|sales|growth|partner", s, re.I))


def _dedupe(xs: list[str]) -> list[str]:
    seen, out = set(), []
    for x in xs:
        if x and x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out
