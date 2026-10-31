"""Independent verification pass: re-fetch every person on the top paths with /person/enrich (full, dated career),
recompute each tie from those records, and keep only ties that still hold. Owner: Member A.

Search results can be partial or stale; enrich is the canonical record. A tie survives only if the overlap is still
there in BOTH full profiles. Every Crustdata Evidence item gets the call_id of the record it was checked against.
"""
from __future__ import annotations

from . import events as ev
from .crust import Crust, CrustError, to_person
from .events import Emit
from .models import IntroPath, Person
from .paths import path_score
from .score import score_tie

MAX_VERIFY = 25  # one enrich request (≤25 profiles, 1 credit each)


async def verify_paths(c: Crust, paths: list[IntroPath], emit: Emit) -> list[IntroPath]:
    people: dict[int, Person] = {}
    for p in paths:
        for n in p.nodes:
            if n.person_id and n.profile_url and n.source_endpoint != "/person/enrich":
                people.setdefault(n.person_id, n)
    full: dict[int, Person] = {}
    call_id = None
    if people:
        batch = list(people.values())[:MAX_VERIFY]
        urls = [p.profile_url for p in batch]
        try:
            rows = await c.person_enrich(urls)
            call_id = c.last_call_id
        except CrustError as e:
            ev.warn(emit, f"Verification enrich failed ({e.message}). Keeping search-based ties, marked unverified.")
            return paths
        for row in rows:
            if row.get("matches"):
                q = to_person(row["matches"][0]["person_data"], "/person/enrich")
                if q.person_id:
                    full[q.person_id] = q
            elif row.get("match_status") == "redacted":
                ev.warn(emit, f"A connector asked Crustdata to remove their data. Dropping them ({row.get('matched_on')}).")

    kept: list[IntroPath] = []
    for p in paths:
        nodes = [full.get(n.person_id, n) for n in p.nodes]
        requested = {b.person_id for b in batch} if people else set()
        if any(n.person_id in requested and n.person_id not in full for n in p.nodes):
            ev.warn(emit, f"Dropped path #{p.rank}: a person on it could not be re-verified")
            continue
        new_ties, ok = [], True
        for old, (a, b) in zip(p.ties, zip(nodes, nodes[1:])):
            t = score_tie(a, b)
            extra = [f for f in old.factors if f.name == "web_cooccurrence"]  # web evidence is independent
            t.factors += extra
            t.score = min(100.0, t.score + sum(f.contribution for f in extra))
            if not t.overlaps and t.kind != "classmate":
                ok = False
                t.verification = f"overlap not found in full profiles (enrich {call_id})"
            else:
                t.verified = True
                ov = t.overlaps[0] if t.overlaps else None
                t.verification = (f"re-checked against full Crustdata profiles (enrich {call_id or 'cached'}): "
                                  + (f"{ov.company_name} {ov.start.isoformat()[:7]} → {ov.end.isoformat()[:7]}"
                                     if ov else "classmates"))
            for fct in t.factors:
                for e in fct.evidence:
                    if e.kind == "crustdata" and not e.call_id:
                        e.call_id = call_id
            new_ties.append(t)
        if not ok:
            ev.warn(emit, f"Dropped path #{p.rank} ({' → '.join(n.name for n in nodes)}): "
                          f"the overlap disappeared in the full profiles")
            continue
        kept.append(IntroPath(nodes=nodes, ties=new_ties, score=path_score(new_ties), why=p.why, rank=p.rank,
                               via_seed=p.via_seed))
    kept.sort(key=lambda p: (not p.via_seed, -p.score))
    for i, p in enumerate(kept, 1):
        p.rank = i
    ev.step(emit, "verify", "done", f"{len(kept)}/{len(paths)} paths verified against full profiles",
            f"{len(full)} profiles re-fetched in one call ({call_id or 'none needed'})")
    return kept
