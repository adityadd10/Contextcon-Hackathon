# WarmPath

**Warm intros to anyone, with every link verified on Crustdata's identity graph.**
Team: Aditya · Vaibhav · Apurba · ContextCon 03 · IIT Bombay · Theme: Infrastructure for agents (also Hiring, Revenue, Investing)

> Ask *"get me a warm intro to whoever runs data at Swiggy, ideally through IIT Bombay people"*. WarmPath resolves
> the real person, finds who actually worked next to them, scores how well each pair knows each other with reasons,
> and writes a ready-to-forward intro request. Every link cites the Crustdata records behind it.

## The service
_Which service it takes on, who does that job today, and who pays for it._

People pay for introductions every day:

| Who pays today | What they pay for |
|---|---|
| Founders raising money | Fundraising advisors and placement agents, often a share of the round, for investor intros |
| Companies hiring | Executive-search and recruiting firms, for referrals and sourcing |
| Sales teams | Warm-path tools (e.g. Sales Navigator TeamLink) plus SDR hours spent hunting for a mutual contact |
| Universities | Alumni offices that broker student ↔ alumni intros |

The job is always the same: find *who actually knows the target well enough to introduce you*, then ask them.
Today that means scrolling through profiles and guessing ("I think Rahul knows her"). A **tool** stops at a list of
names. WarmPath is a **service**: it delivers the finished intro request, with the reasons, and a person only steps in
to approve the send.

## What it does now
_The parts of the job it handles end to end, and where it still needs a person._

One sentence in, finished work out, no manual steps:

