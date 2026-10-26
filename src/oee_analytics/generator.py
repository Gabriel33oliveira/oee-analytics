"""Seeded synthetic plant data generator.

Simulates a small plant and produces the three CSV inputs (machines, states,
production). The same :class:`GeneratorConfig` always yields the same data.

Each machine's timeline alternates RUNNING periods with IDLE and DOWN events,
and has one 30-minute PLANNED_STOP per day for maintenance. The final state of
each machine lasts until ``config.end``. Production is reported in intervals of
at most 15 minutes of RUNNING time, at 75-98% of the ideal rate.
"""

from __future__ import annotations

import datetime
import math
import os
import random
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from oee_analytics.io import (
    MACHINE_COLUMNS,
    MACHINES_FILE,
    PRODUCTION_COLUMNS,
    PRODUCTION_FILE,
    STATE_COLUMNS,
    STATES_FILE,
    Dataset,
    load_dataset,
)
from oee_analytics.models import Machine, MachineState, Shift
from oee_analytics.shifts import DEFAULT_SHIFTS, shift_for

# Weights are deliberately skewed so the downtime Pareto has a clear head.
REASON_CODES: dict[str, float] = {
    "MECHANICAL_FAILURE": 35,
    "MATERIAL_SHORTAGE": 22,
    "CHANGEOVER": 15,
    "NO_OPERATOR": 12,
    "QUALITY_HOLD": 9,
    "ELECTRICAL_FAULT": 7,
}

# Mean DOWN duration in minutes per reason code.
_DOWN_MINUTES: dict[str, float] = {
    "MECHANICAL_FAILURE": 45,
    "MATERIAL_SHORTAGE": 25,
    "CHANGEOVER": 30,
    "NO_OPERATOR": 20,
    "QUALITY_HOLD": 35,
    "ELECTRICAL_FAULT": 40,
}

# Shift effects: >1 reliability means longer RUNNING periods; scrap is a base rate.
_SHIFT_RELIABILITY = {"A": 1.0, "B": 0.9, "C": 0.75}
_SHIFT_SCRAP_RATE = {"A": 0.015, "B": 0.02, "C": 0.04}
_DEFAULT_RELIABILITY = 0.9
_DEFAULT_SCRAP_RATE = 0.02

_MEAN_RUNNING_MINUTES = 90
_IDLE_PROBABILITY = 0.35
_PLANNED_STOP = datetime.timedelta(minutes=30)
_PRODUCTION_INTERVAL = datetime.timedelta(minutes=15)
_SPEED_RANGE = (0.75, 0.98)
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"

DEFAULT_MACHINES: tuple[Machine, ...] = (
    Machine("M1", "Stamping Press", 30),
    Machine("M2", "CNC Lathe", 45),
    Machine("M3", "Injection Molder", 60),
    Machine("M4", "Assembly Cell", 90),
)


@dataclass(frozen=True)
class GeneratorConfig:
    """Parameters of a synthetic plant simulation."""

    start: datetime.datetime = datetime.datetime(2026, 1, 5, 6, 0)
    days: int = 7
    seed: int = 42
    machines: Sequence[Machine] = field(default_factory=lambda: DEFAULT_MACHINES)
    shifts: Sequence[Shift] = field(default_factory=lambda: DEFAULT_SHIFTS)

    def __post_init__(self) -> None:
        if self.days < 1:
            raise ValueError(f"days must be >= 1, got {self.days!r}")
        if not self.machines:
            raise ValueError("at least one machine is required")

    @property
    def end(self) -> datetime.datetime:
        """End of the simulated period: ``start`` plus ``days``."""
        return self.start + datetime.timedelta(days=self.days)


@dataclass(frozen=True)
class _Segment:
    start: datetime.datetime
    end: datetime.datetime
    state: MachineState
    reason: str | None = None


def _minutes(rng: random.Random, mean: float, low: float, high: float) -> datetime.timedelta:
    """Exponentially distributed duration, clipped and rounded to whole minutes."""
    value = min(max(rng.expovariate(1 / mean), low), high)
    return datetime.timedelta(minutes=round(value))


def _fill(
    rng: random.Random,
    start: datetime.datetime,
    end: datetime.datetime,
    reliability: float,
    shifts: Sequence[Shift],
) -> list[_Segment]:
    """Alternate RUNNING with IDLE/DOWN events over [start, end), starting RUNNING."""
    segments: list[_Segment] = []
    t = start
    running = True
    codes, weights = list(REASON_CODES), list(REASON_CODES.values())
    while t < end:
        shift = shift_for(t, shifts)
        if running:
            mean = _MEAN_RUNNING_MINUTES * reliability * _SHIFT_RELIABILITY.get(
                shift, _DEFAULT_RELIABILITY
            )
            duration = _minutes(rng, mean, 20, 240)
            state, reason = MachineState.RUNNING, None
        elif rng.random() < _IDLE_PROBABILITY:
            duration = _minutes(rng, 10, 5, 30)
            state, reason = MachineState.IDLE, None
        else:
            reason = rng.choices(codes, weights)[0]
            duration = _minutes(rng, _DOWN_MINUTES[reason], 5, 180)
            state = MachineState.DOWN
        seg_end = min(t + duration, end)
        segments.append(_Segment(t, seg_end, state, reason))
        t = seg_end
        running = not running
    return segments


