# Team updates (newest at the top)

Aditya's Claude Code appends an entry each improvement loop (about every 25 min until 15:00).
**Vaibhav and Apurba: `git pull --rebase`, then read the newest entry and tell your Claude Code
"read docs/UPDATES.md and do my items".**

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
