import asyncio
from datetime import date

from warmpath import draft, llm
from warmpath.draft import check_claims, draft_intro, template, write_outbox
from warmpath.models import Person, Stint, TargetSpec
from warmpath.paths import build_paths


def _path(with_seed=False):
    t = Person(name="Priya Raman", person_id=1, current_title="Head of Data", source_endpoint="/person/enrich",
               profile_url="https://www.linkedin.com/in/priya/",
               stints=[Stint("Swiggy", 10, "Head of Data", date(2021, 1, 1), None, True, company_headcount=5000,
                             ref="person:1#experience.current[0]"),
                       Stint("TinyCo", 20, "Data Lead", date(2017, 1, 1), date(2020, 6, 1), company_headcount=40,
                             ref="person:1#experience.past[0]")])
    c = Person(name="Rahul Mehta", person_id=2, source_endpoint="/person/enrich",
               stints=[Stint("TinyCo", 20, "Analyst", date(2017, 3, 1), date(2020, 1, 1), company_headcount=40,
                             ref="person:2#experience.past[0]"),
                       Stint("Acme", 30, "PM", date(2020, 2, 1), None, True, company_headcount=60,
                             ref="person:2#experience.current[0]")])
    seeds = [Person(name="Vaibhav N", person_id=3, source_endpoint="/person/enrich",
                    stints=[Stint("Acme", 30, "Engineer", date(2020, 3, 1), None, True, company_headcount=60,
                                  ref="person:3#experience.current[0]")])] if with_seed else []
    return build_paths(t, [c], seeds, TargetSpec(raw="x", purpose="sales"))[0]


def test_template_is_fully_supported_and_cited():
    for seed in (False, True):
        p = _path(seed)
        d = template(p, TargetSpec(raw="x", purpose="sales"))
        assert d.claims_unsupported == [], d.claims_unsupported
        assert d.claims_checked >= 4
        assert "TinyCo" in d.body and "2017" in d.body and d.to == "Rahul Mehta"
        assert d.citations and all(e.ref for e in d.citations)
        if seed:
            assert len(p.nodes) == 3 and "Acme" in d.body and "[Vaibhav N]" in d.body


def test_check_claims_flags_made_up_facts():
    p = _path()
    ok = "Rahul, you and Priya overlapped at TinyCo from 2017 to 2020."
    assert check_claims(ok, p) == []
    for lie in ("You both worked at Google together.",             # wrong company
                "You two overlapped at TinyCo back in 2012.",       # wrong year
                "Priya grew the team by 40% last year.",            # invented number
                "I met Ananya at a conference.",                    # invented person
                "She studied at Stanford with you."):               # invented school
        assert check_claims(lie, p) == [lie], lie


def test_llm_draft_with_hallucination_is_rejected(monkeypatch):
    async def liar(*_a, **_k):
        return "Hi Rahul, you and Priya built the Google Maps team together in 2015. Could you intro us?"
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete", liar)
    d = asyncio.run(draft_intro(_path(), TargetSpec(raw="x", purpose="sales")))
    assert "Google" not in d.body and d.llm_rejected and d.claims_unsupported == []


def test_llm_draft_that_sticks_to_facts_is_kept(monkeypatch):
    async def good(*_a, **_k):
        return "Subject: hi\nHi Rahul,\n\nSince you and Priya overlapped at TinyCo, would you forward a note? Thanks!"
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete", good)
    d = asyncio.run(draft_intro(_path(), TargetSpec(raw="x", purpose="sales")))
    assert d.body.startswith("Hi Rahul") and "Subject" not in d.body and not d.llm_rejected


def test_outbox_file_lists_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(draft, "OUTBOX", tmp_path)
    f = write_outbox(template(_path(), TargetSpec(raw="x")), "run1")
    text = f.read_text(encoding="utf-8")
    assert "NOT SENT" in text and "person:1#experience.past[0]" in text and "every sentence checked" in text
