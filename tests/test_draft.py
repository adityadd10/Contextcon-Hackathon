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
    path = build_paths(t, [c], seeds, TargetSpec(raw="x", purpose="sales"))[0]
    for tie in path.ties:
        tie.verified = True
    return path


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


def test_unverified_path_is_flagged_and_never_llm_polished(monkeypatch):
    async def never(*_a, **_k):
        raise AssertionError("LLM must not polish an unverified path")
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete", never)
    p = _path()
    p.ties[0].verified = False
    d = asyncio.run(draft_intro(p, TargetSpec(raw="x")))
    assert d.claims_unsupported and "not re-verified" in d.claims_unsupported[0]
    assert "verified via Crustdata" not in d.forwardable_blurb


def test_verified_path_gets_footer(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: False)
    d = asyncio.run(draft_intro(_path(), TargetSpec(raw="x")))
    assert d.forwardable_blurb.endswith("(verified via Crustdata)") and not d.claims_unsupported


def _hop_path():
    """you -> Asha (Acme) -> Rahul (Beta) -> Priya (TinyCo): a 3-hop chain from the graph."""
    from warmpath.models import IntroPath
    from warmpath.score import score_tie
    S = lambda co, cid, s, e, ref: Stint(co, cid, "Engineer", date(*s), date(*e), company_headcount=40, ref=ref)
    me = Person("Vaibhav N", 1, source_endpoint="e", stints=[S("Acme", 10, (2018, 1, 1), (2021, 1, 1), "m0")])
    asha = Person("Asha Rao", 2, source_endpoint="e", stints=[S("Acme", 10, (2018, 6, 1), (2020, 6, 1), "a0"),
                                                               S("Beta", 20, (2020, 7, 1), (2023, 1, 1), "a1")])
    rahul = Person("Rahul Mehta", 3, source_endpoint="e", stints=[S("Beta", 20, (2021, 1, 1), (2022, 6, 1), "r0"),
                                                                   S("TinyCo", 30, (2022, 7, 1), (2025, 1, 1), "r1")])
    priya = Person("Priya Raman", 4, current_title="Head of Data", source_endpoint="e",
                   stints=[S("TinyCo", 30, (2022, 1, 1), (2025, 6, 1), "p0")])
    nodes = [me, asha, rahul, priya]
    ties = [score_tie(a, b) for a, b in zip(nodes, nodes[1:])]
    for t in ties:
        t.verified = True
    return IntroPath(nodes, ties, 60, "", rank=1)


def test_multi_hop_draft_goes_to_the_person_you_know_and_attributes_each_hop():
    """Aditya, 14:xx: the draft went to the last connector but said 'we overlapped at' about the first one."""
    d = template(_hop_path(), TargetSpec(raw="x"))
    assert d.to == "Asha Rao" and d.body.startswith("Hi Asha,")
    assert "We overlapped at Acme" in d.body                                  # me <-> Asha: true
    assert "you and Rahul Mehta overlapped at Beta" in d.body                 # Asha <-> Rahul: true
    assert "Rahul Mehta and Priya Raman overlapped at TinyCo" in d.body       # Rahul <-> Priya: true
    assert "you two overlapped at TinyCo" not in d.body                       # the old misattribution
    assert "passing the short note below to Rahul" in d.body
    assert "Rahul suggested" in d.forwardable_blurb                           # Rahul hands it to Priya
    assert d.claims_unsupported == []


def test_two_and_three_node_drafts_unchanged():
    p3 = _path(with_seed=True)
    d = template(p3, TargetSpec(raw="x"))
    assert d.to == p3.nodes[1].name and "We overlapped at Acme" in d.body and "you two overlapped at TinyCo" in d.body
    p2 = _path()
    d = template(p2, TargetSpec(raw="x"))
    assert d.to == "Rahul Mehta" and "We overlapped" not in d.body
