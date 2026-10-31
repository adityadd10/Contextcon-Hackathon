"""CLI: uv run warmpath "warm intro to the head of data at Swiggy via IIT Bombay alumni".  Owner: Member C.

    warmpath "<request>"                      find warm paths (live steps, cited ties, drafts to outbox/)
    warmpath crawl --seeds <url>,<url> --depth 2 --budget 80
    warmpath graph stats | knows <id> | path <from> <to> | brokers | export
    warmpath serve [--port 8000]              web UI
    warmpath mcp                              MCP server (stdio)
"""
from __future__ import annotations

import asyncio
import os
import sys

from rich.console import Console

from .pipeline import run

console = Console()
ICON = {"start": "[cyan]…[/]", "progress": "[blue]·[/]", "done": "[green]✓[/]", "error": "[red]✗[/]"}


def show(e: dict) -> None:
    t = e["type"]
    if t == "step" and e["status"] == "progress":
        console.print(f"    [blue]·[/] {e['label']} [dim]{e.get('detail', '')}[/]")
    elif t == "step":
        console.print(f"{ICON.get(e['status'], '·')} [bold]{e['label']}[/] [dim]{e.get('detail', '')}[/]")
    elif t == "warning":
        console.print(f"[yellow]! {e['message']}[/]")
    elif t == "error":
        console.print(f"[red]ERROR {e['message']}[/]")
    elif t == "path":
        p = e["path"]
        chain = " → ".join(n["name"] for n in p["nodes"])
        console.print(f"\n[bold magenta]#{p['rank']}  {p['score']:.0f}/100[/]  {chain}\n   [dim]{p['why']}[/]")
        for tie in p["ties"]:
            for fct in tie["factors"]:
                cites = ", ".join(x["ref"] for x in fct["evidence"][:2])
                console.print(f"     +{fct['contribution']:>4} {fct['explanation']} [dim]{cites}[/]")
    elif t == "draft":
        d = e["draft"]
        bad = d.get("claims_unsupported") or []
        check = f"[red]{len(bad)} unsupported claim(s)[/]" if bad else f"[green]✓ {d['claims_checked']} claims cited[/]"
        console.print(f"  [bold]draft → {d['to']}[/] [dim]({d['subject']})[/] {check}")
    elif t == "done":
        r = e["result"]
        console.print(f"\n[dim]{len(r['audit'])} API calls · {r['credits_used']} credits · {r['elapsed_s']}s · "
                      f"report in reports/, drafts in outbox/[/]")


async def _crawl(args: list[str]) -> None:
    from .crawl import crawl
    from .crust import Crust
    from .graphdb import GraphStore
    opts = dict(zip(args[::2], args[1::2]))
    seeds = [u for u in (opts.get("--seeds") or os.getenv("WARMPATH_SEEDS", "")).split(",") if u.strip()]
    if not seeds:
        console.print("[red]give --seeds <profile_url>,<profile_url> or set WARMPATH_SEEDS[/]")
        return
    budget = float(opts.get("--budget", 80))
    async with Crust(budget=budget) as c:
        await crawl(c, GraphStore(), seeds, depth=int(opts.get("--depth", 1)), emit=show)


def _graph(args: list[str]) -> None:
    from .graphdb import GraphStore
    g = GraphStore()
    cmd = args[0] if args else "stats"
    if cmd == "stats":
        console.print_json(data=g.stats())
    elif cmd == "knows" and len(args) > 1:            # warmpath graph knows <person_id>
        for p, w, props in g.knows(int(args[1])):
            console.print(f"{w:5.1f}  {p.name} [dim]({p.person_id}) {props['factors'][0]['explanation'] if props.get('factors') else ''}[/]")
    elif cmd == "path" and len(args) > 2:             # warmpath graph path <from_id> <to_id>
        ids = g.strongest_path(int(args[1]), int(args[2]), max_hops=6)
        console.print(" → ".join(g.person(i).name for i in ids) if ids else "[yellow]no path in graph yet[/]")
    elif cmd == "brokers":
        for row in g.super_connectors():
            console.print(f"{row['betweenness']:.4f}  {row['name']}  [dim]degree {row['degree']}[/]")
    elif cmd == "export":
        console.print(f"wrote {g.export_cypher()} (Neo4j: cat data/graph.cypher | cypher-shell)")
    else:
        console.print("usage: warmpath graph stats | knows <id> | path <from> <to> | brokers | export")


def main() -> None:
    argv = sys.argv[1:]
    if argv[:1] == ["crawl"]:
        return asyncio.run(_crawl(argv[1:]))
    if argv[:1] == ["graph"]:
        return _graph(argv[1:])
    if argv[:1] == ["serve"]:
        import uvicorn
        opts = dict(zip(argv[1::2], argv[2::2]))
        return uvicorn.run("warmpath.server:app", host=opts.get("--host", "127.0.0.1"), port=int(opts.get("--port", 8000)))
    if argv[:1] == ["mcp"]:
        from .mcp_server import main as mcp_main
        return mcp_main()
    q = " ".join(argv) or input("Who do you want to reach? ")
    asyncio.run(run(q, show))


if __name__ == "__main__":
    main()
