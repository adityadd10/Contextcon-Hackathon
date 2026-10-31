"""Shared data contracts. Every module talks in these types — change them only with team agreement.

All dataclasses are JSON-serialisable via `to_dict()` (dates become ISO strings).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal


def to_dict(obj: Any) -> Any:
    """Recursively convert dataclasses/dates to plain JSON-safe structures."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_dict(v) for v in obj]
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


# ---------------------------------------------------------------- citations

@dataclass
class Evidence:
    """One verifiable fact. Every factor, tie and draft sentence must point at Evidence."""
    claim: str                                   # human sentence, e.g. "Rahul worked at Flipkart 2019-03 → 2021-06"
    kind: Literal["crustdata", "web", "derived"]
    endpoint: str                                # "/person/enrich", "/web/search/live", or "computed"
    ref: str                                     # record path, e.g. "person:1068035#experience.past[2]"
    url: str | None = None                       # clickable source (profile URL / web page)
    call_id: str | None = None                   # links to CallRecord.call_id in the audit trail


@dataclass
class CallRecord:
    """Audit-trail entry for one Crustdata/LLM call (tamper-evident via response sha256)."""
    call_id: str
    endpoint: str
    request: dict
    status: int
    credits: float
    sha256: str
    ts: float
    cached: bool = False
    error: str | None = None


# ---------------------------------------------------------------- entities

@dataclass
class Stint:
    """One role at one employer."""
    company_name: str
    company_id: int | None = None                # canonical crustdata_company_id — THE join key
    title: str | None = None
    start: date | None = None
    end: date | None = None                      # None = current / present
    is_current: bool = False
    function: str | None = None                  # function_category
    seniority: str | None = None                 # seniority_level
    location: str | None = None
    company_headcount: int | None = None         # latest headcount if known
    ref: str = ""                                # e.g. "person:123#experience.past[2]"


@dataclass
class School:
    name: str
    degree: str | None = None
    field_of_study: str | None = None
    start: date | None = None
    end: date | None = None
    ref: str = ""


@dataclass
class Person:
    name: str
    person_id: int | None = None                 # crustdata_person_id
    headline: str | None = None
    current_title: str | None = None
    location: str | None = None
    profile_url: str | None = None
    stints: list[Stint] = field(default_factory=list)
    schools: list[School] = field(default_factory=list)
    last_updated: str | None = None
    source_endpoint: str = ""                    # where this record came from


@dataclass
class Company:
    name: str
    company_id: int | None = None
    domain: str | None = None
    profile_url: str | None = None
    headcount: int | None = None
    employee_count_range: str | None = None
    year_founded: int | None = None
    industries: list[str] = field(default_factory=list)
    confidence: float | None = None


# ---------------------------------------------------------------- request

@dataclass
class NetworkSpec:
    """Who counts as 'reachable by me'."""
    schools: list[str] = field(default_factory=list)            # e.g. ["IIT Bombay"]
    companies: list[str] = field(default_factory=list)          # e.g. ex-employers of the team
    seed_profile_urls: list[str] = field(default_factory=list)  # the team's own LinkedIn URLs


@dataclass
class TargetSpec:
    """Parsed form of the user's free-text request (output of parse.py)."""
    raw: str
    person_name: str | None = None
    profile_url: str | None = None
    company: str | None = None                   # name / domain / URL as typed
    role: str | None = None                      # e.g. "head of data"
    purpose: Literal["hiring", "sales", "fundraising", "referral", "other"] = "other"
    network: NetworkSpec = field(default_factory=NetworkSpec)
    max_paths: int = 5
    parser: Literal["llm", "rules"] = "rules"


# ---------------------------------------------------------------- graph

@dataclass
class Overlap:
    company_name: str
    company_id: int | None
    start: date
    end: date
    months: float
    a_stint_ref: str
    b_stint_ref: str


@dataclass
class Factor:
    """One explainable component of a tie score."""
    name: str                                    # "overlap_months", "company_size", "same_function", ...
    value: Any
    contribution: float                          # points added to the 0-100 score
    explanation: str
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class Tie:
    """Edge between two people: how well they likely know each other."""
    a: Person
    b: Person
    score: float                                 # 0-100
    factors: list[Factor] = field(default_factory=list)
    overlaps: list[Overlap] = field(default_factory=list)
    kind: Literal["colleague", "classmate", "web", "self"] = "colleague"
    verified: bool = False                       # re-checked against full /person/enrich records (verify.py)
    verification: str = ""                       # how it was verified, or why it was dropped


@dataclass
class IntroPath:
    """Ordered chain: nodes[0] = you/network entry … nodes[-1] = target."""
    nodes: list[Person]
    ties: list[Tie]
    score: float                                 # 0-100, path strength
    why: str                                     # one-line rationale
    rank: int = 0


@dataclass
class Draft:
    path_rank: int
    to: str                                      # connector name (never sent — local outbox only)
    subject: str
    body: str
    forwardable_blurb: str
    claims_checked: int = 0
    claims_unsupported: list[str] = field(default_factory=list)
    citations: list[Evidence] = field(default_factory=list)      # the records the draft's facts come from
    llm_rejected: list[str] = field(default_factory=list)        # LLM sentences dropped by check_claims


@dataclass
class RunResult:
    request: str
    spec: TargetSpec
    target: Person | None
    target_company: Company | None
    paths: list[IntroPath] = field(default_factory=list)
    drafts: list[Draft] = field(default_factory=list)
    audit: list[CallRecord] = field(default_factory=list)
    credits_used: float = 0.0
    warnings: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
