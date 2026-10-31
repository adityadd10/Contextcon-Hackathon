"""Product workspace around the pipeline: run history, the human review inbox, briefs, and deploy guardrails.

Everything reads the files the pipeline already writes (reports/<run_id>.json), so nothing here changes how runs work.

- history    every past run, reopenable instantly for 0 credits
- inbox      drafts across runs as a review queue: edit → approve / reject. Nothing is ever sent; an approved draft is
             written to outbox/<run_id>-pathN.approved.md for a person to send themselves.
- brief      a run as a shareable, fully cited Markdown document
- guardrails optional access key, per-client rate limit and a daily credit cap for a public deployment

Owner: Member C.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import defaultdict, deque
from datetime import date, datetime
from pathlib import Path

REPORTS = Path("reports")
OUTBOX = Path("outbox")
REVIEW_DB = Path("data/review.json")
RUN_ID = re.compile(r"^[\w-]{1,40}$")
STATUSES = ("review", "approved", "rejected")
MAX_DRAFT_CHARS = 5000

_lock = threading.Lock()


# ------------------------------------------------------------------ history

def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # half-written or corrupt report: skip it, never crash the listing


def report(run_id: str) -> dict | None:
    if not RUN_ID.match(run_id or ""):
        return None
    p = REPORTS / f"{run_id}.json"
    return _load(p) if p.is_file() else None


def history(limit: int = 50) -> list[dict]:
    """Newest first: one compact row per past run."""
    if not REPORTS.is_dir():
        return []
    files = sorted(REPORTS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    rows = []
    for p in files[: limit * 2]:
        r = _load(p)
        if not r or not isinstance(r, dict):
            continue
        t, paths = r.get("target") or {}, r.get("paths") or []
        rows.append({"run_id": p.stem, "request": r.get("request", ""), "ts": p.stat().st_mtime,
                     "target": t.get("name"), "title": t.get("current_title"),
                     "company": (r.get("target_company") or {}).get("name"),
                     "paths": len(paths), "best": round(paths[0]["score"]) if paths else None,
                     "credits": r.get("credits_used", 0), "elapsed": r.get("elapsed_s", 0),
                     "drafts": len(r.get("drafts") or [])})
        if len(rows) >= limit:
            break
    return rows


def latest_run_id(request: str, since: float) -> str | None:
    """The report the pipeline just wrote for this request (it writes the file, then emits `done`)."""
    if not REPORTS.is_dir():
        return None
    for p in sorted(REPORTS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        if p.stat().st_mtime + 1 < since:
            break
        r = _load(p)
        if r and r.get("request") == request:
            return p.stem
    return None


# ------------------------------------------------------------------ review inbox

def _reviews() -> dict:
    try:
        return json.loads(REVIEW_DB.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_reviews(db: dict) -> None:
    REVIEW_DB.parent.mkdir(parents=True, exist_ok=True)
    tmp = REVIEW_DB.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, indent=1), encoding="utf-8")
    tmp.replace(REVIEW_DB)  # atomic: a crash mid-write never corrupts the inbox


def inbox(limit_runs: int = 50) -> list[dict]:
    """Every draft from recent runs, with its review state (default: waiting for review)."""
    db, items = _reviews(), []
    for h in history(limit_runs):
        r = report(h["run_id"]) or {}
        for d in r.get("drafts") or []:
            key = f"{h['run_id']}:{d.get('path_rank')}"
            rv = db.get(key, {})
            items.append({"key": key, "run_id": h["run_id"], "request": h["request"], "target": h["target"],
                          "ts": h["ts"], "to": d.get("to"), "subject": d.get("subject"),
                          "body": rv.get("body", d.get("body", "")),
                          "forwardable_blurb": rv.get("forwardable_blurb", d.get("forwardable_blurb", "")),
                          "edited": "body" in rv or "forwardable_blurb" in rv,
                          "claims_checked": d.get("claims_checked", 0),
                          "claims_unsupported": d.get("claims_unsupported") or [],
                          "status": rv.get("status", "review"), "updated": rv.get("updated")})
    return items


def review(key: str, status: str | None = None, body: str | None = None, blurb: str | None = None) -> dict:
    """Update one draft's review state / text. Approving writes the final text to outbox/ (never sends it)."""
    run_id, _, rank = (key or "").partition(":")
    r = report(run_id)
    draft = next((d for d in (r or {}).get("drafts") or [] if str(d.get("path_rank")) == rank), None)
    if not draft:
        raise KeyError("draft not found")
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    for name, text in (("body", body), ("forwardable_blurb", blurb)):
        if text is not None and len(text) > MAX_DRAFT_CHARS:
            raise ValueError(f"{name} is longer than {MAX_DRAFT_CHARS} characters")
    with _lock:
        db = _reviews()
        rv = db.setdefault(key, {})
        if body is not None:
            rv["body"] = body.strip()
        if blurb is not None:
            rv["forwardable_blurb"] = blurb.strip()
        if status is not None:
            rv["status"] = status
        rv["updated"] = time.time()
        _save_reviews(db)
    final_body = rv.get("body", draft.get("body", ""))
    final_blurb = rv.get("forwardable_blurb", draft.get("forwardable_blurb", ""))
    approved = OUTBOX / f"{run_id}-path{rank}.approved.md"
    if rv.get("status") == "approved":
        OUTBOX.mkdir(exist_ok=True)
        approved.write_text(f"# {draft.get('subject', '')}\n\n**To:** {draft.get('to', '')} "
                            f"(approved {datetime.now():%Y-%m-%d %H:%M}, not sent: send it yourself)\n\n"
                            f"{final_body}\n\n---\n> {final_blurb}\n", encoding="utf-8")
    elif approved.exists():
        approved.unlink()
    return {"key": key, "status": rv.get("status", "review"), "body": final_body,
            "forwardable_blurb": final_blurb, "updated": rv["updated"]}


