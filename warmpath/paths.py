"""Rank intro paths: seed → connector → target (or connector → target).  Owner: Member B.

Path score = 0.7 × weakest tie + 0.3 × mean tie, × 0.85^(hops−1): a chain is only as warm as its weakest link.
"""
from __future__ import annotations

from .models import IntroPath, Person, TargetSpec, Tie
from .score import score_tie

MIN_TIE = 25.0
HOP_DECAY = 0.85


def path_score(ties: list[Tie]) -> float:
    if not ties:
        return 0.0
    scores = [t.score for t in ties]
    s = 0.7 * min(scores) + 0.3 * (sum(scores) / len(scores))
    return round(s * HOP_DECAY ** (len(ties) - 1), 1)


def same_person(a: Person, b: Person) -> bool:
    """Identity by Crustdata ID, else profile URL. Never by name alone: same-name people are common."""
    if a.person_id is not None and b.person_id is not None:
        return a.person_id == b.person_id
    if a.profile_url and b.profile_url:
        return a.profile_url.rstrip("/").lower() == b.profile_url.rstrip("/").lower()
    return a is b


def _dedupe(people: list[Person], exclude: list[Person]) -> list[Person]:
    out: list[Person] = []
    for p in people:
        if any(same_person(p, x) for x in exclude) or any(same_person(p, x) for x in out):
            continue
        out.append(p)
    return out


def build_paths(target: Person, connectors: list[Person], seeds: list[Person], spec: TargetSpec) -> list[IntroPath]:
    paths: list[IntroPath] = []
    seeds = _dedupe(seeds, [target])
    # seeds that already know the target directly
    for s in seeds:
        t = score_tie(s, target)
        if t.score >= MIN_TIE:
            paths.append(IntroPath(nodes=[s, target], ties=[t], score=path_score([t]),
                                   why=f"{s.name} already knows {target.name}: {_top_reason(t)}"))
    for c in _dedupe(connectors, [target, *seeds]):
        t_ct = score_tie(c, target)
        if t_ct.score < MIN_TIE:
            continue
        best_seed = None
        for s in seeds:
            t_sc = score_tie(s, c)
            if t_sc.score >= MIN_TIE and (best_seed is None or t_sc.score > best_seed[1].score):
                best_seed = (s, t_sc)
        if best_seed:
            s, t_sc = best_seed
            ties = [t_sc, t_ct]
            paths.append(IntroPath(nodes=[s, c, target], ties=ties, score=path_score(ties),
                                   why=f"{s.name} → {c.name}: {_top_reason(t_sc)}; "
                                       f"{c.name} → {target.name}: {_top_reason(t_ct)}"))
        else:
            paths.append(IntroPath(nodes=[c, target], ties=[t_ct], score=path_score([t_ct]),
                                   why=f"{c.name} → {target.name}: {_top_reason(t_ct)}"))
    # ties broken by total months worked together, then fewer hops
    paths.sort(key=lambda p: (-p.score, -sum(o.months for t in p.ties for o in t.overlaps[:1]), len(p.ties)))
    for i, p in enumerate(paths, 1):
        p.rank = i
    return paths[: spec.max_paths]


def _top_reason(t: Tie) -> str:
    if not t.factors:
        return "weak signal"
    return max(t.factors, key=lambda f: f.contribution).explanation
