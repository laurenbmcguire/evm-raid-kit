"""Working-day calendar (Mon-Fri minus holidays) built on numpy business-day functions.

Conventions used across the package:

* ``index(d)``   number of working days in ``[origin, d)``. For a working day ``d`` this
                 is its 0-based position in the project calendar.
* ``elapsed(d)`` number of working days in ``[origin, d]`` (days *completed* by the end
                 of ``d``). This is the "actual time" (AT) used by earned schedule.
* ``date_at(i)`` the i-th working day (0-based) counted from the origin.
"""

from __future__ import annotations

import datetime as dt
from typing import Iterable

import numpy as np
import pandas as pd


def to_date(value) -> dt.date:
    """Coerce str / datetime / Timestamp / numpy datetime64 to ``datetime.date``."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return pd.Timestamp(value).date()


def _d64(value) -> np.datetime64:
    return np.datetime64(to_date(value), "D")


class WorkCalendar:
    """A Monday-Friday working calendar with an origin date and holiday list."""

    def __init__(self, origin, holidays: Iterable = (), weekmask: str = "1111100"):
        self.origin = to_date(origin)
        self.holidays = sorted({to_date(h) for h in holidays})
        self.weekmask = weekmask
        self._cal = np.busdaycalendar(
            weekmask=weekmask,
            holidays=np.array([_d64(h) for h in self.holidays], dtype="datetime64[D]"),
        )
        self._o = _d64(self.origin)

    # ------------------------------------------------------------------ queries
    def is_workday(self, d) -> bool:
        return bool(np.is_busday(_d64(d), busdaycal=self._cal))

    def index(self, d) -> int:
        """Working days in [origin, d). Negative if d precedes the origin."""
        return int(np.busday_count(self._o, _d64(d), busdaycal=self._cal))

    def elapsed(self, d) -> int:
        """Working days in [origin, d] (completed by the end of d)."""
        return int(np.busday_count(self._o, _d64(d) + np.timedelta64(1, "D"), busdaycal=self._cal))

    def date_at(self, i: int) -> dt.date:
        """The i-th working day from the origin (0-based)."""
        out = np.busday_offset(self._o, int(i), roll="forward", busdaycal=self._cal)
        return pd.Timestamp(out).date()

    def count(self, start, end) -> int:
        """Inclusive count of working days between two dates."""
        return int(
            np.busday_count(_d64(start), _d64(end) + np.timedelta64(1, "D"), busdaycal=self._cal)
        )

    def add_workdays(self, d, n: int) -> dt.date:
        """Roll d forward to a working day, then move n working days."""
        out = np.busday_offset(_d64(d), int(n), roll="forward", busdaycal=self._cal)
        return pd.Timestamp(out).date()

    def workdays(self, start, end) -> list[dt.date]:
        days = pd.date_range(to_date(start), to_date(end), freq="D")
        return [d.date() for d in days if self.is_workday(d)]
