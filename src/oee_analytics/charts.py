"""Matplotlib charts rendered as inline SVG strings for the HTML report.

Every function takes a table produced by :mod:`oee_analytics.metrics` or
:mod:`oee_analytics.analysis` and returns an ``<svg>`` element with no XML
declaration, DOCTYPE or metadata, ready to embed in HTML.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from contextlib import contextmanager

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

# Restrained palette: slate tones for the OEE components, one deep teal for
# OEE itself and a burnt orange reserved for the Pareto cumulative line.
INK = "#1f2933"
MUTED = "#52606d"
GRID = "#e4e7eb"
COMPONENT_COLORS = {
    "availability": "#9fb3c8",
    "performance": "#627d98",
    "quality": "#334e68",
}
OEE_COLOR = "#0f766e"
BAR_COLOR = "#486581"
CUMULATIVE_COLOR = "#b45309"

COMPONENT_LABELS = {
    "availability": "Availability",
    "performance": "Performance",
    "quality": "Quality",
    "oee": "OEE",
}

_FIGSIZE = (7.2, 3.6)
_SVG_START = re.compile(r"<svg\b")
_METADATA = {"Creator": None, "Date": None, "Format": None, "Type": None}


@contextmanager
def _style(salt: str) -> Iterator[None]:
    """Shared rc settings; ``salt`` keeps generated ids unique across charts."""
    rc = {
        "svg.fonttype": "none",
        "svg.hashsalt": salt,
        "font.family": "sans-serif",
        "font.size": 9,
        "text.color": INK,
        "axes.labelcolor": MUTED,
        "axes.edgecolor": GRID,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.titlesize": 10,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.major.size": 0,
        "ytick.major.size": 0,
        "legend.frameon": False,
        "legend.fontsize": 8.5,
    }
    with plt.rc_context(rc):
        yield


def _to_svg(fig: Figure, label: str) -> str:
    """Serialize ``fig`` to an ``<svg>`` string labelled for screen readers."""
    buffer = io.StringIO()
    fig.savefig(buffer, format="svg", bbox_inches="tight", metadata=_METADATA)
    plt.close(fig)
    svg = buffer.getvalue()
    match = _SVG_START.search(svg)
    if match is None:  # pragma: no cover - matplotlib always emits an <svg> root
        raise RuntimeError("matplotlib did not produce an <svg> element")
    svg = svg[match.start():].strip()
    escaped = label.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
    return svg.replace("<svg", f'<svg role="img" aria-label="{escaped}"', 1)


def _grid(ax: Axes) -> None:
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)


def _empty(ax: Axes) -> None:
    ax.text(0.5, 0.5, "No data", ha="center", va="center", color=MUTED, transform=ax.transAxes)
    ax.set_xticks([])
    ax.set_yticks([])


def _component_bars(table: pd.DataFrame, key: str, xlabel: str, salt: str, label: str) -> str:
    with _style(salt):
        fig, ax = plt.subplots(figsize=_FIGSIZE)
        if table.empty:
            _empty(ax)
            return _to_svg(fig, label)
        groups = [str(g) for g in table[key]]
        x = np.arange(len(groups))
        series = list(COMPONENT_COLORS.items()) + [("oee", OEE_COLOR)]
        width = 0.8 / len(series)
        for i, (column, color) in enumerate(series):
            values = table[column].astype(float) * 100.0
            bars = ax.bar(
                x + (i - (len(series) - 1) / 2) * width,
                values,
                width * 0.92,
                color=color,
                label=COMPONENT_LABELS[column],
            )
            if column == "oee":
                ax.bar_label(bars, fmt="%.1f", padding=2, fontsize=8, color=INK)
        ax.set_xticks(x, groups)
        ax.set_xlabel(xlabel)
        ax.set_ylim(0, 105)
        ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
        _grid(ax)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=len(series))
        return _to_svg(fig, label)


def oee_by_machine_chart(table: pd.DataFrame) -> str:
    """Grouped bars of availability, performance, quality and OEE per machine.

    ``table`` needs ``machine_id`` and the four ratio columns, as returned by
    ``compute_oee(dataset)`` or ``compare_machines(dataset)``.
    """
    table = table.sort_values("machine_id", kind="stable")
    return _component_bars(
        table,
        "machine_id",
        "Machine",
        "oee_by_machine",
        "Availability, performance, quality and OEE per machine",
    )


def oee_by_shift_chart(table: pd.DataFrame) -> str:
    """Grouped bars of availability, performance, quality and OEE per shift.

    ``table`` needs ``shift`` and the four ratio columns, as returned by
    ``compute_oee(dataset, group_by=("shift",))`` or ``compare_shifts(dataset)``.
    """
    table = table.sort_values("shift", kind="stable")
    return _component_bars(
        table,
        "shift",
        "Shift",
        "oee_by_shift",
        "Availability, performance, quality and OEE per shift",
    )


def pareto_chart(pareto: pd.DataFrame) -> str:
    """Downtime minutes per reason code with the cumulative share on a second axis.

    ``pareto`` is the output of :func:`oee_analytics.analysis.downtime_pareto`.
    A dashed line marks the 80% threshold on the cumulative axis.
    """
    label = "Downtime Pareto: minutes of downtime per reason code with cumulative share"
    with _style("pareto"):
        fig, ax = plt.subplots(figsize=_FIGSIZE)
        if pareto.empty:
            _empty(ax)
            return _to_svg(fig, label)
        x = np.arange(len(pareto))
        reasons = [str(r).replace("_", "\n") for r in pareto["reason_code"]]
        ax.bar(x, pareto["downtime_min"].astype(float), 0.6, color=BAR_COLOR, label="Downtime")
        ax.set_xticks(x, reasons, fontsize=8)
        ax.set_ylabel("Downtime (min)")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
        _grid(ax)

        cum = ax.twinx()
        cum.spines["right"].set_visible(True)
        cum.plot(
            x,
            pareto["cumulative_pct"].astype(float),
            color=CUMULATIVE_COLOR,
            marker="o",
            markersize=4,
            linewidth=1.6,
            label="Cumulative %",
        )
        cum.axhline(80, color=MUTED, linestyle="--", linewidth=1, label="80% line")
        cum.set_ylim(0, 105)
        cum.yaxis.set_major_formatter(PercentFormatter(decimals=0))
        cum.set_ylabel("Cumulative share")

        handles, labels = [], []
        for axis in (ax, cum):
            h, lab = axis.get_legend_handles_labels()
            handles += h
            labels += lab
        ax.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=3)
        return _to_svg(fig, label)


def daily_trend_chart(table: pd.DataFrame) -> str:
    """Plant OEE per day as a line.

    ``table`` needs ``date`` and ``oee`` columns, as returned by
    ``compute_oee(dataset, group_by=("date",))``.
    """
    label = "Plant OEE per day"
    with _style("daily_trend"):
        fig, ax = plt.subplots(figsize=_FIGSIZE)
        if table.empty:
            _empty(ax)
            return _to_svg(fig, label)
        table = table.sort_values("date", kind="stable")
        dates = pd.to_datetime(table["date"])
        values = table["oee"].astype(float) * 100.0
        x = np.arange(len(table))
        ax.plot(x, values, color=OEE_COLOR, marker="o", markersize=4, linewidth=1.8)
        for xi, v in zip(x, values):
            ax.annotate(
                f"{v:.1f}", (xi, v), textcoords="offset points", xytext=(0, 7),
                ha="center", fontsize=8, color=INK,
            )
        ax.set_xticks(x, [d.strftime("%a %d %b") for d in dates], fontsize=8)
        ax.set_xlabel("Day (overnight shift counted on its start date)")
        ax.set_ylim(0, 100)
        ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
        ax.set_ylabel("OEE")
        _grid(ax)
        return _to_svg(fig, label)
