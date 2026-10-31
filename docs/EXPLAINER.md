# WarmPath, explained

**Warm intros to anyone, with every link verified on Crustdata's identity graph.**
ContextCon 03 · IIT Bombay · Team: Aditya · Vaibhav · Apurba

This document has two halves. **Part 1** explains the project in plain language: what it does and why it matters. No code
knowledge is needed. **Part 2** is the technical deep dive: architecture, algorithms, data, verification and testing.

---

# Part 1: the simple version

## The problem in one picture

You want to talk to someone important: an investor, a hiring manager, the head of data at a company you want to sell to.
You have two options:

| Cold message | Warm intro |
|---|---|
| "Hi, you don't know me, but…" | "Hi, my friend Rahul worked with you for two years and suggested I reach out." |
| Most are ignored | Far more likely to get a reply |
| Free, and anyone can do it | Hard: you have to work out **who knows the person, and how well** |

Finding a warm intro today means scrolling through profiles and guessing: *"I think Rahul knows her? They were both at
Flipkart…"* Flipkart has tens of thousands of employees, so "both at Flipkart" means almost nothing.

People already **pay** to get this done:
- **Founders raising money** pay fundraising advisors, often a share of the round, for introductions to investors.
- **Companies hiring** pay recruiters and executive-search firms.
- **Sales teams** pay for warm-path tools and spend hours of SDR time hunting for mutual contacts.
- **Universities** run alumni offices that broker student ↔ alumni introductions.

## What WarmPath does

You type one sentence, the way you'd say it to a friend:

> *"Get me a warm intro to whoever runs data at Swiggy, ideally through IIT Bombay people."*

About 30 seconds later, WarmPath gives you:

1. **Who the person is.** It finds the actual head of data at the actual Swiggy (there are five companies called "Swiggy" in the data).
2. **Who can introduce you.** These are people who really **worked alongside** them: same company, at the **same time**.
3. **How well each pair knows each other**, as a score out of 100 with plain-language reasons: *"overlapped 24 months
   at a 330-person company, same team, recently"*.
4. **The best routes**, starting with routes through **you and your own team** ("Your paths").
5. **A ready-to-send intro request** to the first person on the route, plus a short note they can forward.

Nothing is ever sent automatically. Drafts land in an outbox and a person approves them, as the hackathon rules require.

## Why you can trust it

Every connection WarmPath shows can be checked:
- It's built on **Crustdata**, which keeps one verified record per person and per company. Two people are linked only if
  both of their records show the **same company ID** with **overlapping dates**. Nobody "clicked connect"; it's evidence.
- After finding a route, WarmPath **re-checks every link** against the full, fresh profiles and drops anything that doesn't hold up.
- Every reason has a **citation**: click it to see the exact record and the exact API call it came from.
- The intro drafts may only say things that are backed by evidence. A checker flags anything that isn't.

## It gets smarter every time

Everything WarmPath learns goes into its own **social graph**, like a LinkedIn connection graph where every connection
is earned through shared work. Our team's crawl plus today's requests built a graph of **788 people and 3,791 verified
relationships**. The next request reuses what's already known, so it's faster, cheaper and finds longer routes:
*you → your ex-colleague → their ex-colleague → the target.*

## A real example from today

We asked WarmPath to reach a **VC General Partner** for a seed round. Three students with no VC network got:
- **Route 1:** one teammate → a former colleague from an **8-person startup** → the partner (the two overlapped there too,
  and the web has articles mentioning both).
- **Route 2:** another teammate → the first teammate (they work together at the IIT Bombay Placement Office) → …
- **Route 3:** the third teammate, through four people, every hop verified.
- Plus five strong outside connectors.

## How we know it works

- We tested it on **11 real startups**. For each founder, we asked: *who is most likely to know them?* WarmPath ranked
  their real co-founder **#1 in 91% of cases**. Picking a random colleague does that 9% of the time.
- **28 test scenarios**: typos ("teh data guy at swigy"), Hindi and Hinglish, empty input, hacking attempts, unknown
  companies, people who asked to be removed. All 28 pass, with **zero silent failures and zero fake connections**.
- **204 automated tests** run on every change.

---

# Part 2: the technical version

## Architecture

