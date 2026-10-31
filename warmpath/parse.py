"""Free-text request → TargetSpec.  Owner: Member B.

LLM first (OpenRouter), rule-based fallback always available. The rules handle typos and text-speak
("teh data guy at swiggy pls"), profile/company URLs, domains, Hinglish ("swiggy mein data head se intro"),
"<role> of <Company>", "<Name> (<Company>)" and network hints ("via IITB folks", "through ex-Microsoft people").
The LLM may fill gaps or fix typos, but it can never introduce a person or company the user didn't type.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from . import llm
from .models import NetworkSpec, TargetSpec

PROFILE_RE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[\w\-%]+/?", re.I)
COMPANY_URL_RE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[\w\-%]+/?", re.I)
DOMAIN_RE = re.compile(r"\b([a-z0-9\-]+\.(?:com|io|ai|in|co|org|net|app|dev|tech))\b", re.I)
SCHOOL_ALIASES = {
    "iitb": "IIT Bombay", "iit bombay": "IIT Bombay", "iit-b": "IIT Bombay", "iit b": "IIT Bombay",
    "iit delhi": "IIT Delhi", "iitd": "IIT Delhi", "iit madras": "IIT Madras", "iitm": "IIT Madras",
    "iit kanpur": "IIT Kanpur", "iitk": "IIT Kanpur", "iit kharagpur": "IIT Kharagpur", "iit kgp": "IIT Kharagpur",
    "iit roorkee": "IIT Roorkee", "iit guwahati": "IIT Guwahati", "iisc": "Indian Institute of Science",
    "iiit hyderabad": "IIIT Hyderabad", "bits pilani": "BITS Pilani", "bits": "BITS Pilani",
    "nit trichy": "NIT Trichy", "vjti": "VJTI", "stanford": "Stanford University", "harvard": "Harvard University",
    "iim ahmedabad": "IIM Ahmedabad", "iima": "IIM Ahmedabad", "iim bangalore": "IIM Bangalore",
    "iimb": "IIM Bangalore", "iim calcutta": "IIM Calcutta", "iimc": "IIM Calcutta",
    "mit": "Massachusetts Institute of Technology",
}
PURPOSE_WORDS = {
    "hiring": ["hire", "hiring", "recruit", "candidate"],
    "sales": ["sell", "sales", "demo", "pitch", "customer", "buyer", "prospect"],
    "fundraising": ["rais", "fundrais", "investor", "vc", "vcs", "seed round", "series", "funding"],
    "referral": ["referral", "refer me", "job at", "internship", "intern ", "job opening"],
}
# text-speak and typos, applied word by word before parsing
SLANG = {"teh": "the", "da": "the", "2": "to", "sum1": "someone", "some1": "someone", "ppl": "people",
         "pls": "", "plz": "", "pl": "", "yaar": "", "bro": "", "u": "you", "ur": "your", "thru": "through",
         "w/": "with", "intro'": "intro"}
ROLE_ABBR = {"engg": "engineering", "eng": "engineering", "mgr": "manager", "mktg": "marketing",
             "prod": "product", "hr": "HR", "vp": "VP", "svp": "SVP", "evp": "EVP"}
ROLE_RE = re.compile(r"\b(head|vp|svp|evp|director|chief|cto|ceo|cfo|coo|cpo|cmo|cxo|founder|co-?founder|lead|"
                     r"manager|engineer|engineering|data|product|recruit\w*|talent|hr|design\w*|market\w*|sales|"
                     r"growth|partner|ml|ai|analytics|scientist|architect|president|principal|owner|gm|"
                     r"procurement|finance|operations|ops|security|infra\w*|platform|devrel|bd)\b", re.I)
FILLER_RE = re.compile(r"^(?:(?:the|a|an|their|someone|somebody|anyone|anybody|person|people|whoever|who|"
                       r"runs|leads|heads|handles|manages|owns|is|in charge of|responsible for|senior|"
                       r"(?:from|on|in) the)\s+)+", re.I)
TRAIL_FILLER_RE = re.compile(r"\s+(?:guy|gal|lady|person|people|folks|team|ppl|wala|vala)$", re.I)
# the last of these before the company is where the role / name starts
VERB_RE = re.compile(r"\b(?:intro(?:duce|duction)?\s+(?:me\s+)?to|introduce\s+me\s+to|me\s+to|reach|meet|"
                     r"connect\s+(?:me\s+)?(?:with|to)|talk\s+to|speak\s+to|get\s+to|in\s+touch\s+with|to)\s+", re.I)
COMPANY_STOP = {"for", "via", "through", "who", "and", "to", "please", "ideally", "asap", "so", "because", "he",
                "she", "they", "we", "i", "if", "since", "as", "with", "using", "or", "but", "who's", "whos", "the"}
NETWORK_FILLER = {"alumni", "folks", "people", "network", "friends", "colleagues", "someone", "anyone", "my", "our",
                  "connections", "contacts", "the", "a", "an", "mutual", "mutuals", "linkedin", "warm", "intro"}

SYSTEM = """You turn a request for a warm introduction into JSON with keys:
person_name (string|null), profile_url (string|null), company (string|null: company name or domain),
role (string|null: the role/title of the person to reach if no name given, e.g. "head of data"),
purpose (one of hiring|sales|fundraising|referral|other),
schools (list of school names the intro path should go through, expanded e.g. "IITB" -> "IIT Bombay"),
companies (list of companies the intro path should go through), max_paths (int, default 5).
Fix obvious typos in company names ("swigy" -> "Swiggy"). The request may be in Hinglish.
Use null when unknown. Never invent names."""


async def parse_request(text: str) -> TargetSpec:
    spec = parse_rules(text)
    data = await llm.complete_json(SYSTEM, text) if llm.available() else None
    if not isinstance(data, dict):
        return spec
    # the LLM may only name people/companies that are actually in the request (fuzzy, to allow typo fixes)
    name = _str(data.get("person_name"))
    if name and _in_text(name, text, 85):
        spec.person_name = name
        if spec.role and spec.role.lower() == name.lower():
            spec.role = None
    company = _str(data.get("company"))
    if company and not spec.profile_url and (_in_text(company, text, 80) or not spec.company):
        if not COMPANY_URL_RE.search(spec.company or ""):  # never replace a URL the user pasted
            spec.company = company
    role = _str(data.get("role"))
    if role and not spec.person_name:
        spec.role = role
    if data.get("purpose") in PURPOSE_WORDS or data.get("purpose") == "other":
        if data["purpose"] != "other" or spec.purpose == "other":
            spec.purpose = data["purpose"]
    spec.network.schools = _dedupe([*spec.network.schools, *_strs(data.get("schools"))])
    spec.network.companies = _dedupe([*spec.network.companies,
                                      *(c for c in _strs(data.get("companies")) if _in_text(c, text, 80))])
    if isinstance(data.get("max_paths"), int):
        spec.max_paths = max(1, min(10, data["max_paths"]))
    spec.parser = "llm"
    return spec


def parse_rules(text: str) -> TargetSpec:
    spec = TargetSpec(raw=text, network=NetworkSpec())
    t = " ".join(text.split())
    urls = PROFILE_RE.findall(t)
    if urls:
        spec.profile_url = urls[0]
        spec.network.seed_profile_urls = urls[1:]
    t = PROFILE_RE.sub(" ", t)
    if m := COMPANY_URL_RE.search(t):
        spec.company = m.group(0)
    t = COMPANY_URL_RE.sub(" ", t)
    t = _normalise(t)
    low = t.lower()

    for alias, canon in SCHOOL_ALIASES.items():
        if re.search(rf"(?<![\w-]){re.escape(alias)}(?![\w-])", low):
            spec.network.schools.append(canon)
    spec.network.schools = _dedupe(spec.network.schools)
    spec.purpose = _purpose(low)  # type: ignore[assignment]
    spec.network.companies = _network_companies(t)

    # Hinglish: "<company> mein <role> se intro karwa do"
    hm = re.search(r"\b([\w.&\-]+)\s+(?:mein|me|main|ke|ka|ki)\s+(.+?)\s+(?:se|ko|wale|waale)\b", t, re.I)
    if hm and not spec.company and re.search(r"\b(?:intro|milwa|karwa|karva|baat)\w*", low):
        spec.company = hm.group(1)
        _set_role_or_name(spec, hm.group(2), had_verb=True)
        return spec

    co_start = _url_prep(t) if spec.company else _find_company(t, spec)
    head = t[:co_start] if co_start is not None else t
    verbs = list(VERB_RE.finditer(head))
    segment = head[verbs[-1].end():] if verbs else head
    segment = re.sub(r"\(.*?\)", " ", segment)
    if not spec.profile_url:
        _set_role_or_name(spec, segment, had_verb=bool(verbs))
    return spec


def _normalise(t: str) -> str:
    words = []
    for w in t.split():
        core = w.strip(",.!?;:")
        rep = SLANG.get(core.lower())
        words.append(w.replace(core, rep) if rep is not None and core else w)
    t = " ".join(x for x in words if x.strip(",.!?;:"))
    return re.sub(r"([!?.,])\1+", r"\1", t).strip()


def _purpose(low: str) -> str:
    for purpose, words in PURPOSE_WORDS.items():
        if any(re.search(rf"\b{re.escape(w.strip())}", low) for w in words):
            return purpose
    return "other"


def _is_school(s: str) -> bool:
    low = s.lower()
    return any(re.match(rf"{re.escape(a)}(?![\w-])", low) for a in SCHOOL_ALIASES) or bool(
        re.match(r"(iit|iim|nit|iiit|bits)\b", low))


def _find_company(t: str, spec: TargetSpec) -> int | None:
    """Locate the target's company and set spec.company. Returns where the role/name segment ends."""
    for preps in (r"at\s+|@\s*|from\s+", r"of\s+|in\s+"):   # "head of data at Swiggy": 'at' wins over 'of'
        for m in re.finditer(rf"(?:^|\s)(?:{preps})(?=\S)", t, re.I):
            name = _company_words(t[m.end():])
            if not name or _is_school(name):
                continue
            if preps.startswith("of") and name.split()[0].lower() in {"the", "a", "an", "charge", "touch", "growth"}:
                continue
            spec.company = name
            return m.start()
    if (paren := re.search(r"\(([^)]{2,40})\)", t)) and not _is_school(paren.group(1)):
        spec.company = paren.group(1).strip()
        return None
    if (d := DOMAIN_RE.search(t)) and "linkedin" not in d.group(1).lower():
        spec.company = d.group(1)
        return d.start()
    return None


