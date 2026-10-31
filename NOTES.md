# Build notes: what we tried, what failed

The deck says: *"Keep notes. What you try and what fails. They make the strongest demos and the best answers in the finals."*
Everyone appends here (newest at the bottom). Format: `HH:MM · who · tried → result → decision`.

## Ideas we weighed before building
- Resume claim verifier (Hiring): solid fit for the data, but common. Rejected as not distinctive.
- Runway Radar: predicting portfolio cash-outs (Investing). High-stakes, hard to validate in 5 hours. Rejected.
- Inbound lead desk / pre-send fact guard / procurement vendor-pick: too close to existing tools. Rejected.
- **WarmPath (chosen):** "who knows whom, scored by how closely they worked". Only possible with a canonical
  person-company graph that has dates, so it plays directly to Crustdata's strength. Low stakes, high process impact.

## Design decisions
- 10:55 · A · ties = same `crustdata_company_id` + overlapping dates, checked client-side (search filters match any
  role, not the same role) → kept.
- 11:12 · A · graph DB: Neo4j needs Docker and a running server, which judges can't easily run → chose embedded SQLite
  property graph + networkx, with Cypher export for Neo4j.
- 11:12 · A · strongest path = Dijkstra on `-ln(score/100)`, so a chain of strong ties beats a short weak one.

## Log
- 11:35 · Aditya · no API key yet → built `warmpath/fake.py` (offline Crustdata with doc-shaped responses) and an
  end-to-end test suite. Found a **real bug**: the school filter `(.) "IIT Bombay"` misses profiles that say
  "Indian Institute of Technology Bombay" → added alias expansion (IIT/IIM/IIIT/NIT/BITS) for search and classmate matching.
- 11:35 · Aditya · `retry-after: 0` was treated as missing (falsy) → fixed. Pacing can be disabled for tests.
- 11:35 · Aditya · same-name test: two "Priya Sharma"s; the company filter picks the right one. Redacted / unknown company → graceful warnings.
- 11:45 · Aditya · loop 1: company resolution failed on typos/suffixes/lowercase → fallback chain (identify name →
  cleaned name → guessed domains → web search for the company page → identify URL). The first version searched the raw string
  ("Swigy Pvt Ltd company") and failed; searching the cleaned name works.
- 11:45 · Aditya · budget guard over-estimated person search (0.5/result) and blocked the target search under a small budget →
  0.33/result, matching the pricing table (0.03 + 0.1 experience + 0.1 education + filters).
- 11:45 · Aditya · parser gaps found by end-to-end tests ("head of data" → "head", name-only requests, lowercase company)
  → handed to Vaibhav in docs/UPDATES.md.
- 11:58 · Aditya · OpenRouter: the default free model names were stale (llama-3.3/deepseek gone). Listed /models and tested 3:
  Nemotron 3 Ultra works (3.7 s, correct JSON), Gemma 4 31B upstream 429, Inkling 403 (blocked for API use). Free tier = 50 req/day
  per key → LLM use must be capped and cached; rules stay the backbone.
- 12:00 · Aditya · first LIVE run. Live surprises: (a) "Swiggy" identifies to 5 companies, 3 at confidence 1.0, so the size
  tie-break picks the real one; (b) nobody at Swiggy is titled "Head of Data", so the strict title search returned 0 → added
  seniority-aware fallbacks; (c) education uses start_year/end_year, so classmates never fired → fixed; (d)
  `current.crustdata_company_id` is not a filter field (400). The alias is `current.company_id`.
- 12:05 · Aditya · big-company noise: 129–465 IITB people "at Swiggy", mostly other teams → narrowed with team keyword +
  start_date ≤ target end → 12 people. Also the LLM leaked the target company into the network filter → guard in discover.
- 12:08 · Aditya · graph memory on real data: run 1 = 28 credits/63 s, run 3 = 5 credits/17 s (51 connectors recalled).
- 12:15 · Aditya · verification pass: search profiles can be partial, so every top-path person is re-fetched with one batched
  enrich and ties are recomputed from full records; vanished overlaps are dropped. First test design failed because the
  big-company team narrowing had already excluded the "stale" connector (good behaviour), so the test was rebuilt on a
  small-company tie. Live: 5/5 verified, 1 call.
- 11:53 · Apurba · fixtures: recorded `fixtures/mock_events.jsonl` from a real `WARMPATH_FAKE=1` pipeline run instead of
  hand-writing it → the UI's offline replay can never drift from the real event schema. Re-record after event changes.
- 11:53 · Apurba · server: `/api/run` + `/api/crawl` stream SSE via an asyncio.Queue fed by `emit`; the pipeline task is
  cancelled when the browser disconnects, so a closed tab stops spending credits. Exceptions become `error` events
  instead of a silently dead stream.
- 11:53 · Apurba · edge evidence: `subgraph()` stores factor summaries but not citations, so clicking an edge calls
  `/api/graph/tie`, which re-runs `score_tie` on the two stored records. Every factor shows its Evidence, and it goes
  through GraphStore only.
- 11:53 · Apurba · MCP: the `mcp` package resolved to 2.x, where `FastMCP` was renamed `MCPServer`
  (`mcp.server.mcpserver`) → wrote mcp_server.py against 2.x. Tools: find_warm_paths, explain_tie, graph_path.
- 11:53 · Apurba · found: "teh data guy at swiggy pls" resolves no target (parser misses the lowercase company), so this is
  already on Vaibhav's list in UPDATES.md. It's the robustness shot in the video, so it needs fixing before recording.
- 12:19 · Apurba · worst-case pass on server/UI/CLI/MCP, with 26 new tests in `tests/test_product.py` (new file, offline). Streams
  never fail with a bare HTTP error: empty, huge or garbage queries, a missing key, a pipeline crash, a hung run (timeout
  `WARMPATH_RUN_TIMEOUT`, default 240 s), a missing or corrupt replay file and bad crawl seeds all arrive as `error` + `end` events
  with a fix-it message. Concurrent runs are queued (one paid run at a time, shared SQLite), and the waiting run is told why.
  SSE heartbeats every 15 s keep quiet rate-limited runs alive.
- 12:19 · Apurba · found by the tests: the same seed profile written two ways (`linkedin.com/in/a` vs `https://www.linkedin.com/in/a/`)
  was enriched twice and so paid for twice → seeds are now normalised and deduplicated.
- 12:19 · Apurba · UI worst cases, checked in headless Chromium: the vis-network CDN blocked (venue Wi-Fi) → paths, drafts and audit
  still work, with a notice in place of the graph. EventSource auto-reconnect would silently re-run (and re-bill) the pipeline →
  disabled. Double-click starts only one run. A lost server says "run stopped" instead of spinning forever. Empty graph, unknown
  people and non-numeric ids all give readable messages. CLI: Ctrl-C, piped stdin, bad flags and Crustdata text containing rich
  markup (`[bold]`) are handled, with exit codes 0/1/2/130.
- 12:19 · Apurba · for Aditya: `pipeline.run` returns before emitting `done` when the target can't be resolved (the `return`
  inside `try` skips the final emit). The UI now handles a clean end with no `done`, but CLI/MCP callers get no `done` event.
