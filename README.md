# WarmPath

**Warm intros to anyone, with every link verified on Crustdata's identity graph.**
ContextCon 03 · IIT Bombay · Theme: Infrastructure for agents (also Hiring, Revenue, Investing)

> _Team: fill in the sections below before 3:00 PM. Judges start here. Structure follows the event deck's README guide._

## The service
_Which service it takes on, who does that job today, and who pays for it._

People pay for introductions every day: fundraising advisors and placement agents (a share of the round), executive
search and recruiting firms, sales teams (warm-path tools plus SDR hours), alumni offices. The job is finding *who
actually knows the target well enough to introduce you*, and then asking them. Today that's manual profile-scrolling and guessing.

## What it does now
_The parts of the job it handles end to end, and where it still needs a person._

TODO (A/C): request → resolve target → connectors with overlap → explainable tie scores → ranked paths → cited intro
drafts in `outbox/` → persistent social graph. A person is needed only to approve sending.

## What it could do next
_What we'd build with more time, and why now isn't the time._

TODO (all)

## How to run it, and how it's built
```bash
git clone https://github.com/adityadd10/Contextcon-Hackathon.git && cd Contextcon-Hackathon
uv sync && cp .env.example .env   # add CRUSTDATA_API_KEY (+ optional OPENROUTER_API_KEY)
uv run warmpath "warm intro to the head of data at Swiggy via IIT Bombay alumni"
uv run uvicorn warmpath.server:app    # web UI at http://localhost:8000
uv run warmpath crawl --seeds <profile_url>,<profile_url> --depth 2
uv run warmpath graph stats | brokers | path <from_id> <to_id> | export
```
TODO (A): architecture diagram; agents, models, tools, data; **where we call Crustdata** (Company Identify, Person
Search, Person Enrich, Company Enrich, Web Search) and why each.

## The approaches we tried
_What worked, what didn't, and why we chose the one we built._ (Source: [NOTES.md](NOTES.md))

TODO (B)

## Testing
TODO (B): unit tests, co-founder recovery eval (top-1/top-3 vs baseline), messy-input suite.

---
Team docs: [docs/TEAM_GUIDE.md](docs/TEAM_GUIDE.md) (work split, deliverables, judging) · [docs/PLAN.md](docs/PLAN.md) (technical spec)