def _url_prep(t: str) -> int | None:
    """The company URL was cut out: the role ends at a dangling 'at' / '@' / 'of'."""
    m = re.search(r"\s(?:at|@|of|from)\s*$", t, re.I) or re.search(r"\s(?:at|@|of|from)\s+(?:for|via|,)", t, re.I)
    return m.start() if m else None


def _company_words(rest: str) -> str:
    out = []
    for w in re.split(r"\s+", rest.strip()):
        core = w.strip(",.!?;:'\"")
        if not core or core.lower() in COMPANY_STOP or not re.match(r"[\w&]", core):
            break
        out.append(core)
        if w != core.rstrip(".") and re.search(r"[,!?;:]$", w):
            break
        if len(out) == 3:
            break
    name = " ".join(out).strip(" .")
    return "" if not name or ROLE_RE.fullmatch(name) else name


def _network_companies(t: str) -> list[str]:
    out = []
    for m in re.finditer(r"\b(?:via|through|using)\s+(?:my\s+|our\s+|the\s+|some\s+)?(?:ex[-\s]?)?([A-Za-z][\w&.\-]*)",
                         t, re.I):
        word = m.group(1)
        if word.lower() in NETWORK_FILLER or _is_school(t[m.start(1):]) or word.lower().startswith("ex-"):
            continue
        out.append(word)
    out += [m.group(1) for m in re.finditer(r"\bex[-\s]([A-Z][\w&.\-]*)", t)]
    return _dedupe([w.strip(".,") for w in out if not _is_school(w)])