# ------------------------------------------------------------------ shareable brief

def brief_markdown(run_id: str) -> str | None:
    """One run as a shareable document: the answer, every route, every factor with its source."""
    r = report(run_id)
    if not r:
        return None
    t, co = r.get("target") or {}, r.get("target_company") or {}
    out = [f"# Warm intro brief: {t.get('name') or 'unresolved target'}", "",
           f"> Request: \"{r.get('request', '')}\"", ""]
    if t:
        role = ", ".join(x for x in (t.get("current_title"), co.get("name")) if x)
        out += [f"**Target:** {t.get('name')}" + (f" ({role})" if role else "")
                + (f" · {t['profile_url']}" if t.get("profile_url") else ""), ""]
    paths = r.get("paths") or []
    if not paths:
        out += ["No warm route was found for this request.", ""]
    for p in paths:
        chain = " → ".join(n.get("name", "?") for n in p.get("nodes") or [])
        tag = "your network" if p.get("via_seed") else "other connector"
        out += [f"## Route {p.get('rank')}: {chain}", "",
                f"Strength **{round(p.get('score', 0))}/100** · {tag} · {p.get('why', '')}", ""]
        for tie in p.get("ties") or []:
            a, b = (tie.get("a") or {}).get("name"), (tie.get("b") or {}).get("name")
            ver = f" · verified: {tie['verification']}" if tie.get("verified") and tie.get("verification") else ""
            out.append(f"**{a} ↔ {b}**: {round(tie.get('score', 0))}/100{ver}")
            for f in tie.get("factors") or []:
                srcs = "; ".join(f"{e.get('endpoint')} `{e.get('ref')}`" + (f" {e['url']}" if e.get("url") else "")
                                 + (f" (audit {e['call_id']})" if e.get("call_id") else "")
                                 for e in f.get("evidence") or [])
                out.append(f"- +{round(f.get('contribution', 0))} {f.get('explanation')}" + (f"  \n  Sources: {srcs}" if srcs else ""))
            out.append("")
    db = _reviews()
    for d in r.get("drafts") or []:
        rv = db.get(f"{run_id}:{d.get('path_rank')}", {})
        out += [f"## Draft for {d.get('to')} (route {d.get('path_rank')}, {rv.get('status', 'awaiting review')})", "",
                f"**Subject:** {d.get('subject')}", "", rv.get("body", d.get("body", "")), "",
                f"> {rv.get('forwardable_blurb', d.get('forwardable_blurb', ''))}", ""]
    audit = r.get("audit") or []
    out += ["## Audit trail", "", f"{len(audit)} Crustdata calls · {r.get('credits_used', 0)} credits · "
            f"{r.get('elapsed_s', 0)} s", "", "| call | endpoint | status | credits | response sha256 |", "|---|---|---|---|---|"]
    out += [f"| {c.get('call_id')} | {c.get('endpoint')} | {c.get('status')} | {c.get('credits')} | `{(c.get('sha256') or '')[:16]}` |"
            for c in audit]
    out += ["", "_Generated by WarmPath. Nothing was sent to anyone._", ""]
    return "\n".join(out)


# ------------------------------------------------------------------ deploy guardrails

class Guard:
    """Optional limits for a public deployment, all off by default (env vars):

    WARMPATH_ACCESS_KEY     require this key (cookie set by visiting /?key=..., or header x-warmpath-key)
    WARMPATH_RATE_PER_HOUR  paid runs per client per hour (default 30)
    WARMPATH_DAILY_CREDITS  stop paid runs once this many credits were spent today (default 0 = no cap)
    """

    def __init__(self) -> None:
        self.key = os.getenv("WARMPATH_ACCESS_KEY", "")
        self.rate = int(os.getenv("WARMPATH_RATE_PER_HOUR", "30") or 0)
        self.daily = float(os.getenv("WARMPATH_DAILY_CREDITS", "0") or 0)
        self.hits: dict[str, deque] = defaultdict(deque)
        self.spent: dict[str, float] = defaultdict(float)
        self._lock = threading.Lock()

    def allowed_key(self, supplied: str | None) -> bool:
        return not self.key or (supplied or "") == self.key

    def check_paid(self, client: str) -> str | None:
        """None if this client may start a paid run now, else a human reason."""
        today = date.today().isoformat()
        if self.daily and self.spent[today] >= self.daily:
            return (f"Today's credit cap ({self.daily:g}) is used up. Use 'Recorded demo' or past searches, "
                    "which are free, or raise WARMPATH_DAILY_CREDITS.")
        if self.rate:
            now, q = time.time(), self.hits[client]
            with self._lock:
                while q and now - q[0] > 3600:
                    q.popleft()
                if len(q) >= self.rate:
                    wait = int(3600 - (now - q[0])) // 60 + 1
                    return f"Too many searches from this connection. Try again in about {wait} min."
                q.append(now)
        return None

    def record(self, credits: float) -> None:
        with self._lock:
            self.spent[date.today().isoformat()] += float(credits or 0)

    def status(self) -> dict:
        return {"access_key": bool(self.key), "rate_per_hour": self.rate, "daily_credit_cap": self.daily,
                "spent_today": round(self.spent[date.today().isoformat()], 2)}
