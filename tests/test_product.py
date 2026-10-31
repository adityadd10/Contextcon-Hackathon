"""Worst-case tests for the product layer: server (SSE + graph API), CLI and MCP.  Owner: Member C (Apurba).

Everything runs offline against the fake Crustdata world, in a temp directory so the real graph is never touched.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from warmpath import cli, mcp_server, server


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                       # graph.db, reports/, outbox/, .cache/ all land in tmp
    monkeypatch.setenv("WARMPATH_FAKE", "1")
    monkeypatch.setenv("WARMPATH_SEEDS", "https://www.linkedin.com/in/aditya-seed")
    monkeypatch.setenv("CRUSTDATA_API_KEY", "")
    monkeypatch.setattr(server, "MOCK_DELAY", 0)


@pytest.fixture
def client():
    return TestClient(server.app)


def events(resp) -> list[dict]:
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


def types(evs: list[dict]) -> list[str]:
    return [e["type"] for e in evs]


# ------------------------------------------------------------------ /api/run: bad input never gives a dead stream

@pytest.mark.parametrize("q", ["", "   ", "\x00\x07\n\t"])
def test_run_empty_or_garbage_query_explains(client, q):
    evs = events(client.get("/api/run", params={"q": q}))
    assert types(evs) == ["error", "end"]
    assert "who you want to reach" in evs[0]["message"]


def test_run_huge_query_is_rejected_with_reason(client):
    evs = events(client.get("/api/run", params={"q": "data " * 400}))
    assert types(evs) == ["error", "end"] and "under 1000" in evs[0]["message"]


def test_run_without_key_says_how_to_fix(client, monkeypatch):
    monkeypatch.delenv("WARMPATH_FAKE")
    evs = events(client.get("/api/run", params={"q": "head of data at Swiggy"}))
    assert types(evs) == ["error", "end"] and "CRUSTDATA_API_KEY" in evs[0]["message"]


def test_run_end_to_end_fake_world(client):
    evs = events(client.get("/api/run", params={"q": "intro to Priya Sharma at Swigy Pvt Ltd"}))
    t = types(evs)
    assert t[-1] == "end" and "done" in t and "path" in t and "draft" in t and "error" not in t


def test_run_unicode_and_injection_text_is_harmless(client):
    evs = events(client.get("/api/run", params={"q": "intro to <script>alert(1)</script> प्रिया at Swiggy 🚀"}))
    assert evs[-1]["type"] == "end"                   # parsed as plain text; no crash, the UI escapes it


def test_pipeline_crash_becomes_error_event(client, monkeypatch):
    import warmpath.pipeline as pl

    async def boom(q, emit):
        emit({"type": "step", "id": "parse", "status": "start", "label": "x", "detail": ""})
        raise ValueError("kaboom")
    monkeypatch.setattr(pl, "run", boom)
    evs = events(client.get("/api/run", params={"q": "anyone at Swiggy"}))
    assert types(evs) == ["step", "error", "end"] and "kaboom" in evs[1]["message"]


def test_hung_run_times_out(client, monkeypatch):
    import warmpath.pipeline as pl

    async def hang(q, emit):
        await asyncio.sleep(30)
    monkeypatch.setattr(pl, "run", hang)
    monkeypatch.setattr(server, "RUN_TIMEOUT", 0.2)
    evs = events(client.get("/api/run", params={"q": "anyone at Swiggy"}))
    assert types(evs) == ["error", "end"] and "Stopped after" in evs[0]["message"]


def test_concurrent_runs_are_queued_not_interleaved(monkeypatch):
    import warmpath.pipeline as pl
    order: list[str] = []

    async def slow(q, emit):
        order.append(f"start {q}")
        await asyncio.sleep(0.2)
        order.append(f"end {q}")
        emit({"type": "done", "result": {}})
    monkeypatch.setattr(pl, "run", slow)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://t") as c:
            return await asyncio.gather(c.get("/api/run", params={"q": "a"}), c.get("/api/run", params={"q": "b"}))
    r1, r2 = asyncio.run(go())
    assert order in (["start a", "end a", "start b", "end b"], ["start b", "end b", "start a", "end a"])
    assert any(e.get("id") == "queue" for e in events(r1) + events(r2))   # the waiting run was told why


# ------------------------------------------------------------------ mock replay

def test_mock_replay_streams_a_full_run(client):
    t = types(events(client.get("/api/run", params={"mock": 1})))
    assert t[-1] == "end" and "done" in t and "path" in t


def test_mock_missing_file(client, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "MOCK", tmp_path / "nope.jsonl")
    evs = events(client.get("/api/run", params={"mock": 1}))
    assert types(evs) == ["error", "end"] and "replay file missing" in evs[0]["message"]


def test_mock_corrupt_line_is_skipped(client, monkeypatch, tmp_path):
    f = tmp_path / "m.jsonl"
    f.write_text('{"type":"step","id":"a","status":"start","label":"x"}\n{not json\n\n{"type":"done","result":{}}\n')
    monkeypatch.setattr(server, "MOCK", f)
    assert types(events(client.get("/api/run", params={"mock": 1}))) == ["step", "warning", "done", "end"]


# ------------------------------------------------------------------ /api/crawl

def test_crawl_rejects_non_profile_urls(client):
    evs = events(client.get("/api/crawl", params={"seeds": "hello, https://evil.example.com/x"}))
    assert types(evs) == ["error", "end"] and "evil.example.com" in evs[0]["message"]


def test_crawl_skips_bad_seeds_but_runs_good_ones(client):
    evs = events(client.get("/api/crawl", params={
        "seeds": "www.linkedin.com/in/aditya-seed, junk", "depth": 99, "budget": -5}))
    t = types(evs)
    assert t[0] == "warning" and "junk" in evs[0]["message"]
    assert "done" in t and t[-1] == "end" and "error" not in t


def test_parse_seeds_normalises_and_dedupes():
    ok, bad = server.parse_seeds(" linkedin.com/in/a , https://www.linkedin.com/in/a/\n<https://in.linkedin.com/in/b> ftp://x")
    assert ok == ["https://linkedin.com/in/a", "https://in.linkedin.com/in/b"] and bad == ["ftp://x"]


# ------------------------------------------------------------------ graph API on an empty / odd graph

def test_graph_endpoints_on_empty_graph(client):
    assert client.get("/api/graph/stats").json()["people"] == 0
    assert client.get("/api/graph/subgraph").json() == {"nodes": [], "edges": []}
    assert client.get("/api/graph/brokers").json() == []
    r = client.get("/api/graph/path", params={"a": 1, "b": 2}).json()
    assert r["found"] is False and "not in the graph" in r["reason"]


def test_graph_bad_inputs_return_readable_errors(client):
    assert client.get("/api/graph/tie", params={"a": 1, "b": 1}).status_code == 400
    r = client.get("/api/graph/tie", params={"a": 1, "b": 2})
    assert r.status_code == 404 and "not in the graph" in r.json()["error"]
    assert client.get("/api/graph/subgraph", params={"center": "'; DROP TABLE nodes;--"}).status_code == 400
    assert client.get("/api/graph/subgraph", params={"center": "person:424242"}).status_code == 404
    assert client.get("/api/graph/path", params={"a": "x", "b": 2}).status_code == 422
    assert client.get("/api/graph/path", params={"a": 3, "b": 3}).status_code == 400


def test_graph_after_a_run_has_cited_path(client):
    events(client.get("/api/run", params={"q": "warm intro to whoever runs data at Swiggy via IITB"}))
    r = client.get("/api/graph/path", params={"a": 9, "b": 1}).json()
    assert r["found"] and r["hops"] >= 1
    assert all(f["evidence"] for t in r["ties"] for f in t["factors"] if f["name"] == "overlap_months")
    assert client.get("/api/graph/subgraph", params={"center": "person:1"}).json()["nodes"]


# ------------------------------------------------------------------ CLI

def run_cli(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["warmpath", *argv])
    with pytest.raises(SystemExit) as e:
        cli.main()
    return e.value.code


def test_cli_exit_codes(monkeypatch):
    assert run_cli(monkeypatch, "intro to Priya Sharma at Swiggy") == 0
    assert run_cli(monkeypatch, "   ") == 2                         # nothing to do
    assert run_cli(monkeypatch, "graph", "knows", "abc") == 2         # not a person id
    assert run_cli(monkeypatch, "graph", "path", "1", "1") == 0       # same person: "no path", not a crash
    assert run_cli(monkeypatch, "crawl", "--depth") == 2              # flag without a value
    assert run_cli(monkeypatch, "crawl", "--seeds", "junk") == 2      # no valid seed
    assert run_cli(monkeypatch, "serve", "--port", "http") == 2


def test_cli_missing_key_is_one_line(monkeypatch, capsys):
    monkeypatch.delenv("WARMPATH_FAKE")
    assert run_cli(monkeypatch, "anyone at Swiggy") == 1
    assert "CRUSTDATA_API_KEY" in capsys.readouterr().out


def test_cli_ctrl_c(monkeypatch):
    def interrupt(coro, *_):
        coro.close()
        raise KeyboardInterrupt
    monkeypatch.setattr(cli.asyncio, "run", interrupt)
    assert run_cli(monkeypatch, "anyone at Swiggy") == 130


def test_cli_show_survives_malformed_and_markup_events(capsys):
    cli.show({"type": "path"})                                        # missing payload
    cli.show({"type": "step", "status": "done", "label": "[bold red]x[/] [/oops]", "detail": None})
    cli.show({"type": "path", "path": {"nodes": [{"name": "[link=evil]A"}], "ties": [], "score": None}})
    out = capsys.readouterr().out
    assert "[/oops]" in out and "[link=evil]A" in out


# ------------------------------------------------------------------ MCP tools

def call(tool: str, **args):
    res = asyncio.run(mcp_server.mcp.call_tool(tool, args))
    return json.loads(res.content[0].text)


def test_mcp_bad_inputs_return_errors_not_crashes():
    assert "empty request" in call("find_warm_paths", request="  ")["error"]
    assert "too long" in call("find_warm_paths", request="x" * 2000)["error"]
    assert "different" in call("explain_tie", person_a=1, person_b=1)["error"]
    assert "not in the WarmPath graph" in call("explain_tie", person_a=1, person_b=2)["error"]
    assert call("graph_path", person_a=1, person_b=2, max_hops=99)["found"] is False


def test_mcp_find_warm_paths_end_to_end():
    r = call("find_warm_paths", request="intro to Priya Sharma at Swiggy")
    assert r["target"]["name"] == "Priya Sharma" and r["paths"]
    assert all(f["evidence"] for p in r["paths"] for t in p["ties"] for f in t["factors"] if f["points"] >= 20)
    g = call("graph_path", person_a=r["paths"][0]["ties"][0]["person_ids"][0], person_b=r["target"]["person_id"])
    assert g["found"]


def test_mcp_pipeline_crash_is_reported(monkeypatch):
    import warmpath.pipeline as pl

    async def boom(q):
        raise RuntimeError("upstream down")
    monkeypatch.setattr(pl, "run", boom)
    assert "upstream down" in call("find_warm_paths", request="anyone at Swiggy")["error"]


# ------------------------------------------------------------------ workspace: history, brief, inbox, account map, guardrails

def _run_once(client, q="intro to Priya Sharma at Swiggy") -> str:
    done = [e for e in events(client.get("/api/run", params={"q": q})) if e["type"] == "done"][0]
    assert done["run_id"]
    return done["run_id"]


def test_history_and_brief(client):
    assert client.get("/api/history").json() == []
    run_id = _run_once(client)
    h = client.get("/api/history").json()
    assert h[0]["run_id"] == run_id and h[0]["target"] == "Priya Sharma"
    full = client.get(f"/api/history/{run_id}").json()
    assert full["paths"] and full["run_id"] == run_id
    md = client.get(f"/api/report/{run_id}.md").text
    assert md.startswith("# Warm intro brief: Priya Sharma") and "Sources:" in md and "## Audit trail" in md
    dl = client.get(f"/api/report/{run_id}.md", params={"download": 1})
    assert "attachment" in dl.headers["content-disposition"]


def test_history_survives_corrupt_report_and_rejects_traversal(client, tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "broken.json").write_text("{not json")
    assert client.get("/api/history").json() == []
    assert client.get("/api/history/..%2F..%2Fetc").status_code == 404
    assert client.get("/api/report/a.b.md").status_code == 404


def test_inbox_review_flow(client, tmp_path):
    run_id = _run_once(client)
    box = client.get("/api/inbox").json()
    key = box["items"][0]["key"]
    assert box["counts"]["review"] >= 1 and key.startswith(run_id)
    r = client.post("/api/inbox", json={"key": key, "status": "approved", "body": "Edited by a person."}).json()
    assert r["status"] == "approved" and r["body"] == "Edited by a person."
    approved = list((tmp_path / "outbox").glob("*.approved.md"))
    assert approved and "Edited by a person." in approved[0].read_text() and "not sent" in approved[0].read_text()
    item = next(i for i in client.get("/api/inbox").json()["items"] if i["key"] == key)
    assert item["edited"] and item["status"] == "approved"
    client.post("/api/inbox", json={"key": key, "status": "rejected"})
    assert not list((tmp_path / "outbox").glob("*.approved.md"))      # un-approving removes the approved copy
    assert client.post("/api/inbox", json={"key": key, "status": "sent"}).status_code == 400
    assert client.post("/api/inbox", json={"key": key, "body": "x" * 6000}).status_code == 400
    assert client.post("/api/inbox", json={"key": "nope:1"}).status_code == 404
    assert client.post("/api/inbox", json={"key": 5}).status_code == 400


def test_account_map_streams_one_row_per_unique_target(client):
    evs = events(client.get("/api/batch", params={
        "targets": "intro to Priya Sharma at Swiggy\n\nINTRO TO PRIYA SHARMA AT SWIGGY\nasdfgh qwerty\n# a comment"}))
    rows = [e for e in evs if e["type"] == "batch" and e["state"] in ("done", "error")]
    assert [r["i"] for r in rows] == [0, 1]
    assert rows[0]["target"] == "Priya Sharma" and rows[0]["score"] and rows[0]["run_id"]
    assert rows[1]["target"] is None and rows[1]["routes"] == 0
    assert evs[-1]["type"] == "end"


def test_account_map_limits(client):
    assert types(events(client.get("/api/batch", params={"targets": "  \n "}))) == ["error", "end"]
    many = "\n".join(f"head of data at company{i}" for i in range(20))
    assert "too many" in events(client.get("/api/batch", params={"targets": many}))[0]["message"]


def test_access_key_rate_limit_and_daily_cap(client, monkeypatch):
    g = server.ws.Guard()
    monkeypatch.setattr(server, "guard", g)
    g.key = "s3cret"
    assert client.get("/api/graph/stats").status_code == 401
    assert client.get("/").status_code == 401
    assert client.get("/api/health").status_code == 200                   # health stays open for the host's checks
    assert client.get("/", params={"key": "wrong"}, follow_redirects=False).status_code == 401
    r = client.get("/", params={"key": "s3cret"}, follow_redirects=False)
    assert r.status_code == 303 and "wp_key" in r.headers["set-cookie"]
    assert client.get("/api/graph/stats", headers={"x-warmpath-key": "s3cret"}).status_code == 200
    g.key, g.rate = "", 2
    assert "error" not in types(events(client.get("/api/run", params={"q": "intro to Priya Sharma at Swiggy"})))
    events(client.get("/api/run", params={"q": "intro to Priya Sharma at Swiggy"}))
    third = events(client.get("/api/run", params={"q": "intro to Priya Sharma at Swiggy"}))
    assert types(third) == ["error", "end"] and "Too many" in third[0]["message"]
    assert "done" in types(events(client.get("/api/run", params={"mock": 1})))   # replay is free, never limited
    g.rate, g.daily = 0, 1.0
    g.record(5)
    capped = events(client.get("/api/run", params={"q": "intro to Priya Sharma at Swiggy"}))
    assert "credit cap" in capped[0]["message"]


def test_security_headers(client):
    h = client.get("/").headers
    assert h["x-frame-options"] == "DENY" and "default-src 'self'" in h["content-security-policy"]
