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
