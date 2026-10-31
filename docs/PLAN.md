# WarmPath: build plan (ContextCon IIT Bombay, Crustdata track)

> **One line:** Type who you want to reach. WarmPath finds the people who actually worked
> alongside them, scores how well each pair knows each other, and hands you a ready-to-forward intro
> request. Every link is backed by Crustdata records you can click and check.

Theme: **Infrastructure for agents**, from the deck's list: *"A map of who knows whom, scored by how
closely they worked."* It is also used in Hiring (referrals), Revenue (reach the decision-maker) and
Investing (fundraising intros).

---

## 1. The problem and the process we replace

| Today (manual) | With WarmPath (no one at the keyboard) |
|---|---|
| Cold message on a professional network, single-digit reply rate | A warm intro from someone who sat next to the target for two years |
| An analyst scrolls through profiles guessing "do these two know each other?" | A join on the **canonical `crustdata_company_id` plus overlapping dates**, computed in seconds |
| "I think Rahul knows her" (no proof) | Every tie cites both Crustdata records, the overlap window, the company size at the time, and any web co-mentions |
| Writing the intro ask by hand | A double-opt-in draft for the connector plus a forwardable blurb, fact-checked against the evidence |

Why it fits Crustdata: an LLM wrapper can't do this. The tie only exists because Crustdata maps every
role to a canonical company ID with dates, which is the identity graph the track asks us to build on.

## 2. End-to-end flow (what the demo shows)

```
"get me a warm intro to whoever runs data at Swiggy, ideally via IIT Bombay folks"
  │
  ├─1 PARSE      free LLM (OpenRouter) → TargetSpec{role, company, network.schools=[IIT Bombay]}
  │              rule-based fallback if the LLM is down
  ├─2 RESOLVE    /company/identify (free) → company_id → /person/search (title + company_id)
  │              → pick the decision-maker (confidence + reason) → /person/enrich full career
  ├─3 DISCOVER   for the target's best stints: /person/search company_id = X AND network filter
  │              → keep people whose dates overlapped with the target's (computed client-side)
  │              + seeds: the team's own profiles → 1-hop / 2-hop paths
  ├─4 SCORE      explainable tie strength 0-100 (factors below), optional /web/search/live co-mentions
  ├─5 PATHS      rank You → connector → target chains (weakest-link scoring)
  ├─6 DRAFT      intro request + forwardable blurb; every sentence must map to Evidence
  └─7 DELIVER    web UI (live steps + graph + cited path cards) · local outbox/*.md · audit trail JSON
```

Rule from the event: **nothing is sent to real people.** Drafts go to `outbox/` only.

## 3. Tie-strength model (explainable, every factor cites evidence)

| Factor | Points | Evidence |
|---|---|---|
| Overlap duration at the same `company_id` | up to 40 (`40 × min(1, months/24)`) | both stints (`person:ID#experience.past[i]`) |
| Company size during the overlap | 25 if ≤50 people, 18 ≤200, 10 ≤1k, 5 ≤10k, 2 above | `company_headcount_latest` / company enrich |
| Same function / similar title | up to 10 | `function_category`, title similarity |
| Same location | 5 | stint location |
| Recency of the overlap | up to 10 (full if it ended ≤3y ago, decays) | dates |
| Worked together at more than one company | +10 per extra company | multiple overlaps |
| Classmates (same school, overlapping years) | 15 | `education.schools[i]` |
| Web co-occurrence (co-authors, co-founders, joint talk) | +15 | `/web/search/live` result URL |

Score = min(100, sum). Path score = `0.7 × weakest tie + 0.3 × mean tie`, × `0.85^(hops−1)`.

## 4. Feature list

### MVP (must ship by 13:30)
1. Free-text request → `TargetSpec` (LLM plus rule-based fallback; handles "the data guy at swiggy", typos, URLs)
2. Target resolution with disambiguation and a confidence reason (company identify → person search → enrich)
3. Connector discovery at the target's top 3–4 stints, filtered by network (school / company / seeds)
4. Overlap computation and explainable tie score
5. Ranked intro paths with citations on every edge
6. Intro drafts to `outbox/`, with the draft's claims checked against evidence
7. Web UI: input box, live step stream (SSE), path graph, path cards with citations, audit drawer
8. CLI: `uv run warmpath "…"`
9. Robustness: retries/backoff on 429/5xx, pacing to rate limits, disk cache, credit budget,
   redacted/not_found handling, missing dates, company aliases

