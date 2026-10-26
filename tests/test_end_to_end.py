import importlib.util
from pathlib import Path

from oee_analytics import cli

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def test_full_pipeline(tmp_path, capsys):
    data_dir = tmp_path / "plant"
    report = tmp_path / "report.html"
    steps = [
        ["generate", "--out", str(data_dir), "--days", "7", "--seed", "42"],
        ["summary", str(data_dir)],
        ["pareto", str(data_dir)],
        ["compare", str(data_dir), "--by", "machine"],
        ["report", str(data_dir), "--out", str(report)],
    ]
    for argv in steps:
        assert cli.main(argv) == 0, argv
    assert report.is_file()
    assert report.read_text(encoding="utf-8").lstrip().lower().startswith("<!doctype html")
    capsys.readouterr()


def test_public_api_imports():
    from oee_analytics import (  # noqa: F401
        GeneratorConfig,
        build_report,
        compare_machines,
        compare_shifts,
        compute_oee,
        compute_overall,
        downtime_pareto,
        generate,
        load_dataset,
    )


def _load_example_script():
    spec = importlib.util.spec_from_file_location(
        "generate_sample", EXAMPLES_DIR / "generate_sample.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_sample_matches_script(tmp_path):
    data_dir, report = _load_example_script().build_sample(tmp_path)
    for name in ("machines.csv", "states.csv", "production.csv"):
        committed = EXAMPLES_DIR / "sample_data" / name
        assert committed.read_bytes() == (data_dir / name).read_bytes(), name
    committed_report = EXAMPLES_DIR / "sample_report.html"
    assert committed_report.read_bytes() == report.read_bytes()
