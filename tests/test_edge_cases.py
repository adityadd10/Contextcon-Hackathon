"""Adversarial inputs: every run must end with exactly one `done`, never raise, never hang, and explain failures."""
import asyncio
import os

import pytest

from warmpath import crust as crust_mod
from warmpath.crust import Crust
from warmpath.fake import FakeCrust
from warmpath.graphdb import GraphStore
from warmpath.pipeline import run

CASES = ["", "   ", "\n\n", "?", "a", "intro", "warm intro to", "intro to at", "at Swiggy", "Swiggy",
         "WARM INTRO TO THE HEAD OF DATA AT SWIGGY", "teh data guy at swigy pls", "intro to Priya Sharma",
         "intro to priya sharma at swiggy", "linkedin.com/in/priya-sharma", "https://www.linkedin.com/in/redacted-person",
         "https://www.linkedin.com/in/does-not-exist", "intro to the CEO at Nonexistent Corp",
         "intro to the head of data at https://www.linkedin.com/company/swiggy", "x" * 5000, "😀 intro to 😀 at 🍕",
         "intro to '; DROP TABLE nodes; -- at Swiggy", "intro to <script>alert(1)</script> at Swiggy",
         "intro to [bold]x[/bold] at Swiggy", "मुझे Swiggy के head of data से मिलवाओ",
         "bhai swiggy mein data head se intro karwa do iitb wale se", "intro to the head of data at Swiggy via Swiggy",
         "intro to the head of data at Swiggy via IITB, IITD, BITS and NIT Raipur",
         "intro to the head of data at Swiggy\x00\x07", "intro to the head of data at Swiggy " * 50]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(crust_mod, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setenv("WARMPATH_SEEDS", "")
    monkeypatch.setenv("WARMPATH_LLM", "0")


async def _run(q, g):
    ev = []
    async with Crust(api_key="x", use_cache=False, transport=FakeCrust(False).transport(), pace=False) as c:
        r = await asyncio.wait_for(run(q, ev.append, crust=c, graph=g), 30)
    return r, ev


@pytest.mark.parametrize("q", CASES, ids=[repr(c[:30]) for c in CASES])
def test_every_input_terminates_cleanly_and_explains(q):
    g = GraphStore("g.db")
    r, ev = asyncio.run(_run(q, g))
    types = [e["type"] for e in ev]
    assert types.count("done") == 1 and types[-1] == "done"
    assert "error" not in types
    if r.target is None:  # a failure must always tell the user why
        assert "warning" in types or any(e["type"] == "step" and e["status"] == "error" for e in ev)
        assert any(e["type"] == "warning" for e in ev), f"silent failure for {q!r}"


def test_graph_survives_two_concurrent_writers():
    """Server can run a crawl and a request at once: no 'database is locked'."""
    async def both():
        return await asyncio.gather(_run("intro to the head of data at Swiggy", GraphStore("g.db")),
                                    _run("intro to Rahul Verma at Tiny Analytics", GraphStore("g.db")))
    (r1, e1), (r2, e2) = asyncio.run(both())
    assert r1.target and r2.target and "error" not in [e["type"] for e in e1 + e2]


def test_profile_url_normalisation():
    from warmpath.resolve import normalize_profile_url as n
    for raw in ["linkedin.com/in/abc-1", "https://in.linkedin.com/in/abc-1?trk=x", "http://www.linkedin.com/in/abc-1/"]:
        assert n(raw) == "https://www.linkedin.com/in/abc-1/"


def test_bare_company_and_acronym_role_are_understood():
    ev = []

    async def go():
        from warmpath.models import TargetSpec
        from warmpath.resolve import resolve_target
        async with Crust(api_key="x", use_cache=False, transport=FakeCrust(False).transport(), pace=False) as c:
            a = await resolve_target(c, TargetSpec(raw="Swiggy"), ev.append)
            b = await resolve_target(c, TargetSpec(raw="x", company="Swiggy", role="hod"), ev.append)
            return a, b
    (t1, co1), _ = asyncio.run(go())
    assert co1 and co1.name == "Swiggy"
    assert any("Treating 'Swiggy' as a company" in e.get("label", "") for e in ev)


@pytest.mark.parametrize("name,generic", [("Various Startups", True), ("Stealth Startup", True), ("Self Employed", True),
                                          ("Confidential Company", True), ("Freelancer", True), ("Swiggy", False),
                                          ("Stealth Health Inc", False), ("Startup India", False)])
def test_placeholder_employers_never_create_ties(name, generic):
    from warmpath.crust import is_generic_employer
    assert is_generic_employer(name) is generic


def test_fake_mode_never_touches_the_real_graph(monkeypatch):
    import importlib, warmpath.graphdb as gdb
    monkeypatch.setenv("WARMPATH_FAKE", "1")
    assert importlib.reload(gdb).DB_PATH.name == "graph.fake.db"
    monkeypatch.setenv("WARMPATH_FAKE", "0")
    assert importlib.reload(gdb).DB_PATH.name == "graph.db"


def test_privacy_mode_masks_strangers_but_keeps_target(monkeypatch):
    import json as _j
    monkeypatch.setenv("WARMPATH_MASK_NAMES", "1")
    r, ev = asyncio.run(_run("warm intro to the head of data at Swiggy via IIT Bombay alumni", GraphStore("g.db")))
    shown = _j.dumps([e for e in ev if e["type"] in ("node", "path", "draft", "done", "edge")])
    assert r.paths and "Rahul Verma" not in shown and "Rahul" not in shown   # connector masked everywhere
    assert "Priya Sharma" in shown                                           # the requested target stays readable
    assert r.paths[0].nodes[0].name == "Rahul Verma"                         # the real run is untouched
