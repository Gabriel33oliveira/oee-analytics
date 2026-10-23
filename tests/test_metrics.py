import datetime
import math

import pandas as pd
import pytest

from oee_analytics.generator import GeneratorConfig, generate
from oee_analytics.io import Dataset
from oee_analytics.metrics import (
    OeeResult,
    compute_oee,
    compute_overall,
    split_by_shift,
    state_intervals,
)
from oee_analytics.models import Machine

DAY = datetime.date(2026, 3, 2)


def ts(hour, minute=0, day=0):
    return pd.Timestamp(datetime.datetime.combine(DAY, datetime.time(hour, minute))) + pd.Timedelta(
        days=day
    )


def states_df(rows):
    return pd.DataFrame(
        [
            {"timestamp": t, "machine_id": m, "state": s, "reason_code": r}
            for t, m, s, r in rows
        ],
        columns=["timestamp", "machine_id", "state", "reason_code"],
    )


def production_df(rows):
    df = pd.DataFrame(
        [{"timestamp": t, "machine_id": m, "good_count": g, "scrap_count": s} for t, m, g, s in rows],
        columns=["timestamp", "machine_id", "good_count", "scrap_count"],
    )
    return df.astype({"good_count": "int64", "scrap_count": "int64"})


def single_machine_dataset():
    """M1 from 06:00 to 14:00: 30 min PLANNED_STOP, 45 min DOWN, the rest RUNNING."""
    states = states_df(
        [
            (ts(6), "M1", "RUNNING", None),
            (ts(8), "M1", "PLANNED_STOP", None),
            (ts(8, 30), "M1", "RUNNING", None),
            (ts(10), "M1", "DOWN", "MECHANICAL_FAILURE"),
            (ts(10, 45), "M1", "RUNNING", None),
        ]
    )
    production = production_df([(ts(10), "M1", 400, 20), (ts(13, 59), "M1", 300, 9)])
    return Dataset([Machine("M1", "Press", 30)], states, production)


def test_single_machine_oee_by_hand():
    result = compute_oee(single_machine_dataset(), end=ts(14))
    assert len(result) == 1
    row = result.iloc[0]
    planned = 8 * 3600 - 30 * 60  # 27000
    run = planned - 45 * 60  # 24300
    assert row["machine_id"] == "M1"
    assert row["planned_time_s"] == pytest.approx(planned)
    assert row["run_time_s"] == pytest.approx(run)
    assert row["downtime_s"] == pytest.approx(45 * 60)
    assert (row["total_count"], row["good_count"], row["scrap_count"]) == (729, 700, 29)
    assert row["availability"] == pytest.approx(0.9)
    assert row["performance"] == pytest.approx(729 * 30 / run)  # 0.9
    assert row["quality"] == pytest.approx(700 / 729)
    assert row["oee"] == pytest.approx(0.9 * 0.9 * 700 / 729)


def test_state_intervals_last_state_ends_at_end():
    states = states_df(
        [
            (ts(6), "M1", "RUNNING", None),
            (ts(7), "M1", "DOWN", "CHANGEOVER"),
            (ts(6, 30), "M2", "IDLE", None),
        ]
    )
    out = state_intervals(states, ts(8))
    assert list(out.columns) == ["machine_id", "state", "reason_code", "start", "end", "duration_s"]
    assert out["machine_id"].tolist() == ["M1", "M1", "M2"]
    assert out["end"].tolist() == [ts(7), ts(8), ts(8)]
    assert out["duration_s"].tolist() == [3600, 3600, 5400]
    assert out["reason_code"].tolist()[1] == "CHANGEOVER"


def test_split_interval_across_shift_boundary():
    intervals = state_intervals(states_df([(ts(13), "M1", "RUNNING", None)]), ts(15))
    out = split_by_shift(intervals)
    assert out["shift"].tolist() == ["A", "B"]
    assert out["duration_s"].tolist() == [3600, 3600]
    assert out["start"].tolist() == [ts(13), ts(14)]
    assert out["end"].tolist() == [ts(14), ts(15)]
    assert out["date"].tolist() == [DAY, DAY]


def test_overnight_interval_dated_by_c_shift_start():
    # 23:00 -> 05:00 next day lies entirely in the C shift that started on DAY.
    intervals = state_intervals(states_df([(ts(23), "M1", "RUNNING", None)]), ts(5, day=1))
    out = split_by_shift(intervals)
    assert out["shift"].tolist() == ["C"]
    assert out["date"].tolist() == [DAY]
    assert out["duration_s"].sum() == 6 * 3600

    # A piece that starts after midnight still belongs to the previous day's C shift.
    intervals = state_intervals(
        states_df([(ts(2, day=1), "M1", "DOWN", "NO_OPERATOR")]), ts(7, day=1)
    )
    out = split_by_shift(intervals)
    assert out["shift"].tolist() == ["C", "A"]
    assert out["date"].tolist() == [DAY, DAY + datetime.timedelta(days=1)]


