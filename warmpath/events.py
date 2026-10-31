"""Event helpers. The UI/CLI render these dicts live (schema: docs/PLAN.md §6)."""
from __future__ import annotations

from typing import Any, Callable

from .models import Person, to_dict

Emit = Callable[[dict], Any]


def noop(_: dict) -> None:
    pass


def step(emit: Emit, id: str, status: str, label: str, detail: str = "") -> None:
    emit({"type": "step", "id": id, "status": status, "label": label, "detail": detail})


def node(emit: Emit, role: str, person: Person) -> None:
    emit({"type": "node", "role": role, "person": to_dict(person)})


def edge(emit: Emit, a: Person, b: Person, score: float, label: str) -> None:
    emit({"type": "edge", "a": a.person_id, "b": b.person_id, "score": round(score, 1), "label": label})


def warn(emit: Emit, message: str) -> None:
    emit({"type": "warning", "message": message})
