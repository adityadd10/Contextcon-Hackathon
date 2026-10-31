"""Product eval: run every gold scenario end to end and score it. Owner: Member A.

    uv run python -m eval.run_eval              # fake + live (live uses the response cache; new requests cost credits)
    uv run python -m eval.run_eval --fake       # offline only, 0 credits, deterministic (use before every push)
    uv run python -m eval.run_eval --llm        # same, with the free LLM on (parity check: should not change answers)

Writes eval/scorecard.md (per scenario + per category + overall, with the delta against the previous run) and appends
one line per run to eval/history.jsonl (git sha + metrics), so every change can be judged better or worse.

Metrics per run (from the event stream + RunResult + audit trail):
  completed        exactly one `done` event and no `error` event
  correct          every expectation in the scenario holds (target / no-target / warnings / paths / seed path)
  silent_failure   no target and no warning explaining why
  citation_cov     share of scoring factors that carry ≥1 Evidence
  verified_rate    share of returned ties re-checked against full profiles
  traceable_rate   share of Crustdata evidence whose call_id exists in the audit trail
  false_ties       ties built on placeholder employers ("Self-employed", "Various Startups"); must be 0
  unsupported      draft claims the claim-checker could not back with evidence; must be 0
  credits / seconds / api_calls / cache_rate / llm_calls
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from eval.scenarios import SCENARIOS, Scenario

load_dotenv(".env")
OUT = Path(__file__).parent
HISTORY = OUT / "history.jsonl"
SCORECARD = OUT / "scorecard.md"


async def run_one(sc: Scenario) -> dict:
    from warmpath import llm
    from warmpath.crust import Crust, is_generic_employer
    from warmpath.graphdb import GraphStore
    from warmpath.pipeline import run

    events: list[dict] = []
    llm_before = llm.calls_used() if hasattr(llm, "calls_used") else 0
    t0 = time.time()
    if sc.world == "fake":
        from warmpath.fake import FakeCrust
        crust = Crust(api_key="x", use_cache=False, transport=FakeCrust(False).transport(), pace=False)
        graph = GraphStore(OUT / ".fake_graph.db")
        seeds_env = os.environ.pop("WARMPATH_SEEDS", None)
    else:
        crust, graph, seeds_env = Crust(), GraphStore(), None
    try:
        async with crust as c:
            r = await asyncio.wait_for(run(sc.query, events.append, crust=c, graph=graph), 240)
    except Exception as e:  # the harness itself must never die on one scenario
        return {"id": sc.id, "category": sc.category, "world": sc.world, "query": sc.query, "completed": False,
                "correct": False, "crash": f"{type(e).__name__}: {e}", "seconds": round(time.time() - t0, 1)}
    finally:
        graph.close()
        if seeds_env is not None:
            os.environ["WARMPATH_SEEDS"] = seeds_env

    types = [e["type"] for e in events]
    warnings = [e.get("message", "") for e in events if e["type"] == "warning"]
    ties = [t for p in r.paths for t in p.ties]
    factors = [f for t in ties for f in t.factors]
    crust_ev = [e for f in factors for e in f.evidence if e.kind == "crustdata"]
    call_ids = {a.call_id for a in r.audit}
    tgt = r.target
    cur_cos = " | ".join(s.company_name for s in (tgt.stints if tgt else []) if s.is_current)

    checks: dict[str, bool] = {}
    x = sc.expect
    if x.get("no_target"):
        checks["no_target"] = tgt is None
    else:
        checks["target_found"] = tgt is not None
    if "target_name" in x:
        checks["target_name"] = bool(tgt and re.search(x["target_name"], tgt.name, re.I))
    if "target_title" in x:
        checks["target_title"] = bool(tgt and re.search(x["target_title"], tgt.current_title or tgt.headline or "", re.I))
    if "target_company" in x:
        checks["target_company"] = bool(tgt and re.search(x["target_company"], cur_cos, re.I))
    if "warn" in x:
        checks["warning"] = any(re.search(x["warn"], w, re.I) for w in warnings)
    if "min_paths" in x:
        checks["min_paths"] = len(r.paths) >= x["min_paths"]
    if x.get("seed_path"):
        checks["seed_path"] = any(getattr(p, "via_seed", False) for p in r.paths)

    m = {
        "id": sc.id, "category": sc.category, "world": sc.world, "query": sc.query[:70],
        "completed": types.count("done") == 1 and "error" not in types,
        "silent_failure": tgt is None and not warnings,
        "checks": checks,
        "paths": len(r.paths),
        "citation_cov": round(sum(1 for f in factors if f.evidence) / len(factors), 3) if factors else None,
        "verified_rate": round(sum(1 for t in ties if t.verified) / len(ties), 3) if ties else None,
        "traceable_rate": round(sum(1 for e in crust_ev if e.call_id in call_ids) / len(crust_ev), 3) if crust_ev else None,
        "false_ties": sum(1 for t in ties for o in t.overlaps if is_generic_employer(o.company_name)),
        "unsupported": sum(len(d.claims_unsupported) for d in r.drafts),
        "credits": r.credits_used, "seconds": round(time.time() - t0, 1), "api_calls": len(r.audit),
        "cache_rate": round(sum(1 for a in r.audit if a.cached) / len(r.audit), 2) if r.audit else None,
        "llm_calls": (llm.calls_used() if hasattr(llm, "calls_used") else 0) - llm_before,
        "group": sc.group,
        "target_id": tgt.person_id if tgt else None,       # ids only (no names) are stored in history
        "top_score": max((p.score for p in r.paths), default=None),
        "seed_path": any(getattr(p, "via_seed", False) for p in r.paths),
        "recalled": _recalled(events),
        "fresh": _fresh(tgt),
        "explained": all(p.why and all(t.factors for t in p.ties) for p in r.paths) if r.paths else None,
    }
    budget_ok = (m["credits"] <= x.get("max_credits", 1e9)) and (m["seconds"] <= x.get("max_seconds", 1e9))
    m["correct"] = (m["completed"] and not m["silent_failure"] and all(checks.values()) and m["false_ties"] == 0
                    and m["unsupported"] == 0 and budget_ok
                    and (m["citation_cov"] in (None, 1.0)) and (m["verified_rate"] in (None, 1.0)))
    return m


def _recalled(events: list[dict]) -> float | None:
    """Share of connectors that came from graph memory (0 credits) rather than a fresh search."""
    for e in events:
        if e.get("type") == "step" and e.get("id") == "discover" and e.get("status") == "done":
            total = re.search(r"(\d+) candidate connectors", e.get("label", ""))
            rec = re.search(r"(\d+) recalled", e.get("detail", ""))
            if total and rec and int(total.group(1)):
                return round(int(rec.group(1)) / int(total.group(1)), 3)
    return None


def _fresh(tgt) -> bool | None:
    from warmpath.crust import parse_date
    d = parse_date(getattr(tgt, "last_updated", None)) if tgt else None
    return None if not d else (datetime.now().date() - d).days <= 120


def _p95(vals: list[float]) -> float | None:
    vals = sorted(v for v in vals if v is not None)
    return vals[min(len(vals) - 1, int(round(0.95 * (len(vals) - 1))))] if vals else None


def _consistency(rows: list[dict]) -> float | None:
    groups: dict[str, set] = {}
    for r in rows:
        if r.get("group"):
            groups.setdefault(r["group"], set()).add(r.get("target_id"))
    return round(sum(len(v) == 1 and None not in v for v in groups.values()) / len(groups), 3) if groups else None


def _cofounder() -> dict | None:
    f = OUT / "results.json"
    try:
        return json.loads(f.read_text())["summary"]["WarmPath"]
    except Exception:
        return None


def summarize(rows: list[dict]) -> dict:
    def avg(key, rs):
        vals = [r[key] for r in rs if r.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None
    cats: dict[str, dict] = {}
    for cat in dict.fromkeys(r["category"] for r in rows):
        rs = [r for r in rows if r["category"] == cat]
        cats[cat] = {"n": len(rs), "pass_rate": round(sum(r["correct"] for r in rs) / len(rs), 3)}
    return {
        "n": len(rows), "pass_rate": round(sum(r["correct"] for r in rows) / len(rows), 3),
        "completion_rate": round(sum(r["completed"] for r in rows) / len(rows), 3),
        "silent_failures": sum(r.get("silent_failure", False) for r in rows),
        "crashes": sum(1 for r in rows if r.get("crash")),
        "false_ties": sum(r.get("false_ties", 0) for r in rows),
        "unsupported_claims": sum(r.get("unsupported", 0) for r in rows),
        "citation_cov": avg("citation_cov", rows), "verified_rate": avg("verified_rate", rows),
        "traceable_rate": avg("traceable_rate", rows),
        "avg_seconds": avg("seconds", rows), "total_credits": round(sum(r.get("credits", 0) or 0 for r in rows), 2),
        "llm_calls": sum(r.get("llm_calls", 0) for r in rows), "by_category": cats,
        # ---- product-impact metrics
        "paraphrase_consistency": _consistency(rows),
        "path_found_rate": (lambda rs: round(sum(r["paths"] > 0 for r in rs) / len(rs), 3) if rs else None)(
            [r for r in rows if r.get("target_id")]),
        "warm_path_rate": (lambda rs: round(sum(r["seed_path"] for r in rs) / len(rs), 3) if rs else None)(
            [r for r in rows if r.get("target_id") and r["world"] == "live"]),
        "median_top_score": (lambda v: sorted(v)[len(v) // 2] if v else None)(
            [r["top_score"] for r in rows if r.get("top_score") is not None]),
        "p95_seconds": _p95([r.get("seconds") for r in rows]),
        "cost_per_verified_path": (lambda n: round(sum(r.get("credits", 0) or 0 for r in rows if r["world"] == "live") / n, 2)
                                   if n else None)(sum(r.get("paths", 0) for r in rows if r["world"] == "live")),
        "graph_recall": avg("recalled", rows),
        "target_freshness": (lambda v: round(sum(v) / len(v), 3) if v else None)(
            [r["fresh"] for r in rows if r.get("fresh") is not None]),
        "explained_rate": (lambda v: round(sum(v) / len(v), 3) if v else None)(
            [r["explained"] for r in rows if r.get("explained") is not None]),
        "cofounder_hit@1": (_cofounder() or {}).get("hit@1"),
        "cofounder_hit@3": (_cofounder() or {}).get("hit@3"),
    }


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "?"


def write_scorecard(rows: list[dict], summary: dict, prev: dict | None, label: str) -> None:
    def delta(key):
        if not prev or prev.get(key) is None or summary.get(key) is None:
            return ""
        d = summary[key] - prev[key]
        return "" if abs(d) < 1e-9 else f" ({'+' if d > 0 else ''}{round(d, 3)})"
    pct = lambda v: "n/a" if v is None else f"{v * 100:.0f}%"
    lines = [f"# WarmPath eval scorecard", "",
             f"Run `{label}` · commit `{git_sha()}` · {datetime.now():%Y-%m-%d %H:%M} · `uv run python -m eval.run_eval`", "",
             "| Metric | Value | Target |", "|---|---|---|",
             f"| Scenarios passing | **{pct(summary['pass_rate'])}** of {summary['n']}{delta('pass_rate')} | 100% |",
             f"| Runs completed cleanly (one `done`, no error) | {pct(summary['completion_rate'])}{delta('completion_rate')} | 100% |",
             f"| Silent failures / crashes | {summary['silent_failures']} / {summary['crashes']} | 0 / 0 |",
             f"| Ties on placeholder employers (false ties) | {summary['false_ties']} | 0 |",
             f"| Unsupported claims in drafts | {summary['unsupported_claims']} | 0 |",
             f"| Factors carrying evidence (citation coverage) | {pct(summary['citation_cov'])} | 100% |",
             f"| Ties re-verified against full profiles | {pct(summary['verified_rate'])} | 100% |",
             f"| Crustdata evidence traceable to an audit call | {pct(summary['traceable_rate'])} | 100% |",
             f"| Avg seconds per request | {summary['avg_seconds']}{delta('avg_seconds')} | < 30 |",
             f"| Credits spent this eval run | {summary['total_credits']} | |", "",
             "## Product-impact metrics", "", "| Metric | Value | Why it matters |", "|---|---|---|",
             f"| Paraphrase consistency (rewordings → same person) | {pct(summary['paraphrase_consistency'])}{delta('paraphrase_consistency')} | decisions must not depend on wording |",
             f"| Requests with ≥1 intro path | {pct(summary['path_found_rate'])}{delta('path_found_rate')} | the job got done |",
             f"| Live requests with a path through *our own* team | {pct(summary['warm_path_rate'])}{delta('warm_path_rate')} | actionable today, the core value |",
             f"| Median strength of the best path | {summary['median_top_score']} | ranking quality |",
             f"| Co-founder ranked #1 / top-3 (ground-truth eval) | {pct(summary['cofounder_hit@1'])} / {pct(summary['cofounder_hit@3'])} | tie model is right (random: 9% / 25%) |",
             f"| Credits per verified path (live) | {summary['cost_per_verified_path']} | would a business pay for this |",
             f"| p95 seconds per request | {summary['p95_seconds']} | feels fast |",
             f"| Connectors recalled from graph memory | {pct(summary['graph_recall'])} | the graph gets cheaper and better |",
             f"| Targets refreshed ≤120 days ago | {pct(summary['target_freshness'])} | stale profile = dead intro |",
             f"| Paths with a stated reason on every hop | {pct(summary['explained_rate'])} | every decision shows its reasons |", "",
             "## By edge-case category", "", "| Category | Scenarios | Pass rate |", "|---|---|---|"]
    lines += [f"| {c} | {v['n']} | {pct(v['pass_rate'])} |" for c, v in summary["by_category"].items()]
    lines += ["", "## Scenarios", "", "| ID | World | Category | Request | Pass | Failed checks | Paths | Cite | Verified | s | Credits |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        failed = ", ".join(k for k, v in (r.get("checks") or {}).items() if not v) or r.get("crash", "") or (
            "" if r["correct"] else "quality gate")
        q = r["query"].replace("|", "/").replace("\n", " ")[:48] or "(empty)"
        lines.append(f"| {r['id']} | {r['world']} | {r['category']} | `{q}` | {'✅' if r['correct'] else '❌'} | "
                     f"{failed} | {r.get('paths', '')} | {pct(r.get('citation_cov'))} | {pct(r.get('verified_rate'))} | "
                     f"{r.get('seconds', '')} | {r.get('credits', '')} |")
    SCORECARD.write_text("\n".join(lines) + "\n")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true", help="offline scenarios only")
    ap.add_argument("--live", action="store_true", help="live scenarios only")
    ap.add_argument("--llm", action="store_true", help="keep the free LLM on (default off for determinism)")
    ap.add_argument("--only", help="comma-separated scenario ids")
    a = ap.parse_args()
    if not a.llm:
        os.environ["WARMPATH_LLM"] = "0"
    picks = [s for s in SCENARIOS if (not a.fake or s.world == "fake") and (not a.live or s.world == "live")
             and (not a.only or s.id in a.only.split(","))]
    if any(s.world == "live" for s in picks) and not os.getenv("CRUSTDATA_API_KEY"):
        print("no CRUSTDATA_API_KEY: skipping live scenarios")
        picks = [s for s in picks if s.world == "fake"]
    (OUT / ".fake_graph.db").unlink(missing_ok=True)
    rows = []
    for sc in picks:
        row = await run_one(sc)
        rows.append(row)
        failed = [k for k, v in (row.get("checks") or {}).items() if not v]
        print(f"{'PASS' if row['correct'] else 'FAIL'} {sc.id} {sc.world:4} {sc.category:13} {row.get('seconds', 0):5}s "
              f"{row.get('credits', 0):>6} cr  {sc.query[:50]!r} {failed or row.get('crash', '')}")
    summary = summarize(rows)
    label = "fake" if a.fake else "live" if a.live else "all"
    label += "+llm" if a.llm else ""
    prev = None
    if HISTORY.exists():
        for line in HISTORY.read_text().splitlines():
            h = json.loads(line)
            if h.get("label") == label:
                prev = h["summary"]
    with HISTORY.open("a") as fh:
        fh.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), "sha": git_sha(), "label": label,
                             "summary": summary}) + "\n")
    write_scorecard(rows, summary, prev, label)
    print(json.dumps({k: v for k, v in summary.items() if k != "by_category"}, indent=1))
    print(f"scorecard → {SCORECARD}")


if __name__ == "__main__":
    asyncio.run(main())