1. **Understands the request.** It reads free text, typos, URLs and vague roles ("the data guy at swigy") with an OpenRouter free model and falls back to rules when the LLM is down.
2. **Resolves the target** on Crustdata's identity graph. The company goes through a fallback chain (name → cleaned name → guessed domains → web search → URL). The person is picked with a stated reason ("currently at Swiggy; title best matches *head of data*"), and WarmPath warns on same-name ambiguity, people who left the company, and stale profiles.
3. **Finds connectors**: people who worked at the **same canonical `crustdata_company_id` with overlapping dates**, filtered by your network (school, past companies, the team's own profiles).
4. **Scores every tie** from 0 to 100 with explainable factors: months of overlap, company size at the time, same function, recency, classmates, and web co-mentions. Each factor cites the Crustdata record it came from.
5. **Ranks intro paths.** 1-hop paths (you know the target), 2-hop (you → ex-colleague → target), and multi-hop chains through the persistent graph, where the strongest chain wins, not the shortest.
6. **Drafts the intro ask.** It writes a double-opt-in note to the connector plus a forwardable blurb, and checks every claim against the evidence. Drafts go to `outbox/`. **Nothing is ever sent.**
7. **Learns.** Every person and relationship goes into a persistent social graph, so later queries are cheaper and better.
8. **Audits.** Every API call is logged with its request, credits used and a sha256 of the response.

**Where it still needs a person:** approving and sending the intro (by design, and required by the event rules),
and judging cases where the data is thin (redacted profiles, no dates, or no overlap within the network).

### Three ways to use it
- **Web UI** (`warmpath serve`): live step stream with the reason behind each decision, a path graph (click any edge to see its evidence), path cards with clickable citations, a Drafts tab, an Audit drawer, and a **Social graph** tab. The Social graph tab shows the whole network, lets you click an edge for its evidence, finds the path between any two people, lists super-connectors, and has a "Crawl my network" button.
- **CLI** (`warmpath "<request>"`): the same live output in the terminal.
- **MCP server** (`warmpath mcp`): tools `find_warm_paths`, `explain_tie` and `graph_path`, so any agent (Claude Code or Desktop) can find warm paths. This is the "infrastructure for agents" angle.

## What it could do next
_What we'd build with more time, and why now isn't the time._

- **Account maps for sales:** take a CSV of 20 target accounts and return the best warm path into each. The pipeline already does one account at a time, so this mostly needs batching and credit planning, which takes more credits than a hackathon day has.
- **Watchers:** use `/watch/person` on targets and connectors and alert when a new path appears or a connector changes jobs. This only pays off over weeks, so it can't be demoed in a day.
- **Two-sided consent:** the connector approves forwarding in one click before anything reaches the target. That needs real messaging and accounts, and the rules (rightly) forbid contacting people today.
- **Learned tie weights:** fit the factor weights on accepted vs. ignored intros. That needs outcome data we don't have yet. Today's weights are hand-set and explainable.
- **Neo4j at scale:** the graph already exports Cypher (`warmpath graph export`). Embedded SQLite is right for a demo that judges can run with no server.

## How to run it, and how it's built

```bash
git clone https://github.com/adityadd10/Contextcon-Hackathon.git && cd Contextcon-Hackathon
uv sync && cp .env.example .env   # add CRUSTDATA_API_KEY (+ optional OPENROUTER_API_KEY, WARMPATH_SEEDS)

uv run warmpath "warm intro to the head of data at Swiggy via IIT Bombay alumni"   # CLI
uv run warmpath serve                                                              # web UI → http://localhost:8000
uv run warmpath crawl --seeds <profile_url>,<profile_url> --depth 2               # grow the graph
uv run warmpath graph stats | brokers | path <from_id> <to_id> | export
uv run warmpath mcp                                                                # MCP server (stdio)
claude mcp add warmpath -- uv run --directory "$PWD" python -m warmpath.mcp_server
```

**No API key?** `WARMPATH_FAKE=1 uv run warmpath serve` runs everything against an offline fake Crustdata world
(Swiggy, a 30-person startup, Flipkart, two people named "Priya Sharma", a redacted profile). In the UI, the
*offline replay* toggle replays a recorded run from `fixtures/mock_events.jsonl`.

### Architecture

```
request ─► parse.py ─► resolve.py ─► discover.py ─► score.py ─► paths.py ─► webproof.py ─► draft.py ─► outbox/
           LLM+rules   company+person  connectors     tie 0-100   ranking     web proof     cited drafts
                            │              │              │
                            └──── crust.py (all Crustdata calls: retries, pacing, cache, budget, audit) ────┘
                                                          │
                                  graphdb.py (persistent social graph: SQLite + networkx) ◄─ crawl.py
pipeline.run(request, emit) ─► events ─► server.py (FastAPI + SSE) ─► static/index.html
                                     ├─► cli.py (rich)
                                     └─► mcp_server.py (MCP tools)
```

- **Agents and models:** one deterministic pipeline (`warmpath/pipeline.py`) and one entry point shared by the UI, CLI
  and MCP. The LLM (OpenRouter free models via `llm.py`) is used only for request parsing and drafts. Every LLM use has
  a rule-based fallback, so the system works with no LLM at all.
- **Data:** Crustdata only. The relationship signal is the canonical `crustdata_company_id` on every role, plus dates.
- **Social graph:** `(:Person)-[:WORKED_AT]->(:Company)`, `(:Person)-[:STUDIED_AT]->(:School)` and derived
  `(:Person)-[:KNOWS {weight, factors, evidence}]-(:Person)`. Ingesting a person scores them against everyone already
  in the graph who shares a company or school, so the graph densifies on its own. The strongest path is Dijkstra on
  `-ln(score/100)`. Super-connectors are ranked by betweenness centrality.
- **Tools and stack:** Python 3.12, uv, httpx, FastAPI with Server-Sent Events, SQLite, networkx, rapidfuzz, rich, MCP
  SDK. The UI is a single HTML file using vis-network from a CDN, with no build step.

### Where we call Crustdata (all through `warmpath/crust.py`)

| Endpoint | Where | Why |
|---|---|---|
| `/company/identify` (free) | `resolve.py` | Turns "Swigy Pvt Ltd" / a domain / a URL into the canonical `crustdata_company_id` |
| `/person/search` | `resolve.py`, `discover.py`, `crawl.py` | Finds the decision-maker by title + company, then people at the target's companies (∩ school/network) whose dates overlap |
| `/person/enrich` | `resolve.py`, `discover.py` | Full career + education for the target and the team's seed profiles; handles `matched`/`not_found`/`redacted` |
| `/company/enrich` | `eval/` (in progress) | `people.founders`, used as ground truth for the co-founder recovery eval |
| `/web/search/live` | `resolve.py`, `webproof.py` | Fallback for company resolution; co-mentions (papers, talks, co-founded companies) as extra tie evidence |

The client handles 429s with `retry-after`, paces each endpoint under its rate limit, caches to disk (demo reruns are
free and deterministic), enforces a credit budget (a partial result plus a warning, never a crash), and records every
call in the audit trail.

## The approaches we tried
_What worked, what didn't, and why we chose the one we built._ (Full log: [NOTES.md](NOTES.md))

- **Ideas we rejected:** a résumé-claim verifier (solid but common), "Runway Radar" for predicting portfolio cash-outs
  (too high-stakes to validate in 5 hours), and an inbound-lead desk / fact guard / vendor-pick tool (too close to
  existing tools). WarmPath only works on a canonical person-company graph with dates, so it plays to Crustdata's strength.
- **Ties from search filters vs. client-side overlap:** search filters match *any* role at a company, not the same
  period, so we compute date overlap client-side on canonical company IDs. ✓
- **Neo4j vs. embedded graph:** Neo4j needs Docker and a running server that judges can't easily run. We chose an embedded SQLite property graph plus networkx, with a Cypher export. ✓
- **Shortest vs. strongest path:** the shortest path often runs through a weak "both at a 30k-person company" tie, so we use Dijkstra on `-ln(score)` instead, which makes a chain of strong ties beat a short weak one. ✓
- **What failed:** the school filter `"IIT Bombay"` missed profiles that say "Indian Institute of Technology Bombay", so we added alias expansion. Searching the raw company string "Swigy Pvt Ltd company" failed, but searching the cleaned name works. The budget guard over-estimated search cost and blocked valid searches, so we fixed the estimate.

**How we decide two people know each other.**
- *Tried:* "shared employer" (what most tools do). *Failed:* two people who both worked at Google are almost always
  strangers. Our first scorer gave a Google stranger 52/100 and a Google teammate 67.0, almost the same as two years
  on a 30-person team (67.3).
- *Built:* an explainable tie score (0–100). Every factor is a line you can read and click: months of overlap on the
  same `crustdata_company_id`, company size, same function, similar title, same location, joined together, recency,
  repeat colleagues, classmates, web co-mentions. At companies over 1,000 people a visible `big_company_discount` cuts
  the overlap points unless there's a team signal. Result: small team 72 > Google teammate 54 > Google stranger 26.
- *Paths:* `0.7 × weakest tie + 0.3 × mean`, × 0.85 per extra hop. A chain is only as warm as its weakest link.

**Understanding the request.** Rules alone missed vague phrasing ("the data guy" is really "head of data"), and the
free LLM made real mistakes live: it put the target company into the network filter, which would make every
Swiggy employee "in network". Free models also have 50 requests a day and go down. We run both: rules always (text-speak, URLs, domains, "CTO of X", "X's head of data", "swiggy
mein data head se intro"), and the free LLM only fills gaps. It may not name anyone or any company that isn't in the
request. If the LLM is down, slow or switched off (`WARMPATH_LLM=0`), the rules carry the run.

**Drafts with no made-up facts.** We don't let a free LLM add facts to a message that goes to a real person. The draft starts as a template filled only from evidence. An LLM rewrite is kept only if
`check_claims` finds every year, number and proper noun in the path's Crustdata records. Otherwise the rewrite is
dropped and logged (our tests feed it invented claims, such as a fake shared team at Google, and check they're caught). Every outbox file ends with its sources (record refs and profile URLs).

**Web proof.** Plain name co-occurrence is easy to fool: a LinkedIn "people also viewed" sidebar puts strangers side by side. We skip
profile and contact-directory sites and require both full names, then label each hit (co-founded, co-authored,
spoke together).

### The hardest case
Same-name people and huge companies, where "both at Google" means nothing. Two people named "Priya Sharma" are
disambiguated by company + title match, with a warning when it's still ambiguous. Big-company ties get a visible
`big_company_discount` (company size from the latest headcount: 25 points at ≤50 people, down to 2 above 10k, and
only part of the overlap points kept above 1,000 people), which a same-team signal (function, title, location) partly
restores.

## Testing
```bash
uv run --with pytest pytest -q tests          # whole suite runs offline, no API keys needed
uv run python -m eval.cofounder_eval          # live co-founder eval (~4-6 credits per startup)
uv run python -m eval.cofounder_eval --offline   # re-score saved data, 0 credits
```
- **Messy-input suite** ([tests/test_parse.py](tests/test_parse.py)): 16 real-world requests, including typos ("teh data
  guy at swiggy pls"), text-speak, Hinglish, profile/company URLs, domains, all-caps, a name with no company, and
  network hints. Plus: the LLM can't invent a name, and LLM-down falls back to rules.
- **Tie model** ([tests/test_score.py](tests/test_score.py)): the hardest case (small team beats a big-company
  teammate beats a big-company stranger), Evidence on every factor, missing and impossible dates, same-company matching
  without IDs, id-less dedupe, weakest-link path scoring.
- **Drafts** ([tests/test_draft.py](tests/test_draft.py)): the template passes its own fact check. Five kinds of
  invented claims are caught (wrong company, year, number, person, school). A hallucinating LLM draft is rejected.
- **Web proof, LLM client:** directory pages ignored, API failures handled, LLM cooldown after an outage.
- **Graph and pipeline (offline end-to-end, fake Crustdata world):** graph derivation, the crawler, budget
  exhaustion, 429 retries, typos and redacted profiles.
- **Co-founder recovery eval** ([eval/cofounder_eval.py](eval/cofounder_eval.py)): for ~15 Indian startups, take the
  founders from `/company/enrich` (`people.founders`). Make each founder the target, and rank their co-founders plus up
  to 25 colleagues from `/person/search` by tie score. Is a real co-founder WarmPath's #1 connector? Compared with a
  random colleague (exact expectation), "longest overlap only", and WarmPath without the title factor (co-founders
  often share a "Co-founder" title, which would flatter us). Equal scores count against us.

  **Results (live Crustdata, 31 Oct, 25 credits):** 32 founders across 11 startups, ~24 candidates each.

  | Method | Hit@1 | Hit@3 |
  |---|---|---|
  | **WarmPath** | **91%** | **94%** |
  | WarmPath without the title factor | 91% | 94% |
  | Longest overlap only | 88% | 94% |
  | Random colleague | 9% | 25% |

  The no-title ablation scores the same, so a shared "Co-founder" title isn't what wins. Co-founders are the easy
  case for "longest overlap"; WarmPath matches it here while also discounting big-company strangers, which overlap
  alone can't do. The misses are instructive: Nikhil Kamath's #1 pick is Richard Pattle, his co-founder at True
  Beacon (a real warm tie, just not the one the eval wanted). Two Licious profiles with founder titles share no dated
  overlap with the other founders. Per-founder table: [eval/results.md](eval/results.md).

  Ground truth needed work: Crustdata's `people.founders` lists "Founder's Office" staff and EAs (12 of 14 at
  Razorpay), plus one-job profiles claiming to have founded Zomato with no dates. A co-founder here means a founder
  title *at that company* that started within 2 years of its founding. The rule is applied to everyone in the pool
  (it recovers Unacademy's Hemesh Singh and Urban Company's Abhiraj Singh Bhal, whom the list missed). Duplicate
  records of one person are merged (PhysicsWallah has two "Alakh Pandey" records). Equal scores count against us.

---
Team docs: [docs/TEAM_GUIDE.md](docs/TEAM_GUIDE.md) (work split, deliverables, judging) · [docs/PLAN.md](docs/PLAN.md) (technical spec)
