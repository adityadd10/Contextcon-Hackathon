from datetime import date

import pytest

from warmpath import headcount
from warmpath.models import Person, Stint
from warmpath.score import score_tie


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(headcount, "HISTORY", {})


ROW = [{"matched_on": "1", "matches": [{"company_data": {"headcount": {"total": 4000, "timeseries": [
    {"date": "2021-08-30", "employee_count": 300}, {"date": "2023-01-02", "employee_count": 2000},
    {"date": "2025-06-02", "employee_count": 4000}]}}}]}]


def test_size_during_uses_smallest_point_in_window_and_says_when_history_starts_late():
    headcount.register(1, ROW)
    assert headcount.size_during(1, date(2022, 1, 1), date(2025, 12, 1))[0] == 2000
    n, note = headcount.size_during(1, date(2015, 1, 1), date(2026, 1, 1))
    assert n == 300 and "earliest on record" in note
    assert headcount.size_during(1, date(2015, 1, 1), date(2018, 1, 1)) is None   # ended before records: unknown
    assert headcount.size_during(2, date(2015, 1, 1), date(2026, 1, 1)) is None   # no history loaded


def test_tie_scored_on_size_at_the_time_with_evidence():
    def P(pid, start):
        return Person(name=f"P{pid}", person_id=pid, source_endpoint="t", stints=[
            Stint("Acme", 1, "Engineer", start, date(2022, 6, 1), company_headcount=4000, ref=f"p{pid}")])
    a, b = P(1, date(2021, 1, 1)), P(2, date(2021, 2, 1))
    before = score_tie(a, b)
    headcount.register(1, ROW)
    after = score_tie(a, b)
    size = next(f for f in after.factors if f.name == "company_size")
    assert size.value == 300 and "2021-08" in size.explanation
    assert size.evidence[0].ref == "company:1#headcount.timeseries"
    assert after.score > before.score
