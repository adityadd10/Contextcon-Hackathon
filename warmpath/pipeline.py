"""The one entry point used by server, CLI and MCP.  Owner: Member A (integration)."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from . import events as ev
from .crust import Crust, CrustError
from .discover import find_connectors, load_seeds
from .draft import draft_intro, write_outbox
from .events import Emit
from .graphdb import GraphStore
from .models import IntroPath, Person, RunResult, TargetSpec, to_dict
from .parse import parse_request
from .paths import build_paths, path_score
from .resolve import resolve_target
from .score import score_tie
from .verify import verify_paths
from .webproof import web_cooccurrence

REPORTS = Path("reports")
WEB_PROOF_TOP = int(os.getenv("WARMPATH_WEB_PROOF_TOP", "3"))


async def run(request: str, emit: Emit | None = None, *, crust: Crust | None = None,
              graph: GraphStore | None = None, web_proof: bool = True) -> RunResult:
    emit = emit or ev.noop
    t0 = time.time()
    run_id = time.strftime("%H%M%S-") + uuid.uuid4().hex[:4]
    own = crust is None
    c = crust or Crust()
    g = graph or GraphStore()
    result = RunResult(request=request, spec=None, target=None, target_company=None)  # type: ignore[arg-type]
    try:
        # 1 parse
        ev.step(emit, "parse", "start", "Understanding the request")
        spec = await parse_request(request)
        result.spec = spec
        ev.step(emit, "parse", "done", "Understood the request",
                f"target={spec.person_name or spec.role or spec.profile_url} · company={spec.company} · "
                f"via={spec.network.schools or spec.network.companies or 'anyone'} · parser={spec.parser}")

        # 2 resolve
        ev.step(emit, "resolve", "start", "Resolving the target on Crustdata's identity graph")
        target, company = await resolve_target(c, spec, emit)
        result.target, result.target_company = target, company
        if not target:
            ev.step(emit, "resolve", "error", "Could not resolve the target",
                    "Try adding the company name or a profile URL")
            result.warnings.append("target not resolved")
            return result
        ev.node(emit, "target", target)
        g.upsert_person(target)
        if company:
            g.upsert_company(company)
        ev.step(emit, "resolve", "done", f"Target: {target.name}",
                f"{target.current_title or ''} · {len(target.stints)} roles on record")
        if target.last_updated:
            result.warnings += _freshness(target.last_updated, target.name, emit)

        # 3 discover
        ev.step(emit, "discover", "start", "Finding people who worked alongside the target")
        seeds = await load_seeds(c, spec, emit)
        for s in seeds:
            ev.node(emit, "seed", s)
        connectors = await find_connectors(c, target, spec, seeds, emit)
        # graph memory: people met in earlier runs/crawls at the target's employers cost 0 credits now
        seen = {p.person_id for p in connectors} | {target.person_id} | {s.person_id for s in seeds}
        remembered = [p for p in g.people_at([s.company_id for s in target.stints if s.company_id])
                      if p.person_id not in seen]
        connectors += remembered
        for p in [*seeds, *connectors]:
            g.upsert_person(p)
        ev.step(emit, "discover", "done", f"{len(connectors)} candidate connectors found",
                f"{len(remembered)} recalled from the graph for free · graph now {g.stats()['people']} people")

        # 4 score + 5 paths
        ev.step(emit, "score", "start", "Scoring how closely each pair worked together")
        paths = build_paths(target, connectors, seeds, spec)
        paths = _merge(paths, graph_paths(g, target, seeds), spec)
        emitted: set[int | None] = set()
        for p in paths:
            for a, t in zip(p.nodes, p.ties):
                if a.person_id not in emitted:
                    ev.node(emit, "seed" if a in seeds else "connector", a)
                    emitted.add(a.person_id)
                ov = t.overlaps[0] if t.overlaps else None
                ev.edge(emit, t.a, t.b, t.score,
                        f"{ov.company_name} · {ov.start.isoformat()[:7]}→{ov.end.isoformat()[:7]}" if ov else t.kind)
        ev.step(emit, "score", "done", f"{len(paths)} intro paths above threshold")

        if web_proof and paths:
            ev.step(emit, "webproof", "start", "Looking for web co-mentions (papers, talks, co-founded companies)")
            for p in paths[:WEB_PROOF_TOP]:
                last = p.ties[-1]
                fct = await web_cooccurrence(c, last.a, last.b)
                if fct:
                    last.factors.append(fct)
                    last.score = min(100.0, last.score + fct.contribution)
                    p.score = path_score(p.ties)
                    ev.edge(emit, last.a, last.b, last.score, "web co-mention")
            paths.sort(key=lambda p: -p.score)
            for i, p in enumerate(paths, 1):
                p.rank = i
            ev.step(emit, "webproof", "done", "Web evidence attached")
        if paths:
            ev.step(emit, "verify", "start", "Verifying every link against full Crustdata profiles")
            paths = await verify_paths(c, paths, emit)
            for p in paths:
                for a, b in zip(p.nodes, p.nodes[1:]):
                    g.upsert_person(a, derive_ties=False)
                    g.upsert_person(b, derive_ties=False)
        result.paths = paths
        for p in paths:
            for t in p.ties:
                g.upsert_tie(t)
        emit({"type": "graph", "stats": g.stats()})
        for p in paths:
            emit({"type": "path", "path": to_dict(p)})

        # 6 drafts
        if paths:
            ev.step(emit, "draft", "start", "Drafting intro requests (local outbox only, nothing is sent)")
            for p in paths[:3]:
                d = await draft_intro(p, spec)
                write_outbox(d, run_id)
                result.drafts.append(d)
                emit({"type": "draft", "draft": to_dict(d)})
            ev.step(emit, "draft", "done", f"{len(result.drafts)} drafts written to outbox/")
        else:
            ev.warn(emit, "No warm path found. Try widening the network (drop the school filter) or add seed profiles.")
    except CrustError as e:
        result.warnings.append(str(e))
        emit({"type": "error", "message": str(e)})
    finally:
        result.audit, result.credits_used = c.audit, round(c.credits_used, 2)
        result.elapsed_s = round(time.time() - t0, 1)
        REPORTS.mkdir(exist_ok=True)
        (REPORTS / f"{run_id}.json").write_text(json.dumps(to_dict(result), indent=1, default=str))
        if own:
            await c.__aexit__()
        if graph is None:
            g.close()
    emit({"type": "done", "result": to_dict(result)})
    return result


def _freshness(last_updated: str, name: str, emit: Emit) -> list[str]:
    from datetime import date
    from .crust import parse_date
    d = parse_date(last_updated)
    if d and (date.today() - d).days > 120:
        msg = f"{name}'s profile was last refreshed {(date.today() - d).days} days ago. The current role may be stale."
        ev.warn(emit, msg)
        return [msg]
    return []


def graph_paths(g: GraphStore, target: Person, seeds: list[Person], max_hops: int = 4) -> list[IntroPath]:
    """Multi-hop chains through people learned in *earlier* runs/crawls (strongest path over KNOWS edges)."""
    out = []
    for s in seeds:
        ids = g.strongest_path(s.person_id, target.person_id, max_hops=max_hops)
        if not ids or len(ids) < 3:
            continue  # 1-2 node paths are already covered by build_paths
        nodes = [g.person(i) for i in ids]
        if any(n is None for n in nodes):
            continue
        ties = [score_tie(a, b) for a, b in zip(nodes, nodes[1:])]
        out.append(IntroPath(nodes=nodes, ties=ties, score=path_score(ties),
                             why=f"{len(ties)}-hop chain found in the WarmPath graph: "
                                 + " → ".join(n.name for n in nodes)))
    return out


def _merge(a: list[IntroPath], b: list[IntroPath], spec: TargetSpec) -> list[IntroPath]:
    seen, out = set(), []
    for p in sorted(a + b, key=lambda p: -p.score):
        key = tuple(n.person_id for n in p.nodes)
        if key not in seen:
            seen.add(key)
            out.append(p)
    for i, p in enumerate(out, 1):
        p.rank = i
    return out[: spec.max_paths]
