import datetime

import pytest

from oee_analytics.generator import (
    REASON_CODES,
    GeneratorConfig,
    generate,
    write_dataset,
)
from oee_analytics.io import MACHINES_FILE, PRODUCTION_FILE, STATES_FILE, load_dataset

FILES = (MACHINES_FILE, STATES_FILE, PRODUCTION_FILE)
START = datetime.datetime(2026, 3, 2, 6, 0)


def _write(tmp_path, name, config):
    directory = tmp_path / name
    write_dataset(generate(config), directory)
    return directory


def _read_bytes(directory):
    return {f: (directory / f).read_bytes() for f in FILES}


@pytest.fixture(scope="module")
def config():
    return GeneratorConfig(start=START, days=3, seed=7)


@pytest.fixture
def dataset(tmp_path, config):
    return load_dataset(_write(tmp_path, "plant", config))


def test_same_seed_produces_identical_bytes(tmp_path):
    first = _read_bytes(_write(tmp_path, "a", GeneratorConfig(days=2, seed=1)))
    second = _read_bytes(_write(tmp_path, "b", GeneratorConfig(days=2, seed=1)))
    assert first == second


def test_different_seeds_produce_different_output(tmp_path):
    first = _read_bytes(_write(tmp_path, "a", GeneratorConfig(days=2, seed=1)))
    second = _read_bytes(_write(tmp_path, "b", GeneratorConfig(days=2, seed=2)))
    assert first[STATES_FILE] != second[STATES_FILE]
    assert first[PRODUCTION_FILE] != second[PRODUCTION_FILE]


def test_three_day_run_loads_through_load_dataset(dataset):
    assert len(dataset.states) > 0
    assert len(dataset.production) > 0


def test_default_plant_has_four_machines(dataset):
    machines = dataset.machines
    assert [m.machine_id for m in machines] == ["M1", "M2", "M3", "M4"]
    assert len({m.name for m in machines}) == 4
    assert len({m.ideal_cycle_time_s for m in machines}) == 4


def test_down_rows_have_known_reason_codes(dataset):
    states = dataset.states
    down = states[states["state"] == "DOWN"]
    assert down["reason_code"].notna().all()
    assert set(down["reason_code"]) <= set(REASON_CODES)
    assert down["reason_code"].nunique() >= 4
    assert states.loc[states["state"] != "DOWN", "reason_code"].isna().all()


def test_one_planned_stop_per_machine_per_day(dataset, config):
    stops = dataset.states[dataset.states["state"] == "PLANNED_STOP"]
    for machine in dataset.machines:
        times = stops.loc[stops["machine_id"] == machine.machine_id, "timestamp"]
        days = ((times - START) // datetime.timedelta(days=1)).tolist()
        assert sorted(days) == list(range(config.days))


def test_production_never_exceeds_running_time(dataset, config):
    states, production = dataset.states, dataset.production
    for machine in dataset.machines:
        rows = states[states["machine_id"] == machine.machine_id]
        ends = rows["timestamp"].shift(-1).fillna(config.end)
        durations = (ends - rows["timestamp"]).dt.total_seconds()
        running_seconds = durations[rows["state"] == "RUNNING"].sum()
        counts = production[production["machine_id"] == machine.machine_id]
        produced = int(counts["good_count"].sum() + counts["scrap_count"].sum())
        assert produced > 0
        assert produced * machine.ideal_cycle_time_s <= running_seconds


def test_first_state_starts_at_configured_start(dataset):
    first = dataset.states.groupby("machine_id")["timestamp"].min()
    assert len(first) == 4
    assert (first == START).all()


def test_generate_returns_validated_dataset(config):
    ds = generate(config)
    assert {m.machine_id for m in ds.machines} == set(ds.states["machine_id"])


def test_invalid_days_rejected():
    with pytest.raises(ValueError):
        GeneratorConfig(days=0)
