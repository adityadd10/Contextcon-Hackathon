# WarmPath: team guide (read this first)

**ContextCon 03 · IIT Bombay · 31 Oct 2026 · Code freeze 3:30 PM (last call 3:00 PM)**
Repo: https://github.com/adityadd10/Contextcon-Hackathon (public, since judges must be able to open it)

This is the single source of truth for the team: what we're building, who builds what, what we must submit,
and how we'll be judged. The technical spec (algorithms, API notes, function signatures) is in
[PLAN.md](PLAN.md). Your Claude Code reads [../CLAUDE.md](../CLAUDE.md) automatically.

---

## 1. What we're building, in one breath

**WarmPath replaces the intro broker.** You ask *"get me a warm intro to whoever runs data at Swiggy, ideally through
IIT Bombay people."* WarmPath:

1. Resolves the real person on Crustdata's identity graph.
2. Finds people who actually worked next to them (same canonical company ID, overlapping dates).
3. Scores how well each pair knows each other, with reasons.
4. Writes a ready-to-forward intro request. Every link is cited to Crustdata records.

Everything goes into a **persistent social graph** (people, companies and schools, with derived KNOWS edges) that grows
with every query and crawl. It works like a LinkedIn connection graph, except that each connection is evidence-based
rather than a button click.

**The service we replace (deck: "a service, not a tool"):** today people *pay* for introductions:
- fundraising advisors and placement agents (a share of the round, for investor intros)
- executive-search and recruiting firms (referrals and sourcing)
- sales teams (tools like Sales Navigator TeamLink, plus SDR hours spent hunting warm paths)
- alumni offices

The tool stops at "here are names". **The service delivers the intro request**, ready to go, with the reasons. A person
steps in only for the exception: approving the send. Per the rules, our agent never contacts anyone; drafts go to `outbox/`.

Theme: **Infrastructure for agents.** The deck lists *"A map of who knows whom, scored by how closely they worked"*.
It also serves Hiring, Revenue and Investing.

---

## 2. How we're judged (from the event deck) and how we score on each

| Criterion | Points | What judges ask | How WarmPath earns it | Owner |
|---|---|---|---|---|
| **End-to-end execution** | **25** | Takes a request it has never seen all the way to finished work, with a person only for exceptions? | One sentence in → resolved target → ranked paths → intro drafts in outbox. No manual steps. Works on any company or person. | A |
| **Facts and verification** | **20** | Is every fact correct, does every decision show reasons and sources? | Every tie lists its factors (months of overlap, company size, team, recency) with Crustdata record refs, profile URLs and web URLs. Drafts may only state cited facts. Audit trail: every API call with credits and a response hash. | B |
| **Robustness and edge cases** | **20** | Messy inputs, unusual cases, failing tools? | Typos and vague roles ("the data guy at swiggy"), company aliases/domains/URLs, redacted or not-found profiles, missing dates, 429 retry and pacing, credit budget, LLM down → rule-based fallback, stale-profile warnings. | A + B |
| **Customer value and idea** | **20** | Would a business pay today? Is the approach new? | Intro brokers, recruiters and SDR teams pay for this now. New approach: ties come from *verified co-employment on a canonical graph*, not self-reported connections, and the graph learns and densifies. | all |
| **Demo and understanding** | **15** | Does the demo show the job clearly, does the team understand the problem? | A 2-min Loom on a request it has never seen, sources shown on screen. README plus NOTES.md cover approaches, failures, the hardest case and testing. | C |

**What the judges want to hear** (deck p.39): cover each of these in the video, README and finals. Owners are in §7.
- **The service:** who pays for it today, and why we picked it.
- **The approaches:** the options we weighed, and why we chose this one.
- **What failed:** what worked and what didn't.
- **The hardest case** and how we handle it. Ours: same-name people and huge companies, where "both at Google" means nothing. Size-weighted scoring plus team/function overlap handles this.
- **The testing:** how we know it works. The co-founder recovery eval plus unit tests.
- **What comes next,** and why now isn't the time for it.

