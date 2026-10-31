"""Messy-request suite for the rule-based parser (no LLM, no network)."""
import asyncio

import pytest

from warmpath import llm
from warmpath.parse import parse_request, parse_rules


def _low(x):
    return (x or "").lower()


# (request, expected fields). Values are checked case-insensitively; "role~" means "role contains".
CASES = [
    ("get me a warm intro to whoever runs data at Swiggy, ideally via IITB folks",
     {"company": "swiggy", "role~": "data", "schools": ["IIT Bombay"]}),
    ("teh data guy at swiggy pls",
     {"company": "swiggy", "role~": "data", "person_name": None}),
    ("intro to https://www.linkedin.com/in/someone/ for hiring",
     {"profile_url": "https://www.linkedin.com/in/someone/", "purpose": "hiring"}),
    ("Need to reach the CTO of Zepto for a sales demo",
     {"company": "zepto", "role": "cto", "purpose": "sales"}),
    ("connect me with Kunal Shah from CRED",
     {"company": "cred", "person_name": "kunal shah", "role": None}),
    ("warm intro to head of engg @ razorpay.com",
     {"company": "razorpay.com", "role": "head of engineering"}),
    ("swiggy mein data head se intro karwa do yaar",
     {"company": "swiggy", "role": "data head"}),
    ("who can introduce me to the VP Product at Meesho? we're raising our seed round",
     {"company": "meesho", "role": "vp product", "purpose": "fundraising"}),
    ("intro to someone senior in growth at https://www.linkedin.com/company/zomato/",
     {"company": "https://www.linkedin.com/company/zomato/", "role~": "growth"}),
    ("Looking for a referral for an internship at Google via IIT Bombay alumni",
     {"company": "google", "purpose": "referral", "schools": ["IIT Bombay"], "role": None}),
    ("intro to Nithin Kamath (Zerodha)",
     {"company": "zerodha", "person_name": "nithin kamath"}),
    ("hiring manager for ML at flipkart, through ex-Microsoft folks",
     {"company": "flipkart", "role~": "manager", "companies": ["Microsoft"]}),
    ("get me to Sriharsha Majety",
     {"person_name": "sriharsha majety", "company": None}),
    ("   INTRO TO THE CFO AT PHONEPE!!!   ",
     {"company": "phonepe", "role": "cfo"}),
    ("can sum1 intro me 2 da founder of zepto plz, via iit-b ppl",
     {"company": "zepto", "role": "founder", "schools": ["IIT Bombay"]}),
    ("मुझे Swiggy के head of data से मिलवाओ",
     {"company": "swiggy", "role": "head of data"}),
    ("मुझे IITB वालों के through Zomato के CTO से intro चाहिए",
     {"company": "zomato", "role": "cto", "schools": ["IIT Bombay"]}),
    ("Swiggy", {"company": "swiggy", "role": None, "person_name": None}),
    ("Zepto CTO", {"company": "zepto", "role": "cto"}),
    ("Urban Company", {"company": "urban company"}),
    ("intro to Aditya at Razorpay, he was at IIT Delhi",
     {"company": "razorpay", "person_name": "aditya", "schools": ["IIT Delhi"]}),
]


@pytest.mark.parametrize("text,exp", CASES, ids=[c[0][:40] for c in CASES])
def test_messy_requests(text, exp):
    s = parse_rules(text)
    got = {"company": s.company, "role": s.role, "person_name": s.person_name, "profile_url": s.profile_url,
           "purpose": s.purpose, "schools": s.network.schools, "companies": s.network.companies}
    for key, want in exp.items():
        if key.endswith("~"):
            assert want in _low(got[key[:-1]]), (key, got)
        elif isinstance(want, list):
            assert got[key] == want, (key, got)
        elif want is None:
            assert got[key] is None, (key, got)
        else:
            assert _low(got[key]) == want, (key, got)
    assert s.parser == "rules"


def test_llm_cannot_invent_a_name(monkeypatch):
    async def fake(*_a, **_k):
        return {"person_name": "Priya Raman", "company": "Swiggy", "role": "head of data", "purpose": "sales"}
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete_json", fake)
    s = asyncio.run(parse_request("teh data guy at swigy pls"))
    assert s.person_name is None            # "Priya Raman" never appears in the request
    assert s.company == "Swiggy"            # typo fixed by the LLM, still close to the text
    assert s.role == "head of data" and s.parser == "llm"


def test_llm_down_falls_back_to_rules(monkeypatch):
    async def down(*_a, **_k):
        return None
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete_json", down)
    s = asyncio.run(parse_request("the CTO of Zepto"))
    assert s.parser == "rules" and _low(s.company) == "zepto" and _low(s.role) == "cto"


def test_empty_and_garbage_input_does_not_crash():
    for t in ("", "   ", "???", "asdf qwer"):
        s = parse_rules(t)
        assert s.raw == t


def test_team_reported_bugs():
    """Regressions from docs/UPDATES.md (11:45): role cut at ' of ', name-only requests, lowercase companies."""
    s = parse_rules("warm intro to the head of data at Swiggy")
    assert s.role == "head of data" and s.company == "Swiggy"
    s = parse_rules("intro to Priya Sharma")
    assert s.person_name == "Priya Sharma" and s.company is None and s.role is None
    s = parse_rules("the data guy at swiggy pls")
    assert s.company == "swiggy" and s.role == "data"


def test_target_company_never_in_network(monkeypatch):
    """UPDATES.md (11:58): the LLM put the target company into the network filter."""
    async def fake(*_a, **_k):
        return {"company": "Swiggy", "role": "head of data", "companies": ["Swiggy", "Flipkart"],
                "schools": ["IIT Bombay"]}
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete_json", fake)
    s = asyncio.run(parse_request("yo can u get me to teh data guy at swiggy, thru iitb or flipkart ppl"))
    assert s.network.companies == ["Flipkart"] and s.role == "head of data"
    assert parse_rules("head of data at Swiggy via ex-Swiggy folks").network.companies == []


def test_llm_only_refines_rules(monkeypatch):
    async def fake(*_a, **_k):
        return {"company": "Zomato", "role": "Chief Technology Officer"}
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete_json", fake)
    s = asyncio.run(parse_request("intro to the cto at zepto, maybe via zomato people"))
    assert s.company == "zepto" and s.role == "cto"      # different company / unrelated role: rules win
