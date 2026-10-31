"""Adversarial inputs for Vaibhav's modules (parse, score, draft, webproof, llm), found by the edge-case loops."""
import asyncio
from datetime import date

import pytest

from warmpath import draft, llm, webproof
from warmpath.models import IntroPath, Person, School, Stint, TargetSpec, Tie
from warmpath.parse import parse_rules
from warmpath.score import score_tie


@pytest.mark.parametrize("text,company,role,name", [
    ("a" * 20000, None, None, None),                                   # company capped, no crash
    ("at", None, None, None),
    ("at at at at", None, None, None),
    ("intro to the at", None, None, None),
    ("intro to José Álvarez at Glovo", "Glovo", None, "José Álvarez"),
    ("intro to 李明 at Alibaba", "Alibaba", None, "李明"),
    ("get me in touch with the vp of sales of freshworks", "freshworks", "VP of sales", None),
    ("intro to someone at https://swiggy.com/careers", "swiggy.com", None, None),
    ("intro to Dr. Priya Sharma at AIIMS", "AIIMS", None, "Priya Sharma"),
    ("intro to the CTO at AT&T", "AT&T", "CTO", None),
    ("intro to the CEO at Johnson & Johnson", "Johnson & Johnson", "CEO", None),
    ("", None, None, None), ("🙏🙏", None, None, None), ("'; DROP TABLE people; --", None, None, None),
])
def test_parser_edge_cases(text, company, role, name):
    s = parse_rules(text)
    if text.startswith("aaaa"):
        assert s.company is None or len(s.company) <= 80
        return
    assert (s.company, s.role, s.person_name) == (company, role, name)


def _p(pid, name, stints=(), schools=()):
    return Person(name=name, person_id=pid, stints=list(stints), schools=list(schools), source_endpoint="t")


def test_score_edge_cases():
    st = lambda hc=None: Stint("X", 1, start=date(2020, 1, 1), is_current=True, company_headcount=hc)
    a = _p(None, "A", [st()])
    assert score_tie(a, a).kind == "self" and score_tie(a, a).score == 0              # same object, no id
    blank = [School("", start=date(2010, 1, 1))]
    assert score_tie(_p(1, "A", schools=blank), _p(2, "B", schools=blank)).score == 0  # unnamed schools
    t = score_tie(_p(1, "A", [st(0)]), _p(2, "B", [st(-5)]))
    size = next(f for f in t.factors if f.name == "company_size")
    assert size.value is None and size.contribution == 6.0                            # 0/negative = unknown
    future = Stint("X", 1, start=date(2099, 1, 1), is_current=True)
    assert score_tie(_p(1, "A", [future]), _p(2, "B", [future])).score == 0


def test_draft_edge_cases():
    tgt = _p(9, "", [Stint("X", 1, start=date(2019, 1, 1), is_current=True)])
    d = asyncio.run(draft.draft_intro(IntroPath([tgt], [], 0, ""), TargetSpec(raw="x")))
    assert d.claims_unsupported and d.body == ""                                     # one-node path, no crash
    c = _p(2, "", [Stint("X", 1, start=date(2019, 1, 1), is_current=True)])
    tie = score_tie(c, tgt)
    tie.verified = True
    d = draft.template(IntroPath([c, tgt], [tie], 50, ""), TargetSpec(raw="x"))
    assert "reach this person" in d.body and "Hi there" in d.body


class _FC:
    last_call_id = "c1"

    def __init__(self, res):
        self.res = res

    async def web_search(self, *a, **k):
        return self.res


@pytest.mark.parametrize("res", [None, [], {"results": None}, {"results": [None, {}, "x"]},
                                 {"results": [{"title": None, "url": "https://x.com/a",
                                               "snippet": "Harsha Majety and Nandan Reddy founded it"}]}])
def test_webproof_tolerates_malformed_results(res):
    f = asyncio.run(webproof.web_cooccurrence(_FC(res), Person(name="Harsha Majety"), Person(name="Nandan Reddy")))
    assert f is None or (f.evidence and f.evidence[0].url == "https://x.com/a")


def test_llm_json_edge_cases(monkeypatch):
    for reply, want in ((["a", "list"], None), ('x {"a": {"b": 1}} trailing } junk', {"a": {"b": 1}}),
                        ("{not json} then {\"ok\": true}", {"ok": True}), ("[1, 2]", None)):
        async def fake(*_a, _r=reply, **_k):
            return _r
        monkeypatch.setattr(llm, "complete", fake)
        assert asyncio.run(llm.complete_json("s", "u")) == want, reply
