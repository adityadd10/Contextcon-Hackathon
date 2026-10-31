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
from .models import RunResult, to_dict
from .parse import parse_request
from .paths import build_paths, path_score
from .resolve import resolve_target
from .score import score_tie
from .webproof import web_cooccurrence

REPORTS = Path("reports")
WEB_PROOF_TOP = int(os.getenv("WARMPATH_WEB_PROOF_TOP", "3"))


async def run(request: str, emit: Emit | None = None, *, crust: Crust | None = None,
              web_proof: bool = True) -> RunResult:
    emit = emit or ev.noop
    t0 = time.time()
    run_id = time.strftime("%H%M%S-") + uuid.uuid4().hex[:4]
    own = crust is None
    c = crust or Crust()
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
        ev.step(emit, "discover", "done", f"{len(connectors)} candidate connectors found")

        # 4 score + 5 paths
        ev.step(emit, "score", "start", "Scoring how closely each pair worked together")
        paths = build_paths(target, connectors, seeds, spec)
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
        result.paths = paths
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
