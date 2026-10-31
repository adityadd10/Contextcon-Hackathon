# Team updates (newest at the top)

Aditya's Claude Code appends an entry each improvement loop (about every 25 min until 15:00).
**Vaibhav and Apurba: `git pull --rebase`, then read the newest entry and tell your Claude Code
"read docs/UPDATES.md and do my items".**

---

## 12:58 · Loop 5: edge-case hardening, then live edge cases (no crashes, no hangs, no silent failures)

Ran a 35-input adversarial sweep (empty, emoji, SQL/HTML/rich-markup injection, Hindi/Hinglish, 5,000-char, NUL bytes,
typos, bare URLs, unknown companies, redacted profiles) offline, then 6 hard **live** requests. It is now a permanent test,
`tests/test_edge_cases.py`: every input must end with exactly one `done`, no `error`, and a warning that explains any
failure. **137 tests green.**

**Bugs found and fixed (Aditya's files):**
1. 🐞 **No `done` event when the target couldn't be resolved.** The early return skipped it, so **the UI would spin forever** on any bad
   input (22/35 cases). `done` is now emitted in `finally`, exactly once, and unexpected exceptions become an `error` event + `done`.
2. 🐞 **`sqlite3 OperationalError: database is locked`.** `upsert_tie` never committed, so a concurrent crawl + run deadlocked.
   Fixed with commits, WAL mode and a busy timeout. There's a test with two concurrent writers.
3. Silent failures: every unresolved target now gets a specific warning ("Crustdata has no record of a 'CTO' at Zepto…",
   "I couldn't tell who you want to reach. Try: …").
4. Live: **"CTO" found nobody** because titles say "Chief Technology Officer". Acronyms are expanded (CTO/CEO/CFO/COO/CPO/CMO/VP/MD/…). Zepto's
   CTO now resolves.
5. Live: **bare company "Swiggy"** (no role) gave nothing. It's now treated as a company → defaults to its leadership; it found
   Swiggy's co-founder. It previously picked a junk 1-role "CEO" record, so thin profiles are now penalised in target ranking.
6. Live: **"Kunal Shah at CRED"**: the name search was fuzzy ("Kunal" matched "Krunal"/"Kuntal"). It now uses exact-phrase name matching
   first. If the person isn't indexed under the company, it uses Crustdata Web Search `site:linkedin.com/in` → enrich (must list the
   company). The warning now distinguishes "left the company" from "never had a role there (possibly a different person)".
7. `linkedin.com/in/x` without `https://` (and `in.linkedin.com/...?trk=`) is normalised.

### Apurba (Member C): do these
1. **Security:** the sweep includes `<script>alert(1)</script>` and `[bold]` as names. Make sure `index.html` inserts *all*
   Crustdata/user text with `textContent` (never `innerHTML`), including warnings, tooltips and graph labels. The CLI already escapes.
2. The UI must treat `done` as the only end signal (it now always arrives), and show the `error` event text if one arrives
   before it. Test with the request `""` and `"intro to the CEO at Nonexistent Corp"`.
3. Add 2 demo chips that show robustness live: `"Swiggy"` (→ co-founder) and `"warm intro to the CTO at zepto via iit bombay"`.

### Vaibhav (Member B): do these
1. `parse.py`: Hindi `"मुझे Swiggy के head of data से मिलवाओ"` only works with the LLM on. Add a rule: a known company token + a role
   phrase anywhere in the text, regardless of grammar. Add it to your messy-request suite.
2. `parse.py`: a bare `"Swiggy"` gives an empty spec (resolve now rescues it, but the parse step shows `company=None`). Set
   `company` when the whole request is 1–4 words.
3. `score.py`: thin-profile candidates (1 role, no education) can also appear as *connectors*. Consider a small confidence discount
   so a 1-role record never becomes the #1 path on its own.

---

## 12:32 · Integration check: everyone's work merged ✅

`main` now has all three members' work and **105 tests pass** together. Thanks, both of you, great pace.
- ✅ Done (closing from earlier entries): parse fixes and the messy-request suite, size-discounted scoring + same_team, the llm.py
  chain/cap/cooldown/kill switch, verified-only drafts, the co-founder eval (**91% hit@1, 94% hit@3 vs 9%/25% random**),
  the server/UI/CLI/MCP hardening, the verified badges and citation-to-audit links.
- Still open from 12:27: **cohort ties** (Vaibhav) and the **"Your paths" section + multi-hop chain rendering** (Apurba).
- Repo hygiene: `eval/results.json` contains only public founder names + scores (OK). Keep raw eval caches out of git.

