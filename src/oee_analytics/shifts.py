"""Shift calendar: map timestamps to shifts and split time ranges into shift windows."""

from __future__ import annotations

import datetime
from collections.abc import Iterator, Sequence

from oee_analytics.models import Shift

DEFAULT_SHIFTS: tuple[Shift, ...] = (
    Shift("A", datetime.time(6, 0), datetime.time(14, 0)),
    Shift("B", datetime.time(14, 0), datetime.time(22, 0)),
    Shift("C", datetime.time(22, 0), datetime.time(6, 0)),
)


def shift_for(timestamp: datetime.datetime, shifts: Sequence[Shift] = DEFAULT_SHIFTS) -> str:
    """Return the name of the shift that contains ``timestamp``."""
    t = timestamp.time()
    for shift in shifts:
        if shift.contains(t):
            return shift.name
    raise ValueError(f"No shift covers {timestamp.isoformat()}")


def shift_windows(
    start: datetime.datetime,
    end: datetime.datetime,
    shifts: Sequence[Shift] = DEFAULT_SHIFTS,
) -> Iterator[tuple[str, datetime.datetime, datetime.datetime]]:
    """Yield ``(shift_name, window_start, window_end)`` covering [start, end).

    Windows are in chronological order and clipped to the requested range.
    """
    if end <= start:
        return
    tz = start.tzinfo
    windows: list[tuple[str, datetime.datetime, datetime.datetime]] = []
    # Start one day early so an overnight shift that began yesterday is included.
    day = start.date() - datetime.timedelta(days=1)
    while day <= end.date():
        for shift in shifts:
            w_start = datetime.datetime.combine(day, shift.start, tzinfo=tz)
            end_day = day + datetime.timedelta(days=1) if shift.overnight else day
            w_end = datetime.datetime.combine(end_day, shift.end, tzinfo=tz)
            lo, hi = max(w_start, start), min(w_end, end)
            if lo < hi:
                windows.append((shift.name, lo, hi))
        day += datetime.timedelta(days=1)
    windows.sort(key=lambda w: w[1])
    yield from windows
