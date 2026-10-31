"""End-to-end pipeline on the fake Crustdata API (no network, no credits)."""
import asyncio

import pytest

from warmpath.fake import REDACTED, FakeCrust
from warmpath import crust as crust_mod
from warmpath.crust import Crust
from warmpath.graphdb import GraphStore
from warmpath.pipeline import run


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(crust_mod, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setenv("WARMPATH_SEEDS", "")
    monkeypatch.setattr("warmpath.llm.API_KEY", "")


def go(q, fake=None, seeds=""):
    fake = fake or FakeCrust()
    events = []

    async def main():
        async with Crust(api_key="x", use_cache=False, transport=fake.transport(), pace=False) as c:
            return await run(q, events.append, crust=c, graph=GraphStore("g.db"))
    import os
    os.environ["WARMPATH_SEEDS"] = seeds
    return asyncio.run(main()), events, fake


def test_role_at_company_via_iitb_end_to_end():
    r, events, fake = go("get me a warm intro to whoever runs data at Swiggy, ideally via IITB folks")
    assert r.target and r.target.name == "Priya Sharma" and r.target.person_id == 1
    names = [p.nodes[0].name for p in r.paths]
    assert names[0] == "Rahul Verma"                 # 4 yrs at a 30-person startup beats everyone
    assert "Arjun Rao" not in names                  # not IIT Bombay → outside the network
    top = r.paths[0].ties[-1]
    assert any(f.name == "web_cooccurrence" for f in top.factors)
    assert all(f.evidence for f in top.factors if f.name in ("overlap_months", "web_cooccurrence"))
    assert r.drafts and "Rahul" in r.drafts[0].body
    assert any(e["type"] == "done" for e in events)
    assert fake.calls[0] == fake.calls[1]            # first call got a 429 and was retried
    assert r.audit and all(a.sha256 for a in r.audit)


def test_same_name_disambiguated_by_company():
    r, _, _ = go("intro to Priya Sharma at Swiggy")
    assert r.target.person_id == 1                   # not the other Priya Sharma (teacher)


def test_seed_two_hop_and_graph_memory():
    seed = "https://www.linkedin.com/in/aditya-seed"
    r, _, _ = go("warm intro to the head of data at Swiggy", seeds=seed)
    chains = [[n.name for n in p.nodes] for p in r.paths]
    assert ["Aditya Seed", "Rahul Verma", "Priya Sharma"] in chains
    g = GraphStore("g.db")
    assert g.stats()["people"] >= 4 and g.stats()["relationships"] >= 2


def test_unknown_company_and_redacted_profile_degrade_gracefully():
    r, events, _ = go("intro to the CTO at Nonexistent Corp")
    assert r.target is None and any(e["type"] == "warning" for e in events)
    r, events, _ = go(f"intro to {REDACTED}")
    assert r.target is None and any("remove their data" in e.get("message", "") for e in events)
