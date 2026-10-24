import json

import pytest

from oee_analytics import cli


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("plant")
    assert cli.main(["generate", "--out", str(out), "--days", "2", "--seed", "3"]) == 0
    return out


def test_generate_creates_csvs(tmp_path, capsys):
    code = cli.main(["generate", "--out", str(tmp_path), "--days", "1", "--start", "2026-02-02"])
    assert code == 0
    for name in ("machines.csv", "states.csv", "production.csv"):
        assert (tmp_path / name).is_file()
    assert "states.csv" in capsys.readouterr().out
    assert (tmp_path / "states.csv").read_text().splitlines()[1].startswith("2026-02-02T06:00")


def test_summary(data_dir, capsys):
    assert cli.main(["summary", str(data_dir)]) == 0
    header = capsys.readouterr().out.splitlines()[0].split()
    assert header[0] == "machine_id"
    assert {"availability", "performance", "quality", "oee"} <= set(header)


def test_summary_by_machine_shift(data_dir, capsys):
    assert cli.main(["summary", str(data_dir), "--by", "machine,shift"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split()[:2] == ["machine_id", "shift"]
    assert len(lines) == 2 + 4 * 3


def test_pareto_top(data_dir, capsys):
    assert cli.main(["pareto", str(data_dir), "--top", "3"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == [
        "reason_code", "events", "downtime_min", "share_pct", "cumulative_pct"
    ]
    assert len(lines) == 2 + 3


def test_compare_by_shift(data_dir, capsys):
    assert cli.main(["compare", str(data_dir), "--by", "shift"]) == 0
    lines = capsys.readouterr().out.splitlines()
    header = lines[0].split()
    assert header[0] == "shift"
    assert "rank" in header and "oee_delta_pts" in header
    assert len(lines) == 2 + 3


@pytest.mark.parametrize(
    "args",
    [
        ["summary", "--by", "date"],
        ["pareto", "--machine", "M1"],
        ["compare", "--by", "machine"],
    ],
)
def test_json_output_parses(data_dir, capsys, args):
    assert cli.main([args[0], str(data_dir), *args[1:], "--format", "json"]) == 0
    records = json.loads(capsys.readouterr().out)
    assert isinstance(records, list) and records


def test_csv_output(data_dir, capsys):
    assert cli.main(["compare", str(data_dir), "--by", "machine", "--format", "csv"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("machine_id,")
    assert len(lines) == 1 + 4


def test_corrupt_csv_exits_2(tmp_path, capsys):
    assert cli.main(["generate", "--out", str(tmp_path), "--days", "1"]) == 0
    capsys.readouterr()
    states = tmp_path / "states.csv"
    lines = states.read_text().splitlines()
    lines[1] = "not-a-time," + lines[1].split(",", 1)[1]
    states.write_text("\n".join(lines) + "\n")
    assert cli.main(["summary", str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    err = captured.err.strip()
    assert "states.csv" in err and "timestamp" in err
    assert len(err.splitlines()) == 1


def test_missing_directory_exits_2(tmp_path, capsys):
    assert cli.main(["pareto", str(tmp_path / "nope")]) == 2
    assert capsys.readouterr().err.startswith("oee: error:")
