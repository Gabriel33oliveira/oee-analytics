"""Load and validate the CSV event logs (machines, states, production)."""

from __future__ import annotations

import os
import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from oee_analytics.models import Machine, MachineState

MACHINES_FILE = "machines.csv"
STATES_FILE = "states.csv"
PRODUCTION_FILE = "production.csv"

MACHINE_COLUMNS = ("machine_id", "name", "ideal_cycle_time_s")
STATE_COLUMNS = ("timestamp", "machine_id", "state", "reason_code")
PRODUCTION_COLUMNS = ("timestamp", "machine_id", "good_count", "scrap_count")

_INT_RE = re.compile(r"^[+-]?\d+$")
_VALID_STATES = {s.value for s in MachineState}


class DataValidationError(ValueError):
    """Raised when an input CSV file does not match its expected schema."""


@dataclass(frozen=True)
class Dataset:
    """All inputs needed for an OEE analysis."""

    machines: list[Machine]
    states: pd.DataFrame
    production: pd.DataFrame


def _error(path: Path, row: int | None, problem: str) -> DataValidationError:
    where = f"{path.name}: row {row}" if row is not None else path.name
    return DataValidationError(f"{where}: {problem}")


def _row_number(index: int) -> int:
    """CSV line number of a data row (line 1 is the header)."""
    return index + 2


def _read_csv(path: Path, columns: tuple[str, ...]) -> pd.DataFrame:
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError:
        raise _error(path, None, f"missing columns: {', '.join(columns)}") from None
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise _error(path, None, f"missing columns: {', '.join(missing)}")
    df = df[list(columns)].copy()
    for col in columns:
        df[col] = df[col].str.strip()
    return df.reset_index(drop=True)


def _parse_timestamps(path: Path, values: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(values, format="ISO8601", errors="coerce")
    for i, (raw, ts) in enumerate(zip(values, parsed)):
        if pd.isna(ts):
            raise _error(path, _row_number(i), f"unparseable timestamp {raw!r}")
    return parsed


def _check_machine_ids(
    path: Path, values: pd.Series, machine_ids: Collection[str] | None
) -> None:
    for i, machine_id in enumerate(values):
        if not machine_id:
            raise _error(path, _row_number(i), "missing machine_id")
        if machine_ids is not None and machine_id not in machine_ids:
            raise _error(
                path,
                _row_number(i),
                f"machine_id {machine_id!r} is not defined in {MACHINES_FILE}",
            )


def load_machines(path: str | os.PathLike[str]) -> list[Machine]:
    """Load ``machines.csv`` into a list of :class:`Machine`."""
    path = Path(path)
    df = _read_csv(path, MACHINE_COLUMNS)
    machines: list[Machine] = []
    seen: set[str] = set()
    for i, row in enumerate(df.itertuples(index=False)):
        line = _row_number(i)
        if not row.machine_id:
            raise _error(path, line, "missing machine_id")
        if row.machine_id in seen:
            raise _error(path, line, f"duplicate machine_id {row.machine_id!r}")
        try:
            cycle = float(row.ideal_cycle_time_s)
        except ValueError:
            raise _error(
                path, line, f"ideal_cycle_time_s {row.ideal_cycle_time_s!r} is not a number"
            ) from None
        try:
            machines.append(Machine(row.machine_id, row.name, cycle))
        except ValueError as exc:
            raise _error(path, line, str(exc)) from None
        seen.add(row.machine_id)
    return machines


def load_states(
    path: str | os.PathLike[str], machine_ids: Collection[str] | None = None
) -> pd.DataFrame:
    """Load ``states.csv``, sorted by machine_id then timestamp.

    Each row is a state change that lasts until the next row for the same machine.
    ``reason_code`` is required for DOWN rows and must be empty otherwise; empty
    reason codes are returned as ``None``. If ``machine_ids`` is given, every
    machine_id must be one of them.
    """
    path = Path(path)
    df = _read_csv(path, STATE_COLUMNS)
    df["timestamp"] = _parse_timestamps(path, df["timestamp"])
    _check_machine_ids(path, df["machine_id"], machine_ids)
    for i, (state, reason) in enumerate(zip(df["state"], df["reason_code"])):
        line = _row_number(i)
        if state not in _VALID_STATES:
            raise _error(
                path,
                line,
                f"unknown state {state!r} (expected one of {', '.join(sorted(_VALID_STATES))})",
            )
        if state == MachineState.DOWN.value and not reason:
            raise _error(path, line, "missing reason_code for DOWN state")
        if state != MachineState.DOWN.value and reason:
            raise _error(path, line, f"unexpected reason_code {reason!r} for {state} state")
    df["reason_code"] = pd.Series(
        [r or None for r in df["reason_code"]], index=df.index, dtype=object
    )
    return df.sort_values(["machine_id", "timestamp"], kind="stable").reset_index(drop=True)


def load_production(
    path: str | os.PathLike[str], machine_ids: Collection[str] | None = None
) -> pd.DataFrame:
    """Load ``production.csv``, sorted by machine_id then timestamp.

    Counts must be non-negative integers. If ``machine_ids`` is given, every
    machine_id must be one of them.
    """
    path = Path(path)
    df = _read_csv(path, PRODUCTION_COLUMNS)
    df["timestamp"] = _parse_timestamps(path, df["timestamp"])
    _check_machine_ids(path, df["machine_id"], machine_ids)
    for col in ("good_count", "scrap_count"):
        for i, raw in enumerate(df[col]):
            if not _INT_RE.match(raw):
                raise _error(path, _row_number(i), f"{col} {raw!r} is not an integer")
            if int(raw) < 0:
                raise _error(path, _row_number(i), f"{col} {raw} is negative")
        df[col] = df[col].astype("int64")
    return df.sort_values(["machine_id", "timestamp"], kind="stable").reset_index(drop=True)


def load_dataset(directory: str | os.PathLike[str]) -> Dataset:
    """Load and cross-validate the three CSV files in ``directory``."""
    directory = Path(directory)
    machines = load_machines(directory / MACHINES_FILE)
    machine_ids = {m.machine_id for m in machines}
    states = load_states(directory / STATES_FILE, machine_ids)
    production = load_production(directory / PRODUCTION_FILE, machine_ids)
    return Dataset(machines=machines, states=states, production=production)
