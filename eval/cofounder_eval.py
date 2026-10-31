"""Co-founder recovery eval: does WarmPath pick a startup's real co-founder as the #1 connector?  Owner: Member B.

For each startup: /company/identify → /company/enrich (people.founders) → /person/enrich the founders, plus a
/person/search pool of colleagues at the same company. Each founder in turn is the target. Every other person
(co-founders + colleagues) is ranked by tie score. Hit@1 / Hit@3 = a real co-founder ranked #1 / in the top 3.

Ranked against:
  * random colleague: exact expectation of picking uniformly from the same pool
  * longest overlap: months worked together only (the naive "they were both there" approach)
  * WarmPath without the title factor: ablation, since co-founders often share a "Co-founder" title

Equal scores are broken *against* the co-founder, so the numbers never flatter us.

    uv run python -m eval.cofounder_eval                    # live: ~4-6 credits per startup, data saved to eval/data/
    uv run python -m eval.cofounder_eval --offline          # re-score the saved data, 0 credits
    uv run python -m eval.cofounder_eval --companies Razorpay,Zepto --budget 60
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass
from datetime import date
from math import comb
from pathlib import Path
from typing import Callable

from rapidfuzz import fuzz

from warmpath.crust import parse_date
from warmpath import headcount
from warmpath.models import Person, School, Stint, to_dict
from warmpath.paths import same_person
from warmpath.score import find_overlaps, score_tie

HERE = Path(__file__).parent
DATA = HERE / "data"
STARTUPS = ["Razorpay", "Zepto", "Swiggy", "Zomato", "Meesho", "Groww", "PhysicsWallah", "Unacademy", "Postman",
            "BrowserStack", "Chargebee", "Hasura", "Zerodha", "Urban Company", "Licious", "Rapido", "Ather Energy",
            "Khatabook", "Slice", "Dunzo"]
POOL = 25

Scorer = Callable[[Person, Person], float]


# ---------------------------------------------------------------- scoring (pure, unit-tested)

def warmpath_score(c: Person, t: Person) -> float:
    return score_tie(c, t).score


def no_title_score(c: Person, t: Person) -> float:
    tie = score_tie(c, t)
    return max(0.0, sum(f.contribution for f in tie.factors if f.name != "similar_title"))


def overlap_score(c: Person, t: Person) -> float:
    ov = find_overlaps(c, t)
    return ov[0].months if ov else 0.0


METHODS: dict[str, Scorer] = {"WarmPath": warmpath_score, "WarmPath w/o title": no_title_score,
                              "Longest overlap": overlap_score}


def cofounder_rank(target: Person, cofounders: list[Person], others: list[Person], scorer: Scorer) -> int:
    """1-based rank of the best co-founder among all candidates. Ties count against the co-founder."""
    best_cf = max(scorer(c, target) for c in cofounders)
    return 1 + sum(1 for o in others if scorer(o, target) >= best_cf)


def random_hit(k: int, n: int, at: int) -> float:
    """P(at least one of k co-founders in a random top-`at` pick from n candidates)."""
    if n <= 0 or k <= 0:
        return 0.0
    at = min(at, n)
    return 1 - comb(n - k, at) / comb(n, at)


@dataclass
class FounderResult:
    company: str
    founder: str
    cofounders: list[str]
    pool: int
    ranks: dict[str, int]
    best_cofounder_score: float
    top_pick: str
    top_pick_why: str


def founded_here(p: Person, company_id: int | None, year_founded: int | None) -> bool:
    """Same founder test as is_founder(), on a parsed Person (used for people found by /person/search)."""
    return any(s.company_id == company_id and s.title and _founder_title(s.title) and s.start
               and (year_founded is None or abs(s.start.year - year_founded) <= 2) for s in p.stints)


def evaluate_company(company: str, founders: list[Person], colleagues: list[Person],
                     company_id: int | None = None, year_founded: int | None = None) -> list[FounderResult]:
    """Rank every founder's co-founders against the colleague pool.

    The ground truth is applied evenly: a colleague who passes the same founder test (Crustdata's founders
    list misses some, e.g. Unacademy's Hemesh Singh) counts as a co-founder. Two records with the same name
    are one person (PhysicsWallah has two "Alakh Pandey" records), never a co-founder pair.
    """
    pool = [p for p in colleagues if not any(same_person(p, f) for f in founders)]
    if company_id is not None:
        founders = founders + [p for p in pool if founded_here(p, company_id, year_founded)]
        pool = [p for p in pool if not any(p is f for f in founders)]
    uniq: list[Person] = []
    for f in founders:
        if not any(_same_name(f, u) for u in uniq):
            uniq.append(f)
    pool = [p for p in pool if not any(_same_name(p, u) for u in uniq)]
    out = []
    for f in uniq:
        cofounders = [x for x in uniq if x is not f]
        if not cofounders:
            continue
        candidates = cofounders + pool
        ranks = {m: cofounder_rank(f, cofounders, pool, s) for m, s in METHODS.items()}
        ties = sorted((score_tie(c, f) for c in candidates), key=lambda t: -t.score)
        top = ties[0]
        why = max(top.factors, key=lambda x: x.contribution).explanation if top.factors else "no signal"
        out.append(FounderResult(company, f.name, [c.name for c in cofounders], len(candidates), ranks,
                                 max(score_tie(c, f).score for c in cofounders), top.a.name, why))
    return out


def _same_name(a: Person, b: Person) -> bool:
    return re.sub(r"\W+", " ", a.name.lower()).strip() == re.sub(r"\W+", " ", b.name.lower()).strip()


def summarise(results: list[FounderResult]) -> dict:
    n = len(results)
    if not n:
        return {"founders": 0}
    s: dict = {"founders": n, "companies": len({r.company for r in results})}
    for m in METHODS:
        s[m] = {"hit@1": sum(r.ranks[m] == 1 for r in results) / n, "hit@3": sum(r.ranks[m] <= 3 for r in results) / n}
    s["Random colleague"] = {
        "hit@1": sum(random_hit(len(r.cofounders), r.pool, 1) for r in results) / n,
        "hit@3": sum(random_hit(len(r.cofounders), r.pool, 3) for r in results) / n}
    s["mean_pool"] = sum(r.pool for r in results) / n
    return s


# ---------------------------------------------------------------- data collection (live API)

def _find(obj, key: str):
    """First value stored under `key` anywhere in a nested response (the enrich shape varies by version)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        obj = list(obj.values())
    if isinstance(obj, list):
        for v in obj:
            if (r := _find(v, key)) is not None:
                return r
    return None


FOUNDER_RE = re.compile(r"\bco-?\s?founder\b|\bfounder\b", re.I)
NOT_FOUNDER = re.compile(r"founder[’']?s?\s+office|assistant|\bto the\b|chief of staff|\bEA\b", re.I)


def _founder_title(t: str) -> bool:
    return bool(FOUNDER_RE.search(t)) and not NOT_FOUNDER.search(t)


def is_founder(d: dict, company_id: int | None = None, company_name: str = "",
               year_founded: int | None = None) -> bool:
    """A real co-founder: a founder title *at this company* that started within 2 years of its founding.

    people.founders is noisy: "Founder's Office" staff and EAs (12 of 14 at Razorpay), and one-job profiles that
    claim to have founded Zomato with no dates. Anything we can't check is left out, never guessed.
    """
    if company_id is None and not company_name:   # no company context: profile title only
        bp = d.get("basic_profile") or {}
        return _founder_title(bp.get("current_title") or bp.get("headline") or "")
    emp = (d.get("experience") or {}).get("employment_details") or {}
    for st in (emp.get("current") or []) + (emp.get("past") or []):
        at_co = (company_id is not None and str(st.get("employer_company_id") or st.get("crustdata_company_id"))
                 == str(company_id)) or (company_name and fuzz.token_set_ratio(
                     (st.get("employer_name") or st.get("name") or "").lower(), company_name.lower()) >= 90)
        t = st.get("employee_title") or st.get("title") or ""
        if not at_co or not _founder_title(t):
            continue
        start = parse_date(st.get("employee_start_date") or st.get("start_date"))
        if start and (year_founded is None or abs(start.year - year_founded) <= 2):
            return True
    return False


def _profile_url(d: dict) -> str | None:
    for v in d.values() if isinstance(d, dict) else []:
        if isinstance(v, str) and "linkedin.com/in/" in v:
            return v
        if isinstance(v, dict) and (u := _profile_url(v)):
            return u
    return None


async def collect(c, company: str, log=print) -> dict | None:
    from warmpath.crust import CrustError, f, to_person
    from warmpath.events import noop
    from warmpath.resolve import resolve_company

    co = await resolve_company(c, company, noop)
    if not co or not co.company_id:
        log(f"  {company}: not found in Crustdata")
        return None
    try:
        rows = await c.company_enrich([co.company_id], fields=["basic_info", "headcount", "people"])
        headcount.register(co.company_id, rows)
    except CrustError as e:
        log(f"  {company}: company enrich failed ({e.message})")
        return None
    year = _find(rows, "year_founded") or co.year_founded
    year = int(str(year)[:4]) if year and str(year)[:4].isdigit() else None
    listed = [x for x in _find(rows, "founders") or [] if isinstance(x, dict)]
    raw_founders = [x for x in listed if is_founder(x, co.company_id, co.name, year)]
    log(f"  {company}: {len(raw_founders)} of {len(listed)} listed founders verified (founded {year or '?'})")
    urls = list(dict.fromkeys(u for u in (_profile_url(x) for x in raw_founders) if u))
    if len(urls) < 2:
        log(f"  {company}: {len(urls)} founder profile(s) listed, need 2+, skipped")
        return None
    founders = []
    for row in await c.person_enrich(urls[:10]):
        if row.get("matches"):
            founders.append(to_person(row["matches"][0]["person_data"], "/person/enrich"))
    if len(founders) < 2:
        log(f"  {company}: only {len(founders)} founder(s) enriched (redacted/not found), skipped")
        return None
    res = await c.person_search(f("experience.employment_details.company_id", "=", co.company_id), limit=POOL)
    colleagues = [to_person(p, "/person/search") for p in (res.get("profiles") or res.get("results") or [])]
    log(f"  {company}: {len(founders)} founders, {len(colleagues)} colleagues (id {co.company_id})")
    return {"company": co.name, "company_id": co.company_id, "year_founded": year,
            "headcount_history": [[d.isoformat(), n] for d, n in headcount.HISTORY.get(co.company_id, [])],
            "founders": to_dict(founders),
            "colleagues": to_dict(colleagues)}


# ---------------------------------------------------------------- persistence

def _d(v) -> date | None:
    return date.fromisoformat(v) if v else None


def person_from_dict(d: dict) -> Person:
    st = [Stint(**{**s, "start": _d(s.get("start")), "end": _d(s.get("end"))}) for s in d.get("stints", [])]
    sc = [School(**{**s, "start": _d(s.get("start")), "end": _d(s.get("end"))}) for s in d.get("schools", [])]
    return Person(**{**d, "stints": st, "schools": sc})


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def load_saved() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(DATA.glob("*.json"))]