---

## 3. Deliverables checklist (submit by 3:30 PM, one person submits for the team)

| # | Deliverable | Requirement (from the deck) | Owner | Due |
|---|---|---|---|---|
| 1 | **Public GitHub repo** | Judges must be able to open it. Commit history must start on 31 Oct; commit as you go. | A | continuous |
| 2 | **README.md** | Five required sections: *the service* (who does it today, who pays) · *what it does now* (end to end, where it still needs a person) · *what it could do next* (and why not now) · *how to run it and how it's built* (agents, models, tools, data, **where it calls Crustdata**) · *the approaches we tried* (what worked, what didn't, why this one) | C writes, A + B add their parts | 3:00 PM |
| 3 | **2-minute Loom video** | Your product taking a request it has never seen to finished work. Show the whole job, show your sources, one-sentence intro, **check it plays in a private window**. | C records, all review | 3:15 PM |
| 4 | **Submission form** | Team name, one-line description, theme · repo link · Loom link · for **every member**: name and email exactly as on the YC registration, IIT Bombay email, roll number, personal email, GitHub username | A submits | 3:20 PM |
| 5 | **NOTES.md** | "Keep notes: what you try and what fails." This feeds the README and the finals Q&A. Everyone appends. | all | continuous |
| 6 | **Finals prep** (if top 10, announced 5:00 PM) | 5-min **live** demo plus 2 min of questions. Have a warm cache and a backup recording. | all | 5:00 PM |

Resubmitting with the same team name before 3:30 PM replaces the earlier one, so **submit a first version at 3:00 PM** and update it after.

> 📝 Fill in now (Member A): Team name: `__________` · One-liner: *"WarmPath: warm intros to anyone,
> every link verified on Crustdata's identity graph."* · Theme: Infrastructure for agents

---

## 4. Work split

Rule: **only edit the files you own.** Shared files (`models.py`, `events.py`, `CLAUDE.md`, the docs) get a separate
small commit and a heads-up in the team chat. That's how we avoid merge conflicts with three Claude Codes on one repo.

### Member A: Aditya: data and graph core, integration, submission
**Owns:** `warmpath/crust.py`, `resolve.py`, `discover.py`, `pipeline.py`, `graphdb.py`, `crawl.py`
1. Live-test against the real API with `.env`. Fix any differences between the docs and the real responses in `crust.py` and `to_person`.
2. Make `uv run warmpath "<request>"` work end to end on 3 different requests by **1:00 PM**.
3. Crawl the team's profiles into the graph (`warmpath crawl --seeds ... --depth 2`) by 2:00 PM.
4. Robustness: same-name disambiguation, `redacted`/`not_found`, budget stops, stale profiles.
5. Own the repo, the merges and the submission form. Write the README's "how it's built / where we call Crustdata" section.

### Member B: intelligence: parsing, scoring, drafts, eval
**Owns:** `warmpath/parse.py`, `score.py`, `paths.py`, `webproof.py`, `draft.py`, `llm.py`, `eval/`, `tests/`
1. `parse.py`: OpenRouter free model plus a rule-based fallback. Test 15 messy requests (typos, URLs, Hinglish, vague roles).
2. `score.py`/`paths.py`: tune the tie model (PLAN §3) so "small team, long overlap" beats "both at a big company". Every Factor carries Evidence.
3. `draft.py`: drafts contain **only** cited facts. `check_claims` must flag anything unsupported.
4. **`eval/cofounder_eval.py`**: for about 15 real startups, take the founders from `/company/enrich` (`people.founders`), then check
   whether the real co-founder is WarmPath's #1 connector. Report top-1/top-3 accuracy against a random-colleague baseline.
   This gives us our "how we know it works" number.
5. Write the README's "approaches we tried" and "testing" sections from NOTES.md.

