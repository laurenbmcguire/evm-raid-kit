"""Working-day calendar, earned schedule and CPM against hand-computed values."""

import datetime as dt

import numpy as np
import pytest

from evmkit.cpm import cpm, parse_deps
from evmkit.schedule import earned_schedule, es_metrics, forecast_finish
from evmkit.workcal import WorkCalendar


def test_work_calendar_weekends_and_holidays():
    cal = WorkCalendar("2026-03-02", holidays=["2026-03-06"])  # Friday holiday
    assert cal.is_workday("2026-03-05") and not cal.is_workday("2026-03-06")
    assert cal.count("2026-03-02", "2026-03-13") == 9          # 10 weekdays minus the holiday
    assert cal.index("2026-03-09") == 4                        # Mon-Thu before it
    assert cal.elapsed("2026-03-08") == 4                      # Sunday: nothing new completed
    assert cal.date_at(4) == dt.date(2026, 3, 9)               # skips Fri holiday and weekend
    assert cal.add_workdays("2026-03-05", 1) == dt.date(2026, 3, 9)


def test_earned_schedule_hand_computed():
    pv_cum = np.arange(0, 1001, 100, dtype=float)  # 10 working days, 100 per day
    # EV 450: C = 4 (PV[4] = 400 <= 450 < 500), ES = 4 + 50/100 = 4.5
    assert earned_schedule(pv_cum, 450) == pytest.approx(4.5)
    m = es_metrics(pv_cum, ev=450, at=6)
    assert m["spi_t"] == pytest.approx(0.75)            # 4.5 / 6
    assert m["sv_t_days"] == pytest.approx(-1.5)
    assert m["ieac_t_days"] == pytest.approx(10 / 0.75)  # 13.33
    assert earned_schedule(pv_cum, 0) == 0
    assert earned_schedule(pv_cum, 1000) == 10


def test_forecast_finish_from_spi_t():
    cal = WorkCalendar("2026-03-02")
    planned, forecast, slip = forecast_finish(cal, planned_duration=10, spi_t=0.75)
    assert planned == dt.date(2026, 3, 13)     # day index 9
    assert forecast == dt.date(2026, 3, 19)    # ceil(13.33) = 14 days -> index 13
    assert slip == 4


def test_cpm_forward_backward_pass_and_float():
    # A(3) -> B(2), A -> C(4), B,C -> D(1)
    res = cpm({"A": 3, "B": 2, "C": 4, "D": 1}, {"B": ["A"], "C": ["A"], "D": ["B", "C"]})
    t = res.table
    assert res.duration == 8
    assert (t.at["B", "es"], t.at["B", "ef"], t.at["B", "ls"], t.at["B", "lf"]) == (3, 5, 5, 7)
    assert t.at["B", "total_float"] == 2 and t.at["B", "free_float"] == 2
    assert t.at["C", "total_float"] == 0 and t.at["D", "es"] == 7
    assert res.critical_path == ["A", "C", "D"]


def test_cpm_rejects_cycles_and_unknown_deps():
    with pytest.raises(ValueError):
        cpm({"A": 1, "B": 1}, {"A": ["B"], "B": ["A"]})
    with pytest.raises(ValueError):
        cpm({"A": 1}, {"A": ["Z"]})
    assert parse_deps("T03; T04") == ["T03", "T04"]
    assert parse_deps(float("nan")) == []
