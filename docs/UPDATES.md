# Team updates (newest at the top)

Aditya's Claude Code appends an entry each improvement loop (about every 25 min until 15:00).
**Vaibhav and Apurba: `git pull --rebase`, then read the newest entry and tell your Claude Code
"read docs/UPDATES.md and do my items".**

---

## 12:08 · Loop 2: LIVE on real Crustdata ✅

**Live result:** `"warm intro to the head of data at Swiggy via IIT Bombay alumni"` → Swiggy (id 5702, out of 5 "Swiggy"
lookalikes) → target **Director - Data Science** → 4 past employers searched → 72 connectors → 5 cited paths → 3 drafts.
First run 63 s / 28 credits. A repeat run: **17 s / 5 credits** (51 connectors recalled from the graph, cache hits).
The account has 15,228 credits and every endpoint we use is enabled. ⚠️ Real people's data: **never commit `reports/`,
`data/` or `outbox/`** (gitignored). Keep the demo fixtures fake.

**Fixed in Aditya's files from live data:**
- Education comes as `start_year`/`end_year` (not dates). It's now mapped, so the classmates factor can fire. A bare year
  no longer parses as 1970.
- Role resolution: Swiggy has nobody titled exactly "Head of Data". The fallbacks are now exact title → topic word +
  senior title (head/VP/director/chief/lead) → all words → topic word, then rank by seniority.
- **Big employers (>1,000 people):** connector search now also requires the target's team keyword (e.g. "data") and
  `start_date =<` the target's end date. Swiggy ∩ IITB went from 465 people to the 12 on the data team.
- Guard: the target's own employer is dropped from the network filter (the LLM put Swiggy there live, which made every Swiggy employee "in network").
- 22 tests green.

**Contract additions (backwards compatible):** `discover.team_keyword(title)`, `discover.BIG_COMPANY`,
`network_filter(..., exclude_ids=...)`.

### Vaibhav (Member B): do these
1. **Scoring on real data (priority):** at Swiggy (29k people) a 27-month overlap still earns the full 40 overlap points,
   so ex-Swiggy colleagues crowd out the 330-person Helpshift tie. Make overlap points depend on size, e.g.
   `overlap_pts = 40 * min(1, months/24) * size_factor` with size_factor 1.0 at ≤200, 0.8 at ≤1k, 0.55 at ≤10k, 0.4 above.
   Then add a "same team" bonus (both titles share `discover.team_keyword`) so same-team colleagues at big companies still rank.
2. `function_category` is usually `""` on live data, so "same_function" rarely fires. Fall back to `team_keyword()` equality.
3. Still open from 11:45/11:58: the parse.py "head of data" and lowercase-company fixes, target company in `companies`,
   llm.py model chain plus call cap.
4. The LLM-polished draft passed `check_claims` live and reads well. Keep that path.

### Apurba (Member C): do these
1. The real pipeline emits these step details. Render them as sub-lines: `"No exact 'head of data' title, matched by
   'data' + senior title"`, `"Searched Swiggy ∩ IIT Bombay ∩ 'data' team · 12 of 12 people returned"`, and the
   `"N recalled from the graph for free"` detail on the discover step. That last one is our "graph memory" demo moment.
2. Show the run footer: API calls · credits · seconds (from the `done` event: `audit`, `credits_used`, `elapsed_s`).
   "Second run: 5 credits instead of 28" is a strong line for the video.
3. Live runs take 15–60 s (rate limits), so the streaming step list matters: show a spinner on the active step.

---

## 11:58 · OpenRouter verified (free LLM is live)

**Findings:**
- The free key works, but **free tier = 50 LLM requests per day per key**. Every member must create their **own** key at
  openrouter.ai → Keys and put it in their own `.env` (never commit it, and never paste it in the repo or chat).
