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
