"""The one entry point used by server, CLI and MCP.  Owner: Member A (integration)."""
from __future__ import annotations

import asyncio
import json
import re
import os
import time
import uuid
from pathlib import Path

from . import events as ev
from . import headcount
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
    masker = NameMasker(emit) if os.getenv("WARMPATH_MASK_NAMES") == "1" else None
    if masker:
        emit = masker
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
            if not (spec.person_name or spec.role or spec.company or spec.profile_url):
                ev.warn(emit, "I couldn't tell who you want to reach. Try: \"warm intro to the head of data at "
                              "Swiggy\", a person's name plus company, or a LinkedIn profile URL.")
            ev.step(emit, "resolve", "error", "Could not resolve the target",
                    "Try adding the company name or a profile URL")
            result.warnings.append("target not resolved")
            return result
        if masker:
            masker.protect(target)
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
        if masker:
            for sd in seeds:
                masker.protect(sd)
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
        # company size *during* each overlap (Vaibhav's headcount history): target's employers first, then the
        # seeds' (2-hop ties); one batched /company/enrich, cached, ~2 credits per company
        hc_ids = list(dict.fromkeys([s.company_id for s in target.stints if s.company_id] +
                                    [s.company_id for sd in seeds for s in sd.stints if s.company_id]))[:25]
        try:
            n_hist = await headcount.load(c, hc_ids)
            ev.step(emit, "score", "progress", "Loaded headcount history",
                    f"{n_hist}/{len(hc_ids)} employers have size-over-time data (company size during each overlap)")
        except Exception as e:  # history is an enhancement: scoring falls back to latest headcount
            ev.warn(emit, f"Headcount history unavailable ({type(e).__name__}); using latest company size")
        paths = build_paths(target, connectors, seeds, spec)
        paths = _merge(paths, graph_paths(g, target, seeds), spec, seeds)
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
            paths.sort(key=lambda p: (not p.via_seed, -p.score))
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
            drafts = await asyncio.gather(*(draft_intro(p, spec) for p in paths[:3]))  # LLM calls in parallel
            for d in drafts:
                write_outbox(d, run_id)
                result.drafts.append(d)
                emit({"type": "draft", "draft": to_dict(d)})
            ev.step(emit, "draft", "done", f"{len(result.drafts)} drafts written to outbox/")
        else:
            ev.warn(emit, "No warm path found. Try widening the network (drop the school filter) or add seed profiles.")
    except CrustError as e:
        result.warnings.append(str(e))
        emit({"type": "error", "message": str(e)})
    except Exception as e:  # unexpected tool response / bug: report it, never leave the UI hanging
        msg = f"Unexpected {type(e).__name__}: {e}"
        result.warnings.append(msg)
        emit({"type": "error", "message": msg})
    finally:
        result.audit, result.credits_used = c.audit, round(c.credits_used, 2)
        result.elapsed_s = round(time.time() - t0, 1)
        try:
            REPORTS.mkdir(exist_ok=True)
            (REPORTS / f"{run_id}.json").write_text(json.dumps(to_dict(result), indent=1, default=str))
        except OSError as e:
            result.warnings.append(f"could not write report: {e}")
        if own:
            await c.__aexit__()
        if graph is None:
            g.close()
        # exactly one `done` per run, on every exit path (early return, error, success)
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


def _merge(a: list[IntroPath], b: list[IntroPath], spec: TargetSpec, seeds: list[Person] | None = None
           ) -> list[IntroPath]:
    """Paths that start at one of *your* profiles come first (they're actionable today), then the best others."""
    seed_ids = {s.person_id for s in seeds or []}
    for p in a + b:
        p.via_seed = p.nodes[0].person_id in seed_ids
    seen, out = set(), []
    for p in sorted(a + b, key=lambda p: (not p.via_seed, -p.score)):
        key = tuple(n.person_id for n in p.nodes)
        if key not in seen:
            seen.add(key)
            out.append(p)
    mine = [p for p in out if p.via_seed][: spec.max_paths]
    others = [p for p in out if not p.via_seed][: spec.max_paths]
    out = mine + others
    for i, p in enumerate(out, 1):
        p.rank = i
    return out


class NameMasker:
    """Privacy mode for demos and recordings (WARMPATH_MASK_NAMES=1): every person shown who is neither the requester's
    own team (seeds) nor the requested target is reduced to initials, along with their profile URL, in everything emitted.
    The underlying run, report and outbox are unchanged; only what is displayed is masked."""

    def __init__(self, emit: Emit):
        self.emit, self.protected, self.names = emit, set(), {}

    def protect(self, p: Person) -> None:
        self.protected.add(p.person_id)

    def _learn(self, obj) -> None:
        if isinstance(obj, dict):
            pid, name = obj.get("person_id"), obj.get("name")
            if pid is not None and isinstance(name, str) and name.strip() and "stints" in obj \
                    and pid not in self.protected:
                words = [w for w in re.split(r"[\s,]+", name) if w[:1].isalpha()][:3]
                self.names[name] = "".join(w[0].upper() + "." for w in words) or "?"
            for v in obj.values():
                self._learn(v)
        elif isinstance(obj, list):
            for v in obj:
                self._learn(v)

    def __call__(self, e: dict):
        self._learn(e)
        if not self.names:
            return self.emit(e)
        text = json.dumps(e, default=str)
        for name in sorted(self.names, key=len, reverse=True):
            text = text.replace(json.dumps(name)[1:-1], self.names[name])
            # also each first name on its own ("Hi Rahul,")
            first = name.split()[0]
            if len(first) > 2:
                text = re.sub(rf"\b{re.escape(first)}\b", self.names[name], text)
        out = json.loads(text)
        for obj in _walk(out):
            if isinstance(obj, dict) and obj.get("person_id") not in self.protected and "stints" in obj:
                obj["profile_url"] = None
        return self.emit(out)


def _walk(obj):
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)
