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
- 11:32 · B · rule parser v1 was case-sensitive on the company ("at Swiggy" ok, "at swiggy" missed) and read "intro"
  as the preposition "in" + "tro" → rewrote it: text-speak normaliser (teh/da/2/sum1/pls), company URL and domain
  detection, "<role> of <Co>" only when there's no "at", "<Co>'s <role>", "<Name> (<Co>)", Hinglish
  "<co> mein <role> se intro", network hints ("via ex-Microsoft folks"). 16-case messy suite, all green.
- 11:32 · B · LLM parse could return a person the user never named → its person/company are kept only if they
  fuzzy-match the request text (lets it fix "swigy" → "Swiggy", blocks invented names). Rules stay the fallback.
- 11:34 · B · hardest case, measured on a hand-made scenario (target: 2y at a 30-person startup, then Google 180k):
  v1 scores were small-team pair 67.3, Google same-team 67.0, Google same-function-only 62, Google total stranger 52.
  "Both at Google" was worth almost as much as two years on a tiny team. Tuning the size points alone can't fix
  it: size is worth at most 25 of 100, while overlap months give up to 40 to anyone at any company. → explicit, explainable `big_company_discount` factor: at >1k people we
  keep 80% / 55% / 35% of the overlap points, and give 35% back if there's a team signal (same function, similar
  title, same location). Now: small team 72.3 > Google same team 54 > same function only 46 > stranger 26.
  "Joined within two months" only counts at ≤1k people (thousands join Google every month).
- 11:34 · B · a past stint with no end date was treated as "still there", inventing years of overlap → cap at 1 year
  and say so in the factor text. End-before-start records produce no claim at all.
- 11:34 · B · paths bug: `c.person_id == target.person_id` is True when both are None, so every id-less connector was
  dropped. Identity is now Crustdata id, else profile URL, never name (same-name people are common).
- 11:36 · B · claim checker v1 only checked years → now checks years, numbers/%, durations and every capitalised word
  against the path's evidence vocabulary (names, employers, titles, schools, factor text). The template itself is
  checked too (it had "15 minutes", which the checker rightly flagged → reworded). LLM drafts with any unsupported
  sentence are dropped and kept in `Draft.llm_rejected` for the UI. Outbox files list every source record.
- 11:36 · B · web proof counted LinkedIn "people also viewed" sidebars as co-mentions → skip profile/directory hosts
  and require full names close together; label hits co-founded / co-authored / spoke together.
- 11:36 · B · free LLM down = 4 models × 40s timeout per call, per draft → 20s timeout, 45s overall deadline, 2-min
  cooldown after a total failure, `WARMPATH_LLM=0` kill switch for the "works with the LLM off" demo.
- 11:38 · B · eval harness: co-founder recovery. Ties are broken against us; random baseline computed exactly;
  ablation without the title factor because both co-founders often have "Co-founder" titles (would flatter us).
- 12:15 · B · did the UPDATES.md items: new verified free-model chain; 429 → next model, 403 → skip that model for
  the process; `LLM_MAX_CALLS` (default 6) + in-memory cache, so a rerun costs no LLM calls; the target company is
  dropped from the network filter; the LLM only fills gaps or refines the rules ("data" → "head of data" yes,
  "cto" → a different phrasing no, a different company no). The 3 parser bugs were already fixed by the rewrite, so
  they're now regression tests.
- 12:15 · B · score saturation at 100: the suggested `100(1-e^(-raw/60))` would also inflate weak ties (25 → 34) and
  silently move every MIN_TIE threshold → chose a knee: linear up to 70, soft cap above (raw 100 → 89, 115 → 93).
  `score.tie_score(factors)` recomputes a tie after adding a factor.
- 12:15 · B · first full offline run (fake world, LLM off): "teh data guy at swigy pls, via iitb ppl" → Priya Sharma
  via a 2-hop path, draft fact check 10/10 sentences, 9 sources listed. Fixed: an ongoing overlap was cited as
  "ended <this month>"; blurb wording.