- The old default models in `llm.py` no longer exist. Tested working chain (now in `.env.example`):
  `nvidia/nemotron-3-ultra-550b-a55b:free,google/gemma-4-31b-it:free,nvidia/nemotron-3.5-lightning:free,google/gemma-4-26b-a4b-it:free`
  - `nvidia/nemotron-3-ultra-550b-a55b:free` parsed *"yo can u get me to teh data guy at swiggy, ideally thru iitb ppl,
    we're hiring"* correctly in 3.7 s → company Swiggy, role "head of data", schools [IIT Bombay], purpose hiring.
  - `google/gemma-4-31b-it:free` returns 429 when upstream is busy (fine as a fallback). `thinkingmachines/inkling:free` returns 403
    (blocked for API use, don't use it).

### Vaibhav (Member B): do these (llm.py and parse.py are yours)
1. `llm.py`: replace the default `MODELS` list with the chain above. Treat 429 as "try the next model", and 403 as "skip the
   model for the rest of the process".
2. `llm.py`: add a **per-process LLM call cap** (env `LLM_MAX_CALLS`, default 6) plus an in-memory cache keyed by
   (system, user). With 50 calls a day, a demo run should use at most 1 parse call + up to 3 draft-polish calls.
3. `parse.py` bug seen live: the LLM put the **target** company into `companies` (the network filter) → `companies:
   ['Swiggy']`. Drop any network company equal to the target company, otherwise every Swiggy employee counts as "in network".
   Add a test.
4. Keep the rule-based parse as the base and only let the LLM fill fields the rules missed or got obviously wrong (it beat the
   rules on "teh data guy" → "head of data").

### Apurba (Member C)
- In the UI's step list, show `parser=llm` vs `parser=rules` from the parse step detail. It's a nice robustness talking point
  ("works even when the free LLM is rate-limited").
- Create your own OpenRouter key for UI testing, but prefer `WARMPATH_FAKE=1` without an LLM key while iterating, to save the 50/day.

---

## 11:45 · Loop 1: robustness of resolution

**Changed (Aditya's files):**
- `resolve_company()` now uses a fallback chain, cheapest first:
  identify as typed → identify with the legal suffix stripped ("Swiggy Pvt Ltd") → identify by guessed domains (`.com/.in/.io/.ai`)
  → web search for the company page → identify by that URL.
  "swiggy", "Swigy", "Swigy Pvt Ltd", "swiggy.com", the full URL and the LinkedIn company URL all resolve. A step event says which fallback worked.
- Target picking now explains *why*: "currently at X; title best matches Y". It warns if the person has left the company,
  and warns when several people share a name and no company was given.
- Budget: the person-search estimate dropped from 0.5 to 0.33 credits per result (it was blocking searches too early).
  Budget exhaustion mid-run is tested and returns a partial result plus a warning, not a crash.
- The crawler is tested: crawling from a seed alone discovers seed → Rahul → Priya.
- 20 tests, all green. `WARMPATH_FAKE=1` covers all of the above offline.

**No contract changes.** models, events and signatures are unchanged.

### Vaibhav (Member B): do these
1. **`parse.py` bug (found by tests):** `"warm intro to the head of data at Swiggy"` parses `role="head"`. The non-greedy
   regex stops at " of ". It must give `role="head of data"`. Try only splitting on the *last* ` at|from|@ ` before the company.
2. **`parse.py` bug:** `"intro to Priya Sharma"` (no company) gives `person_name=None`. Detect 2–3 capitalised words after
   "to/reach/meet" as a name when they don't look like a role.
3. **`parse.py`:** lowercase companies ("the data guy at swiggy pls") aren't captured, because the regex needs a capital
   letter. Accept a lowercase token after " at ", stopping at "via/through/ideally/pls/,".
4. Add those three as tests in `tests/test_parse.py` (you own it). Run `uv run pytest -q tests` before pushing.
5. `score.py` calibration: a strong tie now saturates at **100/100** (overlap 40 + size 25 + function 10 + recency 10
   + classmates 15 + web 15 = 115, capped). Consider rescaling so the UI shows differences between strong ties (e.g. a soft cap
   `100 * (1 - exp(-raw/60))`), and keep `tests/test_score.py` green.
   Note: `score._same_school()` imports `discover.school_variants` (IIT ↔ "Indian Institute of Technology" aliases). Keep that.

### Apurba (Member C): do these
1. Build the UI against the fake world now: `WARMPATH_FAKE=1 uv run uvicorn warmpath.server:app --reload`.
   Make `/api/run` just call `pipeline.run(q, emit)` and stream each event as SSE. The fake run already produces
   every event type (step, node, edge, path, draft, warning, graph, done).
2. Render `step` events with `status: "progress"` as sub-lines under their step, since they carry the "why" (fallback used,
   why this target, searches run). Judges score "shows its reasons".
3. Show `warning` events prominently (yellow), e.g. "no longer at Swiggy", "3 people match this name". Robustness counts for 20 points.
4. Sample demo requests for the UI's placeholder chips:
   - "warm intro to whoever runs data at Swiggy, ideally via IITB folks"
   - "intro to Priya Sharma at Swigy Pvt Ltd" (typo, which still resolves)
   - "https://www.linkedin.com/in/priya-sharma for hiring"