def _merge(segments: list[_Segment]) -> list[_Segment]:
    """Join adjacent segments with the same state and reason."""
    merged: list[_Segment] = []
    for seg in segments:
        prev = merged[-1] if merged else None
        if prev and prev.state == seg.state and prev.reason == seg.reason and prev.end == seg.start:
            merged[-1] = _Segment(prev.start, seg.end, prev.state, prev.reason)
        else:
            merged.append(seg)
    return merged


def _timeline(
    rng: random.Random, config: GeneratorConfig, index: int, reliability: float
) -> list[_Segment]:
    segments: list[_Segment] = []
    # Stagger maintenance so machines are not all stopped at the same time.
    stop_offset = datetime.timedelta(hours=2 + 5 * (index % 4), minutes=15 * (index // 4))
    for day in range(config.days):
        day_start = config.start + datetime.timedelta(days=day)
        day_end = day_start + datetime.timedelta(days=1)
        stop_start = day_start + stop_offset
        stop_end = stop_start + _PLANNED_STOP
        segments += _fill(rng, day_start, stop_start, reliability, config.shifts)
        segments.append(_Segment(stop_start, stop_end, MachineState.PLANNED_STOP))
        segments += _fill(rng, stop_end, day_end, reliability, config.shifts)
    return _merge(segments)


def _production_rows(
    rng: random.Random,
    machine: Machine,
    segments: list[_Segment],
    scrap_factor: float,
    shifts: Sequence[Shift],
) -> list[tuple[datetime.datetime, int, int]]:
    """Counts for each RUNNING interval, cut at 15-minute wall-clock boundaries."""
    rows: list[tuple[datetime.datetime, int, int]] = []
    for seg in segments:
        if seg.state != MachineState.RUNNING:
            continue
        t = seg.start
        while t < seg.end:
            midnight = datetime.datetime.combine(t.date(), datetime.time(), tzinfo=t.tzinfo)
            steps = math.floor((t - midnight) / _PRODUCTION_INTERVAL) + 1
            chunk_end = min(midnight + steps * _PRODUCTION_INTERVAL, seg.end)
            seconds = (chunk_end - t).total_seconds()
            speed = rng.uniform(*_SPEED_RANGE)
            total = math.floor(seconds * speed / machine.ideal_cycle_time_s)
            if total > 0:
                rate = _SHIFT_SCRAP_RATE.get(shift_for(t, shifts), _DEFAULT_SCRAP_RATE)
                rate *= scrap_factor
                scrap = sum(rng.random() < rate for _ in range(total))
                rows.append((chunk_end, total - scrap, scrap))
            t = chunk_end
    return rows


def _fmt(ts: datetime.datetime) -> str:
    return ts.strftime(_TIMESTAMP_FORMAT)


def _fmt_number(value: float) -> str:
    return f"{value:g}"


def _write_csv(path: Path, header: Sequence[str], rows: list[Sequence[str]]) -> None:
    lines = [",".join(header)] + [",".join(row) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")


def _write_files(
    directory: Path,
    machines: Sequence[Machine],
    states: list[Sequence[str]],
    production: list[Sequence[str]],
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    machine_rows = [
        (m.machine_id, m.name, _fmt_number(m.ideal_cycle_time_s)) for m in machines
    ]
    _write_csv(directory / MACHINES_FILE, MACHINE_COLUMNS, machine_rows)
    _write_csv(directory / STATES_FILE, STATE_COLUMNS, states)
    _write_csv(directory / PRODUCTION_FILE, PRODUCTION_COLUMNS, production)


def generate(config: GeneratorConfig | None = None) -> Dataset:
    """Simulate the plant described by ``config`` and return a validated Dataset."""
    config = config or GeneratorConfig()
    rng = random.Random(config.seed)
    state_rows: list[Sequence[str]] = []
    production_rows: list[Sequence[str]] = []
    for index, machine in enumerate(config.machines):
        reliability = rng.uniform(0.8, 1.2)
        scrap_factor = rng.uniform(0.7, 1.5)
        segments = _timeline(rng, config, index, reliability)
        for seg in segments:
            state_rows.append(
                (_fmt(seg.start), machine.machine_id, seg.state.value, seg.reason or "")
            )
        for ts, good, scrap in _production_rows(
            rng, machine, segments, scrap_factor, config.shifts
        ):
            production_rows.append((_fmt(ts), machine.machine_id, str(good), str(scrap)))
    # Round-trip through the loaders so generated data always passes validation.
    with tempfile.TemporaryDirectory() as tmp:
        _write_files(Path(tmp), config.machines, state_rows, production_rows)
        return load_dataset(tmp)


def write_dataset(dataset: Dataset, directory: str | os.PathLike[str]) -> None:
    """Write ``dataset`` as machines.csv, states.csv and production.csv in ``directory``."""
    states = [
        (_fmt(row.timestamp), row.machine_id, row.state, row.reason_code or "")
        for row in dataset.states.itertuples(index=False)
    ]
    production = [
        (_fmt(row.timestamp), row.machine_id, str(row.good_count), str(row.scrap_count))
        for row in dataset.production.itertuples(index=False)
    ]
    _write_files(Path(directory), dataset.machines, states, production)
