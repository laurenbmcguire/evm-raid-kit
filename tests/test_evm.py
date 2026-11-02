"""EVM formulas checked against hand-computed values."""

import datetime as dt

import pandas as pd
import pytest

from evmkit import evm
from evmkit.workcal import WorkCalendar


def test_evm_metrics_hand_computed():
    # BAC 1000, PV 500, EV 400, AC 500
    m = evm.evm_metrics(bac=1000, pv=500, ev=400, ac=500)
    assert m["sv"] == -100            # 400 - 500
    assert m["cv"] == -100            # 400 - 500
    assert m["spi"] == pytest.approx(0.8)   # 400 / 500
    assert m["cpi"] == pytest.approx(0.8)   # 400 / 500
    assert m["eac_cpi"] == pytest.approx(1250.0)       # 1000 / 0.8
    assert m["eac_atypical"] == pytest.approx(1100.0)  # 500 + (1000 - 400)
    assert m["eac_cpi_spi"] == pytest.approx(1437.5)   # 500 + 600 / (0.8 * 0.8)
    assert m["etc"] == pytest.approx(750.0)            # 1250 - 500
    assert m["vac"] == pytest.approx(-250.0)           # 1000 - 1250
    assert m["tcpi_bac"] == pytest.approx(1.2)         # 600 / 500
    assert m["tcpi_eac"] == pytest.approx(0.8)         # 600 / 750


def test_eac_methods_second_case():
    # BAC 100k, PV 40k, EV 30k, AC 37.5k -> SPI 0.75, CPI 0.8
    m = evm.evm_metrics(bac=100_000, pv=40_000, ev=30_000, ac=37_500)
    assert m["spi"] == pytest.approx(0.75)
    assert m["cpi"] == pytest.approx(0.8)
    assert m["eac_cpi"] == pytest.approx(125_000)
    assert m["eac_atypical"] == pytest.approx(107_500)              # 37.5k + 70k
    assert m["eac_cpi_spi"] == pytest.approx(37_500 + 70_000 / 0.6)  # 154,166.67
    assert m["vac_pct"] == pytest.approx(-0.25)
    assert m["tcpi_bac"] == pytest.approx(70_000 / 62_500)          # 1.12
    assert m["pct_complete"] == pytest.approx(0.30)


def _plan(rows):
    df = pd.DataFrame(rows, columns=["id", "wbs", "name", "budget", "planned_start", "planned_finish",
                                     "percent_complete", "actual_cost"])
    df["planned_start"] = pd.to_datetime(df["planned_start"])
    df["planned_finish"] = pd.to_datetime(df["planned_finish"])
    return df


def test_pv_linear_spread_skips_weekends_and_holidays():
    # Holiday on Wed 4 Mar: task A (Mon 2 - Fri 6 Mar) has 4 working days -> 250/day.
    cal = WorkCalendar("2026-03-02", holidays=["2026-03-04"])
    plan = _plan([
        ("A", "1.1", "A", 1000, "2026-03-02", "2026-03-06", 0, 0),
        ("B", "1.2", "B", 500, "2026-03-09", "2026-03-13", 0, 0),  # 5 days -> 100/day
    ])
    plan = evm.add_calendar_columns(plan, cal)
    assert plan["duration"].tolist() == [4, 5]
    assert evm.pv_by_task(plan, cal, "2026-03-03")["A"] == pytest.approx(500)   # Mon + Tue
    assert evm.pv_by_task(plan, cal, "2026-03-04")["A"] == pytest.approx(500)   # holiday adds nothing
    assert evm.pv_by_task(plan, cal, "2026-03-05")["A"] == pytest.approx(750)
    assert evm.pv_by_task(plan, cal, "2026-03-08").sum() == pytest.approx(1000)  # Sunday
    assert evm.pv_by_task(plan, cal, "2026-03-10").sum() == pytest.approx(1200)  # + 2/5 of 500
    cum = evm.pv_cumulative(plan, cal)
    assert cum.tolist() == pytest.approx([0, 250, 500, 750, 1000, 1100, 1200, 1300, 1400, 1500])


def test_task_table_ev_from_percent_and_ac_from_timesheets():
    cal = WorkCalendar("2026-03-02")
    plan = _plan([
        ("A", "1.1", "A", 1000, "2026-03-02", "2026-03-06", 100, 1100),
        ("B", "1.2", "B", 2000, "2026-03-09", "2026-03-20", 25, 600),
    ])
    ts = pd.DataFrame({
        "week_ending": pd.to_datetime(["2026-03-06", "2026-03-13", "2026-03-13"]),
        "task_id": ["A", "A", "B"],
        "actual_cost": [900.0, 200.0, 600.0],
        "percent_complete": [90, 100, 25],
    })
    t = evm.task_table(plan, ts, cal, "2026-03-13", use_plan=True).set_index("id")
    assert t.at["A", "ev"] == pytest.approx(1000)      # 100% x 1000
    assert t.at["B", "ev"] == pytest.approx(500)       # 25% x 2000
    assert t.at["A", "ac"] == pytest.approx(1100)      # 900 + 200
    assert t.at["B", "pv"] == pytest.approx(1000)      # 5 of 10 days x 2000
    assert t.at["B", "cpi"] == pytest.approx(500 / 600)
    # Earlier date: progress comes from the timesheet snapshot, AC only from weeks <= date.
    early = evm.task_table(plan, ts, cal, dt.date(2026, 3, 6), use_plan=False).set_index("id")
    assert early.at["A", "ev"] == pytest.approx(900)
    assert early.at["A", "ac"] == pytest.approx(900)
    assert early.at["B", "ev"] == 0
