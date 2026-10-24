import datetime

import pandas as pd
import pytest

from oee_analytics.analysis import (
    PARETO_COLUMNS,
    compare_machines,
    compare_shifts,
    downtime_pareto,
    format_table,
)
from oee_analytics.generator import GeneratorConfig, generate
from oee_analytics.io import Dataset
from oee_analytics.metrics import compute_overall
from oee_analytics.models import Machine

DAY = datetime.date(2026, 3, 2)


def ts(hour, minute=0):
    return pd.Timestamp(datetime.datetime.combine(DAY, datetime.time(hour, minute)))


END = ts(16)


def handcrafted_dataset():
    """Known DOWN durations, 06:00-16:00 (shift A until 14:00, then B).

    M1: MECHANICAL 60 min (A), MATERIAL 20 min (A), MECHANICAL 13:30-14:30 (30 A + 30 B)
    M2: CHANGEOVER 45 min (A), MATERIAL 10 min (B)
    """
    rows = [
        (ts(6), "M1", "RUNNING", None),
        (ts(7), "M1", "DOWN", "MECHANICAL_FAILURE"),
        (ts(8), "M1", "RUNNING", None),
        (ts(9), "M1", "DOWN", "MATERIAL_SHORTAGE"),
        (ts(9, 20), "M1", "RUNNING", None),
        (ts(13, 30), "M1", "DOWN", "MECHANICAL_FAILURE"),
        (ts(14, 30), "M1", "RUNNING", None),
        (ts(6), "M2", "RUNNING", None),
        (ts(10), "M2", "DOWN", "CHANGEOVER"),
        (ts(10, 45), "M2", "RUNNING", None),
        (ts(15), "M2", "DOWN", "MATERIAL_SHORTAGE"),
        (ts(15, 10), "M2", "RUNNING", None),
    ]
    states = pd.DataFrame(rows, columns=["timestamp", "machine_id", "state", "reason_code"])
    production = pd.DataFrame(
        [(ts(12), "M1", 500, 10), (ts(12), "M2", 300, 5)],
        columns=["timestamp", "machine_id", "good_count", "scrap_count"],
    )
    machines = [Machine("M1", "Press", 30), Machine("M2", "Lathe", 45)]
    return Dataset(machines, states, production)


def as_dict(pareto):
    return dict(zip(pareto["reason_code"], pareto["downtime_min"]))


def test_pareto_totals_and_order():
    pareto = downtime_pareto(handcrafted_dataset(), end=END)
    assert list(pareto.columns) == list(PARETO_COLUMNS)
    assert list(pareto["reason_code"]) == ["MECHANICAL_FAILURE", "CHANGEOVER", "MATERIAL_SHORTAGE"]
    assert list(pareto["downtime_min"]) == pytest.approx([120, 45, 30])
    assert list(pareto["events"]) == [2, 1, 2]
    assert pareto["share_pct"].sum() == pytest.approx(100.0)
    assert pareto["downtime_min"].is_monotonic_decreasing
    assert pareto["cumulative_pct"].is_monotonic_increasing
    assert pareto["cumulative_pct"].iloc[-1] == pytest.approx(100.0)
    assert pareto["share_pct"].iloc[0] == pytest.approx(120 / 195 * 100)


def test_pareto_machine_filter():
    ds = handcrafted_dataset()
    assert as_dict(downtime_pareto(ds, machine_id="M1", end=END)) == pytest.approx(
        {"MECHANICAL_FAILURE": 120, "MATERIAL_SHORTAGE": 20}
    )
    m2 = downtime_pareto(ds, machine_id="M2", end=END)
    assert as_dict(m2) == pytest.approx({"CHANGEOVER": 45, "MATERIAL_SHORTAGE": 10})
    assert m2["cumulative_pct"].iloc[-1] == pytest.approx(100.0)


def test_pareto_shift_filter_splits_crossing_event():
    ds = handcrafted_dataset()
    a = downtime_pareto(ds, shift="A", end=END)
    assert as_dict(a) == pytest.approx(
        {"MECHANICAL_FAILURE": 90, "CHANGEOVER": 45, "MATERIAL_SHORTAGE": 20}
    )
    assert dict(zip(a["reason_code"], a["events"]))["MECHANICAL_FAILURE"] == 2
    b = downtime_pareto(ds, shift="B", end=END)
    assert as_dict(b) == pytest.approx({"MECHANICAL_FAILURE": 30, "MATERIAL_SHORTAGE": 10})
    both = downtime_pareto(ds, machine_id="M2", shift="B", end=END)
    assert as_dict(both) == pytest.approx({"MATERIAL_SHORTAGE": 10})


def test_pareto_no_downtime_is_empty():
    pareto = downtime_pareto(handcrafted_dataset(), machine_id="M9", end=END)
    assert pareto.empty
    assert list(pareto.columns) == list(PARETO_COLUMNS)


@pytest.fixture(scope="module")
def generated():
    config = GeneratorConfig(days=3, seed=7)
    return generate(config), config.end


def test_compare_machines_ranks(generated):
    ds, end = generated
    table = compare_machines(ds, end=end)
    assert sorted(table["rank"]) == [1, 2, 3, 4]
    best = table.loc[table["rank"] == 1, "oee"].iloc[0]
    assert best == table["oee"].max()
    assert table["oee"].is_monotonic_decreasing


def test_oee_delta_pts_vs_plant(generated):
    ds, end = generated
    plant = compute_overall(ds, end=end).oee
    for table in (compare_machines(ds, end=end), compare_shifts(ds, end=end)):
        expected = (table["oee"] - plant) * 100
        assert list(table["oee_delta_pts"]) == pytest.approx(list(expected))
    shifts = compare_shifts(ds, end=end)
    assert sorted(shifts["shift"]) == ["A", "B", "C"]
    assert sorted(shifts["rank"]) == [1, 2, 3]


def test_format_table_aligns_and_formats_ratios():
    df = pd.DataFrame(
        {"machine_id": ["M1", "M10"], "oee": [0.8567, 0.5], "downtime_min": [12.345, 3.0]}
    )
    lines = format_table(df).splitlines()
    assert lines[0].split() == ["machine_id", "oee", "downtime_min"]
    assert "85.7%" in lines[2] and "50.0%" in lines[3]
    assert "12.3" in lines[2]
    assert len({len(line) for line in lines}) == 1
