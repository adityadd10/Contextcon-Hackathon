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
from rich.markup import escape

from .pipeline import run

console = Console()
ICON = {"start": "[cyan]…[/]", "progress": "[blue]·[/]", "done": "[green]✓[/]", "error": "[red]✗[/]"}


def show(e: dict) -> None:
    try:
        _show(e)
    except (KeyError, TypeError, ValueError) as err:  # a malformed event must never kill a run
        console.print(f"[dim]· (unrenderable {e.get('type', '?')} event: {err})[/]")


def _show(e: dict) -> None:
    t = e.get("type")
    x = lambda v: escape(str(v if v is not None else ""))  # Crustdata text is data, never rich markup
    if t == "step" and e["status"] == "progress":
        console.print(f"    [blue]·[/] {x(e['label'])} [dim]{x(e.get('detail'))}[/]")
    elif t == "step":
        console.print(f"{ICON.get(e['status'], '·')} [bold]{x(e['label'])}[/] [dim]{x(e.get('detail'))}[/]")
    elif t == "warning":
        console.print(f"[yellow]! {x(e['message'])}[/]")
    elif t == "error":
        console.print(f"[red]ERROR {x(e['message'])}[/]")
    elif t == "path":
        p = e["path"]
        chain = " → ".join(x(n.get("name") or "?") for n in p.get("nodes") or [])
        verified = p.get("ties") and all(tie.get("verified") for tie in p["ties"])
        console.print(f"\n[bold magenta]#{x(p.get('rank'))}  {float(p.get('score') or 0):.0f}/100[/]  {chain}"
                      f"{'  [green]✓ verified[/]' if verified else ''}\n   [dim]{x(p.get('why'))}[/]")
        for tie in p.get("ties") or []:
            for fct in tie.get("factors") or []:
                cites = ", ".join(x(ev.get("ref")) for ev in (fct.get("evidence") or [])[:2])
                console.print(f"     +{float(fct.get('contribution') or 0):>4.1f} {x(fct.get('explanation'))} [dim]{cites}[/]")
    elif t == "draft":
        d = e["draft"]
        bad = d.get("claims_unsupported") or []
        check = f"[red]{len(bad)} unsupported claim(s)[/]" if bad else f"[green]✓ {x(d.get('claims_checked', 0))} claims cited[/]"
        console.print(f"  [bold]draft → {x(d.get('to'))}[/] [dim]({x(d.get('subject'))})[/] {check}")
    elif t == "done":
        r = e["result"]
        console.print(f"\n[dim]{len(r.get('audit') or [])} API calls · {x(r.get('credits_used'))} credits · "
                      f"{x(r.get('elapsed_s'))}s · report in reports/, drafts in outbox/[/]")


def _opts(args: list[str]) -> dict[str, str]:
    """--key value pairs; a flag without a value raises a readable error."""
    out: dict[str, str] = {}
    it = iter(args)
    for k in it:
        if not k.startswith("--"):
            raise ValueError(f"unexpected argument {k!r}")
        v = next(it, None)
        if v is None or v.startswith("--"):
            raise ValueError(f"{k} needs a value")
        out[k] = v
    return out


