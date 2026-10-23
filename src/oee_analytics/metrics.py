"""OEE metric engine: state intervals, shift splitting and OEE per group.

Definitions:

- planned_time = total time minus PLANNED_STOP time
- run_time = RUNNING time
- downtime = DOWN + IDLE time
- availability = run_time / planned_time
- performance = sum(ideal_cycle_time_s * total_count) / run_time, capped at 1.0
- quality = good_count / total_count
- oee = availability * performance * quality

Ratios are computed from summed times and counts, so aggregating machines or
shifts weights them by time, never by averaging ratios. A zero denominator
gives 0.0.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass, fields

import pandas as pd

from oee_analytics.io import Dataset
from oee_analytics.models import MachineState, Shift
from oee_analytics.shifts import DEFAULT_SHIFTS, shift_windows

GROUP_KEYS = ("machine_id", "shift", "date")

INTERVAL_COLUMNS = ("machine_id", "state", "reason_code", "start", "end", "duration_s")


@dataclass(frozen=True)
class OeeResult:
    """OEE components and the times and counts they are computed from."""

    planned_time_s: float
    run_time_s: float
    downtime_s: float
    total_count: int
    good_count: int
    scrap_count: int
    availability: float
    performance: float
    quality: float
    oee: float


RESULT_COLUMNS = tuple(f.name for f in fields(OeeResult))


def _ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Element-wise division that yields 0.0 where the denominator is zero."""
    safe = denominator.where(denominator != 0)
    return (numerator / safe).fillna(0.0).astype(float)


def state_intervals(states: pd.DataFrame, end: datetime.datetime) -> pd.DataFrame:
    """Turn state-change rows into intervals.

    Each state lasts until the next change for the same machine; the last one
    ends at ``end``. Intervals are clipped to ``end`` and empty ones are dropped.
    """
    end_ts = pd.Timestamp(end)
    df = states.sort_values(["machine_id", "timestamp"], kind="stable").reset_index(drop=True)
    starts = df["timestamp"]
    ends = df.groupby("machine_id", sort=False)["timestamp"].shift(-1).fillna(end_ts)
    ends = ends.where(ends <= end_ts, end_ts)
    out = pd.DataFrame(
        {
            "machine_id": df["machine_id"],
            "state": df["state"],
            "reason_code": df["reason_code"],
            "start": starts,
            "end": ends,
        }
    )
    out = out[out["end"] > out["start"]].reset_index(drop=True)
    out["duration_s"] = (out["end"] - out["start"]).dt.total_seconds()
    return out[list(INTERVAL_COLUMNS)]


def _shift_date(ts: datetime.datetime, shift: Shift) -> datetime.date:
    """Date the shift containing ``ts`` started (the day before for after-midnight times)."""
    if shift.overnight and ts.time() < shift.end:
        return ts.date() - datetime.timedelta(days=1)
    return ts.date()


def _shifts_by_name(shifts: Sequence[Shift]) -> dict[str, Shift]:
    return {s.name: s for s in shifts}


def split_by_shift(
    intervals: pd.DataFrame, shifts: Sequence[Shift] = DEFAULT_SHIFTS
) -> pd.DataFrame:
    """Split intervals at shift boundaries and add ``shift`` and ``date`` columns.

    For an overnight shift, ``date`` is the date the shift started.
    """
    by_name = _shifts_by_name(shifts)
    rows: list[dict] = []
    for row in intervals.to_dict("records"):
        start = pd.Timestamp(row["start"]).to_pydatetime()
        end = pd.Timestamp(row["end"]).to_pydatetime()
        for name, w_start, w_end in shift_windows(start, end, shifts):
            piece = dict(row)
            piece.update(
                start=pd.Timestamp(w_start),
                end=pd.Timestamp(w_end),
                duration_s=(w_end - w_start).total_seconds(),
                shift=name,
                date=_shift_date(w_start, by_name[name]),
            )
            rows.append(piece)
    columns = list(intervals.columns) + ["shift", "date"]
    return pd.DataFrame(rows, columns=columns)


def _assign_production(
    production: pd.DataFrame, shifts: Sequence[Shift]
) -> pd.DataFrame:
    """Add ``shift`` and ``date`` columns to production rows, by timestamp."""
    by_name = _shifts_by_name(shifts)
    out = production.copy()
    names: list[str] = []
    dates: list[datetime.date] = []
    for ts in out["timestamp"]:
        t = pd.Timestamp(ts).to_pydatetime()
        shift = next((s for s in shifts if s.contains(t.time())), None)
        if shift is None:
            raise ValueError(f"No shift covers {t.isoformat()}")
        names.append(shift.name)
        dates.append(_shift_date(t, by_name[shift.name]))
    out["shift"] = pd.Series(names, index=out.index, dtype=object)
    out["date"] = pd.Series(dates, index=out.index, dtype=object)
    return out


