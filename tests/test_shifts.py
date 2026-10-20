from datetime import datetime, timedelta

import pytest

from oee_analytics.shifts import shift_for, shift_windows


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (6, 0, "A"),
        (13, 59, "A"),
        (14, 0, "B"),
        (21, 59, "B"),
        (22, 0, "C"),
        (23, 30, "C"),
        (0, 0, "C"),
        (5, 59, "C"),
    ],
)
def test_shift_for(hour, minute, expected):
    assert shift_for(datetime(2026, 1, 5, hour, minute)) == expected


def test_shift_windows_full_day():
    start = datetime(2026, 1, 5)
    end = start + timedelta(days=1)
    windows = list(shift_windows(start, end))

    assert [w[0] for w in windows] == ["C", "A", "B", "C"]
    assert windows[0][1:] == (start, datetime(2026, 1, 5, 6))
    assert windows[-1][1:] == (datetime(2026, 1, 5, 22), end)
    assert sum((w[2] - w[1] for w in windows), timedelta()) == timedelta(hours=24)


def test_shift_windows_contiguous_and_clipped():
    start = datetime(2026, 1, 5, 10, 30)
    end = datetime(2026, 1, 7, 3, 15)
    windows = list(shift_windows(start, end))

    assert windows[0] == ("A", start, datetime(2026, 1, 5, 14))
    assert windows[-1] == ("C", datetime(2026, 1, 6, 22), end)
    for prev, nxt in zip(windows, windows[1:]):
        assert prev[2] == nxt[1]
    assert sum((w[2] - w[1] for w in windows), timedelta()) == end - start


def test_shift_windows_empty_range():
    t = datetime(2026, 1, 5, 8)
    assert list(shift_windows(t, t)) == []
