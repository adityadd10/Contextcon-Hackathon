"""Rank intro paths: seed → connector → target (or connector → target).  Owner: Member B."""
from __future__ import annotations

from .models import IntroPath, Person, TargetSpec, Tie
from .score import score_tie

MIN_TIE = 25.0


def path_score(ties: list[Tie]) -> float:
    scores = [t.score for t in ties]
    s = 0.7 * min(scores) + 0.3 * (sum(scores) / len(scores))
    return round(s * 0.85 ** (len(ties) - 1), 1)


def build_paths(target: Person, connectors: list[Person], seeds: list[Person], spec: TargetSpec) -> list[IntroPath]:
    paths: list[IntroPath] = []
    # seeds that already know the target directly
    for s in seeds:
        t = score_tie(s, target)
        if t.score >= MIN_TIE:
            paths.append(IntroPath(nodes=[s, target], ties=[t], score=path_score([t]),
                                   why=f"{s.name} already knows {target.name}: {_top_reason(t)}"))
    for c in connectors:
        if c.person_id == target.person_id:
            continue
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
    paths.sort(key=lambda p: -p.score)
    for i, p in enumerate(paths, 1):
        p.rank = i
    return paths[: spec.max_paths]


def _top_reason(t: Tie) -> str:
    if not t.factors:
        return "weak signal"
    return max(t.factors, key=lambda f: f.contribution).explanation