def _default_end(dataset: Dataset) -> datetime.datetime | None:
    stamps = [
        df["timestamp"].max()
        for df in (dataset.states, dataset.production)
        if not df.empty
    ]
    return max(stamps) if stamps else None


def compute_oee(
    dataset: Dataset,
    group_by: Sequence[str] = ("machine_id",),
    shifts: Sequence[Shift] = DEFAULT_SHIFTS,
    end: datetime.datetime | None = None,
) -> pd.DataFrame:
    """Compute OEE with one row per group and one column per :class:`OeeResult` field.

    ``group_by`` is any combination of ``machine_id``, ``shift`` and ``date``,
    or an empty tuple for the whole plant. ``end`` closes the last state of
    each machine; it defaults to the latest timestamp in the dataset.
    """
    keys = list(group_by)
    unknown = [k for k in keys if k not in GROUP_KEYS]
    if unknown:
        raise ValueError(
            f"unknown group_by key(s) {unknown!r} (expected any of {', '.join(GROUP_KEYS)})"
        )
    if len(set(keys)) != len(keys):
        raise ValueError(f"duplicate group_by keys in {keys!r}")

    if end is None:
        end = _default_end(dataset)
    if end is not None:
        intervals = split_by_shift(state_intervals(dataset.states, end), shifts)
    else:
        intervals = pd.DataFrame(columns=list(INTERVAL_COLUMNS) + ["shift", "date"])
    production = _assign_production(dataset.production, shifts)
    cycle = {m.machine_id: m.ideal_cycle_time_s for m in dataset.machines}
    production["total_count"] = production["good_count"] + production["scrap_count"]
    production["ideal_time_s"] = (
        production["machine_id"].map(cycle).astype(float) * production["total_count"]
    )

    # A constant key lets the empty group_by share the same groupby code path.
    group_cols = keys or ["_all"]
    intervals = intervals.assign(_all=0)
    production = production.assign(_all=0)

    durations = intervals["duration_s"].astype(float)
    intervals = intervals.assign(
        total_s=durations,
        planned_stop_s=durations.where(intervals["state"] == MachineState.PLANNED_STOP.value, 0.0),
        run_time_s=durations.where(intervals["state"] == MachineState.RUNNING.value, 0.0),
        downtime_s=durations.where(
            intervals["state"].isin([MachineState.DOWN.value, MachineState.IDLE.value]), 0.0
        ),
    )
    times = intervals.groupby(group_cols, sort=True)[
        ["total_s", "planned_stop_s", "run_time_s", "downtime_s"]
    ].sum()
    counts = production.groupby(group_cols, sort=True)[
        ["total_count", "good_count", "scrap_count", "ideal_time_s"]
    ].sum()
    agg = times.join(counts, how="outer").fillna(0)
    if agg.empty and not keys:
        agg = pd.DataFrame(0.0, index=pd.Index([0], name="_all"), columns=agg.columns)

    planned = (agg["total_s"] - agg["planned_stop_s"]).astype(float)
    run = agg["run_time_s"].astype(float)
    total = agg["total_count"].astype("int64")
    good = agg["good_count"].astype("int64")
    availability = _ratio(run, planned)
    performance = _ratio(agg["ideal_time_s"].astype(float), run).clip(upper=1.0)
    quality = _ratio(good.astype(float), total.astype(float))
    result = pd.DataFrame(
        {
            "planned_time_s": planned,
            "run_time_s": run,
            "downtime_s": agg["downtime_s"].astype(float),
            "total_count": total,
            "good_count": good,
            "scrap_count": agg["scrap_count"].astype("int64"),
            "availability": availability,
            "performance": performance,
            "quality": quality,
            "oee": availability * performance * quality,
        },
        index=agg.index,
    ).reset_index()
    if not keys:
        result = result.drop(columns="_all")
    return result[keys + list(RESULT_COLUMNS)].reset_index(drop=True)


def compute_overall(
    dataset: Dataset,
    shifts: Sequence[Shift] = DEFAULT_SHIFTS,
    end: datetime.datetime | None = None,
) -> OeeResult:
    """Plant-level OEE across all machines, shifts and days."""
    row = compute_oee(dataset, group_by=(), shifts=shifts, end=end).iloc[0]
    return OeeResult(
        **{
            name: int(row[name]) if name.endswith("_count") else float(row[name])
            for name in RESULT_COLUMNS
        }
    )
