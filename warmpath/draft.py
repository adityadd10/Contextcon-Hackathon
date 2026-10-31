"""Intro drafts: built only from Evidence on the path.  Owner: Member B.

The template is deterministic and states only facts taken from the path (zero hallucination by construction).
LLM polish is optional and is kept only if `check_claims` finds nothing unsupported: every year, duration,
number and proper noun it uses must appear in the path's evidence. Otherwise we keep the template.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import llm
from .models import Draft, Evidence, IntroPath, Person, TargetSpec, Tie

OUTBOX = Path("outbox")
ASK = {"hiring": "about a role we're hiring for", "sales": "about a problem we think we can help with",
       "fundraising": "about our fundraise", "referral": "for career advice and possibly a referral",
       "other": "for a quick conversation"}
# capitalised words that carry no factual claim
COMMON = set("""i i'm i'd i've i'll hi hey hello dear thanks thank cheers best regards warm warmly would could
can will may might please totally fine no not if so and but or also just quick short note intro introduction
request your you you're we we're our my me it it's this that they them their he she his her hope hoping
noticed saw since as given happy glad open forward forwarding below above re subject linkedin crustdata
mon tue wed thu fri monday tuesday wednesday thursday friday absolutely sure any let know looking reaching
out love keen great nice really much appreciate appreciated grateful ps p.s. no-pressure""".split())


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _facts(path: IntroPath) -> list[str]:
    return [f.explanation for t in path.ties for f in t.factors if f.contribution >= 5]


def _citations(path: IntroPath) -> list[Evidence]:
    seen, out = set(), []
    for t in path.ties:
        for f in t.factors:
            for e in f.evidence:
                if (e.ref, e.claim) not in seen:
                    seen.add((e.ref, e.claim))
                    out.append(e)
    return out


def _allowed(path: IntroPath) -> str:
    """Everything a draft may state: names, employers, titles, schools, factor text and evidence claims."""
    parts: list[str] = [*_facts(path), *(e.claim for e in _citations(path))]
    for n in path.nodes:
        parts += [n.name, n.current_title or "", n.headline or "", n.location or ""]
        parts += [f"{s.company_name} {s.title or ''} {s.location or ''}" for s in n.stints]
        parts += [s.name for s in n.schools]
    for t in path.ties:
        parts += [f"{o.company_name} {o.start.year} {o.end.year} {o.months:.0f}" for o in t.overlaps]
    return " ".join(parts).lower()


def check_claims(text: str, path: IntroPath) -> list[str]:
    """Return the sentences that state a year, number or proper noun not backed by the path's evidence."""
    allowed = _allowed(path)
    allowed_words = set(re.findall(r"[a-z0-9][a-z0-9&.\-']*", allowed))
    bad = []
    for sent in _sentences(text):
        clean = re.sub(r"\[[^\]]*\]", " ", sent)               # "[Your name]" placeholders are fine
        nums = re.findall(r"\b\d[\d,.]*%?", clean)
        if any(n.rstrip(".,") not in allowed for n in nums):
            bad.append(sent)
            continue
        words = re.findall(r"[A-Za-z][\w&\-']*", clean)
        for i, w in enumerate(words):
            core = re.sub(r"'s$", "", w)
            if i == 0 or not core[:1].isupper() or core.lower() in COMMON:
                continue
            if core.lower() not in allowed_words:
                bad.append(sent)
                break
    return bad


def _shared(t: Tie, you: bool = True) -> str:
    who = "you two" if you else "they"
    if t.overlaps:
        o = t.overlaps[0]
        return f"{who} overlapped at {o.company_name} ({o.start.year}–{o.end.year})"
    cls = next((f for f in t.factors if f.name == "classmates"), None)
    if cls:
        return f"{who} were at {cls.value} at the same time"
    return f"{who} crossed paths"


def _first(p: Person) -> str:
    return p.name.split()[0] if p.name and p.name != "?" else "there"


def template(path: IntroPath, spec: TargetSpec) -> Draft:
    target, connector = path.nodes[-1], path.nodes[-2]
    role = target.current_title or "their current role"
    sender = path.nodes[0] if len(path.nodes) >= 3 else None
    opener = (f"We overlapped at {path.ties[0].overlaps[0].company_name}, so I hope this isn't too out of the blue. "
              if sender and path.ties[0].overlaps else "")
    body = (f"Hi {_first(connector)},\n\n{opener}"
            f"I'm hoping to reach {target.name} ({role}) {ASK[spec.purpose]}. "
            f"I noticed {_shared(path.ties[-1])}, so you might be the right person to ask.\n\n"
            f"Would you be open to forwarding the short note below? Totally fine if not.\n\nThanks!\n"
            f"{'[' + sender.name + ']' if sender else '[Your name]'}")
    blurb = (f"Hi {_first(target)}, a quick intro request: [Your name] would love a short call "
             f"{ASK[spec.purpose]}. {_first(connector)} suggested you'd be the right person.")
    d = Draft(path_rank=path.rank, to=connector.name, subject=f"Intro to {target.name}?", body=body,
              forwardable_blurb=blurb, citations=_citations(path))
    _verify(d, path)
    return d


def _verify(d: Draft, path: IntroPath) -> None:
    sents = _sentences(d.body) + _sentences(d.forwardable_blurb)
    d.claims_checked = len(sents)
    d.claims_unsupported = check_claims(d.body, path) + check_claims(d.forwardable_blurb, path)


async def draft_intro(path: IntroPath, spec: TargetSpec) -> Draft:
    d = template(path, spec)
    if llm.available():
        facts = "\n".join(f"- {x}" for x in _facts(path))
        txt = await llm.complete(
            "You write short, warm, specific intro-request emails. Use ONLY the facts given. Do not add any "
            "company, school, date, number or name that is not in the facts. Output only the email body.",
            f"Connector: {d.to}\nTarget: {path.nodes[-1].name} ({path.nodes[-1].current_title or 'role unknown'})\n"
            f"Purpose: {spec.purpose}\nFacts:\n{facts}\n\n"
            f"Rewrite this draft, under 120 words, keep the same meaning:\n{d.body}", max_tokens=400)
        if txt:
            txt = re.sub(r"(?im)^\s*subject:.*$", "", txt).strip()
            bad = check_claims(txt, path)
            if bad or len(txt.split()) > 180:
                d.llm_rejected = bad or ["too long"]
            else:
                d.body = txt
                _verify(d, path)
    return d


def write_outbox(d: Draft, run_id: str) -> Path:
    OUTBOX.mkdir(exist_ok=True)
    p = OUTBOX / f"{run_id}-path{d.path_rank}.md"
    status = ("✅ every sentence checked against the evidence" if not d.claims_unsupported
              else f"⚠️ {len(d.claims_unsupported)} unsupported sentence(s): " + " | ".join(d.claims_unsupported))
    sources = "\n".join(f"- {e.claim} · `{e.ref}`" + (f" · {e.url}" if e.url else "") for e in d.citations)
    p.write_text(f"# {d.subject}\n\n**To:** {d.to} (NOT SENT, local outbox only)\n\n{d.body}\n\n---\n"
                 f"**Forwardable blurb:**\n\n> {d.forwardable_blurb}\n\n---\n"
                 f"**Fact check:** {status} ({d.claims_checked} sentences)\n\n"
                 f"**Sources:**\n{sources or '- (none)'}\n", encoding="utf-8")
    return p
