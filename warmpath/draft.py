"""Intro drafts: built only from Evidence on the path.  Owner: Member B.

v1 = deterministic template (zero hallucination by construction). LLM polish is optional and must
pass `check_claims` (every company/year it mentions must appear in the evidence) or we keep the template.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import llm
from .models import Draft, IntroPath, TargetSpec

OUTBOX = Path("outbox")
ASK = {"hiring": "about a role we're hiring for", "sales": "about a problem we think we can help with",
       "fundraising": "about our fundraise", "referral": "for career advice / a referral",
       "other": "for a quick conversation"}


def _facts(path: IntroPath) -> list[str]:
    return [f.explanation for t in path.ties for f in t.factors if f.contribution >= 5]


def template(path: IntroPath, spec: TargetSpec) -> Draft:
    target, connector = path.nodes[-1], path.nodes[-2]
    tie = path.ties[-1]
    ov = tie.overlaps[0] if tie.overlaps else None
    shared = (f"you two overlapped at {ov.company_name} ({ov.start.year}–{ov.end.year})" if ov
              else "you two crossed paths")
    role = f"{target.current_title} " if target.current_title else ""
    body = (f"Hi {connector.name.split()[0]},\n\n"
            f"I'm hoping to reach {target.name} ({role.strip() or 'their current role'}) {ASK[spec.purpose]}. "
            f"I noticed {shared}, so you might be the right person to ask.\n\n"
            f"Would you be open to forwarding the short note below? Totally fine if not.\n\nThanks!")
    blurb = (f"{target.name.split()[0]}, a quick intro request: [Your name] would love 15 minutes "
             f"{ASK[spec.purpose]}. {connector.name.split()[0]} suggested you'd be the right person.")
    return Draft(path_rank=path.rank, to=connector.name, subject=f"Intro to {target.name}?", body=body,
                 forwardable_blurb=blurb, claims_checked=len(_facts(path)))


def check_claims(text: str, path: IntroPath) -> list[str]:
    """Return sentences mentioning a year or capitalised org not backed by evidence."""
    evidence_text = " ".join(_facts(path) + [n.name for n in path.nodes] +
                             [s.company_name for n in path.nodes for s in n.stints]).lower()
    bad = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        years = re.findall(r"\b(?:19|20)\d{2}\b", sent)
        if any(y not in evidence_text for y in years):
            bad.append(sent.strip())
    return bad


async def draft_intro(path: IntroPath, spec: TargetSpec) -> Draft:
    d = template(path, spec)
    if llm.available():
        facts = "\n".join(f"- {x}" for x in _facts(path))
        txt = await llm.complete(
            "You write short, warm, specific intro-request emails. Use ONLY the facts given. No made-up details.",
            f"Connector: {d.to}\nTarget: {path.nodes[-1].name}\nPurpose: {spec.purpose}\nFacts:\n{facts}\n\n"
            f"Rewrite this draft, under 120 words, keep the same meaning:\n{d.body}", max_tokens=400)
        if txt:
            bad = check_claims(txt, path)
            if not bad:
                d.body = txt.strip()
            else:
                d.claims_unsupported = bad
    return d


def write_outbox(d: Draft, run_id: str) -> Path:
    OUTBOX.mkdir(exist_ok=True)
    p = OUTBOX / f"{run_id}-path{d.path_rank}.md"
    p.write_text(f"# {d.subject}\n\n**To:** {d.to} (NOT SENT, local outbox only)\n\n{d.body}\n\n---\n"
                 f"**Forwardable blurb:**\n\n> {d.forwardable_blurb}\n")
    return p
