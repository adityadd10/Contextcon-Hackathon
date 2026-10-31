"""WarmPath social graph: an embedded, persistent property graph (SQLite) + graph algorithms (networkx).

Nodes   person:<crustdata_person_id> · company:<crustdata_company_id> · school:<normalised name>
Edges   WORKED_AT  (person → company)   props: title, start, end, is_current, function
        STUDIED_AT (person → school)    props: degree, field, start, end
        KNOWS      (person ↔ person)    weight = tie score 0-100, props: factors + overlaps, evidence: citations

Every node/edge keeps provenance (source endpoint + record ref) so any relationship can be audited.
KNOWS edges are *derived*: whenever a person is ingested, they're scored against everyone already in the graph
who shares a canonical company_id (or a school), so the graph densifies on its own as runs and crawls add people.

Owner: Member A.
"""
from __future__ import annotations

import json
import os
import math
import re
import sqlite3
import time
from pathlib import Path

import networkx as nx

from .crust import is_generic_employer, parse_date
from .models import Company, Person, School, Stint, Tie, to_dict
from .score import score_tie

# fake mode gets its own graph so offline demo data never mixes with real people (and vice versa)
DB_PATH = Path("data/graph.fake.db" if os.getenv("WARMPATH_FAKE") == "1" else "data/graph.db")
MIN_TIE = 25.0
MAX_CANDIDATES = 600  # cap per company/school when deriving KNOWS edges

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY, type TEXT NOT NULL, label TEXT, props TEXT,
  first_seen REAL, last_seen REAL, source TEXT
);
CREATE TABLE IF NOT EXISTS edges (
  src TEXT NOT NULL, dst TEXT NOT NULL, type TEXT NOT NULL, key TEXT NOT NULL DEFAULT '',
  weight REAL, props TEXT, evidence TEXT, updated REAL,
  PRIMARY KEY (src, dst, type, key)
);
CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst, type);
CREATE INDEX IF NOT EXISTS edges_type ON edges(type, src);
CREATE INDEX IF NOT EXISTS nodes_type ON nodes(type);
"""


def person_node(pid: int | None) -> str:
    return f"person:{pid}"


def company_node(s: Stint | Company) -> str:
    cid = s.company_id
    name = s.company_name if isinstance(s, Stint) else s.name
    return f"company:{cid}" if cid else f"company:name:{_norm(name)}"


def school_node(name: str) -> str:
    return f"school:{_norm(name)}"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def person_from_dict(d: dict) -> Person:
    """Rehydrate a Person stored as JSON (inverse of models.to_dict)."""
    stints = [Stint(**{**s, "start": parse_date(s.get("start")), "end": parse_date(s.get("end"))})
              for s in d.get("stints") or [] if not is_generic_employer(s.get("company_name"))]
    schools = [School(**{**s, "start": parse_date(s.get("start")), "end": parse_date(s.get("end"))})
               for s in d.get("schools") or []]
    return Person(**{**d, "stints": stints, "schools": schools})


class GraphStore:
    def __init__(self, path: Path | str = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # WAL + busy timeout: the server may run a crawl and a request at the same time
        self.db = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        try:
            self.db.commit()
        finally:
            self.db.close()

    # ------------------------------------------------------------ writes

    def _upsert_node(self, nid: str, type_: str, label: str, props: dict, source: str) -> bool:
        now = time.time()
        cur = self.db.execute("SELECT props FROM nodes WHERE id = ?", (nid,)).fetchone()
        if cur:
            merged = {**json.loads(cur["props"] or "{}"), **{k: v for k, v in props.items() if v not in (None, [], "")}}
            self.db.execute("UPDATE nodes SET label=?, props=?, last_seen=?, source=? WHERE id=?",
                            (label, json.dumps(merged, default=str), now, source, nid))
            return False
        self.db.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?)",
                        (nid, type_, label, json.dumps(props, default=str), now, now, source))
        return True

    def _upsert_edge(self, src: str, dst: str, type_: str, key: str = "", weight: float | None = None,
                     props: dict | None = None, evidence: list | None = None) -> None:
        self.db.execute(
            "INSERT INTO edges VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(src,dst,type,key) DO UPDATE SET "
            "weight=excluded.weight, props=excluded.props, evidence=excluded.evidence, updated=excluded.updated",
            (src, dst, type_, key, weight, json.dumps(props or {}, default=str),
             json.dumps(evidence or [], default=str), time.time()))

    def upsert_company(self, co: Company) -> None:
        self._upsert_node(company_node(co), "company", co.name, to_dict(co), "/company/identify")
        self.db.commit()

    def upsert_person(self, p: Person, derive_ties: bool = True) -> dict:
        """Add/refresh a person, their employers and schools; derive KNOWS edges. Returns counts."""
        if not p.person_id:
            return {"new": False, "ties": 0}
        pid = person_node(p.person_id)
        # keep the richest version (enrich beats search) when merging
        old = self.person(p.person_id)
        if old and len(old.stints) > len(p.stints) and not p.source_endpoint.endswith("enrich"):
            p = old
        is_new = self._upsert_node(pid, "person", p.name, to_dict(p), p.source_endpoint)
        for s in p.stints:
            cn = company_node(s)
            self._upsert_node(cn, "company", s.company_name,
                              {"company_id": s.company_id, "headcount": s.company_headcount}, p.source_endpoint)
            self._upsert_edge(pid, cn, "WORKED_AT", key=f"{s.title}|{s.start}",
                              props={"title": s.title, "start": s.start, "end": s.end, "is_current": s.is_current,
                                     "function": s.function, "ref": s.ref})
        for sc in p.schools:
            sn = school_node(sc.name)
            self._upsert_node(sn, "school", sc.name, {}, p.source_endpoint)
            self._upsert_edge(pid, sn, "STUDIED_AT", key=f"{sc.degree}|{sc.start}",
                              props={"degree": sc.degree, "field": sc.field_of_study, "start": sc.start,
                                     "end": sc.end, "ref": sc.ref})
        ties = self._derive_ties(p) if derive_ties else 0
        self.db.commit()
        return {"new": is_new, "ties": ties}

    def upsert_tie(self, t: Tie) -> None:
        a, b = sorted([person_node(t.a.person_id), person_node(t.b.person_id)])
        self._upsert_edge(a, b, "KNOWS", weight=t.score,
                          props={"kind": t.kind, "overlaps": to_dict(t.overlaps),
                                 "factors": [{"name": f.name, "contribution": f.contribution,
                                              "explanation": f.explanation} for f in t.factors]},
                          evidence=[to_dict(e) for f in t.factors for e in f.evidence])
        self.db.commit()

    def _derive_ties(self, p: Person) -> int:
        me = person_node(p.person_id)
        hubs = [company_node(s) for s in p.stints] + [school_node(s.name) for s in p.schools]
        if not hubs:
            return 0
        qs = ",".join("?" * len(hubs))
        rows = self.db.execute(
            f"SELECT DISTINCT e.src FROM edges e WHERE e.type IN ('WORKED_AT','STUDIED_AT') "
            f"AND e.dst IN ({qs}) AND e.src != ? LIMIT {MAX_CANDIDATES}", (*hubs, me)).fetchall()
        n = 0
        for r in rows:
            other = self.person(int(r["src"].split(":")[1]))
            if not other:
                continue
            t = score_tie(p, other)
            if t.score >= MIN_TIE:
                self.upsert_tie(t)
                n += 1
        return n

    # ------------------------------------------------------------ reads

    def person(self, person_id: int | None) -> Person | None:
        row = self.db.execute("SELECT props FROM nodes WHERE id = ?", (person_node(person_id),)).fetchone()
        return person_from_dict(json.loads(row["props"])) if row else None

    def people_at(self, company_ids: list[int]) -> list[Person]:
        """Everyone in the graph who ever worked at any of these canonical companies."""
        if not company_ids:
            return []
        hubs = [f"company:{c}" for c in company_ids]
        rows = self.db.execute(
            f"SELECT DISTINCT src FROM edges WHERE type='WORKED_AT' AND dst IN ({','.join('?' * len(hubs))})",
            hubs).fetchall()
        return [p for r in rows if (p := self.person(int(r["src"].split(":")[1])))]

    def knows(self, person_id: int, min_weight: float = MIN_TIE) -> list[tuple[Person, float, dict]]:
        me = person_node(person_id)
        rows = self.db.execute(
            "SELECT src, dst, weight, props FROM edges WHERE type='KNOWS' AND (src=? OR dst=?) AND weight >= ? "
            "ORDER BY weight DESC", (me, me, min_weight)).fetchall()
        out = []
        for r in rows:
            other = r["dst"] if r["src"] == me else r["src"]
            if p := self.person(int(other.split(":")[1])):
                out.append((p, r["weight"], json.loads(r["props"])))
        return out

    def stats(self) -> dict:
        nodes = dict(self.db.execute("SELECT type, COUNT(*) FROM nodes GROUP BY type").fetchall())
        edges = dict(self.db.execute("SELECT type, COUNT(*) FROM edges GROUP BY type").fetchall())
        return {"nodes": nodes, "edges": edges,
                "people": nodes.get("person", 0), "relationships": edges.get("KNOWS", 0)}

    # ------------------------------------------------------------ algorithms

    def social_graph(self, min_weight: float = MIN_TIE) -> nx.Graph:
        """People-only graph; edge cost = -ln(score/100), so the cheapest path is the strongest chain."""
        g = nx.Graph()
        for r in self.db.execute("SELECT id, label FROM nodes WHERE type='person'"):
            g.add_node(r["id"], label=r["label"])
        for r in self.db.execute("SELECT src, dst, weight FROM edges WHERE type='KNOWS' AND weight >= ?",
                                 (min_weight,)):
            w = max(1.0, min(99.0, r["weight"]))
            g.add_edge(r["src"], r["dst"], weight=w, cost=-math.log(w / 100))
        return g

    def strongest_path(self, a_pid: int, b_pid: int, max_hops: int = 4) -> list[int] | None:
        g = self.social_graph()
        a, b = person_node(a_pid), person_node(b_pid)
        if a not in g or b not in g:
            return None
        try:
            path = nx.dijkstra_path(g, a, b, weight="cost")
        except nx.NetworkXNoPath:
            return None
        return [int(n.split(":")[1]) for n in path] if len(path) - 1 <= max_hops else None

    def degrees_of_separation(self, a_pid: int, b_pid: int) -> int | None:
        g = self.social_graph()
        try:
            return nx.shortest_path_length(g, person_node(a_pid), person_node(b_pid))
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def super_connectors(self, top: int = 10) -> list[dict]:
        """People who bridge the most clusters (betweenness), the best intro brokers in the graph."""
        g = self.social_graph()
        if g.number_of_edges() == 0:
            return []
        k = min(200, g.number_of_nodes())
        bc = nx.betweenness_centrality(g, k=k, weight="cost", seed=7)
        best = sorted(bc.items(), key=lambda kv: -kv[1])[:top]
        return [{"id": n, "name": g.nodes[n].get("label"), "betweenness": round(v, 4), "degree": g.degree(n)}
                for n, v in best]

    def communities(self, min_size: int = 3) -> list[list[str]]:
        g = self.social_graph()
        if g.number_of_edges() == 0:
            return []
        comms = nx.algorithms.community.greedy_modularity_communities(g, weight="weight")
        return [[g.nodes[n].get("label", n) for n in c] for c in comms if len(c) >= min_size]

    def subgraph(self, center: str | None = None, depth: int = 2, limit: int = 300) -> dict:
        """Nodes + edges (people, companies, schools) for the UI graph explorer."""
        if center:
            g = self.social_graph(min_weight=0)
            keep = set(nx.ego_graph(g, center, radius=depth).nodes) if center in g else {center}
        else:
            keep = {r["id"] for r in self.db.execute(
                "SELECT id FROM nodes WHERE type='person' ORDER BY last_seen DESC LIMIT ?", (limit,))}
        if not keep:
            return {"nodes": [], "edges": []}
        qs = ",".join("?" * len(keep))
        edges = [dict(r) for r in self.db.execute(
            f"SELECT src, dst, type, weight, props FROM edges WHERE src IN ({qs})", tuple(keep))]
        ids = keep | {e["dst"] for e in edges}
        nodes = [dict(r) for r in self.db.execute(
            f"SELECT id, type, label FROM nodes WHERE id IN ({','.join('?' * len(ids))})", tuple(ids))]
        for e in edges:
            e["props"] = json.loads(e["props"] or "{}")
        return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------ export

    def export_cypher(self, out: Path | str = "data/graph.cypher") -> Path:
        """Neo4j import script: `cat data/graph.cypher | cypher-shell`."""
        out = Path(out)
        lines = []
        for r in self.db.execute("SELECT id, type, label FROM nodes"):
            lines.append(f"MERGE (n:{r['type'].capitalize()} {{id: {json.dumps(r['id'])}}}) "
                         f"SET n.name = {json.dumps(r['label'])};")
        for r in self.db.execute("SELECT src, dst, type, weight FROM edges"):
            w = f" SET r.weight = {r['weight']}" if r["weight"] is not None else ""
            lines.append(f"MATCH (a {{id: {json.dumps(r['src'])}}}), (b {{id: {json.dumps(r['dst'])}}}) "
                         f"MERGE (a)-[r:{r['type']}]->(b){w};")
        out.write_text("\n".join(lines))
        return out