### Differentiators (13:30–14:30)
10. **Seeds / "my network"**: paste the team's 3 profile URLs. Finds 1-hop ties (you already know the target)
    and 2-hop ties (you → ex-colleague → target) using a person search on `company_id ∈ your companies AND ∈ target's companies`
11. **Web proof**: `/web/search/live "A" "B"` adds co-authored papers, co-founded companies and joint talks as cited evidence
12. **Freshness guard**: warns if the target's or connector's profile is stale or they changed jobs recently (paths may be dead)
13. **MCP server** exposing `find_warm_paths`, `explain_tie(a,b)`, `resolve_person` so any agent (Claude Desktop/Code) can use WarmPath
14. **Eval harness** (credibility with judges): take N real companies → founders from `/company/enrich people.founders`.
    For each founder, is their real co-founder WarmPath's #1 connector? Report top-1/top-3 accuracy versus a "random colleague" baseline
15. **Audit trail**: every API call logged with request, credits (`x-credits-used`) and response sha256, downloadable as JSON

### Stretch (only if ahead)
16. Batch mode: CSV of 20 target accounts → best path per account (an "account map" for sales)
17. Watcher: `/watch/person` on the target and connectors. Alerts when a new path appears or a connector changes job
18. Demo replay mode: run entirely from the committed cache (`WARMPATH_CACHE=1`), for stage-safe finals with no network risk
19. Intro "warmth explainer" card: a plain-English reason ("You both shipped at a 40-person Razorpay team in 2019")

## 5. Team split (3 members, each with Claude Code). Own your files to avoid merge conflicts.

| | **Member A (Aditya): data and graph core + integration** | **Member B: intelligence** | **Member C: product, UI and demo** |
|---|---|---|---|
| Owns | `warmpath/crust.py`, `resolve.py`, `discover.py`, `pipeline.py` | `parse.py`, `score.py`, `paths.py`, `webproof.py`, `draft.py`, `eval/` | `server.py`, `static/*`, `cli.py`, `mcp_server.py`, `README.md`, demo video |
| MVP | Resolve target; connector search; seeds; enrich; budget/caching | LLM + rule parser; tie scoring; path ranking; drafts + claim check | FastAPI SSE server; single-page UI with graph (vis-network via CDN); CLI with rich; mock events |
| Then | Freshness guard; batch mode; watcher | Web proof; eval harness + metrics table | MCP server; demo script; record video; README with architecture diagram |

Shared contracts (agree before changing):
- `warmpath/models.py`: all dataclasses. Add fields freely; **don't rename or remove** without telling the team.
- `warmpath/events.py`: the event schema the UI consumes (see below).
- Function signatures in section 6.

### Git workflow
- One GitHub repo, everyone on `main`, **small commits, `git pull --rebase` before every push**.
- Touch only your own files. Changes to shared files go in a separate commit with a message in the team chat.
- `.env` is never committed. Each member copies `.env.example` → `.env`.

## 6. Module contracts (signatures are fixed; internals are up to the owner)

```python
# parse.py (B)
async def parse_request(text: str) -> TargetSpec

# resolve.py (A)
async def resolve_target(c: Crust, spec: TargetSpec, emit: Emit) -> tuple[Person | None, Company | None]

# discover.py (A)
async def load_seeds(c: Crust, spec: TargetSpec, emit: Emit) -> list[Person]
async def find_connectors(c: Crust, target: Person, spec: TargetSpec, seeds: list[Person], emit: Emit) -> list[Person]

# score.py (B)
def find_overlaps(a: Person, b: Person, min_months: float = 2) -> list[Overlap]
def score_tie(a: Person, b: Person) -> Tie

# webproof.py (B)
async def web_cooccurrence(c: Crust, a: Person, b: Person) -> Factor | None

# paths.py (B)
def build_paths(target: Person, connectors: list[Person], seeds: list[Person], spec: TargetSpec) -> list[IntroPath]

# draft.py (B)
async def draft_intro(path: IntroPath, spec: TargetSpec) -> Draft

# pipeline.py (A): the single entry point used by server, cli and mcp
async def run(request: str, emit: Emit | None = None, **opts) -> RunResult
```

### Event schema (`emit(event: dict)`, which the UI renders live)
```json
{"type":"step","id":"resolve","status":"start|done|error","label":"Resolving target","detail":"..."}
{"type":"node","role":"target|connector|seed","person":{...Person}}
{"type":"edge","a":123,"b":456,"score":72.5,"label":"Flipkart · 2019-03→2021-06"}
{"type":"path","path":{...IntroPath}}
{"type":"draft","draft":{...Draft}}
{"type":"warning","message":"Target profile last updated 140 days ago"}
{"type":"done","result":{...RunResult}}
{"type":"error","message":"..."}
```
Member C: write `fixtures/mock_events.jsonl` first, matching this schema, so the UI can be built before the backend works.

