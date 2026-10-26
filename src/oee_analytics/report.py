"""Self-contained HTML report: KPI cards, charts and comparison tables."""

from __future__ import annotations

import datetime
import os
from importlib import resources
from pathlib import Path

import pandas as pd
from jinja2 import Environment, StrictUndefined
from markupsafe import Markup

from oee_analytics import __version__
from oee_analytics.analysis import compare_machines, compare_shifts, downtime_pareto
from oee_analytics.charts import (
    daily_trend_chart,
    oee_by_machine_chart,
    oee_by_shift_chart,
    pareto_chart,
)
from oee_analytics.io import Dataset
from oee_analytics.metrics import compute_oee, compute_overall

TEMPLATE_NAME = "report.html.j2"


def format_pct(ratio: float) -> str:
    """Format a 0-1 ratio as a percentage with one decimal, e.g. ``0.8123 -> '81.2%'``."""
    return f"{float(ratio) * 100:.1f}%"


def format_share(pct: float) -> str:
    """Format a value already in percent with one decimal, e.g. ``45.67 -> '45.7%'``."""
    return f"{float(pct):.1f}%"


def format_points(points: float) -> str:
    """Format a signed difference in percentage points, e.g. ``-2.34 -> '−2.3 pts'``."""
    text = f"{float(points):+.1f}".replace("-", "−")
    return f"{text} pts"


def format_minutes(minutes: float) -> str:
    """Format a duration in minutes with one decimal and a thousands separator."""
    return f"{float(minutes):,.1f}"


def format_count(value: int) -> str:
    """Format an integer count with a thousands separator, e.g. ``12345 -> '12,345'``."""
    return f"{int(value):,}"


def _load_template() -> str:
    """Read the template from package data so it works from an installed wheel."""
    path = resources.files("oee_analytics").joinpath("templates", TEMPLATE_NAME)
    return path.read_text(encoding="utf-8")


def _environment() -> Environment:
    env = Environment(autoescape=True, undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
    env.filters.update(
        pct=format_pct,
        share=format_share,
        points=format_points,
        minutes=format_minutes,
        count=format_count,
    )
    return env


def _date_range(dataset: Dataset) -> tuple[datetime.datetime, datetime.datetime] | None:
    frames = [df["timestamp"] for df in (dataset.states, dataset.production) if not df.empty]
    if not frames:
        return None
    stamps = pd.concat(frames)
    return stamps.min().to_pydatetime(), stamps.max().to_pydatetime()


def build_report(
    dataset: Dataset,
    title: str = "OEE Report",
    generated_at: datetime.datetime | None = None,
) -> str:
    """Render the full report for ``dataset`` as a single HTML document.

    The HTML embeds its CSS and SVG charts, so it needs no network access.
    ``generated_at`` defaults to the current local time.
    """
    if generated_at is None:
        generated_at = datetime.datetime.now().replace(microsecond=0)
    overall = compute_overall(dataset)
    by_machine = compare_machines(dataset)
    by_shift = compare_shifts(dataset)
    by_date = compute_oee(dataset, group_by=("date",))
    pareto = downtime_pareto(dataset)
    names = {m.machine_id: m.name for m in dataset.machines}

    charts = {
        "machine": oee_by_machine_chart(by_machine),
        "shift": oee_by_shift_chart(by_shift),
        "pareto": pareto_chart(pareto),
        "trend": daily_trend_chart(by_date),
    }
    context = {
        "title": title,
        "version": __version__,
        "date_range": _date_range(dataset),
        "generated_at": generated_at,
        "overall": overall,
        "machines": [
            {**row, "name": names.get(row["machine_id"], "")}
            for row in by_machine.to_dict("records")
        ],
        "shifts": by_shift.to_dict("records"),
        "pareto": pareto.to_dict("records"),
        "total_downtime_min": float(pareto["downtime_min"].sum()) if not pareto.empty else 0.0,
        "charts": {key: Markup(svg) for key, svg in charts.items()},
    }
    template = _environment().from_string(_load_template())
    return template.render(**context)


def write_report(
    dataset: Dataset, path: str | os.PathLike[str], title: str = "OEE Report"
) -> Path:
    """Write :func:`build_report` output to ``path`` (UTF-8) and return the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_report(dataset, title=title), encoding="utf-8")
    return path