def _num(opts: dict, key: str, default: float, lo: float, hi: float, cast=float):
    raw = opts.get(key, default)
    try:
        v = cast(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number, got {raw!r}")
    return max(lo, min(hi, v))


def _pid(raw: str) -> int:
    try:
        return int(raw.removeprefix("person:"))
    except ValueError:
        raise ValueError(f"expected a crustdata_person_id (a number), got {raw!r}")


async def _crawl(args: list[str]) -> None:
    from .crawl import crawl
    from .crust import Crust
    from .graphdb import GraphStore
    from .server import parse_seeds
    opts = _opts(args)
    seeds, rejected = parse_seeds(opts.get("--seeds") or os.getenv("WARMPATH_SEEDS", ""))
    for u in rejected:
        console.print(f"[yellow]! skipped, not a profile URL: {u}[/]")
    if not seeds:
        raise ValueError("give --seeds <profile_url>,<profile_url> or set WARMPATH_SEEDS")
    budget = _num(opts, "--budget", 80, 1, 500)
    depth = _num(opts, "--depth", 1, 1, 3, int)
    g = GraphStore()
    try:
        async with Crust(budget=budget) as c:
            await crawl(c, g, seeds, depth=depth, emit=show)
    finally:
        g.close()


def _graph(args: list[str]) -> None:
    from .graphdb import GraphStore
    g = GraphStore()
    try:
        cmd = args[0] if args else "stats"
        if cmd == "stats":
            console.print_json(data=g.stats())
        elif cmd == "knows" and len(args) > 1:            # warmpath graph knows <person_id>
            rows = g.knows(_pid(args[1]))
            if not rows:
                console.print("[yellow]no relationships for that person in the graph yet[/]")
            for p, w, props in rows:
                console.print(f"{w:5.1f}  {p.name} [dim]({p.person_id}) {props['factors'][0]['explanation'] if props.get('factors') else ''}[/]")
        elif cmd == "path" and len(args) > 2:             # warmpath graph path <from_id> <to_id>
            a, b = _pid(args[1]), _pid(args[2])
            ids = g.strongest_path(a, b, max_hops=6) if a != b else None
            names = [(g.person(i).name if g.person(i) else f"#{i}") for i in ids or []]
            console.print(" → ".join(names) if len(names) > 1 else "[yellow]no path in graph yet[/]")
        elif cmd == "brokers":
            rows = g.super_connectors()
            if not rows:
                console.print("[yellow]no relationships yet: run a request or a crawl first[/]")
            for row in rows:
                console.print(f"{row['betweenness']:.4f}  {row['name']}  [dim]degree {row['degree']}[/]")
        elif cmd == "export":
            console.print(f"wrote {g.export_cypher()} (Neo4j: cat data/graph.cypher | cypher-shell)")
        else:
            console.print("usage: warmpath graph stats | knows <id> | path <from> <to> | brokers | export")
    finally:
        g.close()


def _ask() -> str:
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return input("Who do you want to reach? ")


def _run(argv: list[str]) -> int:
    if argv[:1] in (["-h"], ["--help"], ["help"]):
        console.print(__doc__)
        return 0
    if argv[:1] == ["crawl"]:
        asyncio.run(_crawl(argv[1:]))
        return 0
    if argv[:1] == ["graph"]:
        _graph(argv[1:])
        return 0
    if argv[:1] == ["serve"]:
        import uvicorn
        opts = _opts(argv[1:])
        uvicorn.run("warmpath.server:app", host=opts.get("--host", "127.0.0.1"),
                    port=_num(opts, "--port", 8000, 1, 65535, int))
        return 0
    if argv[:1] == ["mcp"]:
        from .mcp_server import main as mcp_main
        mcp_main()
        return 0
    from .server import MAX_QUERY, clean_query
    q = clean_query(" ".join(argv) or _ask())
    if not q:
        console.print('[red]Tell me who to reach, e.g. warmpath "warm intro to the head of data at Swiggy"[/]')
        return 2
    if len(q) > MAX_QUERY:
        console.print(f"[yellow]! request is {len(q)} characters, using the first {MAX_QUERY}[/]")
        q = q[:MAX_QUERY]
    r = asyncio.run(run(q, show))
    return 0 if r.target else 1


def main() -> None:
    try:
        code = _run(sys.argv[1:])
    except KeyboardInterrupt:
        console.print("\n[yellow]stopped. Partial results (if any) are in reports/[/]")
        code = 130
    except EOFError:
        console.print("\n[red]no request given[/]")
        code = 2
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        code = 2
    except RuntimeError as e:  # e.g. missing CRUSTDATA_API_KEY
        console.print(f"[red]{e}[/]")
        code = 1
    except Exception as e:  # last resort: one readable line instead of a traceback mid-demo
        console.print(f"[red]ERROR {type(e).__name__}: {e}[/]\n[dim]set WARMPATH_DEBUG=1 for the traceback[/]")
        if os.getenv("WARMPATH_DEBUG"):
            raise
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()