## 7. Timeline (IST)

| Time | Milestone |
|---|---|
| 11:15 | Everyone: clone, `uv sync`, `.env`, read this file. C writes mock events |
| 11:15–13:00 | Build the MVP modules in parallel |
| **13:00** | **Integration #1:** `uv run warmpath "..."` works end to end on real data |
| 13:30 | Mentor checkpoint: show the live UI run |
| 13:30–14:30 | Differentiators (seeds 2-hop, web proof, MCP, eval) |
| **14:30** | **Feature freeze.** Warm the cache for 3 demo queries |
| 14:30–15:10 | Record the 2-min video (script below), write the README |
| 15:15 | Final push, submit repo + video (deadline 15:30) |

## 8. Two-minute demo script

1. (0:00–0:15) Problem: "Cold outreach gets ignored. Warm intros work, but finding one takes hours of guessing."
2. (0:15–1:15) Type the request live → steps stream in → the graph builds → top 3 paths with scores.
   Click an edge: both Crustdata records, the overlap dates, company size at the time, the web co-mention link.
3. (1:15–1:40) Open the draft in the outbox: every claim is ticked against the evidence. Show the audit trail (calls, credits, hashes).
4. (1:40–2:00) Robustness and eval: a messy input with a typo still resolves, plus "co-founder recovered as #1 connector in X/N companies". Close with the MCP tool used from Claude.

## 9. Crustdata API notes (verified from the docs)

- Headers: `authorization: Bearer KEY`, `x-api-version: 2025-11-01`. Errors come as `{"error":{"type","message"}}`.
- `/person/search` body `{filters, limit, fields, cursor}`. Ops: `=`, `!=`, `in`, `not_in`, `(.)` (all words, fuzzy),
  `[.]` (phrase), `=>`, `=<` (**not** `>=`/`<=`). Groups use `{"op":"and"|"or","conditions":[...]}`.
  Key filters: `experience.employment_details.company_id` (also `.current.` / `.past.`), `...title`, `...start_date`,
  `education.schools.school`, `basic_profile.name`, `basic_profile.location.full_location`.
  The response returns `crustdata_company_id` on each stint. 0.03/result + 0.1 per premium group. 30 rpm.
- `/person/enrich` `{professional_network_profile_urls[≤25], fields}`. Ask for `experience`, `education` explicitly. 1 credit, 15 rpm.
  `match_status`: `matched` / `not_found` / `redacted` (handle all three).
- `/company/identify` `{names|domains|professional_network_profile_urls}` is free; returns `matches[].company_data.basic_info`.
- `/company/enrich` `{crustdata_company_ids, fields:["basic_info","headcount","people"]}`: `headcount.total`, `people.founders`. 2 credits.
- `/web/search/live` `{query, sources:["web"|"news"|"scholar"...], site?}` → `results[{title,url,snippet}]`. 1 credit, 10 rpm.
- The `x-credits-used` response header gives the cost of each call. `crust.py` sums it against `WARMPATH_BUDGET`.

## 10. Kickoff prompts (paste into each member's Claude Code)

**Member B:**
> Read CLAUDE.md and docs/PLAN.md. I'm Member B (intelligence). Implement warmpath/parse.py (OpenRouter LLM via
> warmpath/llm.py plus a robust rule-based fallback), score.py (find_overlaps, score_tie per section 3 with Evidence on
> every Factor), paths.py, webproof.py and draft.py (drafts may only state facts present in the path's Evidence;
> list any unsupported claim). Keep to the section 6 signatures. Add unit tests in tests/ with hand-made Person objects (no API).
> Then build eval/cofounder_eval.py (section 4, item 14).

**Member C:**
> Read CLAUDE.md and docs/PLAN.md. I'm Member C (product). First write fixtures/mock_events.jsonl matching the event
> schema in section 6. Then build warmpath/server.py (FastAPI: GET / serves static/index.html, GET /api/run?q=... streams
> SSE events from pipeline.run, or replays the mock file when ?mock=1) and static/index.html: a single page, no build step,
> vis-network from cdnjs. Live step list, a graph (target in the centre, connectors around, seeds outside, edge width = tie
> score), path cards with clickable citations, a drafts tab, an audit drawer. Make it look polished for a demo video.
> Then cli.py (rich live output) and mcp_server.py (mcp package, tools find_warm_paths / explain_tie).
