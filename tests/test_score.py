from datetime import date

from warmpath.models import NetworkSpec, Person, School, Stint, TargetSpec
from warmpath.parse import parse_rules
from warmpath.paths import build_paths
from warmpath.score import find_overlaps, score_tie


def P(pid, name, *stints, schools=()):
    return Person(name=name, person_id=pid, stints=list(stints), schools=list(schools), source_endpoint="test")


def S(cid, co, start, end=None, hc=None, title=None, ref=""):
    return Stint(company_name=co, company_id=cid, start=date(*start), end=date(*end) if end else None,
                 is_current=end is None, company_headcount=hc, title=title, ref=ref or f"{co}-{start}")


def test_overlap_and_score_small_startup_beats_big_co():
    t = P(1, "Target T", S(10, "TinyCo", (2019, 1, 1), (2021, 1, 1), hc=30), S(20, "BigCo", (2021, 2, 1), hc=50000))
    a = P(2, "Alice A", S(10, "TinyCo", (2019, 6, 1), (2022, 1, 1), hc=30))
    b = P(3, "Bob B", S(20, "BigCo", (2022, 1, 1), hc=50000))
    assert find_overlaps(a, t)[0].months > 18
    assert score_tie(a, t).score > score_tie(b, t).score
    assert all(f.evidence or f.name == "recency" for f in score_tie(a, t).factors)


def test_no_overlap_no_tie():
    t = P(1, "Target T", S(10, "TinyCo", (2015, 1, 1), (2016, 1, 1)))
    a = P(2, "Alice A", S(10, "TinyCo", (2018, 1, 1), (2019, 1, 1)))
    assert find_overlaps(a, t) == []
    assert score_tie(a, t).score == 0


def test_two_hop_path_via_seed():
    t = P(1, "Target T", S(10, "TinyCo", (2019, 1, 1), (2021, 1, 1), hc=30))
    c = P(2, "Conn C", S(10, "TinyCo", (2019, 1, 1), (2021, 6, 1), hc=30), S(30, "SeedCo", (2021, 7, 1), hc=40))
    seed = P(3, "Me M", S(30, "SeedCo", (2021, 1, 1), hc=40))
    paths = build_paths(t, [c], [seed], TargetSpec(raw="x"))
    assert paths and [n.name for n in paths[0].nodes] == ["Me M", "Conn C", "Target T"]


def test_rule_parser():
    s = parse_rules("get me a warm intro to whoever runs data at Swiggy, ideally via IITB folks")
    assert s.company == "Swiggy" and s.role and "data" in s.role and s.network.schools == ["IIT Bombay"]
    s = parse_rules("intro to https://www.linkedin.com/in/someone/ for hiring")
    assert s.profile_url and s.purpose == "hiring"


def test_team_keyword():
    from warmpath.discover import team_keyword
    assert team_keyword("Director - Data Science") == "data"
    assert team_keyword("Senior Android Engineer") == "engineering" or team_keyword("Senior Android Engineer") == "android"
    assert team_keyword(None) is None
def F(cid, co, start, end=None, hc=None, title=None, fn=None, loc=None, ref=""):
    s = S(cid, co, start, end, hc=hc, title=title, ref=ref)
    s.function, s.location = fn, loc
    return s


def test_hardest_case_big_company_needs_a_team_signal():
    """Small team + long overlap beats a longer overlap at a 50k-person company, even with matching function."""
    t = P(1, "Target T", F(10, "TinyCo", (2018, 1, 1), (2020, 1, 1), hc=30),
          F(20, "Google", (2020, 2, 1), hc=180000, title="Data Scientist", fn="Engineering", loc="Bengaluru"))
    small = P(2, "Small S", F(10, "TinyCo", (2018, 1, 1), (2020, 6, 1), hc=30))
    big_team = P(3, "Big Team", F(20, "Google", (2020, 3, 1), hc=180000, title="Senior Data Scientist",
                                  fn="Engineering", loc="Bengaluru, India"))
    big_stranger = P(4, "Big Stranger", F(20, "Google", (2020, 3, 1), hc=180000, title="Sales Manager",
                                          fn="Sales", loc="Mountain View"))
    s_small, s_team, s_str = (score_tie(x, t) for x in (small, big_team, big_stranger))
    assert s_small.score > s_team.score > s_str.score
    assert s_str.score < 30                       # below a useful-tie threshold on its own
    disc = next(f for f in s_str.factors if f.name == "big_company_discount")
    assert disc.contribution < 0 and "Google" in disc.explanation


