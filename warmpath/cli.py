"""CLI: uv run warmpath "warm intro to the head of data at Swiggy via IIT Bombay alumni".  Owner: Member C (v1 stub)."""
from __future__ import annotations

import asyncio
import sys

from rich.console import Console

from .pipeline import run

console = Console()
ICON = {"start": "[cyan]…[/]", "progress": "[blue]·[/]", "done": "[green]✓[/]", "error": "[red]✗[/]"}


def show(e: dict) -> None:
    t = e["type"]
    if t == "step":
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
    elif t == "done":
        r = e["result"]
        console.print(f"\n[dim]{len(r['audit'])} API calls · {r['credits_used']} credits · {r['elapsed_s']}s · "
                      f"report in reports/, drafts in outbox/[/]")


def main() -> None:
    q = " ".join(sys.argv[1:]) or input("Who do you want to reach? ")
    asyncio.run(run(q, show))


if __name__ == "__main__":
    main()