def _set_role_or_name(spec: TargetSpec, segment: str, had_verb: bool) -> None:
    s = segment.strip(" ,.!?:;-")
    s = re.sub(r"^(?:(?:get|me|a|warm|intro|introduction|can|you|someone|need|looking|for|please)\s+)+", "", s,
               flags=re.I) if not had_verb else s
    s = FILLER_RE.sub("", s).strip()
    s = TRAIL_FILLER_RE.sub("", s).strip(" ,.!?")
    if not s or len(s.split()) > 6:
        return
    # company written before the role: "razorpay ceo", "Swiggy's head of data"
    pre = re.match(r"([\w.&\-]+?)(?:'s|’s)?\s+(.+)$", s)
    if not spec.company and pre and not ROLE_RE.fullmatch(pre.group(1)) and ROLE_RE.match(pre.group(2)) \
            and not _is_school(pre.group(1)) and (had_verb or "'" in s or "’" in s):
        spec.company, s = pre.group(1), pre.group(2)
    if ROLE_RE.search(s):
        spec.role = " ".join(ROLE_ABBR.get(w.lower(), w) for w in s.split())
    elif had_verb and len(s.split()) <= 3 and all(re.fullmatch(r"[A-Za-z.'\-]+", w) for w in s.split()) \
            and not _is_school(s) and s.lower() not in NETWORK_FILLER:
        spec.person_name = s


def _in_text(value: str, text: str, threshold: int) -> bool:
    v, t = value.lower().strip(), text.lower()
    if v in t:
        return True
    if all(tok in t for tok in v.split()):
        return True
    return fuzz.partial_ratio(v, t) >= threshold


def _str(v) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() and v.strip().lower() not in {"null", "none"} else None


def _strs(v) -> list[str]:
    return [x for x in (_str(i) for i in v) if x] if isinstance(v, list) else []


def _dedupe(xs: list[str]) -> list[str]:
    seen, out = set(), []
    for x in xs:
        if x and x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out
