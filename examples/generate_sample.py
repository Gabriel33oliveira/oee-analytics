"""Rebuild the committed sample dataset and HTML report.

Writes a 7-day, seed-42 synthetic dataset to ``examples/sample_data/`` and
renders it to ``examples/sample_report.html``. The report's "generated" time is
fixed so that rerunning the script reproduces the committed files exactly.

Usage:
    python examples/generate_sample.py [OUTPUT_DIR]
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

from oee_analytics import GeneratorConfig, build_report, generate, load_dataset
from oee_analytics.generator import write_dataset

EXAMPLES_DIR = Path(__file__).resolve().parent
CONFIG = GeneratorConfig(start=datetime.datetime(2026, 1, 5, 6, 0), days=7, seed=42)
GENERATED_AT = datetime.datetime(2026, 1, 12, 6, 0)
TITLE = "OEE Report: sample plant, 7 days, seed 42"


def build_sample(out_dir: Path = EXAMPLES_DIR) -> tuple[Path, Path]:
    """Write ``sample_data/`` and ``sample_report.html`` into ``out_dir``."""
    data_dir = out_dir / "sample_data"
    report_path = out_dir / "sample_report.html"
    write_dataset(generate(CONFIG), data_dir)
    # Load from the CSVs, like the CLI does, so the report reflects the files on disk.
    html = build_report(load_dataset(data_dir), title=TITLE, generated_at=GENERATED_AT)
    report_path.write_text(html, encoding="utf-8", newline="\n")
    return data_dir, report_path


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else EXAMPLES_DIR
    for path in build_sample(target):
        print(path)