def test_every_factor_carries_evidence():
    t = P(1, "Target T", F(10, "TinyCo", (2019, 1, 1), (2021, 1, 1), hc=30, fn="Product", loc="Pune"),
          F(11, "MidCo", (2015, 1, 1), (2018, 1, 1), hc=5000), schools=[School("IIT Bombay", start=date(2010, 7, 1),
                                                                                end=date(2014, 5, 1), ref="t#s0")])
    a = P(2, "Alice A", F(10, "TinyCo", (2019, 1, 15), (2022, 1, 1), hc=30, fn="Product", loc="Pune"),
          F(11, "MidCo", (2016, 1, 1), (2017, 6, 1), hc=5000),
          schools=[School("IIT Bombay", start=date(2011, 7, 1), end=date(2015, 5, 1), ref="a#s0")])
    tie = score_tie(a, t)
    names = {f.name for f in tie.factors}
    assert {"overlap_months", "company_size", "same_function", "same_location", "joined_together",
            "recency", "repeat_colleagues", "classmates"} <= names
    assert all(f.evidence for f in tie.factors), [f.name for f in tie.factors if not f.evidence]
    assert 90 < tie.score < 100                  # strong, but not saturated


def test_calibration_keeps_low_scores_and_spreads_strong_ones():
    from warmpath.score import calibrate
    assert calibrate(25) == 25 and calibrate(70) == 70 and calibrate(-5) == 0
    assert 70 < calibrate(80) < calibrate(100) < calibrate(115) < calibrate(200) <= 100
    assert calibrate(100) == 89.0


def test_missing_end_date_is_capped_not_treated_as_current():
    t = P(1, "Target T", S(10, "TinyCo", (2015, 1, 1), hc=30))          # current role since 2015
    a = P(2, "Alice A", S(10, "TinyCo", (2015, 3, 1), hc=30))
    a.stints[0].is_current = False                                         # past role, end date missing
    ov = find_overlaps(a, t)
    assert ov and ov[0].months <= 12.1
    assert "assumed" in score_tie(a, t).factors[0].explanation


def test_bad_dates_and_self_ties():
    t = P(1, "Target T", S(10, "TinyCo", (2020, 1, 1), (2019, 1, 1)))    # end before start
    a = P(2, "Alice A", S(10, "TinyCo", (2018, 1, 1), (2021, 1, 1)))
    assert find_overlaps(a, t) == []
    assert score_tie(t, t).kind == "self" and score_tie(t, t).score == 0


def test_company_name_fallback_when_ids_missing():
    t = P(1, "Target T", S(None, "Razorpay Software Pvt Ltd", (2019, 1, 1), (2021, 1, 1)))
    a = P(2, "Alice A", S(None, "Razorpay", (2019, 6, 1), (2021, 1, 1)))
    b = P(3, "Bob B", S(None, "Razorpay Capital Partners", (2019, 6, 1), (2021, 1, 1)))
    assert find_overlaps(a, t) and not find_overlaps(b, t)


def test_paths_work_without_person_ids_and_dedupe_connectors():
    t = P(None, "Target T", S(10, "TinyCo", (2019, 1, 1), (2021, 1, 1), hc=30))
    t.profile_url = "https://www.linkedin.com/in/target/"
    c = P(None, "Conn C", S(10, "TinyCo", (2019, 1, 1), (2021, 6, 1), hc=30))
    c.profile_url = "https://www.linkedin.com/in/conn/"
    c_again = P(None, "Conn C", S(10, "TinyCo", (2019, 1, 1), (2021, 6, 1), hc=30))
    c_again.profile_url = c.profile_url.upper()             # same person, URL cased differently
    paths = build_paths(t, [c, c_again, t], [], TargetSpec(raw="x"))
    assert len(paths) == 1 and paths[0].nodes[0].name == "Conn C" and paths[0].rank == 1


def test_weakest_link_and_hop_decay():
    from warmpath.models import Tie
    from warmpath.paths import path_score
    a, b = P(1, "A"), P(2, "B")
    strong, weak = Tie(a, b, 90.0), Tie(a, b, 30.0)
    assert path_score([strong]) == 90.0
    assert path_score([strong, weak]) < path_score([weak]) * 1.5   # a weak link drags the whole chain down
    assert path_score([strong, strong]) == round(90 * 0.85, 1)
    assert path_score([]) == 0.0
