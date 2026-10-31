# WarmPath: notes for Claude Code sessions

Hackathon project (ContextCon IIT Bombay, Crustdata track, code freeze 15:30 IST, 31 Oct 2026).
Three people build in parallel. **The full spec, file ownership and contracts are in [docs/PLAN.md](docs/PLAN.md). Read it first.**

## Rules
- Python 3.12, `uv`. Run things with `uv run ...`. Add deps with `uv add` (tell the team).
- Shared contracts: `warmpath/models.py` (dataclasses), the event schema in PLAN §6, the function signatures in PLAN §6.
  Add fields freely. Don't rename or remove without asking.
- Only edit the files your member owns (PLAN §5). Small commits, `git pull --rebase` before pushing.
- The social graph lives in `warmpath/graphdb.py` (`GraphStore`, SQLite at data/graph.db). Read/write it only through that class.
- All Crustdata calls go through `warmpath/crust.py` (`Crust` client). Never call httpx directly, or you lose
  retries, pacing, caching, the credit budget and the audit trail.
- Every claim shown to a user must carry `Evidence` (models.py). No uncited facts in the UI or in drafts.
- LLM (`warmpath/llm.py`, OpenRouter free models) is optional at runtime. Every LLM use needs a rule-based fallback.
- Agents must never contact real people: drafts are written to `outbox/` only.
- Keep code plain and readable: type hints, short docstrings, no heavy frameworks. The frontend is a single static HTML file, CDN libs only.

## Run
```bash
cp .env.example .env   # add CRUSTDATA_API_KEY and OPENROUTER_API_KEY
uv sync
uv run warmpath "warm intro to the head of data at Swiggy via IIT Bombay alumni"
uv run uvicorn warmpath.server:app --reload    # http://localhost:8000
```
