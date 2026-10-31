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