- 12:50 · B · live eval, first run: 40% hit@1. Cause: `people.founders` is noisy. At Razorpay 12 of 14 entries are
  "Founder's Office" staff and EAs; at Zomato most are one-job profiles claiming "Founder" with no dates (Deepinder
  Goyal isn't listed). → a co-founder = founder title at that company, starting within 2 years of its founding.
  This also stopped us paying 1 credit to enrich each fake founder. → 75% hit@1, still below "longest overlap" (86%).
- 12:55 · B · read every miss factor by factor: 4 of 7 were real co-founders the list missed (Hemesh Singh,
  Abhiraj Singh Bhal, Thiyagarajan T) or two Crustdata records for one person (Alakh Pandey). → apply the same
  founder rule to the whole candidate pool, and merge same-name records. → 91% hit@1 / 94% hit@3 (random 9% / 25%,
  longest overlap 88% / 94%, no-title ablation 91%). Remaining misses are real: Nikhil Kamath → Richard Pattle (True
  Beacon co-founder), plus two Licious founder-titled profiles with no dated overlap.
- 12:45 · B · bug found on live data: founders with several stints at one company (title changes) showed
  "overlapped 91 months, 2014-12 → 2022-07" though both are still there, so recency said "ended 4 years ago".
  → `find_overlaps` joins touching windows at the same company into one tenure.
- 12:55 · B · known weakness (next step): company size uses the *latest* headcount, so founders who worked
  together at a 10-person Razorpay get a big-company discount today. `/company/enrich` has a headcount time series;
  using the headcount during the overlap is the fix. Not done now, because it adds a call per company per tie.
- 13:10 · B · UPDATES 12:08/12:15: `function_category` is usually empty live → `same_team` factor when both titles
  name the same team (`discover.team_keyword`), which also counts as a team signal for the big-company discount.
  Drafts: LLM polish only when every tie is `verified`; verified blurbs end "(verified via Crustdata)"; unverified
  links are listed in `claims_unsupported`. Eval re-scored offline: unchanged (91% / 94%).
- 13:10 · B · "teh data guy at swiggy pls" finds no target on origin/main because the parser fix wasn't pushed yet
  (no repo access for Vaibhav2402). Locally it runs end to end in the fake world: Priya Sharma, 2 verified paths, 2 drafts.
- 12:20 · Aditya · team crawl (depth 1, 49 credits) gave 208 people / 1,135 relationships, which looked great but was wrong:
  "Self-employed" etc. were treated as shared employers, building fake cliques (a real false path: Aditya → Ravi →
  "Self-employed" → Dipyaman). Dropped generic employers at parse time → honest 135 people / 253 relationships.
- 12:22 · Aditya · with seeds, stranger paths (65) outranked the personal 4-hop path (26) → seed-first ranking ("your paths").
- 12:25 · Aditya · profiled a fully cached run: 2 s CPU, ~50 s waiting on free-LLM calls → drafts in parallel (34 s);
  the remaining fix (shorter LLM timeouts) is with Vaibhav.
- 13:35 · B · company size during the overlap: new `warmpath/headcount.py` keeps `/company/enrich` headcount history
  (weekly, but only from ~2021). The size factor now uses the smallest recorded headcount inside the overlap and
  cites `company:<id>#headcount.timeseries`; older overlaps say "earliest on record". Deliberately no "joined near
  founding" bonus: the eval defines co-founders that way, so it would be grading its own answer. Eval: unchanged
  (91% / 94%, with a latest-headcount ablation row). All 11 startups were already >1k people when their records start,
  so the gain here is a correct, dated size claim rather than a ranking change. Size text no longer says "worked
  closely" for a 5k-person company.
- 12:40 · Aditya · adversarial sweep (35 inputs) found 2 serious bugs: no `done` on an unresolved target (UI would hang) and
  sqlite "database is locked" (uncommitted upsert_tie). Both fixed; the sweep is now a permanent test.
- 12:50 · Aditya · live edge cases: "CTO" ≠ "Chief Technology Officer" in data → acronym expansion; bare "Swiggy" picked a junk
  1-role "CEO" → leadership default + thin-profile penalty → real co-founder; fuzzy name matching ("Kunal" ~ "Krunal") →
  exact-phrase first + web-search-for-profile fallback. Tried: web fallback alone was ambiguous until we required the profile to
  list the company.
- 13:55 · B · UPDATES 12:58: Devanagari Hindi ("मुझे Swiggy के head of data से मिलवाओ") now parses with the LLM off
  (role = the Latin phrase with a role word, company = the first other one); a bare 1-4 word request ("Swiggy",
  "Zepto CTO") sets the company; `thin_profile` factor (-8 per person with 1 role and no education, cited) so a thin
  record never wins on its own. Eval unchanged. Hindi request runs end to end in the fake world.
- 13:55 · B · ⚠ for Aditya: fake mode shares `.cache/crust` with live runs. After a live "Swiggy" lookup, a fake run
  gets the real id 5702 and finds nobody. Record fake-mode demos with `WARMPATH_CACHE=0` or a separate
  `WARMPATH_CACHE_DIR` (better: key the cache by mode in crust.py).
