import shutil
from pathlib import Path

import pandas as pd
import pytest

from oee_analytics.io import (
    DataValidationError,
    Dataset,
    load_dataset,
    load_machines,
    load_production,
    load_states,
)
from oee_analytics.models import Machine

VALID = Path(__file__).parent / "fixtures" / "valid"

STATES_HEADER = "timestamp,machine_id,state,reason_code\n"
PRODUCTION_HEADER = "timestamp,machine_id,good_count,scrap_count\n"


@pytest.fixture
def dataset_dir(tmp_path):
    """A writable copy of the valid fixture directory."""
    target = tmp_path / "data"
    shutil.copytree(VALID, target)
    return target


def test_load_valid_dataset():
    ds = load_dataset(VALID)

    assert isinstance(ds, Dataset)
    assert ds.machines == [Machine("M1", "Press 1", 30.0), Machine("M2", "Lathe 2", 45.5)]
    assert len(ds.states) == 8
    assert len(ds.production) == 5
    assert pd.api.types.is_datetime64_any_dtype(ds.states["timestamp"])
    assert pd.api.types.is_datetime64_any_dtype(ds.production["timestamp"])
    assert pd.api.types.is_integer_dtype(ds.production["good_count"])
    assert pd.api.types.is_integer_dtype(ds.production["scrap_count"])


def test_states_are_sorted_by_machine_then_timestamp():
    states = load_states(VALID / "states.csv")

    expected = states.sort_values(["machine_id", "timestamp"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(states, expected)
    assert list(states["machine_id"]) == ["M1"] * 3 + ["M2"] * 5
    assert states.loc[0, "timestamp"] == pd.Timestamp("2026-01-05T06:00:00")


def test_reason_code_only_on_down_rows():
    states = load_states(VALID / "states.csv")

    down = states["state"] == "DOWN"
    assert states.loc[down, "reason_code"].notna().all()
    assert states.loc[~down, "reason_code"].isna().all()


def test_production_counts():
    production = load_production(VALID / "production.csv")

    assert production["good_count"].sum() == 430
    assert production["scrap_count"].sum() == 6


def _assert_invalid(path, loader, *fragments):
    with pytest.raises(DataValidationError) as excinfo:
        loader(path)
    message = str(excinfo.value)
    assert path.name in message
    for fragment in fragments:
        assert fragment in message
    return message


def test_missing_column(tmp_path):
    path = tmp_path / "states.csv"
    path.write_text("timestamp,machine_id,state\n2026-01-05T06:00:00,M1,RUNNING\n")

    _assert_invalid(path, load_states, "missing columns", "reason_code")


def test_missing_machine_column(tmp_path):
    path = tmp_path / "machines.csv"
    path.write_text("machine_id,name\nM1,Press 1\n")

    _assert_invalid(path, load_machines, "ideal_cycle_time_s")


def test_bad_timestamp(tmp_path):
    path = tmp_path / "states.csv"
    path.write_text(
        STATES_HEADER
        + "2026-01-05T06:00:00,M1,RUNNING,\n"
        + "yesterday at noon,M1,IDLE,\n"
    )

    _assert_invalid(path, load_states, "row 3", "timestamp", "yesterday at noon")


def test_unknown_state(tmp_path):
    path = tmp_path / "states.csv"
    path.write_text(STATES_HEADER + "2026-01-05T06:00:00,M1,EXPLODED,\n")

    _assert_invalid(path, load_states, "row 2", "unknown state", "EXPLODED")


def test_down_without_reason_code(tmp_path):
    path = tmp_path / "states.csv"
    path.write_text(STATES_HEADER + "2026-01-05T06:00:00,M1,DOWN,\n")

    _assert_invalid(path, load_states, "row 2", "missing reason_code")


def test_running_with_reason_code(tmp_path):
    path = tmp_path / "states.csv"
    path.write_text(STATES_HEADER + "2026-01-05T06:00:00,M1,RUNNING,JAM\n")

    _assert_invalid(path, load_states, "row 2", "unexpected reason_code", "JAM")


def test_negative_scrap_count(tmp_path):
    path = tmp_path / "production.csv"
    path.write_text(
        PRODUCTION_HEADER
        + "2026-01-05T07:00:00,M1,10,0\n"
        + "2026-01-05T08:00:00,M1,10,-2\n"
    )

    _assert_invalid(path, load_production, "row 3", "scrap_count", "negative")


def test_non_integer_count(tmp_path):
    path = tmp_path / "production.csv"
    path.write_text(PRODUCTION_HEADER + "2026-01-05T07:00:00,M1,10.5,0\n")

    _assert_invalid(path, load_production, "row 2", "good_count", "not an integer")


def test_unknown_machine_id_in_states(dataset_dir):
    path = dataset_dir / "states.csv"
    with path.open("a") as f:
        f.write("2026-01-05T14:00:00,M9,RUNNING,\n")

    message = _assert_invalid(path, lambda _: load_dataset(dataset_dir), "M9")
    assert "row 10" in message
    assert "machines.csv" in message


def test_unknown_machine_id_in_production(dataset_dir):
    path = dataset_dir / "production.csv"
    with path.open("a") as f:
        f.write("2026-01-05T14:00:00,M9,5,0\n")

    _assert_invalid(path, lambda _: load_dataset(dataset_dir), "row 7", "M9")


def test_invalid_cycle_time(tmp_path):
    path = tmp_path / "machines.csv"
    path.write_text("machine_id,name,ideal_cycle_time_s\nM1,Press 1,0\n")

    _assert_invalid(path, load_machines, "row 2", "ideal_cycle_time_s")


def test_data_validation_error_is_value_error():
    assert issubclass(DataValidationError, ValueError)
