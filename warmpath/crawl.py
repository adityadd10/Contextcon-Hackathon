"""Grow the social graph outward from seed profiles (BFS over shared employers), within a credit budget.

    uv run warmpath crawl --seeds <url>,<url> --depth 2 --budget 80

depth 1: seeds → everyone at the seeds' best employers
depth 2: + everyone at the employers of the strongest new ties
Owner: Member A.
"""
from __future__ import annotations

from . import events as ev
from .crust import BudgetExceeded, Crust, CrustError, f, to_person
from .discover import CO, PER_QUERY, rank_stints
from .events import Emit
from .graphdb import GraphStore
from .models import Person
from .resolve import enrich_one

FANOUT = 5  # strongest new ties expanded per frontier person


async def crawl(c: Crust, g: GraphStore, seed_urls: list[str], depth: int = 1, emit: Emit = ev.noop,
                stints_per_person: int = 3) -> dict:
    frontier: list[Person] = []
    for url in seed_urls:
        p = await enrich_one(c, url, emit)
        if p:
            g.upsert_person(p)
            ev.node(emit, "seed", p)
            frontier.append(p)
    searched: set[int] = set()
    for level in range(1, depth + 1):
        ev.step(emit, "crawl", "start", f"Crawl depth {level}", f"{len(frontier)} people in frontier")
        nxt: list[Person] = []
        try:
            for person in frontier:
                for s in rank_stints(person, stints_per_person):
                    if s.company_id in searched:
                        continue
                    searched.add(s.company_id)
                    res = await c.person_search(f(CO, "=", s.company_id), limit=PER_QUERY)
                    added = ties = 0
                    for raw in res.get("profiles") or []:
                        q = to_person(raw, "/person/search")
                        r = g.upsert_person(q)
                        added += r["new"]
                        ties += r["ties"]
                    ev.step(emit, "crawl", "progress", f"{s.company_name}",
                            f"+{added} people, +{ties} relationships · graph {g.stats()['people']} people")
                # expand along the strongest fresh ties
                nxt += [p for p, _, _ in g.knows(person.person_id)[:FANOUT]]
        except BudgetExceeded:
            ev.warn(emit, "Credit budget reached. Stopping the crawl here.")
            break
        except CrustError as e:
            ev.warn(emit, f"Crawl step failed: {e.message}")
        frontier = nxt
    stats = g.stats()
    ev.step(emit, "crawl", "done", "Crawl finished",
            f"{stats['people']} people · {stats['relationships']} relationships · {c.credits_used:.1f} credits")
    return stats
