"""Gold scenarios for the product eval (eval/run_eval.py). Owner: Member A.

Each scenario = one request + what a correct run must do. `world="fake"` runs offline against warmpath/fake.py
(deterministic, 0 credits); `world="live"` runs against Crustdata (responses cached in .cache/, so reruns are free).

Expectation keys (all optional):
  target_name / target_title / target_company   regex the resolved target must match (current company for _company)
  no_target          True if the right answer is "nobody": must then explain itself with a warning
  warn               regex at least one warning must match (e.g. the ambiguity notice)
  min_paths          at least this many intro paths
  seed_path          True if a path must start at one of the team's own profiles
  max_credits / max_seconds   efficiency budget for this request
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Scenario:
    id: str
    category: str
    world: str
    query: str
    expect: dict = field(default_factory=dict)
    group: str = ""          # scenarios in one group are rewordings of the same request: must resolve to the same person


S = Scenario
SCENARIOS: list[Scenario] = [
    # ---- happy path (fake world: Priya = head of data at Swiggy, Rahul = her 4-yr colleague at a 30-person startup)
    S("F01", "happy path", "fake", "warm intro to the head of data at Swiggy via IIT Bombay alumni",
      {"target_name": "Priya Sharma", "min_paths": 1}, group="fake-swiggy-data"),
    S("F02", "happy path", "fake", "https://www.linkedin.com/in/priya-sharma", {"target_name": "Priya Sharma", "min_paths": 1}, group="fake-priya-url"),
    # ---- messy input
    S("F03", "messy input", "fake", "teh data guy at swigy pls", {"target_name": "Priya Sharma"}, group="fake-swiggy-data"),
    S("F04", "messy input", "fake", "WARM INTRO TO THE HEAD OF DATA AT SWIGGY", {"target_name": "Priya Sharma"}, group="fake-swiggy-data"),
    S("F05", "messy input", "fake", "bhai swiggy mein data head se intro karwa do iitb wale se", {"target_name": "Priya Sharma"}, group="fake-swiggy-data"),
    S("F06", "messy input", "fake", "linkedin.com/in/priya-sharma", {"target_name": "Priya Sharma"}, group="fake-priya-url"),
    S("F07", "messy input", "fake", "intro to the head of data at Swiggy Pvt Ltd", {"target_name": "Priya Sharma"}, group="fake-swiggy-data"),
    S("F08", "messy input", "fake", "intro to the head of data at https://www.linkedin.com/company/swiggy",
      {"target_name": "Priya Sharma"}, group="fake-swiggy-data"),
    # ---- ambiguity
    S("F09", "ambiguity", "fake", "intro to Priya Sharma at Swiggy", {"target_name": "Priya Sharma", "target_company": "Swiggy"}),
    S("F10", "ambiguity", "fake", "intro to Priya Sharma", {"target_name": "Priya Sharma", "warn": "people match"}),
    # ---- nobody is the right answer
    S("F11", "no answer", "fake", "", {"no_target": True}),
    S("F12", "no answer", "fake", "intro to the CEO at Nonexistent Corp", {"no_target": True}),
    S("F13", "no answer", "fake", "https://www.linkedin.com/in/redacted-person", {"no_target": True, "warn": "remove their data"}),
    S("F14", "no answer", "fake", "https://www.linkedin.com/in/does-not-exist", {"no_target": True}),
    # ---- hostile input
    S("F15", "hostile input", "fake", "intro to <script>alert(1)</script> at Swiggy", {"no_target": True}),
    S("F16", "hostile input", "fake", "intro to '; DROP TABLE nodes; -- at Swiggy", {"no_target": True}),
    S("F17", "hostile input", "fake", "x" * 5000, {"no_target": True}),
    S("F18", "hostile input", "fake", "intro to the head of data at Swiggy\x00\x07", {"target_name": "Priya Sharma"}, group="fake-swiggy-data"),
    # ---- network logic
    S("F19", "network logic", "fake", "intro to the head of data at Swiggy via Swiggy",  # target's employer ≠ network
      {"target_name": "Priya Sharma"}, group="fake-swiggy-data"),

    # ---- LIVE (real Crustdata)
    S("L01", "happy path", "live", "warm intro to the head of data at Swiggy via IIT Bombay alumni",
      {"target_title": "data", "target_company": "swiggy", "min_paths": 1, "max_credits": 60, "max_seconds": 90}, group="live-swiggy-data"),
    S("L02", "messy input", "live", "teh data guy at swigy pls", {"target_title": "data", "target_company": "swiggy"}, group="live-swiggy-data"),
    S("L03", "messy input", "live", "warm intro to the CTO at zepto via iit bombay",
      {"target_title": "chief technology officer|cto", "target_company": "zepto", "min_paths": 1}),
    S("L04", "messy input", "live", "Swiggy", {"target_title": "found", "min_paths": 1}),
    S("L05", "messy input", "live", "linkedin.com/in/adityadarshan", {"target_name": "aditya darshan", "min_paths": 1}),
    S("L06", "ambiguity", "live", "intro to Rahul Sharma", {"target_name": "rahul sharma", "warn": "people match"}),
    S("L07", "ambiguity", "live", "intro to Kunal Shah at CRED", {"target_name": "kunal shah", "warn": "CRED"}),
    S("L08", "no answer", "live", "intro to the head of growth at Nonexistentxyzcorp", {"no_target": True}),
    S("L09", "network logic", "live", "warm intro to the head of data at Swiggy", {"seed_path": True}, group="live-swiggy-data"),
]
