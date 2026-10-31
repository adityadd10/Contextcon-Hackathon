from datetime import date

from warmpath.graphdb import GraphStore
from warmpath.models import Person, School, Stint


def P(pid, name, *stints):
    return Person(name=name, person_id=pid, stints=list(stints), source_endpoint="/person/enrich")


def S(cid, co, start, end=None, hc=40):
    return Stint(company_name=co, company_id=cid, start=date(*start), end=date(*end) if end else None,
                 is_current=end is None, company_headcount=hc, ref=f"{co}{start}")


def test_graph_derives_ties_and_multi_hop_path(tmp_path):
    g = GraphStore(tmp_path / "g.db")
    me = P(1, "Me", S(100, "A", (2018, 1, 1), (2020, 1, 1)))
    x = P(2, "X", S(100, "A", (2018, 6, 1), (2020, 6, 1)), S(200, "B", (2020, 7, 1), (2023, 1, 1)))
    y = P(3, "Y", S(200, "B", (2021, 1, 1), (2024, 1, 1)), S(300, "C", (2024, 2, 1)))
    t = P(4, "Target", S(300, "C", (2023, 1, 1)))
    for p in (me, x, y, t):
        g.upsert_person(p)
    st = g.stats()
    assert st["people"] == 4 and st["relationships"] == 3
    assert g.strongest_path(1, 4) == [1, 2, 3, 4]
    assert g.degrees_of_separation(1, 4) == 3
    assert g.person(2).stints[0].start == date(2018, 6, 1)  # round-trips through JSON
    assert g.super_connectors()[0]["name"] in {"X", "Y"}
    assert g.subgraph()["nodes"]
    assert g.export_cypher(tmp_path / "g.cypher").read_text().count("KNOWS") == 3