```
 request (free text)
   │
   ▼
 parse.py ─────────── rule parser (typos, Hinglish, Devanagari, URLs, acronyms)
   │                   + optional free LLM (OpenRouter), which only refines and can never invent names
   ▼
 resolve.py ───────── /company/identify (free) → fallback chain → /person/search → /person/enrich
   │                   (exact-name match, seniority ranking, leadership default, web-search profile fallback)
   ▼
 discover.py ──────── /person/search  company_id = X  ∧  network filter  (∧ team keyword + date cut at big companies)
   │                   + graph memory (people already known at those companies, 0 credits)
   ▼
 headcount.py ─────── /company/enrich headcount.timeseries → company size *during* each overlap
   ▼
 score.py ─────────── explainable tie strength 0–100 (every factor carries Evidence)
 paths.py + graphdb ─ 1-hop, 2-hop and multi-hop paths (Dijkstra on −ln(score/100)); "your paths" first
   ▼
 webproof.py ──────── /web/search/live: co-authored, co-founded, spoke together
   ▼
 verify.py ────────── ONE batched /person/enrich re-fetch → recompute every tie → drop any that vanish
   ▼
 draft.py ─────────── intro to the sender's own contact + forwardable blurb; claim checker
   ▼
 outputs: SSE event stream → web UI · CLI · MCP server · outbox/*.md · reports/<run>.json (audit trail)
```

Everything runs through **one entry point**, `pipeline.run(request, emit)`. The web UI, the CLI and the MCP server all
consume the same event stream: `step`, `node`, `edge`, `path`, `draft`, `warning`, `graph`, `done`.

## Where we call Crustdata (all through `warmpath/crust.py`)

| Endpoint | Used for | Cost |
|---|---|---|
| `/company/identify` | resolve "swigy", "Swiggy Pvt Ltd", `swiggy.com` or a company URL to one canonical `crustdata_company_id` | free |
| `/person/search` | find the target by name/title at a company; find connectors at each employer | ~0.33 / result |
| `/person/enrich` | full dated career for the target, the team (seeds) and verification | 1 / profile |
| `/company/enrich` | headcount history, so we know company size *at the time* of an overlap | 2 / company |
| `/web/search/live` | co-mention evidence; last-resort company and profile lookup | 1 / query |

The client handles retries and backoff on 429/5xx (honouring `retry-after`), per-endpoint pacing under the rate limits,
a disk cache keyed by request, a per-run **credit budget**, and an **audit trail**: every call with request, status,
`x-credits-used` and the sha256 of the response.

## The key idea: a tie is a join, not a guess

Two people are connected only when both records show a role at the **same canonical `crustdata_company_id`** with
**overlapping dates**. Search filters match across *any* role, so the overlap itself is computed client-side for the same
company and the same window.

### Tie strength (0–100), with every factor cited

| Factor | What it captures |
|---|---|
| Overlap duration | months together at the same company (capped at 2 years) |
| Company size **during** the overlap | 2 years at a 30-person startup ≫ 2 years at a 30,000-person company (headcount time series) |
| Same team | shared function or team keyword in titles ("data", "growth", …); big companies need this signal |
| Recency | a recent overlap beats one from 10 years ago |
| Repeat colleagues | worked together at more than one company |
| Classmates / cohort | same school, overlapping years |
| Web co-occurrence | pages naming both people in full (co-founded, co-authored, spoke together); profile directories are excluded |
| Thin-profile discount | 1-role records are often mis-attributed, so they get less trust |

**Path score** = `0.7 × weakest tie + 0.3 × mean tie`, × `0.85^(hops−1)`. A chain is only as warm as its weakest link.

## The social graph (`warmpath/graphdb.py`)

An embedded **SQLite property graph** (WAL mode, safe under concurrent writes) plus **networkx** algorithms, with no server needed:

```
(:Person)-[:WORKED_AT {title, start, end}]->(:Company {crustdata_company_id})
(:Person)-[:STUDIED_AT {degree, start, end}]->(:School)
(:Person)-[:KNOWS {weight 0-100, factors, evidence}]-(:Person)     ← derived, never self-reported
```

