"""Command-line entry point for the ``oee`` tool."""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from oee_analytics import __version__
from oee_analytics.analysis import compare_machines, compare_shifts, downtime_pareto, format_table
from oee_analytics.generator import GeneratorConfig, generate, write_dataset
from oee_analytics.io import (
    MACHINES_FILE,
    PRODUCTION_FILE,
    STATES_FILE,
    DataValidationError,
    load_dataset,
)
from oee_analytics.metrics import compute_oee
from oee_analytics.shifts import DEFAULT_SHIFTS

FORMATS = ("table", "csv", "json")

SUMMARY_GROUPS = {
    "machine": ("machine_id",),
    "shift": ("shift",),
    "date": ("date",),
    "machine,shift": ("machine_id", "shift"),
}


def _date(value: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date {value!r} (expected YYYY-MM-DD)") from None


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {number}")
    return number


def _add_format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format", choices=FORMATS, default="table", help="output format (default: table)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oee",
        description="Compute OEE, downtime Paretos and shift comparisons from event logs.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    gen = sub.add_parser("generate", help="write a seeded synthetic plant dataset")
    gen.add_argument("--out", required=True, type=Path, metavar="DIR", help="output directory")
    gen.add_argument("--days", type=_positive_int, default=7, help="days to simulate (default: 7)")
    gen.add_argument("--seed", type=int, default=42, help="random seed (default: 42)")
    gen.add_argument(
        "--start",
        type=_date,
        default=datetime.date(2026, 1, 5),
        metavar="YYYY-MM-DD",
        help="first day; the simulation starts at the first shift (default: 2026-01-05)",
    )
    _add_format(gen)

    summary = sub.add_parser("summary", help="OEE table grouped by machine, shift or date")
    summary.add_argument("data_dir", type=Path, metavar="DATA_DIR")
    summary.add_argument(
        "--by", choices=list(SUMMARY_GROUPS), default="machine", help="grouping (default: machine)"
    )
    _add_format(summary)

    pareto = sub.add_parser("pareto", help="downtime Pareto by reason code")
    pareto.add_argument("data_dir", type=Path, metavar="DATA_DIR")
    pareto.add_argument("--machine", metavar="ID", help="only this machine")
    pareto.add_argument("--shift", metavar="NAME", help="only this shift")
    pareto.add_argument("--top", type=_positive_int, metavar="N", help="show the N largest reasons")
    _add_format(pareto)

    compare = sub.add_parser("compare", help="rank shifts or machines by OEE")
    compare.add_argument("data_dir", type=Path, metavar="DATA_DIR")
    compare.add_argument("--by", choices=("machine", "shift"), required=True)
    _add_format(compare)
    return parser


def _render(df: pd.DataFrame, fmt: str) -> str:
    if fmt == "csv":
        return df.to_csv(index=False).rstrip("\n")
    if fmt == "json":
        records = json.loads(df.to_json(orient="records", date_format="iso"))
        return json.dumps(records, indent=2)
    return format_table(df)


def _run_generate(args: argparse.Namespace) -> pd.DataFrame:
    start = datetime.datetime.combine(args.start, DEFAULT_SHIFTS[0].start)
    dataset = generate(GeneratorConfig(start=start, days=args.days, seed=args.seed))
    write_dataset(dataset, args.out)
    return pd.DataFrame(
        {
            "file": [str(args.out / name) for name in (MACHINES_FILE, STATES_FILE, PRODUCTION_FILE)],
            "rows": [len(dataset.machines), len(dataset.states), len(dataset.production)],
        }
    )


def _run(args: argparse.Namespace) -> pd.DataFrame:
    if args.command == "generate":
        return _run_generate(args)
    dataset = load_dataset(args.data_dir)
    if args.command == "summary":
        table = compute_oee(dataset, group_by=SUMMARY_GROUPS[args.by])
        if "date" in table.columns:
            table["date"] = table["date"].astype(str)
        return table
    if args.command == "pareto":
        table = downtime_pareto(dataset, machine_id=args.machine, shift=args.shift)
        return table.head(args.top) if args.top else table
    if args.by == "shift":
        return compare_shifts(dataset)
    return compare_machines(dataset)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        table = _run(args)
    except (DataValidationError, FileNotFoundError) as exc:
        message = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        print(f"oee: error: {message}", file=sys.stderr)
        return 2
    print(_render(table, args.format))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
