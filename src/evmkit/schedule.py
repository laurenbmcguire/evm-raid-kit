"""Earned schedule (Lipke): time-based schedule performance and forecast finish.

With ``PV[n]`` the cumulative planned value after n working days:

* ``C``      = the largest n with ``PV[n] <= EV``
* ``ES``     = C + (EV - PV[C]) / (PV[C+1] - PV[C])
* ``SPI(t)`` = ES / AT,  ``SV(t)`` = ES - AT   (AT = working days elapsed)
* ``IEAC(t)``= PD / SPI(t)  (PD = planned duration in working days)

Unlike the cost-based SPI, SPI(t) does not drift back to 1.0 as a late project nears completion.
"""

from __future__ import annotations

import math

import numpy as np

from evmkit.workcal import WorkCalendar


def earned_schedule(pv_cum: np.ndarray, ev: float) -> float:
    """Earned schedule in working days for a cumulative PV array indexed by days completed."""
    pv_cum = np.asarray(pv_cum, dtype=float)
    pd_days = len(pv_cum) - 1
    if ev <= 0:
        return 0.0
    if ev >= pv_cum[-1]:
        return float(pd_days)
    c = int(np.searchsorted(pv_cum, ev, side="right") - 1)
    c = max(0, min(c, pd_days - 1))
    step = pv_cum[c + 1] - pv_cum[c]
    return float(c + ((ev - pv_cum[c]) / step if step > 0 else 0.0))


def es_metrics(pv_cum: np.ndarray, ev: float, at: float) -> dict:
    """ES, SPI(t), SV(t) and the time-based forecast duration IEAC(t)."""
    pd_days = len(pv_cum) - 1
    es = earned_schedule(pv_cum, ev)
    spi_t = es / at if at > 0 else float("nan")
    ieac_t = pd_days / spi_t if spi_t and not math.isnan(spi_t) else float("nan")
    return {
        "es_days": es,
        "at_days": float(at),
        "planned_duration_days": int(pd_days),
        "spi_t": spi_t,
        "sv_t_days": es - at,
        "ieac_t_days": ieac_t,
    }


def forecast_finish(cal: WorkCalendar, planned_duration: int, spi_t: float) -> tuple:
    """Forecast finish date and slip (working days) from IEAC(t) = PD / SPI(t)."""
    planned_finish = cal.date_at(planned_duration - 1)
    if not spi_t or math.isnan(spi_t):
        return planned_finish, planned_finish, 0
    days = int(math.ceil(planned_duration / spi_t - 1e-9))
    return planned_finish, cal.date_at(days - 1), days - planned_duration
