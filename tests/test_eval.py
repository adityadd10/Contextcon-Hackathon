import json
from datetime import date

from eval import cofounder_eval as ce
from warmpath.models import Person, Stint, to_dict


def P(pid, name, *stints):
    return Person(name=name, person_id=pid, stints=list(stints), source_endpoint="test")


def S(start, end=None, hc=300, title=None, ref=""):
    return Stint("StartupX", 99, title, date(*start), date(*end) if end else None, end is None,
                 company_headcount=hc, ref=ref or f"r{start}{title}")


def _company():
    f1 = P(1, "Founder One", S((2015, 1, 1), title="Co-founder & CEO"))
    f2 = P(2, "Founder Two", S((2015, 2, 1), title="Co-founder & CTO"))
    early = P(3, "Early Hire", S((2016, 1, 1), (2019, 1, 1), title="Engineer"))
    recent = P(4, "Recent Hire", S((2024, 6, 1), title="Analyst"))
    dup = P(2, "Founder Two", S((2015, 2, 1), title="Co-founder & CTO"))   # search returns a founder again
    return [f1, f2], [early, recent, dup]


def test_cofounder_found_and_duplicates_excluded():
    founders, colleagues = _company()
    res = ce.evaluate_company("StartupX", founders, colleagues)
    assert len(res) == 2 and all(r.pool == 3 for r in res)
    assert all(r.ranks["WarmPath"] == 1 for r in res)
    assert res[0].top_pick == "Founder Two"


def test_ties_count_against_us_and_random_baseline():
    t = P(1, "T", S((2015, 1, 1)))
    cf = P(2, "CF", S((2015, 1, 1)))
    twin = P(3, "Twin", S((2015, 1, 1)))
    assert ce.cofounder_rank(t, [cf], [twin], ce.warmpath_score) == 2
    assert ce.random_hit(1, 4, 1) == 0.25 and ce.random_hit(1, 4, 3) == 0.75 and ce.random_hit(1, 2, 3) == 1.0


def test_summary_report_and_round_trip():
    founders, colleagues = _company()
    data = json.loads(json.dumps({"founders": to_dict(founders), "colleagues": to_dict(colleagues)}))
    back = [ce.person_from_dict(p) for p in data["founders"]]
    assert back[0].stints[0].start == date(2015, 1, 1)
    res = ce.evaluate_company("StartupX", back, [ce.person_from_dict(p) for p in data["colleagues"]])
    s = ce.summarise(res)
    assert s["WarmPath"]["hit@1"] == 1.0 and 0 < s["Random colleague"]["hit@1"] < 1
    assert "| WarmPath | 100% |" in ce.report(res, s)


def test_founder_urls_found_in_any_response_shape():
    rows = [{"company_data": {"people": {"founders": [
        {"name": "A", "profile": {"linkedin_profile_url": "https://www.linkedin.com/in/a/"}},
        {"full_name": "B", "professional_network_profile_url": "https://linkedin.com/in/b"}]}}}]
    founders = ce._find(rows, "founders")
    assert [ce._profile_url(x) for x in founders] == ["https://www.linkedin.com/in/a/", "https://linkedin.com/in/b"]


def test_founders_office_staff_are_not_founders():
    def F(title, headline=""):
        return {"basic_profile": {"current_title": title, "headline": headline}}
    assert ce.is_founder(F("CEO & Co-Founder")) and ce.is_founder(F("Co-Founder", "Cofounder, Razorpay"))
    assert not ce.is_founder(F("Corporate Strategy (Founder's Office)"))
    assert not ce.is_founder(F("AI Engineer, Founder’s Office"))
    assert not ce.is_founder(F("Lead Executive Assistant to the CEO and Co-Founder"))


def test_founder_verified_by_stint_at_company_near_founding():
    def F(*stints):
        return {"basic_profile": {"current_title": "Founder"}, "experience": {"employment_details": {"current": [
            {"employer_name": n, "employer_company_id": cid, "employee_title": t, "employee_start_date": d}
            for n, cid, t, d in stints]}}}
    real = F(("Zomato", 61, "Founder & CEO", "2008-07-01"))
    assert ce.is_founder(real, 61, "Zomato", 2008)
    assert not ce.is_founder(F(("Zomato", 61, "Co-Founder", None)), 61, "Zomato", 2008)          # no dates
    assert not ce.is_founder(F(("Zomato", 61, "Founder", "2021-01-01")), 61, "Zomato", 2008)     # joined 13y later
    assert not ce.is_founder(F(("Other", 9, "Founder", "2008-01-01")), 61, "Zomato", 2008)       # founded elsewhere
    assert not ce.is_founder(F(("Zomato", 61, "Founder's Office", "2008-01-01")), 61, "Zomato", 2008)


def test_ground_truth_applied_evenly_and_duplicate_records_merged():
    f1 = P(1, "Founder One", S((2015, 1, 1), title="Co-founder & CEO"))
    f1_dup = P(9, "Founder  One", S((2015, 1, 1), title="Founder"))            # second record, same person
    missed = P(3, "Missed Cofounder", S((2015, 3, 1), title="Co-Founder"))     # not on the founders list
    late = P(4, "Late Founder", S((2021, 1, 1), title="Founder, New Unit"))   # "founder" title years later
    for p in (f1, f1_dup, missed, late):
        for s in p.stints:
            s.company_id = 99
    res = ce.evaluate_company("X", [f1, f1_dup], [missed, late], company_id=99, year_founded=2015)
    assert sorted(r.founder for r in res) == ["Founder One", "Missed Cofounder"]
    assert all(r.pool == 2 and r.ranks["WarmPath"] == 1 for r in res)
