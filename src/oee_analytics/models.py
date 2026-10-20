"""Core domain models."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import Enum


class MachineState(str, Enum):
    """Possible states reported by a machine in the event log."""

    RUNNING = "RUNNING"
    IDLE = "IDLE"
    DOWN = "DOWN"
    PLANNED_STOP = "PLANNED_STOP"


@dataclass(frozen=True)
class Machine:
    """A machine with its ideal (theoretical fastest) cycle time per part."""

    machine_id: str
    name: str
    ideal_cycle_time_s: float

    def __post_init__(self) -> None:
        if not self.ideal_cycle_time_s > 0:
            raise ValueError(
                f"ideal_cycle_time_s must be > 0, got {self.ideal_cycle_time_s!r}"
            )


@dataclass(frozen=True)
class Shift:
    """A named daily shift. ``end`` earlier than ``start`` means it crosses midnight."""

    name: str
    start: datetime.time
    end: datetime.time

    @property
    def overnight(self) -> bool:
        return self.end <= self.start

    def contains(self, t: datetime.time) -> bool:
        """Return True if the time of day ``t`` falls in [start, end)."""
        if self.overnight:
            return t >= self.start or t < self.end
        return self.start <= t < self.end