# ---------------------------------------------------------------- report

def report(results: list[FounderResult], s: dict) -> str:
    if not results:
        return "No founders evaluated."
    lines = [f"# Co-founder recovery eval\n",
             f"{s['founders']} founders across {s['companies']} startups; mean candidate pool {s['mean_pool']:.1f} "
             f"people (co-founders + up to {POOL} colleagues from /person/search).\n",
             "| Method | Hit@1 | Hit@3 |", "|---|---|---|"]
    for m in [*METHODS, *(["WarmPath, latest headcount"] if "WarmPath, latest headcount" in s else []),
              "Random colleague"]:
        lines.append(f"| {m} | {s[m]['hit@1']:.0%} | {s[m]['hit@3']:.0%} |")
    lines += ["", "| Startup | Target founder | Co-founder rank (WarmPath / overlap only) | Pool | WarmPath #1 pick, top reason |",
              "|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.company} | {r.founder} | {r.ranks['WarmPath']} / {r.ranks['Longest overlap']} | {r.pool} "
                     f"| {r.top_pick}: {r.top_pick_why} |")
    return "\n".join(lines) + "\n"


async def main_async(args) -> None:
    datasets: list[dict] = []
    if args.offline:
        datasets = load_saved()
        if not datasets:
            raise SystemExit(f"No saved data in {DATA}. Run once without --offline (needs CRUSTDATA_API_KEY).")
    else:
        from warmpath.crust import BudgetExceeded, Crust
        DATA.mkdir(parents=True, exist_ok=True)
        names = [x.strip() for x in args.companies.split(",")] if args.companies else STARTUPS[: args.n]
        async with Crust(budget=args.budget) as c:
            for name in names:
                try:
                    d = await collect(c, name)
                except BudgetExceeded:
                    print(f"  budget of {args.budget} credits reached, stopping")
                    break
                if d:
                    (DATA / f"{_slug(name)}.json").write_text(json.dumps(d, indent=1), encoding="utf-8")
                    datasets.append(d)
            print(f"credits used: {c.credits_used:.2f}")
    def run_all() -> list[FounderResult]:
        out: list[FounderResult] = []
        for d in datasets:
            out += evaluate_company(d["company"], [person_from_dict(p) for p in d["founders"]],
                                    [person_from_dict(p) for p in d["colleagues"]],
                                    d.get("company_id"), d.get("year_founded"))
        return out

    headcount.HISTORY.clear()                     # ablation: latest headcount only
    latest = summarise(run_all())
    for d in datasets:
        if d.get("headcount_history"):
            headcount.HISTORY[d["company_id"]] = [(date.fromisoformat(x), n) for x, n in d["headcount_history"]]
    results = run_all()
    s = summarise(results)
    if latest.get("founders"):
        s["WarmPath, latest headcount"] = latest["WarmPath"]
    md = report(results, s)
    print(md)
    (HERE / "results.md").write_text(md, encoding="utf-8")
    (HERE / "results.json").write_text(json.dumps({"summary": s, "results": [r.__dict__ for r in results]},
                                                  indent=1), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true", help="re-score saved eval/data/*.json, no API calls")
    ap.add_argument("--companies", help="comma-separated startup names (default: built-in list)")
    ap.add_argument("-n", type=int, default=15, help="how many startups from the built-in list")
    ap.add_argument("--budget", type=float, default=200, help="max Crustdata credits for this run")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