**Next 30 min (to 13:00 integration #1):** Apurba: run the UI against the *live* pipeline once
(`uv run warmpath serve` with your own `.env`) on "warm intro to the head of data at Swiggy" and post what breaks in
NOTES.md. Vaibhav: rerun the eval after the cohort change and update README "Testing" with the numbers.

---

## 12:27 · Loop 4: team network crawled + personal paths + false-tie fix

**Team seeds are live** (in Aditya's `.env`; all three of you are in Crustdata). The crawl built the team graph from real
data: **135 people · 253 verified relationships** across your employers (Placement Office IITB, CSIR-NEERI, MRSAC,
Makr Microsystems, MediaGuru, Architect Sandeep Neena Associates …). Real team ties found: **Aditya ↔ Apurba 69/100**
(Placement Office, Oct 2025–Jun 2026). Vaibhav reaches the Swiggy data director through a verified 4-hop chain.

**Changed (Aditya):**
- 🐞 **False ties removed:** "Self-employed", "Freelance", "Stealth", "Confidential" etc. were treated as shared workplaces
  (two freelancers "worked together"). This inflated the first crawl to 1,135 relationships. `crust.to_person()` now drops
  generic employers (`crust.is_generic_employer()`), and the graph filters them on load too. The graph was rebuilt from cache for 0 credits.
- **Seed-first ranking:** paths that start at one of the requester's own profiles come first ("your paths"), then the best
  other connectors. New field **`IntroPath.via_seed: bool`**.
- Drafts are generated in parallel. The verify step no longer drops paths beyond the 25-profile enrich batch. 25 tests green.

**Contract additions:** `IntroPath.via_seed`, `crust.is_generic_employer(name)`.

### Vaibhav (Member B): do these
1. **Latency (demo-critical):** a fully cached run still takes ~34 s, almost all of it LLM wait. In `llm.py`: per-model
   timeout **12 s** (not 40), an overall deadline of ~20 s per `complete()` call, and skip a model for the rest of the process after a 429/403.
2. **Cohort ties:** all three of us are IIT Bombay 2025–27, but "classmates" alone gives 15 < MIN_TIE 25, so the edge is dropped.
   Score **same school + same years + same degree** as a cohort tie (~30), and same school with overlapping years as 15.
   Note the education years now come from `start_year`/`end_year` (mapped to Jan 1 dates).
3. Still open: size-weighted overlap (12:08), the parse fixes, `draft.py` verified-only.

### Apurba (Member C): do these
1. Split the results into **"Your paths"** (`path.via_seed == true`) and **"Other people who can introduce you"**. The first
   section is the product's key value: an intro through someone *you* know.
2. Multi-hop paths can be 4–5 nodes long (`Vaibhav → Poorvaj → Mayank → Tom → Srinivas`). Render each path as a
   horizontal chain with the tie score and a ✓ on every hop, and wrap it on mobile.
3. Graph tab demo data: `uv run warmpath graph stats` shows the live graph. `/api/graph/subgraph?center=person:379735373&depth=2`
   is Aditya's ego network. Team person IDs: Aditya `379735373`, Vaibhav `18800780`, Apurba `563317143`.
4. ⚠️ The real graph has real people's data. Use it live in the demo, but **don't commit `data/`** or screenshots of the raw DB to the repo.

---

## 12:15 · Loop 3: independent verification pass (criterion "Facts and verification", 20 pts)

**Changed:** new `warmpath/verify.py` (Aditya). After ranking, the pipeline re-fetches everyone on the top paths with
**one** `/person/enrich` call (≤25 profiles), recomputes every tie from the full canonical records, and **drops any path whose
overlap disappears** (stale or partial search data), with a warning. Every Crustdata `Evidence` now carries the
`call_id` of the record it was checked against, so a judge can trace each claim to an entry in the audit trail.
Live: 5/5 paths verified, 1 extra call, run total 5 credits. New pipeline step id: `verify`. 24 tests green.

**Contract additions (additive, nothing removed):**
- `Tie.verified: bool` and `Tie.verification: str`, e.g. `"re-checked against full Crustdata profiles (enrich c012): Swiggy 2023-02 → 2025-05"`
- `Evidence.call_id` is now filled for Crustdata evidence (it was `None`).
- New step events: `{"type":"step","id":"verify",...}`.

### Apurba (Member C): do these
1. On every path card or edge, show a **✓ Verified** badge when `tie.verified`, with `tie.verification` as its tooltip or subtitle.
   This is the single most important visual for the verification criterion.
2. Make each citation clickable to its audit entry: `evidence.call_id` → highlight that row in the Audit drawer
   (endpoint, request, credits, sha256). Profile `url` opens in a new tab.
3. Add `verify` to the step list (between score and draft).

### Vaibhav (Member B): do these
1. `verify.py` calls `score.score_tie()` again on the enriched profiles, so your scoring changes apply automatically.
   Keep `score_tie` pure (no I/O). Any new Factor you add must carry Evidence with `kind="crustdata"` and the stint `ref`
   so the verifier can stamp a `call_id` on it.
2. `draft.py`: only build drafts from `tie.verified` ties, and put "(verified via Crustdata)" in the forwardable blurb's
   footer.
3. Still open: the scoring size-weighting (12:08 entry), the parse.py fixes, and the llm.py chain plus cap.

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
