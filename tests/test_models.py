import dataclasses
import datetime

import pytest

from oee_analytics import __version__, cli
from oee_analytics.models import Machine, MachineState, Shift


def test_machine_accepts_positive_cycle_time():
    m = Machine("M1", "Press 1", 2.5)
    assert m.ideal_cycle_time_s == 2.5


@pytest.mark.parametrize("cycle", [0, -1.0])
def test_machine_rejects_non_positive_cycle_time(cycle):
    with pytest.raises(ValueError):
        Machine("M1", "Press 1", cycle)


def test_machine_is_frozen():
    m = Machine("M1", "Press 1", 2.5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.name = "other"


def test_machine_state_has_exactly_four_values():
    assert {s.value for s in MachineState} == {"RUNNING", "IDLE", "DOWN", "PLANNED_STOP"}
    assert len(MachineState) == 4
    assert MachineState("DOWN") == "DOWN"


def test_shift_allows_overnight():
    s = Shift("C", datetime.time(22), datetime.time(6))
    assert s.overnight
    assert s.contains(datetime.time(23, 30))
    assert s.contains(datetime.time(5, 59))
    assert not s.contains(datetime.time(6))


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "0.1.0" in capsys.readouterr().out
    assert __version__ == "0.1.0"


def test_cli_no_args_returns_zero():
    assert cli.main([]) == 0