- **Self-densifying:** each new person is scored against everyone already known at the same companies or schools.
- **Strongest path:** Dijkstra with cost `−ln(score/100)`, so a chain of strong ties beats a short weak one.
- **Algorithms:** degrees of separation, super-connectors (betweenness), communities, ego subgraphs, Cypher export for Neo4j.
- **Crawler:** `warmpath crawl --seeds <team URLs> --depth 2` grows the team's network breadth-first within a credit budget.

## Verification

1. Every scoring factor carries `Evidence(claim, endpoint, ref, url, call_id)`.
2. `verify.py` re-fetches everyone on the top paths in **one** batched enrich, recomputes each tie from the full canonical
   records, marks `tie.verified = True`, and **drops** paths whose overlap disappears (stale or partial search data).
3. Every Crustdata evidence item is linked to the `call_id` of the API call it was checked against. In the UI, a citation
   click opens that row of the audit drawer (endpoint, request, credits, sha256).
4. Drafts may only state facts present in the evidence. The claim checker verifies names, organisations, years and *who*
   overlapped with *whom*.

## Robustness: what we handle

| Input or situation | What happens |
|---|---|
| Typos / suffixes / lowercase ("swigy", "Swiggy Pvt Ltd") | fallback chain: identify → cleaned name → guessed domains → web search → identify by URL; ranked by exact name → close name → real size |
| Five companies called "Swiggy" | picks the real one (10,001+ people) over lookalikes |
| "CTO", "VP", "MD" | acronyms expanded to the titles actually stored |
| Nobody with that exact title | topic word + senior title, ranked by seniority |
| Bare company ("Swiggy") | defaults to the company's leadership, and says so |
| Same name, different people | exact-phrase name match + company; ambiguity warning with the count |
| Person not indexed under the company | web search for the profile, then enrich (must list the company) |
| Redacted / not-found profiles | skipped with an explanation |
| "Self-employed", "Various Startups", "Stealth" | never treated as a shared workplace (no false ties) |
| Huge employers | narrowed to the target's team and time window |
| Rate limits (429) / network blips | retry with backoff; partial results on budget exhaustion |
| Free LLM down or rate-limited | rule-based parser; model fallback chain; call cap; cooldown |
| Empty, hostile or huge input | exactly one `done` event, never a hang, always a warning explaining why |

## Evaluation

```bash
uv run python -m eval.run_eval --fake    # 19 offline scenarios, 0 credits
uv run python -m eval.run_eval           # + 9 live scenarios on real Crustdata
uv run python -m eval.cofounder_eval --offline
```

| Metric | Result |
|---|---|
| Gold scenarios passing (6 edge-case categories) | **28 / 28** |
| Clean completion · silent failures · crashes | 100% · 0 · 0 |
| False ties · unsupported draft claims | 0 · 0 |
| Citation coverage · ties verified · evidence traceable to an audit call | 100% · 100% · 100% |
| Paraphrase consistency (rewordings → same person) | 100% |
| Real co-founder ranked #1 / top-3 (11 startups, 32 founders) | **91% / 94%** (random: 9% / 25%) |
| p95 latency (cached) | 2.3 s |
| Automated tests | 204 |

Each eval run appends a line to `eval/history.jsonl` (git sha + metrics), so every change is measured as better or worse.

## Interfaces

- **Web UI:** `uv run warmpath serve`. Live steps, "Your paths", per-hop evidence, ✓ verified badges, drafts, audit drawer, graph explorer.
- **CLI:** `uv run warmpath "<request>"`, `warmpath crawl …`, `warmpath graph stats | path | brokers | export`.
- **MCP server:** `uv run warmpath mcp`. Tools `find_warm_paths`, `explain_tie`, `graph_path`, so any agent (Claude, Cursor…) can use WarmPath.

## Privacy and rules

- Agents never contact anyone. Drafts go to `outbox/` and need human approval.
- No contact details are fetched (no emails or phone numbers), only professional history.
- Real people's data (`reports/`, `data/`, `outbox/`, caches) is gitignored and never committed to the public repo.

## Stack

Python 3.12 · uv · httpx (async) · FastAPI + Server-Sent Events · SQLite + networkx · rapidfuzz · vis-network (UI) ·
MCP Python SDK · OpenRouter free models (optional) · pytest. About 4,000 lines of application code.