### Member C: product: UI, graph explorer, MCP, README, video
**Owns:** `warmpath/server.py`, `warmpath/static/*`, `warmpath/cli.py`, `warmpath/mcp_server.py`, `README.md`, `fixtures/`
1. `fixtures/mock_events.jsonl` first (event schema in PLAN §6), so the UI can be built before the backend is ready.
2. `server.py` (FastAPI): `GET /` UI · `GET /api/run?q=` SSE stream from `pipeline.run` (`?mock=1` replays fixtures) ·
   `/api/graph/stats|subgraph|path|brokers` · `GET /api/crawl` SSE.
3. `static/index.html` (single file, vis-network from cdnjs): request box → live steps → path graph → path cards
   with clickable citations → Drafts tab → Audit drawer (calls, credits, hashes) → **Graph tab** (whole network,
   click an edge for its evidence, path between two people, super-connectors, "Crawl my network" button).
   It's what the judges see, so make it look polished.
4. `mcp_server.py`: tools `find_warm_paths`, `explain_tie`, `graph_path`, so any agent can use WarmPath.
5. README (the deck's five sections) and the **Loom video** (script in §6).

---

## 5. Setup instructions: every member, step by step

### 5.1 Credits and keys (5 min)
1. Go to **app.crustdata.com**, sign up with your **@iitb.ac.in** email, click *"Have a promo code?"* and enter **`CONTEXTCON-IITB`**.
   Open the link in your IITB inbox. Your dashboard shows **15,000 credits** and your API key (Home or API Keys).
   (Signed up without the code? Redeem it at app.crustdata.com/billing/credits.)
2. Free LLM: **openrouter.ai** → sign in → Keys → create a key.
3. Optional: add Crustdata's MCP to your Claude Code for exploring data:
   `claude mcp add --transport http crustdata https://install.crustdata.com/mcp`

### 5.2 Get the repo (5 min)
```bash
git clone https://github.com/adityadd10/Contextcon-Hackathon.git
cd Contextcon-Hackathon
# install uv if needed: curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
cp .env.example .env        # paste YOUR CRUSTDATA_API_KEY and OPENROUTER_API_KEY into .env (never commit .env)
uv run --with pytest pytest -q tests      # should be all green
uv run warmpath graph stats               # sanity check: prints an empty graph
```
Ask Aditya to add you as a collaborator on GitHub (repo → Settings → Collaborators) so you can push.

### 5.3 Start your Claude Code
Open the folder in VS Code (or a terminal), start Claude Code, and paste **your** prompt from §5.4. Claude Code reads
`CLAUDE.md` automatically, which points it at this guide and PLAN.md.

**Git rhythm (everyone, every ~20–30 min):**
```bash
git pull --rebase && uv run --with pytest pytest -q tests && git add <your files> && git commit -m "..." && git push
```
Tell your Claude Code: *"commit and push my changes"* works too. It knows the rule about only touching your own files.

### 5.4 Kickoff prompts (copy-paste into Claude Code)

**Member A (Aditya):**
> Read CLAUDE.md, docs/TEAM_GUIDE.md and docs/PLAN.md. I'm Member A. .env now has the keys. Run
> `uv run warmpath "warm intro to the head of data at Swiggy via IIT Bombay alumni"` against the live API. Fix any mismatches
> between the documented and real response shapes in crust.py/resolve.py/discover.py, and make three different requests work
> end to end. Then crawl our team's profiles into the graph. Log every failure and fix in NOTES.md. Commit and push small, often.

**Member B:**
> Read CLAUDE.md, docs/TEAM_GUIDE.md and docs/PLAN.md. I'm Member B (intelligence). I own warmpath/parse.py, score.py, paths.py,
> webproof.py, draft.py, llm.py, eval/ and tests/. Only edit those. (1) Make parse.py robust: OpenRouter free model via llm.py,
> rule-based fallback, and tests for 15 messy requests. (2) Tune score.py/paths.py per PLAN §3. Every Factor needs Evidence.
> Add unit tests with hand-made Person objects. (3) draft.py: drafts contain only cited facts and check_claims flags the rest.
> (4) Build eval/cofounder_eval.py per TEAM_GUIDE §4 and print a results table. Log what you tried and what failed in
> NOTES.md. Commit and push small, often, with `git pull --rebase` first.

**Member C:**
> Read CLAUDE.md, docs/TEAM_GUIDE.md and docs/PLAN.md. I'm Member C (product). I own warmpath/server.py, warmpath/static/*,
> warmpath/cli.py, warmpath/mcp_server.py, README.md and fixtures/. Only edit those. (1) Write fixtures/mock_events.jsonl
> matching the PLAN §6 event schema. (2) Build server.py (FastAPI + SSE: /api/run, /api/crawl, /api/graph/*) and
> static/index.html (single file, vis-network from cdnjs): live steps, path graph, path cards with clickable citations,
> Drafts tab, Audit drawer, and a Graph tab (whole network, click an edge for evidence, path box, super-connectors,
> crawl button). It must look polished for a 2-min demo video. (3) mcp_server.py with tools find_warm_paths, explain_tie,
> graph_path. (4) Fill README.md (the five required sections are already stubbed). Commit and push small, often, with
> `git pull --rebase` first.

---

## 6. The 2-minute Loom video (Member C records, everyone reviews)

| Time | Shot | Point it makes (criterion) |
|---|---|---|
| 0:00–0:10 | One sentence: "People pay brokers and recruiters for warm intros. WarmPath does the whole job, and cites every link." | Customer value |
| 0:10–0:50 | Type a **request it has never seen** (a fresh company or person) → steps stream → target resolved → graph builds → top paths with scores | End-to-end |
| 0:50–1:15 | Click an edge: both Crustdata records, the overlap dates, company size at the time, a web co-mention link. Open the audit drawer: calls, credits, hashes. | Verification |
| 1:15–1:30 | Open the draft in the outbox: every claim ticked, nothing sent. | End-to-end (finished work) |
| 1:30–1:45 | Messy input ("teh data guy at swiggy pls") still resolves. An LLM-off run still works. | Robustness |
| 1:45–2:00 | Graph tab: "N people, M verified relationships learned". A 3-hop path. The eval number: "co-founder recovered as #1 in X/N". | Understanding |

Before submitting: **open the Loom link in a private window and check it plays.**

**Finals (5-min live demo + 2-min Q&A):** the same flow, slower, plus the graph crawl live. Keep the demo queries cached
(`WARMPATH_CACHE=1`) so a slow network can't break the demo, and have the Loom ready as backup.

---

## 7. Timeline (IST)

| Time | Everyone | A | B | C |
|---|---|---|---|---|
| now–11:45 | Credits, clone, `.env`, Claude Code kickoff | live API test | parser tests | mock events + server skeleton |
| 11:45–1:00 | build | end-to-end on real data | scoring + drafts | UI main flow |
| **1:00** | **Integration #1:** UI runs a real request end to end | merge | | |
| 1:30 | Lunch at desk · optional mentor check with the Crustdata team | | | |
| 1:30–2:30 | build | crawl + graph memory | eval harness | Graph tab + MCP |
| **2:30** | **Feature freeze.** Only fixes after this. | warm demo cache | eval numbers into README | record Loom takes |
| 3:00 | **Submit a first version** (last call) | form | README sections | video final |
| 3:20 | Final push and resubmit | | | |
| 3:30 | **Code freeze** | | | |
| 5:00 | Finalists announced → rehearse the 5-min demo | | | |

## 8. Ground rules (from the deck)
- Code only from 10:30 AM. Our commit history starts 31 Oct. **Commit as you go.**
- **Agents contact only our own team and the Crustdata/Techfest teams.** WarmPath never sends a message: drafts go to `outbox/`.
- 429 = too many requests: wait and retry (`crust.py` does this). `/account/credits` shows what's left. Credits are for today, so spend them.
- Help: API, credits or MCP → **Jai** or anyone from the Crustdata team on the floor. Submissions → WhatsApp group.
  Venue → Techfest: Aryan Tamboli (+91 97022 76874), Satwik Patti (+91 78426 25477).
