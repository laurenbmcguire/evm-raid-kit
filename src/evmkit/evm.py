"""Earned value management: PV spread, EV, AC and the standard performance indices.

Formulas (PMI / ANSI-748 conventions):

* SV = EV - PV,  CV = EV - AC
* SPI = EV / PV, CPI = EV / AC
* EAC (CPI method)            = BAC / CPI
* EAC (atypical, budget rate) = AC + (BAC - EV)
* EAC (CPI x SPI composite)   = AC + (BAC - EV) / (CPI * SPI)
* ETC = EAC - AC,  VAC = BAC - EAC   (using the CPI-method EAC as the primary forecast)
* TCPI (to BAC) = (BAC - EV) / (BAC - AC),  TCPI (to EAC) = (BAC - EV) / (EAC - AC)
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

from evmkit.workcal import WorkCalendar, to_date


def _div(a: float, b: float) -> float:
    return float(a) / float(b) if b else float("nan")


def evm_metrics(bac: float, pv: float, ev: float, ac: float) -> dict:
    """All headline EVM metrics from the four base quantities."""
    spi = _div(ev, pv)
    cpi = _div(ev, ac)
    eac_cpi = _div(bac, cpi) if cpi and not math.isnan(cpi) else float("nan")
    eac_atypical = ac + (bac - ev)
    eac_composite = ac + _div(bac - ev, cpi * spi) if cpi and spi else float("nan")
    etc = eac_cpi - ac
    return {
        "bac": float(bac),
        "pv": float(pv),
        "ev": float(ev),
        "ac": float(ac),
        "sv": float(ev - pv),
        "cv": float(ev - ac),
        "spi": spi,
        "cpi": cpi,
        "eac_cpi": eac_cpi,
        "eac_atypical": float(eac_atypical),
        "eac_cpi_spi": eac_composite,
        "etc": etc,
        "vac": float(bac - eac_cpi),
        "vac_pct": _div(bac - eac_cpi, bac),
        "tcpi_bac": _div(bac - ev, bac - ac),
        "tcpi_eac": _div(bac - ev, eac_cpi - ac),
        "pct_planned": _div(pv, bac),
        "pct_complete": _div(ev, bac),
        "pct_spent": _div(ac, bac),
    }


# --------------------------------------------------------------------------- PV
def add_calendar_columns(plan: pd.DataFrame, cal: WorkCalendar) -> pd.DataFrame:
    """Add start index, working-day duration and finish index for each task."""
    out = plan.copy()
    out["start_idx"] = [cal.index(d) for d in out["planned_start"]]
    out["duration"] = [cal.count(s, f) for s, f in zip(out["planned_start"], out["planned_finish"])]
    out["finish_idx"] = out["start_idx"] + out["duration"]  # half-open
    return out


def planned_fraction(start_idx, duration, days_done) -> np.ndarray:
    """Linear planned spread: fraction of each task planned after ``days_done`` working days."""
    start_idx = np.asarray(start_idx, dtype=float)
    duration = np.maximum(np.asarray(duration, dtype=float), 1.0)
    return np.clip((days_done - start_idx) / duration, 0.0, 1.0)


def pv_by_task(plan: pd.DataFrame, cal: WorkCalendar, d) -> pd.Series:
    """PV per task at the end of date ``d``."""
    p = plan if "start_idx" in plan else add_calendar_columns(plan, cal)
    frac = planned_fraction(p["start_idx"], p["duration"], cal.elapsed(d))
    return pd.Series(p["budget"].to_numpy() * frac, index=p["id"].to_numpy())


def pv_cumulative(plan: pd.DataFrame, cal: WorkCalendar, n_days: int | None = None) -> np.ndarray:
    """``out[n]`` = cumulative PV after n completed working days, n = 0..N."""
    p = plan if "start_idx" in plan else add_calendar_columns(plan, cal)
    if n_days is None:
        n_days = int(p["finish_idx"].max())
    n = np.arange(n_days + 1, dtype=float)[:, None]
    frac = planned_fraction(p["start_idx"].to_numpy()[None, :], p["duration"].to_numpy()[None, :], n)
    return (frac * p["budget"].to_numpy()[None, :]).sum(axis=1)


# --------------------------------------------------------------------- AC / EV
def ac_by_task(timesheets: pd.DataFrame, task_ids, d) -> pd.Series:
    """Cumulative actual cost per task from timesheet weeks ending on or before ``d``."""
    d = pd.Timestamp(to_date(d))
    ts = timesheets[timesheets["week_ending"] <= d]
    s = ts.groupby("task_id")["actual_cost"].sum()
    return s.reindex(list(task_ids), fill_value=0.0).astype(float)


def progress_by_task(
    plan: pd.DataFrame, timesheets: pd.DataFrame, d, use_plan: bool = False
) -> pd.Series:
    """Fraction complete per task at date ``d``.

    * ``use_plan`` - take ``plan.percent_complete`` (the plan is "as of" ``d``).
    * timesheets carry a ``percent_complete`` snapshot - latest snapshot on or before ``d``.
    * otherwise - scale the plan's percent by the share of the task's AC spent by ``d``.
    """
    ids = plan["id"].tolist()
    plan_pct = pd.Series(plan["percent_complete"].to_numpy() / 100.0, index=ids)
    if use_plan:
        return plan_pct.astype(float)
    t = pd.Timestamp(to_date(d))
    if "percent_complete" in timesheets.columns:
        ts = timesheets[timesheets["week_ending"] <= t].sort_values("week_ending")
        last = ts.groupby("task_id")["percent_complete"].last() / 100.0
        return last.reindex(ids, fill_value=0.0).astype(float)
    ac_now = ac_by_task(timesheets, ids, timesheets["week_ending"].max())
    ac_t = ac_by_task(timesheets, ids, t)
    share = (ac_t / ac_now.replace(0, np.nan)).fillna(0.0).clip(0, 1)
    return (plan_pct * share).astype(float)


def task_table(
    plan: pd.DataFrame, timesheets: pd.DataFrame, cal: WorkCalendar, d, use_plan: bool
) -> pd.DataFrame:
    """Per-task PV, EV, AC and variances at date ``d``."""
    p = plan if "start_idx" in plan else add_calendar_columns(plan, cal)
    ids = p["id"].tolist()
    pv = pv_by_task(p, cal, d)
    prog = progress_by_task(p, timesheets, d, use_plan=use_plan)
    ac = ac_by_task(timesheets, ids, d)
    out = pd.DataFrame(
        {
            "id": ids,
            "wbs": p["wbs"].to_numpy(),
            "name": p["name"].to_numpy(),
            "budget": p["budget"].to_numpy(dtype=float),
            "pct_planned": (pv / p["budget"].to_numpy()).to_numpy(),
            "pct_complete": prog.to_numpy(),
        }
    )
    out["pv"] = pv.to_numpy()
    out["ev"] = out["pct_complete"] * out["budget"]
    out["ac"] = ac.to_numpy()
    out["sv"] = out["ev"] - out["pv"]
    out["cv"] = out["ev"] - out["ac"]
    out["spi"] = np.where(out["pv"] > 0, out["ev"] / out["pv"].replace(0, np.nan), np.nan)
    out["cpi"] = np.where(out["ac"] > 0, out["ev"] / out["ac"].replace(0, np.nan), np.nan)
    return out


def period_dates(timesheets: pd.DataFrame, status_date) -> list[dt.date]:
    """Reporting periods: every timesheet week ending up to the status date, plus the status date."""
    sd = to_date(status_date)
    weeks = sorted({to_date(w) for w in timesheets["week_ending"] if to_date(w) <= sd})
    if not weeks or weeks[-1] != sd:
        weeks.append(sd)
    return weeks
