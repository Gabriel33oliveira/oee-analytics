import datetime
import fnmatch
import re
import tomllib
from importlib import resources
from pathlib import Path

import pytest

from oee_analytics import charts, cli
from oee_analytics.analysis import compare_machines, compare_shifts, downtime_pareto
from oee_analytics.generator import GeneratorConfig, generate, write_dataset
from oee_analytics.metrics import compute_oee, compute_overall
from oee_analytics.report import TEMPLATE_NAME, build_report, format_pct, write_report

ROOT = Path(__file__).resolve().parents[1]
KPI_LABELS = ("Plant OEE", "Availability", "Performance", "Quality")
SVG_PREFIX = re.compile(r"^(<\?xml[^>]*\?>\s*)?<svg\b")
# src/href attributes, CSS url() and @import pointing at the network.
EXTERNAL_ASSET = re.compile(
    r"""(?:\b(?:src|href|xlink:href)\s*=\s*["']?\s*https?://"""
    r"""|url\(\s*["']?\s*https?://"""
    r"""|@import\s+(?:url\()?\s*["']?\s*https?://)""",
    re.IGNORECASE,
)


@pytest.fixture(scope="module")
def dataset():
    config = GeneratorConfig(start=datetime.datetime(2026, 1, 5, 6, 0), days=3, seed=7)
    return generate(config)


@pytest.fixture(scope="module")
def html(dataset):
    return build_report(dataset, generated_at=datetime.datetime(2026, 1, 9, 8, 30))


def test_report_has_four_charts(html):
    assert html.count("<svg") == 4


def test_report_has_kpi_labels(html):
    for label in KPI_LABELS:
        assert f"<dt>{label}</dt>" in html


def test_report_lists_machines_shifts_and_top_reason(dataset, html):
    for machine in dataset.machines:
        assert f">{machine.machine_id}<" in html
    for shift in ("A", "B", "C"):
        assert f'<th scope="row" class="text">{shift}</th>' in html
    top = downtime_pareto(dataset).iloc[0]["reason_code"]
    assert f">{top}<" in html


def test_report_has_header_dates(html):
    assert "05 Jan 2026 06:00" in html
    assert "09 Jan 2026 08:30" in html


def test_report_has_no_external_assets(html):
    assert EXTERNAL_ASSET.search(html) is None
    assert "<script" not in html
    assert "<link" not in html


def test_kpi_matches_compute_overall(dataset, html):
    match = re.search(r'data-kpi="oee">([^<]+)<', html)
    assert match is not None
    expected = f"{compute_overall(dataset).oee * 100:.1f}%"
    assert match.group(1) == expected == format_pct(compute_overall(dataset).oee)


def test_tables_use_one_decimal_percentages(dataset, html):
    for row in compare_machines(dataset).itertuples():
        assert f"{row.oee * 100:.1f}%" in html


def test_title_is_escaped(dataset):
    out = build_report(dataset, title="Line <1> & 2")
    assert "<title>Line &lt;1&gt; &amp; 2</title>" in out


@pytest.mark.parametrize(
    "render",
    [
        lambda ds: charts.oee_by_machine_chart(compute_oee(ds)),
        lambda ds: charts.oee_by_shift_chart(compare_shifts(ds)),
        lambda ds: charts.pareto_chart(downtime_pareto(ds)),
        lambda ds: charts.daily_trend_chart(compute_oee(ds, group_by=("date",))),
    ],
    ids=["machine", "shift", "pareto", "trend"],
)
def test_chart_functions_return_svg(dataset, render):
    svg = render(dataset)
    assert SVG_PREFIX.match(svg)
    assert svg.rstrip().endswith("</svg>")
    assert 'role="img"' in svg


def test_charts_handle_empty_tables(dataset):
    empty = downtime_pareto(dataset, machine_id="does-not-exist")
    assert SVG_PREFIX.match(charts.pareto_chart(empty))
    assert SVG_PREFIX.match(charts.oee_by_machine_chart(compute_oee(dataset).iloc[0:0]))


def test_template_is_package_data():
    resource = resources.files("oee_analytics").joinpath("templates", TEMPLATE_NAME)
    assert resource.is_file()
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = config["tool"]["setuptools"]["package-data"]["oee_analytics"]
    assert any(fnmatch.fnmatch(f"templates/{TEMPLATE_NAME}", p) for p in patterns)


def test_write_report(dataset, tmp_path):
    path = write_report(dataset, tmp_path / "nested" / "report.html", title="Plant 7")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>")
    assert "<title>Plant 7</title>" in text


def test_cli_report(dataset, tmp_path, capsys):
    data_dir = tmp_path / "plant"
    write_dataset(dataset, data_dir)
    out = tmp_path / "report.html"
    assert cli.main(["report", str(data_dir), "--out", str(out)]) == 0
    assert out.is_file() and out.stat().st_size > 0
    assert "report.html" in capsys.readouterr().out
    assert cli.main(["report", str(data_dir), "--out", str(out), "--title", "Weekly"]) == 0
    assert "<title>Weekly</title>" in out.read_text(encoding="utf-8")


def test_cli_report_missing_data(tmp_path, capsys):
    code = cli.main(["report", str(tmp_path / "missing"), "--out", str(tmp_path / "r.html")])
    assert code == 2
    assert "oee: error:" in capsys.readouterr().err