def test_production_assigned_to_shift_by_timestamp():
    states = states_df([(ts(23), "M1", "RUNNING", None)])
    production = production_df([(ts(23, 30), "M1", 10, 0), (ts(1, day=1), "M1", 5, 1)])
    ds = Dataset([Machine("M1", "Press", 60)], states, production)
    result = compute_oee(ds, group_by=("shift", "date"), end=ts(2, day=1))
    assert len(result) == 1
    row = result.iloc[0]
    assert (row["shift"], row["date"], row["total_count"]) == ("C", DAY, 16)


def two_machine_dataset():
    states = states_df(
        [
            (ts(12), "M1", "RUNNING", None),
            (ts(15), "M1", "DOWN", "CHANGEOVER"),
            (ts(12), "M2", "RUNNING", None),
            (ts(13), "M2", "IDLE", None),
            (ts(15), "M2", "PLANNED_STOP", None),
        ]
    )
    production = production_df(
        [
            (ts(13), "M1", 100, 0),
            (ts(15), "M1", 200, 0),
            (ts(12, 30), "M2", 50, 10),
        ]
    )
    machines = [Machine("M1", "Press", 30), Machine("M2", "Lathe", 30)]
    return Dataset(machines, states, production)


def test_group_by_machine_and_shift_one_row_per_combination():
    result = compute_oee(two_machine_dataset(), group_by=("machine_id", "shift"), end=ts(16))
    combos = list(zip(result["machine_id"], result["shift"]))
    assert combos == [("M1", "A"), ("M1", "B"), ("M2", "A"), ("M2", "B")]
    by_key = result.set_index(["machine_id", "shift"])
    assert by_key.loc[("M1", "A"), "run_time_s"] == 2 * 3600
    assert by_key.loc[("M1", "B"), "run_time_s"] == 3600
    assert by_key.loc[("M1", "B"), "downtime_s"] == 3600
    assert by_key.loc[("M2", "B"), "downtime_s"] == 3600
    assert by_key.loc[("M2", "B"), "planned_time_s"] == 3600
    assert by_key.loc[("M1", "A"), "total_count"] == 100
    assert by_key.loc[("M1", "B"), "total_count"] == 200


def test_plant_level_sums_times_and_counts():
    ds = two_machine_dataset()
    result = compute_oee(ds, group_by=(), end=ts(16))
    assert len(result) == 1
    assert "machine_id" not in result.columns
    row = result.iloc[0]
    # M1: planned 4h, run 3h, 300 parts. M2: planned 3h, run 1h, 60 parts (10 scrap).
    planned, run = 7 * 3600, 4 * 3600
    availability = run / planned
    performance = 360 * 30 / run
    quality = 350 / 360
    assert row["planned_time_s"] == planned
    assert row["run_time_s"] == run
    assert row["availability"] == pytest.approx(availability)
    assert row["performance"] == pytest.approx(performance)
    assert row["quality"] == pytest.approx(quality)
    assert row["oee"] == pytest.approx(availability * performance * quality)

    per_machine = compute_oee(ds, end=ts(16))
    assert row["oee"] != pytest.approx(per_machine["oee"].mean())

    overall = compute_overall(ds, end=ts(16))
    assert isinstance(overall, OeeResult)
    assert overall.oee == pytest.approx(row["oee"])
    assert overall.total_count == 360


def test_zero_run_time_gives_zero_not_nan():
    states = states_df(
        [(ts(6), "M1", "DOWN", "ELECTRICAL_FAULT"), (ts(6), "M2", "PLANNED_STOP", None)]
    )
    ds = Dataset(
        [Machine("M1", "Press", 30), Machine("M2", "Lathe", 30)], states, production_df([])
    )
    result = compute_oee(ds, end=ts(8))
    for col in ("availability", "performance", "quality", "oee"):
        assert result[col].tolist() == [0.0, 0.0]
    assert result.loc[result["machine_id"] == "M2", "planned_time_s"].item() == 0


def test_performance_capped_at_one():
    states = states_df([(ts(6), "M1", "RUNNING", None)])
    production = production_df([(ts(6, 30), "M1", 200, 0)])  # 200 * 30 s > 1 h run
    ds = Dataset([Machine("M1", "Press", 30)], states, production)
    row = compute_oee(ds, end=ts(7)).iloc[0]
    assert row["performance"] == 1.0
    assert row["oee"] == pytest.approx(1.0)


def test_unknown_group_key_rejected():
    with pytest.raises(ValueError, match="group_by"):
        compute_oee(single_machine_dataset(), group_by=("line",))


def test_generator_output_oee_within_bounds():
    config = GeneratorConfig(start=datetime.datetime(2026, 3, 2, 6, 0), days=2, seed=3)
    ds = generate(config)
    result = compute_oee(ds, group_by=("machine_id", "shift", "date"), end=config.end)
    assert len(result) > 0
    for col in ("availability", "performance", "quality", "oee"):
        values = result[col]
        assert not values.isna().any()
        assert ((values >= 0) & (values <= 1)).all()
    overall = compute_overall(ds, end=config.end)
    assert 0 < overall.oee <= 1
    assert math.isclose(
        overall.planned_time_s, 4 * (2 * 86400 - 2 * 1800), rel_tol=0, abs_tol=1e-6
    )
