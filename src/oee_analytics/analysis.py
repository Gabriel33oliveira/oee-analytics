"""Downtime Pareto, shift and machine comparisons, and plain-text tables."""

from __future__ import annotations

import datetime
from collections.abc import Sequence

import pandas as pd

from oee_analytics.io import Dataset
from oee_analytics.metrics import (
    _default_end,
    compute_oee,
    compute_overall,
    split_by_shift,
    state_intervals,
)
from oee_analytics.models import MachineState, Shift
from oee_analytics.shifts import DEFAULT_SHIFTS

PARETO_COLUMNS = ("reason_code", "events", "downtime_min", "share_pct", "cumulative_pct")

# Columns holding 0-1 ratios, shown as percentages by format_table.
RATIO_COLUMNS = frozenset({"availability", "performance", "quality", "oee"})


def downtime_pareto(
    dataset: Dataset,
    machine_id: str | None = None,
    shift: str | None = None,
    shifts: Sequence[Shift] = DEFAULT_SHIFTS,
    end: datetime.datetime | None = None,
) -> pd.DataFrame:
    """Downtime by reason code, sorted by downtime descending.

    Built from DOWN intervals split at shift boundaries. ``events`` counts DOWN
    intervals, so one that crosses a shift change counts once (or once per
    shift when filtering by shift). ``share_pct`` is each reason's share of the
    filtered downtime and ``cumulative_pct`` its running total.
    """
    if end is None:
        end = _default_end(dataset)
    empty = pd.DataFrame(columns=list(PARETO_COLUMNS))
    if end is None:
        return empty

    intervals = state_intervals(dataset.states, end)
    intervals = intervals[intervals["state"] == MachineState.DOWN.value]
    if machine_id is not None:
        intervals = intervals[intervals["machine_id"] == machine_id]
    intervals = intervals.reset_index(drop=True)
    intervals["event_id"] = intervals.index
    pieces = split_by_shift(intervals, shifts)
    if shift is not None:
        pieces = pieces[pieces["shift"] == shift]
    if pieces.empty:
        return empty

    grouped = pieces.groupby("reason_code").agg(
        events=("event_id", "nunique"), downtime_s=("duration_s", "sum")
    )
    grouped = grouped.reset_index().sort_values(
        ["downtime_s", "reason_code"], ascending=[False, True], kind="stable"
    )
    total = grouped["downtime_s"].sum()
    share = grouped["downtime_s"] / total * 100.0
    out = pd.DataFrame(
        {
            "reason_code": grouped["reason_code"],
            "events": grouped["events"].astype("int64"),
            "downtime_min": grouped["downtime_s"] / 60.0,
            "share_pct": share,
            "cumulative_pct": share.cumsum(),
        }
    )
    return out.reset_index(drop=True)


def _compare(
    dataset: Dataset, key: str, shifts: Sequence[Shift], end: datetime.datetime | None
) -> pd.DataFrame:
    table = compute_oee(dataset, group_by=(key,), shifts=shifts, end=end)
    plant = compute_overall(dataset, shifts=shifts, end=end)
    table["rank"] = table["oee"].rank(ascending=False, method="min").astype("int64")
    table["oee_delta_pts"] = (table["oee"] - plant.oee) * 100.0
    return table.sort_values(["rank", key], kind="stable").reset_index(drop=True)


def compare_shifts(
    dataset: Dataset,
    shifts: Sequence[Shift] = DEFAULT_SHIFTS,
    end: datetime.datetime | None = None,
) -> pd.DataFrame:
    """OEE per shift, with ``rank`` (1 = best OEE) and ``oee_delta_pts`` vs the plant."""
    return _compare(dataset, "shift", shifts, end)


def compare_machines(
    dataset: Dataset,
    shifts: Sequence[Shift] = DEFAULT_SHIFTS,
    end: datetime.datetime | None = None,
) -> pd.DataFrame:
    """OEE per machine, with ``rank`` (1 = best OEE) and ``oee_delta_pts`` vs the plant."""
    return _compare(dataset, "machine_id", shifts, end)


def _format_cell(column: str, value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if column in RATIO_COLUMNS:
        return f"{float(value) * 100:.1f}%"
    if column == "oee_delta_pts":
        return f"{float(value):+.1f}"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def format_table(df: pd.DataFrame) -> str:
    """Render ``df`` as an aligned plain-text table.

    Ratio columns (availability, performance, quality, oee) are shown as
    percentages with one decimal; other floats get one decimal. Numeric
    columns are right-aligned, the rest left-aligned.
    """
    columns = [str(c) for c in df.columns]
    rows = [
        [_format_cell(col, value) for col, value in zip(columns, record)]
        for record in df.itertuples(index=False, name=None)
    ]
    numeric = [pd.api.types.is_numeric_dtype(df[c]) for c in df.columns]
    widths = [
        max([len(col)] + [len(row[i]) for row in rows]) for i, col in enumerate(columns)
    ]

    def line(cells: Sequence[str]) -> str:
        parts = [
            cell.rjust(w) if num else cell.ljust(w)
            for cell, w, num in zip(cells, widths, numeric)
        ]
        return "  ".join(parts).rstrip()

    out = [line(columns), line(["-" * w for w in widths])]
    out.extend(line(row) for row in rows)
    return "\n".join(out)
