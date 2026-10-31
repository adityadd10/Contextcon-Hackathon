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
